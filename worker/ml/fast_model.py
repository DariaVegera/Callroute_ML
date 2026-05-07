"""
FastModel — TF-IDF + CatBoost классификатор.
Обучается в ml_training/02_train_fast_model.ipynb
Артефакты: catboost_model.cbm + tfidf.pkl
"""
import pickle
import numpy as np
from typing import Optional

INTENT_LABELS = [
    "return_request",
    "technical_issue",
    "payment_issue",
    "fraud_report",
    "general_inquiry",
    "complaint",
    "account_management",
    "escalation_request",
]

INTENT_TO_QUEUE = {
    "return_request":     "returns_department",
    "technical_issue":    "tech_support",
    "payment_issue":      "billing_department",
    "fraud_report":       "security_team",
    "general_inquiry":    "first_line_support",
    "complaint":          "quality_department",
    "account_management": "account_team",
    "escalation_request": "supervisor_queue",
}

INTENT_TO_PRIORITY = {
    "return_request":     "medium",
    "technical_issue":    "medium",
    "payment_issue":      "high",
    "fraud_report":       "critical",
    "general_inquiry":    "low",
    "complaint":          "medium",
    "account_management": "low",
    "escalation_request": "critical",
}


class FastModel:
    def __init__(self):
        self.tfidf = None
        self.model = None
        self._loaded = False

    def load(self, tfidf_path: str, model_path: str):
        from catboost import CatBoostClassifier

        with open(tfidf_path, "rb") as f:
            self.tfidf = pickle.load(f)

        self.model = CatBoostClassifier()
        self.model.load_model(model_path)
        self._loaded = True

    def _extract_features(self, text: str) -> np.ndarray:
        """TF-IDF + простые мета-признаки."""
        tfidf_vec = self.tfidf.transform([text]).toarray()
        meta = np.array([[
            len(text),
            sum(1 for c in text if c.isupper()) / max(len(text), 1),
            len(text.split()),
        ]])
        return np.hstack([tfidf_vec, meta])

    def predict(self, text: str) -> dict:
        if not self._loaded:
            raise RuntimeError("FastModel not loaded")

        features = self._extract_features(text)
        probas = self.model.predict_proba(features)[0]
        class_idx = int(np.argmax(probas))
        confidence = float(probas[class_idx])
        intent = INTENT_LABELS[class_idx]

        return {
            "intent": intent,
            "confidence": confidence,
            "priority": INTENT_TO_PRIORITY[intent],
            "queue": INTENT_TO_QUEUE[intent],
            "all_probas": {INTENT_LABELS[i]: float(p) for i, p in enumerate(probas)},
        }


# Singleton instance — pre-warmed in worker startup
fast_model_instance: Optional[FastModel] = None


def get_fast_model() -> FastModel:
    global fast_model_instance
    if fast_model_instance is None:
        raise RuntimeError("FastModel not initialized — call init_fast_model() at startup")
    return fast_model_instance


def init_fast_model(tfidf_path: str, model_path: str) -> FastModel:
    global fast_model_instance
    fast_model_instance = FastModel()
    fast_model_instance.load(tfidf_path, model_path)
    return fast_model_instance
