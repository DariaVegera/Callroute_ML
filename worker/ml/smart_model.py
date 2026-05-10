"""
SmartModel — rubert-tiny2 fine-tuned classifier.
Артефакты: smart_model/ (model.safetensors + tokenizer + config.json)

ВАЖНО: метки берём из config.json модели, не из fast_model.py
"""
import json
import os
import numpy as np
from typing import Optional


# Маппинги для 4 классов обученной модели
INTENT_TO_QUEUE = {
    "return_request":     "returns_department",
    "technical_issue":    "tech_support",
    "payment_issue":      "billing_department",
    "fraud_report":       "security_team",
    "general_inquiry":    "first_line_support",
    "complaint":          "quality_department",
    "account_management": "account_team",
    "escalation_request": "supervisor_queue",
    # fallback для любых других
    "entertainment":      "first_line_support",
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
    "entertainment":      "low",
}


class SmartModel:
    def __init__(self):
        self.tokenizer = None
        self.model = None
        self.id2label: dict[int, str] = {}
        self._loaded = False

    def load(self, model_path: str):
        """Загрузка модели. Метки берём из config.json."""
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

        # Читаем id2label из config.json модели
        config_path = os.path.join(model_path, "config.json")
        if os.path.exists(config_path):
            with open(config_path) as f:
                cfg = json.load(f)
            self.id2label = {int(k): v for k, v in cfg.get("id2label", {}).items()}
        
        if not self.id2label:
            # Fallback если config.json нет
            self.id2label = {
                0: "account_management",
                1: "entertainment",
                2: "general_inquiry",
                3: "technical_issue",
            }

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path)
        self.model.to(self.device)
        self.model.eval()
        self._loaded = True

    def predict(self, text: str) -> dict:
        import torch
        import torch.nn.functional as F

        if not self._loaded:
            raise RuntimeError("SmartModel not loaded")

        inputs = self.tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=128,
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)
            probas = F.softmax(outputs.logits, dim=-1)[0].cpu().numpy()

        class_idx = int(np.argmax(probas))
        confidence = float(probas[class_idx])
        intent = self.id2label.get(class_idx, "general_inquiry")

        return {
            "intent": intent,
            "confidence": confidence,
            "priority": INTENT_TO_PRIORITY.get(intent, "low"),
            "queue": INTENT_TO_QUEUE.get(intent, "first_line_support"),
            "all_probas": {self.id2label.get(i, str(i)): float(p) for i, p in enumerate(probas)},
        }


# Singleton
smart_model_instance: Optional["SmartModel"] = None


def get_smart_model() -> "SmartModel":
    global smart_model_instance
    if smart_model_instance is None:
        raise RuntimeError("SmartModel not initialized — call init_smart_model() at startup")
    return smart_model_instance


def init_smart_model(model_path: str) -> "SmartModel":
    global smart_model_instance
    smart_model_instance = SmartModel()
    smart_model_instance.load(model_path)
    return smart_model_instance
