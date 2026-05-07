import os
from celery import Celery
from celery.signals import worker_init

broker_url = os.environ.get("CELERY_BROKER_URL", "redis://redis:6379/0")
result_backend = os.environ.get("CELERY_RESULT_BACKEND", "redis://redis:6379/1")

app = Celery(
    "callroute",
    broker=broker_url,
    backend=result_backend,
    include=[
        "worker.tasks.predict_task",
        "worker.tasks.loyalty_task",
        "worker.tasks.cashback_task",
    ],
)

app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,         # ACK после выполнения — не теряем задачи
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,  # Не хватать лишние задачи в очередь
    task_routes={
        "worker.tasks.predict_task.run_prediction": {
            "queue": "fast",  # overridden per-call
        },
    },
    beat_schedule={
        "recalculate-loyalty-levels": {
            "task": "worker.tasks.loyalty_task.recalculate_loyalty",
            "schedule": 3600.0,  # каждый час
        },
        "weekly-cashback": {
            "task": "worker.tasks.cashback_task.calculate_weekly_cashback",
            "schedule": 604800.0,  # раз в неделю
        },
    },
)


@worker_init.connect
def on_worker_init(sender=None, **kwargs):
    """Загружаем ML-модели при старте воркера (не при каждом запросе)."""
    worker_type = os.environ.get("WORKER_TYPE", "fast")
    from worker.ml.model_registry import init_models_for_worker
    init_models_for_worker(worker_type)
