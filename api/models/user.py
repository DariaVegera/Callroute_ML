import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, ForeignKey, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.core.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(50), default="user")
    loyalty_level: Mapped[str] = mapped_column(String(20), default="bronze")
    predictions_this_month: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    balance: Mapped["UserBalance"] = relationship("UserBalance", back_populates="user", uselist=False)
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="user")
    prediction_tasks: Mapped[list["PredictionTask"]] = relationship("PredictionTask", back_populates="user")


class UserBalance(Base):
    __tablename__ = "user_balances"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    bought_credits: Mapped[float] = mapped_column(Numeric(12, 2), default=0.00)
    bonus_credits: Mapped[float] = mapped_column(Numeric(12, 2), default=0.00)
    version: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

    user: Mapped["User"] = relationship("User", back_populates="balance")
