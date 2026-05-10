import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, DateTime, Numeric, String, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.core.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class HITLTask(Base):
    __tablename__ = "hitl_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    prediction_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("prediction_tasks.id"), nullable=False)
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_prediction: Mapped[str] = mapped_column(String(100), nullable=False)
    model_confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    correct_label: Mapped[str | None] = mapped_column(String(100))  # after human review
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | completed | skipped
    reward_credits: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=5.00)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    completions: Mapped[list["HITLCompletion"]] = relationship("HITLCompletion", back_populates="task")


class HITLCompletion(Base):
    __tablename__ = "hitl_completions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hitl_task_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("hitl_tasks.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    label_chosen: Mapped[str] = mapped_column(String(100), nullable=False)
    bonus_credited: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.00)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    task: Mapped["HITLTask"] = relationship("HITLTask", back_populates="completions")
