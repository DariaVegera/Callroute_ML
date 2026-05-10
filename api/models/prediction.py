import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Numeric, String, ForeignKey, Text, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.core.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class PredictionTier(Base):
    __tablename__ = "prediction_tiers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # fast | smart | batch
    model_key: Mapped[str] = mapped_column(String(100), nullable=False)
    base_cost: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    max_input_chars: Mapped[int] = mapped_column(Integer, default=5000)
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    tasks: Mapped[list["PredictionTask"]] = relationship("PredictionTask", back_populates="tier")


class PredictionTask(Base):
    __tablename__ = "prediction_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    tier_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prediction_tiers.id"), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    # pending | processing | completed | failed | refunded
    predicted_intent: Mapped[str | None] = mapped_column(String(100))
    predicted_priority: Mapped[str | None] = mapped_column(String(20))  # low | medium | high | critical
    queue_recommendation: Mapped[str | None] = mapped_column(String(100))
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    low_confidence: Mapped[bool] = mapped_column(Boolean, default=False)
    credits_charged: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    error_message: Mapped[str | None] = mapped_column(Text)
    celery_task_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship("User", back_populates="prediction_tasks")  # type: ignore
    tier: Mapped["PredictionTier"] = relationship("PredictionTier", back_populates="tasks")


class MLModel(Base):
    __tablename__ = "ml_models"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    artifact_path: Mapped[str] = mapped_column(String(500), nullable=False)
    metrics: Mapped[dict | None] = mapped_column(JSON)  # {"accuracy": 0.92, "f1": 0.91}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
