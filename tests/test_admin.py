"""
test_admin.py — тесты административного роутера.

Покрывает:
- GET /admin/stats — статистика (только admin)
- GET /admin/users — список пользователей (только admin)
- PUT /admin/tiers/{tier_name} — изменение стоимости тарифа
- PUT /admin/loyalty/{level_name} — изменение уровня лояльности
- Защита от обычного пользователя (403)
- Защита от неавторизованного (401)
"""

import pytest
from httpx import AsyncClient
from conftest import (
    unique_email, register_user, auth_headers, create_admin
)


# ══════════════════════════════════════════════════════════════════════
# Хелпер: создать админа и вернуть его заголовки
# ══════════════════════════════════════════════════════════════════════

async def admin_headers(client: AsyncClient, db_session) -> dict:
    email = unique_email("adm")
    await create_admin(db_session, email)
    return await auth_headers(client, email, "adminpass123")


# ══════════════════════════════════════════════════════════════════════
# GET /admin/stats
# ══════════════════════════════════════════════════════════════════════

class TestAdminStats:

    @pytest.mark.asyncio
    async def test_stats_accessible_by_admin(self, client: AsyncClient, db_session):
        """Админ получает статистику."""
        headers = await admin_headers(client, db_session)
        resp = await client.get("/api/v1/admin/stats", headers=headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "total_users" in data
        assert "total_tasks" in data
        assert "completed_tasks" in data
        assert "total_credits_charged" in data

    @pytest.mark.asyncio
    async def test_stats_values_are_numeric(self, client: AsyncClient, db_session):
        """Все значения статистики — числа >= 0."""
        headers = await admin_headers(client, db_session)
        resp = await client.get("/api/v1/admin/stats", headers=headers)
        data = resp.json()
        for key, val in data.items():
            assert isinstance(val, (int, float)), f"{key} is not numeric"
            assert val >= 0, f"{key} is negative"

    @pytest.mark.asyncio
    async def test_stats_forbidden_for_user(self, client: AsyncClient):
        """Обычный пользователь получает 403."""
        email = unique_email("stats_user")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        resp = await client.get("/api/v1/admin/stats", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_stats_forbidden_without_auth(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.get("/api/v1/admin/stats")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_stats_counts_registered_users(self, client: AsyncClient, db_session):
        """После регистрации нового пользователя total_users увеличивается."""
        headers = await admin_headers(client, db_session)

        resp_before = await client.get("/api/v1/admin/stats", headers=headers)
        count_before = resp_before.json()["total_users"]

        await register_user(client, unique_email("newu"))

        resp_after = await client.get("/api/v1/admin/stats", headers=headers)
        count_after = resp_after.json()["total_users"]

        assert count_after > count_before


# ══════════════════════════════════════════════════════════════════════
# GET /admin/users
# ══════════════════════════════════════════════════════════════════════

class TestAdminUsers:

    @pytest.mark.asyncio
    async def test_list_users_accessible_by_admin(self, client: AsyncClient, db_session):
        """Админ получает список пользователей."""
        headers = await admin_headers(client, db_session)
        resp = await client.get("/api/v1/admin/users", headers=headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_list_users_structure(self, client: AsyncClient, db_session):
        """Каждый пользователь в списке содержит обязательные поля."""
        headers = await admin_headers(client, db_session)
        await register_user(client, unique_email("ulist"))

        resp = await client.get("/api/v1/admin/users", headers=headers)
        users = resp.json()
        assert len(users) > 0
        for user in users:
            for field in ["id", "email", "role", "loyalty_level", "is_active", "created_at"]:
                assert field in user, f"Missing field: {field}"

    @pytest.mark.asyncio
    async def test_list_users_forbidden_for_user(self, client: AsyncClient):
        """Обычный пользователь получает 403."""
        email = unique_email("users_user")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        resp = await client.get("/api/v1/admin/users", headers=headers)
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_list_users_forbidden_without_auth(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.get("/api/v1/admin/users")
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_newly_registered_user_appears_in_list(self, client: AsyncClient, db_session):
        """Зарегистрированный пользователь появляется в списке."""
        headers = await admin_headers(client, db_session)
        new_email = unique_email("appears")
        await register_user(client, new_email)

        resp = await client.get("/api/v1/admin/users", headers=headers)
        emails = [u["email"] for u in resp.json()]
        assert new_email in emails

    @pytest.mark.asyncio
    async def test_no_password_in_user_list(self, client: AsyncClient, db_session):
        """Хеш пароля не попадает в список пользователей."""
        headers = await admin_headers(client, db_session)
        await register_user(client, unique_email("nopw"))

        resp = await client.get("/api/v1/admin/users", headers=headers)
        for user in resp.json():
            assert "hashed_password" not in user
            assert "password" not in user


# ══════════════════════════════════════════════════════════════════════
# PUT /admin/tiers/{tier_name}
# ══════════════════════════════════════════════════════════════════════

class TestAdminTiers:

    @pytest.mark.asyncio
    async def test_update_tier_cost(self, client: AsyncClient, db_session):
        """Админ может изменить стоимость тарифа."""
        headers = await admin_headers(client, db_session)

        resp = await client.put(
            "/api/v1/admin/tiers/fast",
            params={"base_cost": 2.50},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["tier"] == "fast"
        assert abs(data["new_cost"] - 2.50) < 0.01

        # Восстановим обратно чтобы не ломать другие тесты
        await client.put(
            "/api/v1/admin/tiers/fast",
            params={"base_cost": 1.00},
            headers=headers,
        )

    @pytest.mark.asyncio
    async def test_update_tier_nonexistent(self, client: AsyncClient, db_session):
        """Несуществующий тариф — 404."""
        headers = await admin_headers(client, db_session)
        resp = await client.put(
            "/api/v1/admin/tiers/nonexistent_tier",
            params={"base_cost": 5.00},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_tier_forbidden_for_user(self, client: AsyncClient):
        """Обычный пользователь не может изменить тариф — 403."""
        email = unique_email("tier_user")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        resp = await client.put(
            "/api/v1/admin/tiers/fast",
            params={"base_cost": 99.00},
            headers=headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_tier_forbidden_without_auth(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.put(
            "/api/v1/admin/tiers/fast",
            params={"base_cost": 5.00},
        )
        assert resp.status_code == 401


# ══════════════════════════════════════════════════════════════════════
# PUT /admin/loyalty/{level_name}
# ══════════════════════════════════════════════════════════════════════

class TestAdminLoyalty:

    @pytest.mark.asyncio
    async def test_update_loyalty_level(self, client: AsyncClient, db_session):
        """Админ может изменить порог и скидку уровня лояльности."""
        headers = await admin_headers(client, db_session)

        resp = await client.put(
            "/api/v1/admin/loyalty/silver",
            params={"min_predictions": 50, "discount_percent": 7.00},
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "updated"
        assert data["level"] == "silver"

        # Восстановим
        await client.put(
            "/api/v1/admin/loyalty/silver",
            params={"min_predictions": 100, "discount_percent": 5.00},
            headers=headers,
        )

    @pytest.mark.asyncio
    async def test_update_loyalty_nonexistent(self, client: AsyncClient, db_session):
        """Несуществующий уровень — 404."""
        headers = await admin_headers(client, db_session)
        resp = await client.put(
            "/api/v1/admin/loyalty/platinum",
            params={"min_predictions": 1000, "discount_percent": 15.00},
            headers=headers,
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_loyalty_forbidden_for_user(self, client: AsyncClient):
        """Обычный пользователь не может изменить уровень — 403."""
        email = unique_email("loy_user")
        await register_user(client, email)
        headers = await auth_headers(client, email)
        resp = await client.put(
            "/api/v1/admin/loyalty/bronze",
            params={"min_predictions": 0, "discount_percent": 0.00},
            headers=headers,
        )
        assert resp.status_code == 403

    @pytest.mark.asyncio
    async def test_update_loyalty_forbidden_without_auth(self, client: AsyncClient):
        """Без токена — 401."""
        resp = await client.put(
            "/api/v1/admin/loyalty/bronze",
            params={"min_predictions": 0, "discount_percent": 0.00},
        )
        assert resp.status_code == 401
