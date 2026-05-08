"""
SmartModel — rubert-tiny2 fine-tuned classifier.
Обучается в ml_training/03_train_smart_model.ipynb
Артефакты: smart_model/ (pytorch_model.bin + tokenizer + config)
"""
import numpy as np
from typing import Optional

from worker.ml.fast_model import INTENT_LABELS, INTENT_TO_QUEUE, INTENT_TO_PRIORITY


class SmartModel:
    def __init__(self):
        self.tokenizer = None
        self.model = None
        self._loaded = False

    def load(self, model_path: str):
        """Загрузка модели. Использует CPU если CUDA недоступна."""
        import torch
        from transformers import AutoTokenizer, AutoModelForSequenceClassification

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
            max_length=512,
            padding=True,
        )
        inputs = {k: v.to(self.device) for k, v in inputs.items()}

        with torch.no_grad():
            outputs = self.model(**inputs)
            probas = F.softmax(outputs.logits, dim=-1)[0].cpu().numpy()

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


# Singleton
smart_model_instance: Optional[SmartModel] = None


def get_smart_model() -> SmartModel:
    global smart_model_instance
    if smart_model_instance is None:
        raise RuntimeError("SmartModel not initialized — call init_smart_model() at startup")
    return smart_model_instance


def init_smart_model(model_path: str) -> SmartModel:
    global smart_model_instance
    smart_model_instance = SmartModel()
    smart_model_instance.load(model_path)
    return smart_model_instance
