"""
test_billing.py — тесты биллинговой подсистемы.

Покрывает:
- GET /billing/balance — текущий баланс с уровнем лояльности
- POST /billing/topup — пополнение баланса (валидация, атомарность)
- GET /billing/transactions — история транзакций, пагинация, фильтр по типу
- GET /billing/tiers — тарифные планы
- GET /billing/loyalty — уровень лояльности и прогресс
- Атомарность: баланс корректен после нескольких пополнений
- Защита: неавторизованный доступ отклоняется
"""

import pytest
from httpx import AsyncClient

from tests.conftest import (
    unique_email, register_user, auth_headers, register_and_login
)


# ══════════════════════════════════════════════════════════════════════
# GET /billing/balance
# ══════════════════════════════════════════════════════════════════════

class TestBillingBalance:

    @pytest.mark.asyncio
    async def test_balance_after_registration(self, client: AsyncClient):
        """После регистрации баланс содержит 100 бонусных кредитов."""
        email = unique_email("bbal")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/balance", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["bought_credits"] == 0.0
        assert data["bonus_credits"] == 100.0
        assert data["total_credits"] == 100.0
        assert data["loyalty_level"] == "bronze"
        assert "discount_pct" in data

    @pytest.mark.asyncio
    async def test_balance_unauthenticated(self, client: AsyncClient):
        """Неавторизованный запрос — 401."""
        resp = await client.get("/api/v1/billing/balance")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_balance_structure(self, client: AsyncClient):
        """Ответ содержит все ожидаемые поля."""
        email = unique_email("bstruct")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/balance", headers=headers)
        data = resp.json()
        required_fields = {"bought_credits", "bonus_credits", "total_credits", "loyalty_level", "discount_pct"}
        assert required_fields.issubset(data.keys())


# ══════════════════════════════════════════════════════════════════════
# POST /billing/topup
# ══════════════════════════════════════════════════════════════════════

