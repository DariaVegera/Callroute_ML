from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from api.core.database import get_db
from api.core.security import get_current_user
from api.models.user import User, UserBalance
from api.models.billing import Transaction, LoyaltyLevel
from api.models.prediction import PredictionTier
from api.services.billing_service import BillingService

router = APIRouter(prefix="/billing", tags=["billing"])


@router.get("/balance")
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserBalance).where(UserBalance.user_id == current_user.id)
    )
    balance = result.scalar_one_or_none()
    if not balance:
        raise HTTPException(status_code=404, detail="Баланс не найден")

    level_result = await db.execute(
        select(LoyaltyLevel).where(LoyaltyLevel.name == current_user.loyalty_level)
    )
    level = level_result.scalar_one_or_none()
    discount = float(level.discount_percent) if level else 0.0

    bought = float(balance.bought_credits)
    bonus = float(balance.bonus_credits)
    return {
        "bought_credits": bought,
        "bonus_credits": bonus,
        "total_credits": bought + bonus,
        "loyalty_level": current_user.loyalty_level,
        "discount_pct": discount,
    }


@router.get("/transactions")
async def get_transactions(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    tx_type: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Transaction).where(Transaction.user_id == current_user.id)
    if tx_type:
        query = query.where(Transaction.type == tx_type)
    query = query.order_by(desc(Transaction.created_at))

    count_result = await db.execute(
        select(func.count()).select_from(
            select(Transaction).where(
                Transaction.user_id == current_user.id
            ).subquery()
        )
    )
    total = count_result.scalar()
    result = await db.execute(query.offset((page - 1) * size).limit(size))
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": str(t.id),
                "type": t.type,
                "amount": float(t.amount),
                "balance_type": t.balance_type,
                "balance_before": float(t.balance_before),
                "balance_after": float(t.balance_after),
                "description": t.description,
                "reference_type": t.reference_type,
                "created_at": t.created_at.isoformat(),
            }
            for t in items
        ],
        "total": total,
        "page": page,
        "size": size,
        "pages": (total + size - 1) // size,
    }


@router.post("/topup")
async def top_up(
    amount: Decimal,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if amount <= 0 or amount > 10000:
        raise HTTPException(status_code=422, detail="Сумма должна быть от 0.01 до 10000")

    await BillingService.top_up(
        user_id=current_user.id,
        amount=amount,
        db=db,
        balance_type="bought",
        description=f"Пополнение баланса: {amount} кредитов",
    )

    result = await db.execute(
        select(UserBalance).where(UserBalance.user_id == current_user.id)
    )
    balance = result.scalar_one_or_none()
    return {
        "status": "ok",
        "new_bought_balance": float(balance.bought_credits),
        "new_bonus_balance": float(balance.bonus_credits),
    }


@router.get("/tiers")
async def get_tiers(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(PredictionTier).where(PredictionTier.is_active == True)
    )
    tiers = result.scalars().all()
    return [
        {
            "id": str(t.id),
            "name": t.name,
            "model_key": t.model_key,
            "base_cost": float(t.base_cost),
            "description": t.description,
            "max_input_chars": t.max_input_chars,
        }
        for t in tiers
    ]


@router.get("/loyalty")
async def get_loyalty_status(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LoyaltyLevel).order_by(LoyaltyLevel.min_predictions)
    )
    all_levels = result.scalars().all()
    level_map = {lv.name: lv for lv in all_levels}
    levels_order = [lv.name for lv in all_levels]

    current = level_map.get(current_user.loyalty_level)
    idx = levels_order.index(current_user.loyalty_level) if current_user.loyalty_level in levels_order else 0

    next_level = None
    to_next = None
    if idx < len(levels_order) - 1:
        next_name = levels_order[idx + 1]
        next_obj = level_map[next_name]
        next_level = next_name
        to_next = max(0, next_obj.min_predictions - current_user.predictions_this_month)

    return {
        "current_level": current_user.loyalty_level,
        "discount_pct": float(current.discount_percent) if current else 0.0,
        "cashback_pct": float(current.cashback_percent) if current else 0.0,
        "predictions_this_month": current_user.predictions_this_month,
        "next_level": next_level,
        "predictions_to_next_level": to_next,
    }


@router.get("/hitl/tasks")
async def get_hitl_tasks(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text
    result = await db.execute(
        text("""
            SELECT ht.id, ht.input_text, ht.model_prediction,
                   ht.model_confidence, ht.reward_credits, ht.expires_at
            FROM hitl_tasks ht
            JOIN prediction_tasks pt ON ht.prediction_task_id = pt.id
            WHERE ht.status = 'pending'
              AND pt.user_id != :uid
              AND (ht.expires_at IS NULL OR ht.expires_at > NOW())
            ORDER BY ht.created_at DESC
            LIMIT 10
        """),
        {"uid": str(current_user.id)}
    )
    rows = result.fetchall()
    return [
        {
            "id": str(r.id),
            "input_text": r.input_text,
            "model_prediction": r.model_prediction,
            "model_confidence": float(r.model_confidence),
            "reward_credits": float(r.reward_credits),
            "expires_at": r.expires_at.isoformat() if r.expires_at else None,
        }
        for r in rows
    ]


@router.post("/hitl/tasks/{hitl_id}/complete")
async def complete_hitl_task(
    hitl_id: str,
    correct_label: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import text
    from api.models.hitl import HITLCompletion
    import uuid as uuid_module

    VALID_INTENTS = [
        "return_request", "technical_issue", "payment_issue", "fraud_report",
        "general_inquiry", "complaint", "account_management", "escalation_request",
    ]
    if correct_label not in VALID_INTENTS:
        raise HTTPException(status_code=422, detail=f"Невалидный интент. Допустимые: {VALID_INTENTS}")

    row = await db.execute(
        text("""
            SELECT ht.id, ht.status, ht.reward_credits, pt.user_id as task_owner
            FROM hitl_tasks ht
            JOIN prediction_tasks pt ON ht.prediction_task_id = pt.id
            WHERE ht.id = :hid
        """),
        {"hid": hitl_id}
    )
    task_row = row.fetchone()

    if not task_row:
        raise HTTPException(status_code=404, detail="HITL-задание не найдено")
    if task_row.status != "pending":
        raise HTTPException(status_code=400, detail="Задание уже выполнено или истекло")
    if str(task_row.task_owner) == str(current_user.id):
        raise HTTPException(status_code=403, detail="Нельзя размечать собственные предикты")

    await db.execute(
        text("""
            UPDATE hitl_tasks
            SET status = 'completed', correct_label = :label
            WHERE id = :hid
        """),
        {"label": correct_label, "hid": hitl_id}
    )

    completion = HITLCompletion(
        hitl_task_id=uuid_module.UUID(hitl_id),
        user_id=current_user.id,
        label_chosen=correct_label,
        bonus_credited=task_row.reward_credits,
    )
    db.add(completion)

    await BillingService.top_up(
        user_id=current_user.id,
        amount=Decimal(str(task_row.reward_credits)),
        db=db,
        balance_type="bonus",
        description=f"HITL разметка — бонус {task_row.reward_credits} кредитов",
    )

    await db.commit()
    return {
        "status": "completed",
        "bonus_credited": float(task_row.reward_credits),
        "message": f"Спасибо! Начислено {task_row.reward_credits} бонусных кредитов.",
    }
