"""
BillingService — атомарное списание кредитов.

Порядок списания: сначала bonus_credits, потом bought_credits.
Используем SELECT FOR UPDATE + version для оптимистичной блокировки.
"""
from decimal import Decimal
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from api.models.user import User, UserBalance
from api.models.billing import Transaction, LoyaltyLevel


class BillingService:

    @staticmethod
    async def get_effective_cost(user_id: UUID, base_cost: Decimal, db: AsyncSession) -> Decimal:
        """Применить скидку лояльности к базовой стоимости."""
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            return base_cost

        level_result = await db.execute(
            select(LoyaltyLevel).where(LoyaltyLevel.name == user.loyalty_level)
        )
        level = level_result.scalar_one_or_none()
        if not level or level.discount_percent == 0:
            return base_cost

        discount = base_cost * (level.discount_percent / Decimal("100"))
        return max(Decimal("0.01"), base_cost - discount)

    @staticmethod
    async def check_balance(user_id: UUID, amount: Decimal, db: AsyncSession) -> bool:
        """Быстрая проверка баланса без блокировки (pre-check)."""
        result = await db.execute(
            select(UserBalance).where(UserBalance.user_id == user_id)
        )
        balance = result.scalar_one_or_none()
        if not balance:
            return False
        total = Decimal(str(balance.bought_credits)) + Decimal(str(balance.bonus_credits))
        return total >= amount

    @staticmethod
    async def deduct_credits(
        user_id: UUID,
        amount: Decimal,
        task_id: UUID,
        db: AsyncSession,
    ) -> dict:
        """
        Атомарное списание с блокировкой строки.
        Сначала списывает bonus, потом bought.
        Возвращает {'deducted': amount, 'from_bonus': x, 'from_bought': y}.
        """
        # SELECT FOR UPDATE — блокируем строку баланса
        result = await db.execute(
            select(UserBalance)
            .where(UserBalance.user_id == user_id)
            .with_for_update()
        )
        balance = result.scalar_one_or_none()
        if not balance:
            raise HTTPException(status_code=404, detail="Balance record not found")

        bonus = Decimal(str(balance.bonus_credits))
        bought = Decimal(str(balance.bought_credits))
        total = bonus + bought

        if total < amount:
            raise HTTPException(status_code=402, detail="Insufficient credits")

        # Списываем с bonus сначала
        from_bonus = min(bonus, amount)
        remaining = amount - from_bonus
        from_bought = remaining

        bonus_before = bonus
        bought_before = bought

        balance.bonus_credits = bonus - from_bonus
        balance.bought_credits = bought - from_bought
        balance.version += 1

        transactions = []

        if from_bonus > 0:
            transactions.append(Transaction(
                user_id=user_id,
                type="DEBIT_PREDICTION",
                amount=from_bonus,
                balance_type="bonus",
                balance_before=float(bonus_before),
                balance_after=float(balance.bonus_credits),
                description=f"Prediction charge (bonus)",
                reference_id=task_id,
                reference_type="prediction",
            ))

        if from_bought > 0:
            transactions.append(Transaction(
                user_id=user_id,
                type="DEBIT_PREDICTION",
                amount=from_bought,
                balance_type="bought",
                balance_before=float(bought_before),
                balance_after=float(balance.bought_credits),
                description=f"Prediction charge (bought)",
                reference_id=task_id,
                reference_type="prediction",
            ))

        for tx in transactions:
            db.add(tx)

        # Increment monthly counter
        user_result = await db.execute(select(User).where(User.id == user_id).with_for_update())
        user = user_result.scalar_one_or_none()
        if user:
            user.predictions_this_month = (user.predictions_this_month or 0) + 1

        await db.commit()

        return {
            "deducted": float(amount),
            "from_bonus": float(from_bonus),
            "from_bought": float(from_bought),
        }

    @staticmethod
    async def refund_credits(
        user_id: UUID,
        amount: Decimal,
        task_id: UUID,
        db: AsyncSession,
    ) -> None:
        """Возврат кредитов на bought-счёт при ошибке воркера."""
        result = await db.execute(
            select(UserBalance)
            .where(UserBalance.user_id == user_id)
            .with_for_update()
        )
        balance = result.scalar_one_or_none()
        if not balance:
            return

        before = float(balance.bought_credits)
        balance.bought_credits = Decimal(str(balance.bought_credits)) + amount
        balance.version += 1

        db.add(Transaction(
            user_id=user_id,
            type="REFUND",
            amount=amount,
            balance_type="bought",
            balance_before=before,
            balance_after=float(balance.bought_credits),
            description="Refund due to prediction failure",
            reference_id=task_id,
            reference_type="prediction",
        ))
        await db.commit()

    @staticmethod
    async def top_up(
        user_id: UUID,
        amount: Decimal,
        db: AsyncSession,
        balance_type: str = "bought",
        description: str = "Manual top-up",
    ) -> None:
        """Пополнение баланса (покупка кредитов или начисление бонусов)."""
        result = await db.execute(
            select(UserBalance)
            .where(UserBalance.user_id == user_id)
            .with_for_update()
        )
        balance = result.scalar_one_or_none()
        if not balance:
            raise HTTPException(status_code=404, detail="Balance not found")

        if balance_type == "bonus":
            before = float(balance.bonus_credits)
            balance.bonus_credits = Decimal(str(balance.bonus_credits)) + amount
            after = float(balance.bonus_credits)
        else:
            before = float(balance.bought_credits)
            balance.bought_credits = Decimal(str(balance.bought_credits)) + amount
            after = float(balance.bought_credits)

        tx_type = "CREDIT_PURCHASE" if balance_type == "bought" else "CREDIT_BONUS_HITL"
        db.add(Transaction(
            user_id=user_id,
            type=tx_type,
            amount=amount,
            balance_type=balance_type,
            balance_before=before,
            balance_after=after,
            description=description,
        ))
        await db.commit()