class TestTopUp:

    @pytest.mark.asyncio
    async def test_topup_success(self, client: AsyncClient):
        """Пополнение баланса увеличивает bought_credits."""
        email = unique_email("topup")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.post(
            "/api/v1/billing/topup",
            params={"amount": 200},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["new_bought_balance"] == 200.0

    @pytest.mark.asyncio
    async def test_topup_multiple_times(self, client: AsyncClient):
        """Несколько пополнений суммируются корректно."""
        email = unique_email("topupx")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await client.post("/api/v1/billing/topup", params={"amount": 100}, headers=headers)
        await client.post("/api/v1/billing/topup", params={"amount": 50}, headers=headers)
        await client.post("/api/v1/billing/topup", params={"amount": 25}, headers=headers)

        resp = await client.get("/api/v1/billing/balance", headers=headers)
        assert resp.json()["bought_credits"] == 175.0

    @pytest.mark.asyncio
    async def test_topup_zero_rejected(self, client: AsyncClient):
        """Пополнение на 0 — ошибка валидации."""
        email = unique_email("topup0")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.post(
            "/api/v1/billing/topup",
            params={"amount": 0},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_topup_exceeds_max_rejected(self, client: AsyncClient):
        """Пополнение больше 10000 — ошибка валидации."""
        email = unique_email("topupmax")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.post(
            "/api/v1/billing/topup",
            params={"amount": 10001},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_topup_negative_rejected(self, client: AsyncClient):
        """Отрицательная сумма — ошибка валидации."""
        email = unique_email("topupneg")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.post(
            "/api/v1/billing/topup",
            params={"amount": -50},
            headers=headers,
        )
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_topup_unauthenticated(self, client: AsyncClient):
        """Пополнение без токена — 401."""
        resp = await client.post("/api/v1/billing/topup", params={"amount": 100})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_topup_creates_transaction(self, client: AsyncClient):
        """После пополнения появляется транзакция типа CREDIT_PURCHASE."""
        email = unique_email("topuptx")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await client.post("/api/v1/billing/topup", params={"amount": 300}, headers=headers)

        resp = await client.get("/api/v1/billing/transactions", headers=headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        purchase_txs = [t for t in items if t["type"] == "CREDIT_PURCHASE"]
        assert len(purchase_txs) >= 1
        assert purchase_txs[0]["amount"] == 300.0
        assert purchase_txs[0]["balance_type"] == "bought"

    @pytest.mark.asyncio
    async def test_topup_does_not_affect_bonus(self, client: AsyncClient):
        """Пополнение не меняет бонусный баланс."""
        email = unique_email("topupb")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        bonus_before = (await client.get("/api/v1/billing/balance", headers=headers)).json()["bonus_credits"]
        await client.post("/api/v1/billing/topup", params={"amount": 500}, headers=headers)
        bonus_after = (await client.get("/api/v1/billing/balance", headers=headers)).json()["bonus_credits"]

        assert bonus_before == bonus_after  # бонус не изменился

    @pytest.mark.asyncio
    async def test_topup_decimal_amount(self, client: AsyncClient):
        """Пополнение дробной суммой работает корректно."""
        email = unique_email("topupdec")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.post(
            "/api/v1/billing/topup",
            params={"amount": 99.99},
            headers=headers,
        )
        assert resp.status_code == 200
        assert abs(resp.json()["new_bought_balance"] - 99.99) < 0.01


# ══════════════════════════════════════════════════════════════════════
# GET /billing/transactions
# ══════════════════════════════════════════════════════════════════════

class TestTransactions:

    @pytest.mark.asyncio
    async def test_transactions_after_signup(self, client: AsyncClient):
        """После регистрации есть транзакция CREDIT_BONUS_SIGNUP."""
        email = unique_email("tx_signup")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/transactions", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        types = [t["type"] for t in data["items"]]
        assert "CREDIT_BONUS_SIGNUP" in types

    @pytest.mark.asyncio
    async def test_transactions_pagination(self, client: AsyncClient):
        """Пагинация работает: page и size корректно ограничивают результат."""
        email = unique_email("tx_page")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        # Создаём несколько транзакций
        for _ in range(5):
            await client.post("/api/v1/billing/topup", params={"amount": 10}, headers=headers)

        resp_full = await client.get("/api/v1/billing/transactions?size=100", headers=headers)
        total = resp_full.json()["total"]

        resp_page = await client.get("/api/v1/billing/transactions?page=1&size=3", headers=headers)
        data = resp_page.json()
        assert len(data["items"]) <= 3
        assert data["size"] == 3
        assert data["total"] == total

    @pytest.mark.asyncio
    async def test_transactions_filter_by_type(self, client: AsyncClient):
        """Фильтр по типу транзакции возвращает только нужные записи."""
        email = unique_email("tx_filter")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await client.post("/api/v1/billing/topup", params={"amount": 50}, headers=headers)

        resp = await client.get(
            "/api/v1/billing/transactions?tx_type=CREDIT_PURCHASE",
            headers=headers,
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert all(t["type"] == "CREDIT_PURCHASE" for t in items)

    @pytest.mark.asyncio
    async def test_transactions_balance_before_after(self, client: AsyncClient):
        """Транзакции содержат корректные balance_before и balance_after."""
        email = unique_email("tx_bal")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await client.post("/api/v1/billing/topup", params={"amount": 100}, headers=headers)

        resp = await client.get(
            "/api/v1/billing/transactions?tx_type=CREDIT_PURCHASE",
            headers=headers,
        )
        tx = resp.json()["items"][0]
        assert tx["balance_before"] >= 0
        assert tx["balance_after"] == tx["balance_before"] + tx["amount"]

    @pytest.mark.asyncio
    async def test_transactions_isolation_between_users(self, client: AsyncClient):
        """Пользователь видит только свои транзакции."""
        email1 = unique_email("tx_iso1")
        email2 = unique_email("tx_iso2")
        await register_user(client, email1)
        await register_user(client, email2)
        headers1 = await auth_headers(client, email1)
        headers2 = await auth_headers(client, email2)

        # Пополняем только первого
        await client.post("/api/v1/billing/topup", params={"amount": 500}, headers=headers1)

        # Второй не должен видеть транзакцию первого
        resp2 = await client.get("/api/v1/billing/transactions?tx_type=CREDIT_PURCHASE", headers=headers2)
        items2 = resp2.json()["items"]
        purchase_amounts = [t["amount"] for t in items2]
        assert 500.0 not in purchase_amounts

    @pytest.mark.asyncio
    async def test_transactions_unauthenticated(self, client: AsyncClient):
        """Неавторизованный запрос — 401."""
        resp = await client.get("/api/v1/billing/transactions")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_transactions_sorted_by_date_desc(self, client: AsyncClient):
        """Транзакции отсортированы от новых к старым."""
        email = unique_email("tx_sort")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        await client.post("/api/v1/billing/topup", params={"amount": 10}, headers=headers)
        await client.post("/api/v1/billing/topup", params={"amount": 20}, headers=headers)

        resp = await client.get("/api/v1/billing/transactions?size=10", headers=headers)
        items = resp.json()["items"]
        if len(items) >= 2:
            from datetime import datetime
            dates = [datetime.fromisoformat(t["created_at"].replace("Z", "+00:00")) for t in items]
            assert dates == sorted(dates, reverse=True)


# ══════════════════════════════════════════════════════════════════════
# GET /billing/tiers
# ══════════════════════════════════════════════════════════════════════

class TestTiers:

    @pytest.mark.asyncio
    async def test_tiers_available(self, client: AsyncClient):
        """Эндпоинт тарифов возвращает список (публичный, без авторизации)."""
        resp = await client.get("/api/v1/billing/tiers")
        assert resp.status_code == 200
        tiers = resp.json()
        assert isinstance(tiers, list)
        assert len(tiers) >= 1

    @pytest.mark.asyncio
    async def test_tiers_have_required_fields(self, client: AsyncClient):
        """Каждый тариф содержит обязательные поля."""
        resp = await client.get("/api/v1/billing/tiers")
        for tier in resp.json():
            assert "id" in tier
            assert "name" in tier
            assert "base_cost" in tier
            assert "model_key" in tier
            assert tier["base_cost"] > 0

    @pytest.mark.asyncio
    async def test_expected_tiers_present(self, client: AsyncClient):
        """В системе есть тарифы fast, smart, batch."""
        resp = await client.get("/api/v1/billing/tiers")
        names = {t["name"] for t in resp.json()}
        assert "fast" in names
        assert "smart" in names


# ══════════════════════════════════════════════════════════════════════
# GET /billing/loyalty
# ══════════════════════════════════════════════════════════════════════

class TestLoyalty:

    @pytest.mark.asyncio
    async def test_loyalty_default_bronze(self, client: AsyncClient):
        """Новый пользователь — уровень bronze."""
        email = unique_email("loy")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/loyalty", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_level"] == "bronze"
        assert data["discount_pct"] == 0.0
        assert data["predictions_this_month"] == 0

    @pytest.mark.asyncio
    async def test_loyalty_shows_next_level(self, client: AsyncClient):
        """Bronze пользователь видит следующий уровень и сколько осталось."""
        email = unique_email("loynext")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/loyalty", headers=headers)
        data = resp.json()
        assert data["next_level"] is not None  # у bronze есть следующий
        assert data["predictions_to_next_level"] is not None
        assert data["predictions_to_next_level"] > 0

    @pytest.mark.asyncio
    async def test_loyalty_cashback_pct_present(self, client: AsyncClient):
        """Ответ содержит cashback_pct."""
        email = unique_email("loycash")
        await register_user(client, email)
        headers = await auth_headers(client, email)

        resp = await client.get("/api/v1/billing/loyalty", headers=headers)
        assert "cashback_pct" in resp.json()

    @pytest.mark.asyncio
    async def test_loyalty_unauthenticated(self, client: AsyncClient):
        """Уровень лояльности без токена — 401."""
        resp = await client.get("/api/v1/billing/loyalty")
        assert resp.status_code == 401
