"""
test_predict.py — тесты роутера предиктов.

Celery send_task замокан — воркер не нужен.
Покрывает:
- POST /predict — создание задачи (успех, нехватка кредитов, слишком короткий текст,
  недопустимый тариф, идемпотентность)
- GET /predict/{task_id} — получение статуса задачи
- GET /predict — список задач с пагинацией и фильтром по статусу
- Изоляция: пользователь не видит чужие задачи

ВАЖНО: тариф batch не используется согласно требованиям.
"""

import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient
from decimal import Decimal
from sqlalchemy import text

from conftest import (
    unique_email, register_user, auth_headers, register_and_login
)

# ── Хелпер ────────────────────────────────────────────────────────────────────

async def top_up(client: AsyncClient, headers: dict, amount: float = 500.0):
    """Пополнить баланс пользователя."""
    resp = await client.post(
        "/api/v1/billing/topup",
        params={"amount": amount},
        headers=headers,
    )
    assert resp.status_code == 200, f"topup failed: {resp.text}"


async def create_predict(
    client: AsyncClient,
    headers: dict,
    text_input: str = "Хочу вернуть товар, он не подошёл по размеру",
    tier: str = "fast",
) -> dict:
    """Создать задачу предикта с замоканным Celery."""
    mock_result = MagicMock()
    mock_result.id = "celery-mock-task-id-001"

    with patch("api.routers.predict.Celery") as MockCelery:
        mock_app = MagicMock()
        mock_app.send_task.return_value = mock_result
        MockCelery.return_value = mock_app

        resp = await client.post(
            "/api/v1/predict",
            params={"text": text_input, "tier": tier},
            headers=headers,
        )
    return resp


# ══════════════════════════════════════════════════════════════════════
# POST /predict — создание задачи
# ══════════════════════════════════════════════════════════════════════

