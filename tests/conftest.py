"""
conftest.py — фикстуры для тестирования CallRoute ML API.

Запуск:
    pip install pytest pytest-asyncio httpx
    pytest tests/ -v

Требования: запущенные postgres + redis (docker-compose up postgres redis)
Или можно использовать SQLite для unit-тестов (см. DATABASE_URL_TEST ниже).
"""

import asyncio
import os
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

# Используем отдельную тестовую БД
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://callroute:callroute_secret@localhost:5432/callroute_test",
)

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["SECRET_KEY"] = "test_secret_key_32_chars_for_tests"
os.environ["DEFAULT_SIGNUP_BONUS"] = "100"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"  # отдельная БД redis для тестов
os.environ["CELERY_BROKER_URL"] = "redis://localhost:6379/15"
os.environ["CELERY_RESULT_BACKEND"] = "redis://localhost:6379/15"

from api.core.database import Base, get_db
from api.main import app

# Тестовый движок
test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(
    bind=test_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@pytest.fixture(scope="session")
def event_loop():
    """Единый event loop на всю сессию тестов."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    """Создаём схему один раз для всей сессии."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # Засеять loyalty_levels и prediction_tiers
    async with TestSessionLocal() as db:
        from sqlalchemy import text
        await db.execute(text("""
            INSERT INTO loyalty_levels (id, name, min_predictions, discount_percent, cashback_percent, description)
            VALUES
                (gen_random_uuid(), 'bronze', 0,   0.00, 1.00, 'Default'),
                (gen_random_uuid(), 'silver', 100, 5.00, 3.00, 'Silver'),
                (gen_random_uuid(), 'gold',   500, 10.00, 5.00, 'Gold')
            ON CONFLICT (name) DO NOTHING
        """))
        await db.execute(text("""
            INSERT INTO prediction_tiers (id, name, model_key, base_cost, max_input_chars, description)
            VALUES
                (gen_random_uuid(), 'fast',  'catboost_tfidf', 1.00, 5000, 'Fast tier'),
                (gen_random_uuid(), 'smart', 'rubert_tiny2',   3.00, 5000, 'Smart tier'),
                (gen_random_uuid(), 'batch', 'rubert_tiny2',   2.00, 5000, 'Batch tier')
            ON CONFLICT (name) DO NOTHING
        """))
        await db.commit()

    yield

    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Сессия БД для каждого теста (с откатом после теста)."""
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """HTTP-клиент с подменённой зависимостью БД."""
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Вспомогательные функции ────────────────────────────────────────────────────

def unique_email(prefix: str = "user") -> str:
    """Генерирует уникальный email для каждого теста."""
    return f"{prefix}_{uuid.uuid4().hex[:8]}@test.com"


async def register_user(client: AsyncClient, email: str, password: str = "password123", full_name: str = "Test User") -> dict:
    """Регистрирует пользователя и возвращает данные ответа."""
    resp = await client.post("/api/v1/auth/register", json={
        "email": email,
        "password": password,
        "full_name": full_name,
    })
    assert resp.status_code == 201, f"Registration failed: {resp.text}"
    return resp.json()


async def get_token(client: AsyncClient, email: str, password: str = "password123") -> str:
    """Логинится и возвращает JWT-токен."""
    resp = await client.post("/api/v1/auth/login", data={
        "username": email,
        "password": password,
    })
    assert resp.status_code == 200, f"Login failed: {resp.text}"
    return resp.json()["access_token"]


async def auth_headers(client: AsyncClient, email: str, password: str = "password123") -> dict:
    """Возвращает заголовки с Bearer токеном."""
    token = await get_token(client, email, password)
    return {"Authorization": f"Bearer {token}"}


async def register_and_login(client: AsyncClient, prefix: str = "user") -> tuple[dict, dict]:
    """Регистрирует пользователя и возвращает (user_data, headers)."""
    email = unique_email(prefix)
    user = await register_user(client, email)
    headers = await auth_headers(client, email)
    return user, headers


async def create_admin(db_session: AsyncSession, email: str, password: str = "adminpass123") -> None:
    """Создаёт пользователя с ролью admin напрямую в БД."""
    from api.core.security import get_password_hash
    from api.models.user import User, UserBalance
    from api.core.config import settings

    admin = User(
        email=email,
        hashed_password=get_password_hash(password),
        full_name="Admin User",
        role="admin",
    )
    db_session.add(admin)
    await db_session.flush()

    balance = UserBalance(
        user_id=admin.id,
        bonus_credits=settings.default_signup_bonus,
    )
    db_session.add(balance)
    await db_session.commit()
