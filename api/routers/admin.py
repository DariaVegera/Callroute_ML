from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from api.core.database import get_db
from api.core.security import get_current_admin
from api.models.user import User, UserBalance
from api.models.billing import Transaction, LoyaltyLevel
from api.models.prediction import PredictionTask, PredictionTier

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def get_stats(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar()
    total_tasks = (await db.execute(select(func.count()).select_from(PredictionTask))).scalar()
    completed = (await db.execute(
        select(func.count()).select_from(PredictionTask).where(PredictionTask.status == "completed")
    )).scalar()
    total_revenue = (await db.execute(
        select(func.sum(PredictionTask.credits_charged)).where(PredictionTask.status == "completed")
    )).scalar() or 0

    return {
        "total_users": total_users,
        "total_tasks": total_tasks,
        "completed_tasks": completed,
        "total_credits_charged": float(total_revenue),
    }


@router.get("/users")
async def list_users(
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at.desc()).limit(100))
    users = result.scalars().all()
    return [
        {
            "id": str(u.id),
            "email": u.email,
            "role": u.role,
            "loyalty_level": u.loyalty_level,
            "predictions_this_month": u.predictions_this_month,
            "is_active": u.is_active,
            "created_at": u.created_at.isoformat(),
        }
        for u in users
    ]


@router.put("/tiers/{tier_name}")
async def update_tier(
    tier_name: str,
    base_cost: Decimal,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(PredictionTier).where(PredictionTier.name == tier_name)
    )
    tier = result.scalar_one_or_none()
    if not tier:
        raise HTTPException(status_code=404, detail="Тариф не найден")
    tier.base_cost = base_cost
    await db.commit()
    return {"status": "updated", "tier": tier_name, "new_cost": float(base_cost)}


@router.put("/loyalty/{level_name}")
async def update_loyalty(
    level_name: str,
    min_predictions: int,
    discount_percent: Decimal,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LoyaltyLevel).where(LoyaltyLevel.name == level_name)
    )
    level = result.scalar_one_or_none()
    if not level:
        raise HTTPException(status_code=404, detail="Уровень не найден")
    level.min_predictions = min_predictions
    level.discount_percent = discount_percent
    await db.commit()
    return {"status": "updated", "level": level_name}
