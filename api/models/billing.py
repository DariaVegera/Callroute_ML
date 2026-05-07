import uuid
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy import DateTime, Numeric, String, ForeignKey, Text, Boolean, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from api.core.database import Base


def now_utc():
    return datetime.now(timezone.utc)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    # DEBIT_PREDICTION | CREDIT_PURCHASE | CREDIT_BONUS_HITL | CREDIT_BONUS_REFERRAL | CREDIT_CASHBACK | REFUND
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_type: Mapped[str] = mapped_column(String(20), nullable=False)  # bought | bonus
    balance_before: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    reference_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reference_type: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    user: Mapped["User"] = relationship("User", back_populates="transactions")  # type: ignore


class LoyaltyLevel(Base):
    __tablename__ = "loyalty_levels"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # bronze | silver | gold
    min_predictions: Mapped[int] = mapped_column(Integer, default=0)
    discount_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.00)
    cashback_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0.00)
    description: Mapped[str | None] = mapped_column(Text)


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    bonus_per_referral: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=50.00)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class ReferralEvent(Base):
    __tablename__ = "referral_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    referrer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    referred_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), unique=True, nullable=False)
    bonus_credited: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.00)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class WeeklyCashbackLog(Base):
    __tablename__ = "weekly_cashback_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    week_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    total_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.00)
    cashback_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0.00)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
