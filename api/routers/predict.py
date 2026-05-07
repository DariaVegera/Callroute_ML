import uuid
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from api.core.database import get_db
from api.core.security import get_current_user
from api.core.config import settings
from api.models.user import User, UserBalance
from api.models.prediction import PredictionTask, PredictionTier
from api.services.billing_service import BillingService

router = APIRouter(prefix="/predict", tags=["predict"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def create_prediction(
    text: str,
    tier: str = "fast",
    idempotency_key: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Валидация текста
    text = text.strip()
    if len(text) < 5:
        raise HTTPException(status_code=422, detail="Текст слишком короткий (минимум 5 символов)")

    # Получаем тариф
    result = await db.execute(
        select(PredictionTier).where(
            PredictionTier.name == tier,
            PredictionTier.is_active == True,
        )
    )
    tier_obj = result.scalar_one_or_none()
    if not tier_obj:
        raise HTTPException(status_code=400, detail=f"Тариф '{tier}' не найден")

    if len(text) > tier_obj.max_input_chars:
        raise HTTPException(
            status_code=422,
            detail=f"Текст превышает лимит {tier_obj.max_input_chars} символов"
        )

    # Рассчитываем стоимость со скидкой лояльности
    effective_cost = await BillingService.get_effective_cost(
        current_user.id, tier_obj.base_cost, db
    )

    # Предварительная проверка баланса
    has_funds = await BillingService.check_balance(current_user.id, effective_cost, db)
    if not has_funds:
        raise HTTPException(
            status_code=402,
            detail=f"Недостаточно кредитов. Необходимо: {effective_cost}"
        )

    # Идемпотентность
    idem_key = idempotency_key or str(uuid.uuid4())
    existing = await db.execute(
        select(PredictionTask).where(PredictionTask.idempotency_key == idem_key)
    )
    existing_task = existing.scalar_one_or_none()
    if existing_task:
        return {
            "task_id": str(existing_task.id),
            "status": existing_task.status,
            "tier": tier,
            "estimated_credits": float(effective_cost),
            "created_at": existing_task.created_at.isoformat(),
        }

    # Создаём задачу
    task = PredictionTask(
        user_id=current_user.id,
        tier_id=tier_obj.id,
        idempotency_key=idem_key,
        input_text=text,
        status="pending",
    )
    db.add(task)
    await db.flush()

    # Отправляем в Celery
    from worker.celery_app import app as celery_app
    celery_result = celery_app.send_task(
        "worker.tasks.predict_task.run_prediction",
        kwargs={
            "task_id": str(task.id),
            "user_id": str(current_user.id),
            "text": text,
            "tier_name": tier,
            "effective_cost": str(effective_cost),
        },
        queue=tier_obj.name,
    )
    task.celery_task_id = celery_result.id
    await db.commit()

    return {
        "task_id": str(task.id),
        "status": "pending",
        "tier": tier,
        "estimated_credits": float(effective_cost),
        "created_at": task.created_at.isoformat(),
    }


@router.get("/{task_id}")
async def get_prediction(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PredictionTask).where(
            PredictionTask.id == uuid.UUID(task_id),
            PredictionTask.user_id == current_user.id,
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    response = {
        "task_id": str(task.id),
        "status": task.status,
        "credits_charged": float(task.credits_charged) if task.credits_charged else None,
        "low_confidence": task.low_confidence,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat(),
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    }

    if task.status == "completed":
        response["result"] = {
            "intent": task.predicted_intent,
            "priority": task.predicted_priority,
            "queue": task.queue_recommendation,
            "confidence": float(task.confidence_score) if task.confidence_score else None,
            "low_confidence": task.low_confidence,
        }

    return response


@router.get("")
async def list_predictions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PredictionTask).where(PredictionTask.user_id == current_user.id)
    if status_filter:
        query = query.where(PredictionTask.status == status_filter)
    query = query.order_by(desc(PredictionTask.created_at))

    count_result = await db.execute(
        select(func.count()).select_from(
            select(PredictionTask).where(
                PredictionTask.user_id == current_user.id
            ).subquery()
        )
    )
    total = count_result.scalar()
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    tasks = result.scalars().all()

    return {
        "items": [
            {
                "task_id": str(t.id),
                "status": t.status,
                "tier_id": str(t.tier_id),
                "predicted_intent": t.predicted_intent,
                "confidence_score": float(t.confidence_score) if t.confidence_score else None,
                "credits_charged": float(t.credits_charged) if t.credits_charged else None,
                "low_confidence": t.low_confidence,
                "created_at": t.created_at.isoformat(),
            }
            for t in tasks
        ],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }
