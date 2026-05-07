"""
ModelRegistry — загружает модели при старте воркера.
Выбирает модель по model_key из тарифа.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Ключи моделей (соответствуют prediction_tiers.model_key в БД)
FAST_MODEL_KEY = "catboost_tfidf"
SMART_MODEL_KEY = "rubert_tiny2"


def init_models_for_worker(worker_type: str):
    """
    worker_type: 'fast' | 'smart'
    Загружает только нужные модели, не грузит лишнее в память.
    """
    if worker_type == "fast":
        tfidf_path = os.environ.get("FAST_TFIDF_PATH", "/app/models/tfidf.pkl")
        model_path = os.environ.get("FAST_MODEL_PATH", "/app/models/catboost_model.cbm")

        if os.path.exists(tfidf_path) and os.path.exists(model_path):
            from worker.ml.fast_model import init_fast_model
            init_fast_model(tfidf_path, model_path)
            logger.info("FastModel (CatBoost) loaded successfully")
        else:
            logger.warning(
                f"FastModel artifacts not found at {tfidf_path} / {model_path}. "
                "Worker will fail on predict. Train models first."
            )

    elif worker_type == "smart":
        model_path = os.environ.get("SMART_MODEL_PATH", "/app/models/smart_model")

        if os.path.exists(model_path):
            from worker.ml.smart_model import init_smart_model
            init_smart_model(model_path)
            logger.info("SmartModel (rubert-tiny2) loaded successfully")
        else:
            logger.warning(
                f"SmartModel artifact not found at {model_path}. "
                "Worker will fail on predict. Train models first."
            )


def predict_with_model(model_key: str, text: str) -> dict:
    """Единая точка вызова предикта по ключу модели."""
    if model_key == FAST_MODEL_KEY:
        from worker.ml.fast_model import get_fast_model
        return get_fast_model().predict(text)
    elif model_key == SMART_MODEL_KEY:
        from worker.ml.smart_model import get_smart_model
        return get_smart_model().predict(text)
    else:
        raise ValueError(f"Unknown model_key: {model_key}")
