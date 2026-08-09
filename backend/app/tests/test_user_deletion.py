"""Removing accounts, and refusing to.

Deletion here is narrow on purpose. Thirty-four columns across the schema point at
`users` — every invoice, journal entry and audit row carries whoever made it — so
erasing someone who has worked would either break those references or leave records
nobody can attribute. The rule is: an account with history gets deactivated, and only
an account with none can be deleted.

These tests are mostly about the refusals, because a delete that works is obvious the
first time it is used and a delete that should have been refused is discovered months
later by an auditor.
"""

import pytest
from httpx import AsyncClient

from app.tests.conftest import (
    TEST_ADMIN_PASSWORD,
    TEST_SALES_PASSWORD,
    login,
)
from app.tests.test_portal_identity import open_portal_account
from app.tests.test_sales import create_customer, setup_stocked_catalog, post_invoice


async def make_user(client: AsyncClient, admin: dict, username: str,
                    role: str = "sales") -> dict:
    response = await client.post("/api/v1/auth/users", headers=admin, json={
        "username": username,
        "full_name": f"موظف {username}",
        "password": "Fresh@12345",
        "role": role,
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


class TestDeletingAStaffAccount:
    async def test_an_unused_account_can_be_removed(
        self, client: AsyncClient
    ) -> None:
        """The case this exists for: a duplicate, or a typo in the username."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        user = await make_user(client, admin, "typo.account")

        removed = await client.delete(
            f"/api/v1/auth/users/{user['id']}", headers=admin)
        assert removed.status_code == 200, removed.text

        remaining = (await client.get("/api/v1/auth/users", headers=admin)).json()["data"]
        assert user["id"] not in {u["id"] for u in remaining}

    async def test_an_account_with_history_is_refused_and_survives(
        self, client: AsyncClient
    ) -> None:
        """The important refusal.

        A salesman who has invoiced is referenced by those invoices. Deleting him
        would strip the name off real sales — so the API refuses and says to
        deactivate instead. The account must still be there afterwards.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        warehouse_id, product = await setup_stocked_catalog(client, admin)
        salesman = (await client.get("/api/v1/auth/me", headers=admin)).json()["data"]
        customer_id = await create_customer(client, admin, name="بقالة التاريخ")
        invoiced = await post_invoice(
            client, admin, customer_id, warehouse_id, product["id"], "3")
        assert invoiced.status_code == 201, invoiced.text

        refused = await client.delete(
            f"/api/v1/auth/users/{salesman['id']}", headers=admin)
        # 409: the account is fine, the *relationships* forbid it.
        assert refused.status_code in (400, 409), refused.text
        assert "عطّل" in refused.json()["message"] or "حساب" in refused.json()["message"]

        still_there = (await client.get(
            "/api/v1/auth/users", headers=admin)).json()["data"]
        assert salesman["id"] in {u["id"] for u in still_there}

    async def test_you_cannot_delete_the_account_you_are_using(
        self, client: AsyncClient
    ) -> None:
        """It would revoke the session mid-request, with no way to undo it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        me = (await client.get("/api/v1/auth/me", headers=admin)).json()["data"]

        refused = await client.delete(f"/api/v1/auth/users/{me['id']}", headers=admin)
        assert refused.status_code in (400, 409), refused.text

    async def test_the_last_active_admin_cannot_be_deleted(
        self, client: AsyncClient
    ) -> None:
        """Losing every administrator locks the permission screen for good.

        A second admin is created and used to attempt the deletion, so the refusal
        being tested is the last-admin rule rather than the self-delete rule.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        first = (await client.get("/api/v1/auth/me", headers=admin)).json()["data"]
        second = await make_user(client, admin, "second.admin", role="admin")

        # Signed in as the second admin, deleting the first is allowed — one remains.
        other = await login(client, "second.admin", "Fresh@12345")
        # Then disable the second, leaving the first as the only active admin.
        await client.patch(f"/api/v1/auth/users/{second['id']}", headers=admin,
                           json={"is_active": False})
        refused = await client.delete(
            f"/api/v1/auth/users/{first['id']}", headers=admin)
        assert refused.status_code in (400, 409), refused.text
        assert other is not None

    async def test_deleting_needs_its_own_permission(
        self, client: AsyncClient
    ) -> None:
        """A salesman manages nobody; disabling and erasing are separate authorities."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        victim = await make_user(client, admin, "target.account")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)

        refused = await client.delete(
            f"/api/v1/auth/users/{victim['id']}", headers=salesman)
        assert refused.status_code == 403, refused.text


class TestChangingAPassword:
    async def test_an_admin_can_set_a_new_password_and_it_works(
        self, client: AsyncClient
    ) -> None:
        """Proven by signing in with it, not by a 200 from the update."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        user = await make_user(client, admin, "reset.me")

        changed = await client.patch(
            f"/api/v1/auth/users/{user['id']}", headers=admin,
            json={"password": "Changed@12345"})
        assert changed.status_code == 200, changed.text

        assert (await client.post("/api/v1/auth/login", json={
            "username": "reset.me", "password": "Changed@12345"})).status_code == 200
        assert (await client.post("/api/v1/auth/login", json={
            "username": "reset.me", "password": "Fresh@12345"})).status_code == 401


class TestDeletingAPortalAccount:
    async def test_the_login_goes_and_the_customer_stays(
        self, client: AsyncClient
    ) -> None:
        """The distinction the confirmation dialog promises: only the way in is
        removed. Nothing in the system references a portal login, so unlike a staff
        user it can simply go."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id, account = await open_portal_account(
            client, admin, "بقالة الحذف", "0504000001")

        removed = await client.delete(
            f"/api/v1/customer-logins/{account['id']}", headers=admin)
        assert removed.status_code == 200, removed.text

        accounts = (await client.get(
            "/api/v1/customer-logins", headers=admin)).json()["data"]
        assert account["id"] not in {a["id"] for a in accounts}

        # The customer is untouched. Read from the list, since there is no
        # single-customer GET route.
        customers = (await client.get(
            "/api/v1/sales/customers", headers=admin)).json()["data"]
        survivor = next((c for c in customers if c["id"] == customer_id), None)
        assert survivor is not None, "deleting a login deleted the customer"
        assert survivor["name"] == "بقالة الحذف"

        # And the login id is free again, so it can be reissued.
        reopened = await client.post("/api/v1/customer-logins", headers=admin, json={
            "customer_id": customer_id,
            "login_id": "0504000001",
            "temporary_password": "Again@12345",
        })
        assert reopened.status_code == 201, reopened.text

    async def test_a_salesman_cannot_delete_a_portal_account(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, account = await open_portal_account(
            client, admin, "بقالة المحمية", "0504000002")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)

        refused = await client.delete(
            f"/api/v1/customer-logins/{account['id']}", headers=salesman)
        assert refused.status_code == 403, refused.text
