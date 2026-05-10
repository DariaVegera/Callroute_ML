import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from api.core.database import get_db
from api.core.security import (
    verify_password, get_password_hash, create_access_token, get_current_user
)
from api.core.config import settings
from api.models.user import User, UserBalance
from api.models.billing import ReferralCode, ReferralEvent, Transaction
from api.schemas.auth import UserRegisterRequest, TokenResponse, UserResponse, BalanceResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse, status_code=201)
async def register(payload: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=get_password_hash(payload.password),
        full_name=payload.full_name,
    )
    db.add(user)
    await db.flush()

    balance = UserBalance(
        user_id=user.id,
        bonus_credits=settings.default_signup_bonus,
    )
    db.add(balance)

    bonus_tx = Transaction(
        user_id=user.id,
        type="CREDIT_BONUS_SIGNUP",
        amount=settings.default_signup_bonus,
        balance_type="bonus",
        balance_before=0,
        balance_after=settings.default_signup_bonus,
        description="Welcome bonus",
        reference_type="signup",
    )
    db.add(bonus_tx)

    ref_code = ReferralCode(
        user_id=user.id,
        code=f"REF-{str(user.id)[:8].upper()}",
    )
    db.add(ref_code)

    if payload.referral_code:
        result = await db.execute(
            select(ReferralCode).where(
                ReferralCode.code == payload.referral_code,
                ReferralCode.is_active == True,
            )
        )
        ref = result.scalar_one_or_none()
        if ref and ref.user_id != user.id:
            referrer_balance_res = await db.execute(
                select(UserBalance).where(UserBalance.user_id == ref.user_id)
            )
            referrer_balance = referrer_balance_res.scalar_one_or_none()
            if referrer_balance:
                before = float(referrer_balance.bonus_credits)
                referrer_balance.bonus_credits = before + float(ref.bonus_per_referral)
                db.add(Transaction(
                    user_id=ref.user_id,
                    type="CREDIT_BONUS_REFERRAL",
                    amount=ref.bonus_per_referral,
                    balance_type="bonus",
                    balance_before=before,
                    balance_after=float(referrer_balance.bonus_credits),
                    description=f"Referral bonus for {user.email}",
                    reference_id=user.id,
                    reference_type="referral",
                ))

            db.add(ReferralEvent(
                referrer_id=ref.user_id,
                referred_id=user.id,
                bonus_credited=ref.bonus_per_referral,
            ))

    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form_data.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is disabled")

    token = create_access_token({"sub": str(user.id), "role": user.role})
    return {"access_token": token, "token_type": "bearer"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/balance", response_model=BalanceResponse)
async def get_balance(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(UserBalance).where(UserBalance.user_id == current_user.id)
    )
    balance = result.scalar_one_or_none()
    if not balance:
        raise HTTPException(status_code=404, detail="Balance not found")
    bought = float(balance.bought_credits)
    bonus = float(balance.bonus_credits)
    return BalanceResponse(
        bought_credits=bought,
        bonus_credits=bonus,
        total_credits=bought + bonus,
    )