class TestCreatePrediction:

    @pytest.mark.asyncio
    async def test_create_prediction_success(self, client: AsyncClient):
        """Успешное создание задачи возвращает 202 и task_id."""
        email = unique_email("pred_ok")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        await top_up(client, headers)

        resp = await create_predict(client, headers)
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert "task_id" in data
        assert data["status"] == "pending"
        assert data["tier"] == "fast"
        assert data["estimated_credits"] > 0

    @pytest.mark.asyncio
    async def test_create_prediction_uses_bonus_credits(self, client: AsyncClient):
        """Предикт можно оплатить из бонусного баланса (100 кредитов при регистрации)."""
        email = unique_email("pred_bonus")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        # НЕ пополняем — используем signup bonus 100 кредитов

        resp = await create_predict(client, headers)
        assert resp.status_code == 202, resp.text

    @pytest.mark.asyncio
    async def test_create_prediction_insufficient_credits(self, client: AsyncClient, db_session):
        """Предикт без кредитов возвращает 402."""
        email = unique_email("pred_broke")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        # Обнуляем баланс напрямую в БД
        await db_session.execute(
            text("UPDATE user_balances SET bonus_credits = 0, bought_credits = 0 WHERE user_id = (SELECT id FROM users WHERE email = :e)"),
            {"e": email}
        )
        await db_session.commit()

        resp = await create_predict(client, headers)
        assert resp.status_code == 402
        assert "кредит" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_create_prediction_text_too_short(self, client: AsyncClient):
        """Текст меньше 5 символов — 422."""
        email = unique_email("pred_short")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        mock_result = MagicMock()
        mock_result.id = "celery-mock"
        with patch("api.routers.predict.Celery") as MockCelery:
            mock_app = MagicMock()
            mock_app.send_task.return_value = mock_result
            MockCelery.return_value = mock_app

            resp = await client.post(
                "/api/v1/predict",
                params={"text": "ab", "tier": "fast"},
                headers=headers,
            )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_create_prediction_invalid_tier(self, client: AsyncClient):
        """Несуществующий тариф — 400."""
        email = unique_email("pred_tier")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        mock_result = MagicMock()
        mock_result.id = "celery-mock"
        with patch("api.routers.predict.Celery") as MockCelery:
            mock_app = MagicMock()
            mock_app.send_task.return_value = mock_result
            MockCelery.return_value = mock_app

            resp = await client.post(
                "/api/v1/predict",
                params={"text": "Тестовый текст для предикта", "tier": "nonexistent"},
                headers=headers,
            )
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_create_prediction_unauthenticated(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.post(
            "/api/v1/predict",
            params={"text": "Тестовый текст для предикта", "tier": "fast"},
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_create_prediction_idempotency(self, client: AsyncClient):
        """Одинаковый idempotency_key возвращает ту же задачу без дублирования."""
        email = unique_email("pred_idem")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        await top_up(client, headers)

        idem_key = "my-unique-key-12345"
        mock_result = MagicMock()
        mock_result.id = "celery-mock-idem"

        with patch("api.routers.predict.Celery") as MockCelery:
            mock_app = MagicMock()
            mock_app.send_task.return_value = mock_result
            MockCelery.return_value = mock_app

            resp1 = await client.post(
                "/api/v1/predict",
                params={"text": "Проблема с оплатой заказа номер 999", "tier": "fast", "idempotency_key": idem_key},
                headers=headers,
            )
            resp2 = await client.post(
                "/api/v1/predict",
                params={"text": "Проблема с оплатой заказа номер 999", "tier": "fast", "idempotency_key": idem_key},
                headers=headers,
            )

        assert resp1.status_code == 202
        assert resp2.status_code in (200, 202)
        assert resp1.json()["task_id"] == resp2.json()["task_id"]

    @pytest.mark.asyncio
    async def test_create_prediction_fast_tier_cost(self, client: AsyncClient):
        """Тариф fast стоит 1.0 кредит (base_cost из seed data)."""
        email = unique_email("pred_cost")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await create_predict(client, headers)
        assert resp.status_code == 202
        assert resp.json()["estimated_credits"] == 1.0

    @pytest.mark.asyncio
    async def test_create_prediction_smart_tier(self, client: AsyncClient):
        """Тариф smart принимается и возвращает 202."""
        email = unique_email("pred_smart")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        await top_up(client, headers)

        resp = await create_predict(
            client, headers,
            text_input="У меня не работает личный кабинет, ошибка при входе",
            tier="smart"
        )
        assert resp.status_code == 202
        assert resp.json()["tier"] == "smart"

    @pytest.mark.asyncio
    async def test_create_prediction_response_structure(self, client: AsyncClient):
        """Ответ содержит все ожидаемые поля."""
        email = unique_email("pred_struct")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await create_predict(client, headers)
        assert resp.status_code == 202
        data = resp.json()
        for field in ["task_id", "status", "tier", "estimated_credits", "created_at"]:
            assert field in data, f"Missing field: {field}"


# ══════════════════════════════════════════════════════════════════════
# GET /predict/{task_id} — статус задачи
# ══════════════════════════════════════════════════════════════════════

class TestGetPrediction:

    @pytest.mark.asyncio
    async def test_get_prediction_pending(self, client: AsyncClient):
        """Новая задача имеет статус pending."""
        email = unique_email("get_pred")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await create_predict(client, headers)
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        resp2 = await client.get(f"/api/v1/predict/{task_id}", headers=headers)
        assert resp2.status_code == 200
        data = resp2.json()
        assert data["task_id"] == task_id
        assert data["status"] in ("pending", "processing", "completed", "failed")

    @pytest.mark.asyncio
    async def test_get_prediction_not_found(self, client: AsyncClient):
        """Несуществующий task_id — 404."""
        email = unique_email("get_404")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get(
            "/api/v1/predict/00000000-0000-0000-0000-000000000001",
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_access_another_users_task(self, client: AsyncClient):
        """Пользователь не может получить задачу чужого пользователя."""
        email1 = unique_email("iso1_pred")
        email2 = unique_email("iso2_pred")
        await register_user(client, email1)
        await register_user(client, email2)
        headers1 = await auth_headers(client, email1)
        headers2 = await auth_headers(client, email2)

        resp = await create_predict(client, headers1)
        assert resp.status_code == 202
        task_id = resp.json()["task_id"]

        # Второй пользователь пытается получить задачу первого
        resp2 = await client.get(f"/api/v1/predict/{task_id}", headers=headers2)
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_get_prediction_unauthenticated(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.get(
            "/api/v1/predict/00000000-0000-0000-0000-000000000001"
        )
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_get_prediction_response_fields(self, client: AsyncClient):
        """Ответ содержит обязательные поля."""
        email = unique_email("pred_fields")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await create_predict(client, headers)
        task_id = resp.json()["task_id"]

        resp2 = await client.get(f"/api/v1/predict/{task_id}", headers=headers)
        data = resp2.json()
        for field in ["task_id", "status", "low_confidence", "created_at"]:
            assert field in data


# ══════════════════════════════════════════════════════════════════════
# GET /predict — список задач
# ══════════════════════════════════════════════════════════════════════

class TestListPredictions:

    @pytest.mark.asyncio
    async def test_list_predictions_empty(self, client: AsyncClient):
        """Новый пользователь — пустой список задач."""
        email = unique_email("list_empty")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/predict", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    @pytest.mark.asyncio
    async def test_list_predictions_after_create(self, client: AsyncClient):
        """После создания задача появляется в списке."""
        email = unique_email("list_after")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp_create = await create_predict(client, headers)
        assert resp_create.status_code == 202
        task_id = resp_create.json()["task_id"]

        resp_list = await client.get("/api/v1/predict", headers=headers)
        assert resp_list.status_code == 200
        items = resp_list.json()["items"]
        ids = [i["task_id"] for i in items]
        assert task_id in ids

    @pytest.mark.asyncio
    async def test_list_predictions_pagination(self, client: AsyncClient):
        """Пагинация: size ограничивает количество результатов."""
        email = unique_email("list_page")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        # Создаём 3 задачи
        for _ in range(3):
            await create_predict(client, headers)

        resp = await client.get("/api/v1/predict?page=1&size=2", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2
        assert data["total"] >= 3

    @pytest.mark.asyncio
    async def test_list_predictions_status_filter(self, client: AsyncClient):
        """Фильтр по статусу возвращает только задачи с нужным статусом."""
        email = unique_email("list_filt")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await create_predict(client, headers)

        resp = await client.get("/api/v1/predict?status_filter=pending", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        # Все задачи в ответе — pending (воркер не работает в тестах)
        for item in items:
            assert item["status"] == "pending"

    @pytest.mark.asyncio
    async def test_list_predictions_isolation(self, client: AsyncClient):
        """Пользователь видит только свои задачи."""
        email1 = unique_email("listiso1")
        email2 = unique_email("listiso2")
        await register_user(client, email1)
        await register_user(client, email2)
        headers1 = await auth_headers(client, email1)
        headers2 = await auth_headers(client, email2)

        resp = await create_predict(client, headers1)
        task_id = resp.json()["task_id"]

        resp2 = await client.get("/api/v1/predict", headers=headers2)
        ids = [i["task_id"] for i in resp2.json()["items"]]
        assert task_id not in ids

    @pytest.mark.asyncio
    async def test_list_predictions_unauthenticated(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.get("/api/v1/predict")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_list_predictions_response_structure(self, client: AsyncClient):
        """Ответ содержит поля пагинации."""
        email = unique_email("list_struct")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/predict", headers=headers)
        data = resp.json()
        for field in ["items", "total", "page", "size", "pages"]:
            assert field in data
