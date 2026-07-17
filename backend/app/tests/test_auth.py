"""Integration tests for the authentication module (login, refresh, RBAC, user CRUD)."""

from httpx import AsyncClient

from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login


class TestLogin:
    async def test_login_success_returns_token_pair(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["data"]["access_token"]
        assert body["data"]["refresh_token"]
        assert body["data"]["user"]["username"] == "admin"
        assert body["data"]["user"]["role"] == "admin"

    async def test_login_wrong_password_fails(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login", json={"username": "admin", "password": "WrongPass123"}
        )
        assert response.status_code == 401
        body = response.json()
        assert body["success"] is False
        assert body["message"] == "اسم المستخدم أو كلمة المرور غير صحيحة."

    async def test_login_unknown_user_same_message(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "no_such_user", "password": "WrongPass123"},
        )
        assert response.status_code == 401
        assert response.json()["message"] == "اسم المستخدم أو كلمة المرور غير صحيحة."

    async def test_login_disabled_account_rejected(self, client: AsyncClient) -> None:
        response = await client.post(
            "/api/v1/auth/login",
            json={"username": "disabled_user", "password": TEST_SALES_PASSWORD},
        )
        assert response.status_code == 403
        assert response.json()["success"] is False

    async def test_login_validation_error_enveloped(self, client: AsyncClient) -> None:
        response = await client.post("/api/v1/auth/login", json={"username": "x"})
        assert response.status_code == 422
        body = response.json()
        assert body["success"] is False
        assert "غير صالحة" in body["message"]


class TestTokens:
    async def test_me_with_valid_token(self, client: AsyncClient) -> None:
        headers = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["data"]["username"] == "salesman"

    async def test_me_without_token_rejected(self, client: AsyncClient) -> None:
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["success"] is False

    async def test_me_with_garbage_token_rejected(self, client: AsyncClient) -> None:
        response = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert response.status_code == 401

    async def test_refresh_returns_new_pair(self, client: AsyncClient) -> None:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        refresh_token = login_response.json()["data"]["refresh_token"]
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
        )
        assert response.status_code == 200
        assert response.json()["data"]["access_token"]

    async def test_access_token_rejected_as_refresh_token(
        self, client: AsyncClient
    ) -> None:
        login_response = await client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        access_token = login_response.json()["data"]["access_token"]
        response = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": access_token}
        )
        assert response.status_code == 401


class TestUserManagement:
    async def test_admin_creates_user(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.post(
            "/api/v1/auth/users",
            headers=headers,
            json={
                "username": "storekeeper1",
                "full_name": "أمين المستودع الأول",
                "password": "Store@1234",
                "role": "storekeeper",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["data"]["role"] == "storekeeper"

        # The new user can log in immediately.
        new_login = await client.post(
            "/api/v1/auth/login",
            json={"username": "storekeeper1", "password": "Store@1234"},
        )
        assert new_login.status_code == 200

    async def test_duplicate_username_rejected(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        payload = {
            "username": "salesman",
            "full_name": "مكرر",
            "password": "Dup@12345",
            "role": "sales",
        }
        response = await client.post(
            "/api/v1/auth/users", headers=headers, json=payload
        )
        assert response.status_code == 409

    async def test_non_admin_cannot_create_user(self, client: AsyncClient) -> None:
        headers = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.post(
            "/api/v1/auth/users",
            headers=headers,
            json={
                "username": "hacker",
                "full_name": "غير مصرح",
                "password": "Hack@1234",
                "role": "admin",
            },
        )
        assert response.status_code == 403

    async def test_non_admin_cannot_list_users(self, client: AsyncClient) -> None:
        headers = await login(client, "salesman", TEST_SALES_PASSWORD)
        response = await client.get("/api/v1/auth/users", headers=headers)
        assert response.status_code == 403

    async def test_admin_lists_users(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/auth/users", headers=headers)
        assert response.status_code == 200
        usernames = [u["username"] for u in response.json()["data"]]
        assert {"admin", "salesman", "disabled_user"} <= set(usernames)

    async def test_admin_deactivates_user(self, client: AsyncClient) -> None:
        headers = await login(client, "admin", TEST_ADMIN_PASSWORD)
        users = (await client.get("/api/v1/auth/users", headers=headers)).json()["data"]
        salesman_id = next(u["id"] for u in users if u["username"] == "salesman")

        response = await client.patch(
            f"/api/v1/auth/users/{salesman_id}",
            headers=headers,
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["data"]["is_active"] is False

        # The deactivated user can no longer log in.
        blocked = await client.post(
            "/api/v1/auth/login",
            json={"username": "salesman", "password": TEST_SALES_PASSWORD},
        )
        assert blocked.status_code == 403
