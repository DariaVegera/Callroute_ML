"""
Основная задача предикта.
Flow: валидация → предикт → биллинг → HITL-очередь (если low_confidence) → обновление БД

Порядок операций специально выстроен так:
1. Сначала инференс (без списания)
2. Только после успешного инференса — списание кредитов
3. Если инференс упал — кредиты не списываются, статус → failed
4. Если списание упало после инференса — retry с тем же effective_cost
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from celery import Task
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from worker.celery_app import app
from worker.ml.model_registry import predict_with_model
from api.core.config import settings

_sync_db_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
_engine = None
_Session = None


def get_sync_session() -> Session:
    global _engine, _Session
    if _engine is None:
        _engine = create_engine(_sync_db_url, pool_size=5, max_overflow=10)
        _Session = sessionmaker(bind=_engine)
    return _Session()


logger = logging.getLogger(__name__)

LOW_CONFIDENCE_THRESHOLD = settings.low_confidence_threshold

from prometheus_client import Counter, Histogram

ML_INFERENCE_DURATION = Histogram(
    "ml_inference_duration_seconds",
    "ML inference time",
    ["model_key"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0],
)

ML_LOW_CONFIDENCE = Counter(
    "ml_low_confidence_total",
    "Predictions with low confidence",
)

CELERY_TASK_DURATION = Histogram(
    "celery_task_duration_seconds",
    "Celery task processing time",
    ["tier"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0],
)

CELERY_TASKS_TOTAL = Counter(
    "celery_tasks_total",
    "Celery task outcomes",
    ["task_name", "status"],
)

BILLING_CREDITS_CHARGED = Counter(
    "billing_credits_charged_total",
    "Total credits charged",
    ["tier", "balance_type"],
)


def _refund_if_charged(db: Session, task_id: str, user_id: str, cost: Decimal, was_charged: bool):
    """Возврат кредитов если списание уже прошло, но задача упала после."""
    if not was_charged:
        return
    try:
        from api.models.user import UserBalance
        from api.models.billing import Transaction
        balance = db.query(UserBalance).filter(
            UserBalance.user_id == UUID(user_id)
        ).with_for_update().first()
        if balance:
            before = float(balance.bought_credits)
            balance.bought_credits = Decimal(str(balance.bought_credits)) + cost
            balance.version += 1
            db.add(Transaction(
                user_id=UUID(user_id),
                type="REFUND",
                amount=cost,
                balance_type="bought",
                balance_before=before,
                balance_after=float(balance.bought_credits),
                description="Refund: worker failed after billing",
                reference_id=UUID(task_id),
                reference_type="prediction",
            ))
            db.commit()
            logger.info(f"Refund issued for task {task_id}: {cost} credits returned")
    except Exception as e:
        logger.exception(f"Refund failed for task {task_id}: {e}")


@app.task(
    bind=True,
    name="worker.tasks.predict_task.run_prediction",
    max_retries=3,
    default_retry_delay=5,
    acks_late=True,
)
def run_prediction(
    self: Task,
    task_id: str,
    user_id: str,
    text: str,
    tier_name: str,
    effective_cost: str,
):
    import time

    start = time.perf_counter()
    db: Session = get_sync_session()
    was_charged = False  # флаг: списание прошло

    try:
        from api.models.prediction import PredictionTask, PredictionTier
        from api.models.user import UserBalance
        from api.models.billing import Transaction
        from api.models.hitl import HITLTask

        # 1. Статус → processing
        task = db.query(PredictionTask).filter(
            PredictionTask.id == UUID(task_id)
        ).with_for_update().first()

        if not task:
            logger.error(f"Task {task_id} not found in DB")
            return

        task.status = "processing"
        db.commit()

        # 2. Определить model_key
        tier = db.query(PredictionTier).filter(PredictionTier.name == tier_name).first()
        if not tier:
            raise ValueError(f"Tier {tier_name} not found")
        model_key = tier.model_key

        # 3. Инференс — до списания, чтобы при падении модели не трогать деньги
        with ML_INFERENCE_DURATION.labels(model_key=model_key).time():
            result = predict_with_model(model_key, text)

        confidence = result["confidence"]
        low_conf = confidence < LOW_CONFIDENCE_THRESHOLD
        if low_conf:
            ML_LOW_CONFIDENCE.inc()

        # 4. Биллинг — только после успешного инференса
        cost = Decimal(effective_cost)
        balance = db.query(UserBalance).filter(
            UserBalance.user_id == UUID(user_id)
        ).with_for_update().first()

        if not balance:
            raise ValueError("Balance not found")

        bonus = Decimal(str(balance.bonus_credits))
        bought = Decimal(str(balance.bought_credits))

        if bonus + bought < cost:
            raise ValueError(f"Insufficient balance at charge time: {bonus + bought} < {cost}")

        from_bonus = min(bonus, cost)
        from_bought = cost - from_bonus

        balance.bonus_credits = bonus - from_bonus
        balance.bought_credits = bought - from_bought
        balance.version += 1

        if from_bonus > 0:
            db.add(Transaction(
                user_id=UUID(user_id),
                type="DEBIT_PREDICTION",
                amount=from_bonus,
                balance_type="bonus",
                balance_before=float(bonus),
                balance_after=float(balance.bonus_credits),
                description=f"Prediction charge (bonus) tier={tier_name}",
                reference_id=UUID(task_id),
                reference_type="prediction",
            ))
            BILLING_CREDITS_CHARGED.labels(tier=tier_name, balance_type="bonus").inc(float(from_bonus))

        if from_bought > 0:
            db.add(Transaction(
                user_id=UUID(user_id),
                type="DEBIT_PREDICTION",
                amount=from_bought,
                balance_type="bought",
                balance_before=float(bought),
                balance_after=float(balance.bought_credits),
                description=f"Prediction charge (bought) tier={tier_name}",
                reference_id=UUID(task_id),
                reference_type="prediction",
            ))
            BILLING_CREDITS_CHARGED.labels(tier=tier_name, balance_type="bought").inc(float(from_bought))

        # Увеличить счётчик предиктов за месяц
        from api.models.user import User
        user_obj = db.query(User).filter(User.id == UUID(user_id)).with_for_update().first()
        if user_obj:
            user_obj.predictions_this_month = (user_obj.predictions_this_month or 0) + 1

        db.commit()
        was_charged = True  # списание прошло успешно

        # 5. Статус → completed
        task = db.query(PredictionTask).filter(
            PredictionTask.id == UUID(task_id)
        ).with_for_update().first()
        task.status = "completed"
        task.predicted_intent = result["intent"]
        task.predicted_priority = result["priority"]
        task.queue_recommendation = result["queue"]
        task.confidence_score = Decimal(str(confidence))
        task.low_confidence = low_conf
        task.credits_charged = cost
        task.completed_at = datetime.now(timezone.utc)

        # 6. Если low_confidence → HITL
        if low_conf:
            db.add(HITLTask(
                prediction_task_id=UUID(task_id),
                input_text=text,
                model_prediction=result["intent"],
                model_confidence=Decimal(str(confidence)),
                status="pending",
                reward_credits=Decimal("5.00"),
            ))

        db.commit()

        elapsed = time.perf_counter() - start
        CELERY_TASK_DURATION.labels(tier=tier_name).observe(elapsed)
        CELERY_TASKS_TOTAL.labels(task_name="run_prediction", status="success").inc()

        logger.info(
            f"Task {task_id} completed: intent={result['intent']} "
            f"conf={confidence:.3f} low={low_conf} elapsed={elapsed:.3f}s"
        )

    except Exception as exc:
        db.rollback()
        CELERY_TASKS_TOTAL.labels(task_name="run_prediction", status="failure").inc()
        logger.exception(f"Task {task_id} failed: {exc}")

        # Если списание уже прошло — рефандим
        if was_charged:
            _refund_if_charged(db, task_id, user_id, Decimal(effective_cost), was_charged)

        # Обновляем статус задачи
        try:
            from api.models.prediction import PredictionTask
            db2 = get_sync_session()
            task = db2.query(PredictionTask).filter(
                PredictionTask.id == UUID(task_id)
            ).first()
            if task and task.status in ("pending", "processing"):
                task.status = "failed"
                task.error_message = str(exc)
                db2.commit()
            db2.close()
        except Exception as inner:
            logger.exception(f"Failed to update task status: {inner}")

        # Retry только если не исчерпали попытки
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc, countdown=2 ** self.request.retries)

    finally:
        db.close()
