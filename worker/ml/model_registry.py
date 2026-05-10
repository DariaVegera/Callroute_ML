"""
ModelRegistry — загружает модели при старте воркера.
Если артефакты не найдены — использует заглушку (stub).
"""
import os
import logging
import random

logger = logging.getLogger(__name__)

FAST_MODEL_KEY = "catboost_tfidf"
SMART_MODEL_KEY = "rubert_tiny2"

INTENT_LABELS = [
    "return_request", "technical_issue", "payment_issue", "fraud_report",
    "general_inquiry", "complaint", "account_management", "escalation_request",
]
INTENT_TO_QUEUE = {
    "return_request": "returns_department", "technical_issue": "tech_support",
    "payment_issue": "billing_department", "fraud_report": "security_team",
    "general_inquiry": "first_line_support", "complaint": "quality_department",
    "account_management": "account_team", "escalation_request": "supervisor_queue",
}
INTENT_TO_PRIORITY = {
    "return_request": "medium", "technical_issue": "medium",
    "payment_issue": "high", "fraud_report": "critical",
    "general_inquiry": "low", "complaint": "medium",
    "account_management": "low", "escalation_request": "critical",
}


def _stub_predict(text: str) -> dict:
    keywords = {
        "возврат": "return_request", "вернуть": "return_request",
        "не работает": "technical_issue", "ошибка": "technical_issue",
        "оплата": "payment_issue", "платёж": "payment_issue",
        "мошенник": "fraud_report", "украли": "fraud_report",
        "жалоба": "complaint", "недоволен": "complaint",
        "аккаунт": "account_management", "пароль": "account_management",
        "руководитель": "escalation_request", "эскалация": "escalation_request",
    }
    intent = "general_inquiry"
    for kw, label in keywords.items():
        if kw in text.lower():
            intent = label
            break
    confidence = round(random.uniform(0.62, 0.95), 4)
    return {
        "intent": intent,
        "confidence": confidence,
        "priority": INTENT_TO_PRIORITY[intent],
        "queue": INTENT_TO_QUEUE[intent],
        "all_probas": {lb: round(random.uniform(0.01, 0.1), 4) for lb in INTENT_LABELS},
    }


def init_models_for_worker(worker_type: str):
    if worker_type == "fast":
        tfidf_path = os.environ.get("FAST_TFIDF_PATH", "/app/models/tfidf.pkl")
        model_path = os.environ.get("FAST_MODEL_PATH", "/app/models/catboost_model.cbm")
        if os.path.exists(tfidf_path) and os.path.exists(model_path):
            from ml.fast_model import init_fast_model
            init_fast_model(tfidf_path, model_path)
            logger.info("FastModel (CatBoost) loaded successfully")
        else:
            logger.warning("FastModel artifacts not found — using stub predictor")
    elif worker_type == "smart":
        model_path = os.environ.get("SMART_MODEL_PATH", "/app/models/smart_model")
        if os.path.exists(model_path):
            from ml.smart_model import init_smart_model
            init_smart_model(model_path)
            logger.info("SmartModel (rubert-tiny2) loaded successfully")
        else:
            logger.warning("SmartModel artifact not found — using stub predictor")


def predict_with_model(model_key: str, text: str) -> dict:
    if model_key == FAST_MODEL_KEY:
        tfidf_path = os.environ.get("FAST_TFIDF_PATH", "/app/models/tfidf.pkl")
        model_path = os.environ.get("FAST_MODEL_PATH", "/app/models/catboost_model.cbm")
        if os.path.exists(tfidf_path) and os.path.exists(model_path):
            from ml.fast_model import get_fast_model
            return get_fast_model().predict(text)
        return _stub_predict(text)
    elif model_key == SMART_MODEL_KEY:
        model_path = os.environ.get("SMART_MODEL_PATH", "/app/models/smart_model")
        if os.path.exists(model_path):
            from ml.smart_model import get_smart_model
            return get_smart_model().predict(text)
        return _stub_predict(text)
    else:
        raise ValueError(f"Unknown model_key: {model_key}")