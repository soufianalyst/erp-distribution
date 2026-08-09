"""The wall between customers and staff.

This is the first surface in the system reachable from outside the company, and the
whole of phase 0 exists to make one thing impossible: a customer's token being read
as a staff member's.

The hole it closes is not hypothetical. Both realms number their subjects from 1 and
the old token was just `{"sub": 7, "type": "access"}`. `get_current_user` did
`db.get(User, 7)`. A customer signing in as customer 7 would have received a token
that every staff endpoint accepted as *user* 7 — whoever that is, whatever they are
allowed to do.

So the tests below are mostly attacks rather than features. The important one walks
the application's own route table, so an endpoint added next year is covered without
anyone remembering to come back here.
"""

import pytest
from httpx import AsyncClient

from app.core.security import create_access_token, decode_token
from app.core.exceptions import AppException
from app.tests.conftest import TEST_ADMIN_PASSWORD, TEST_SALES_PASSWORD, login
from app.tests.test_sales import create_customer

PORTAL_PASSWORD = "Portal@12345"
NEW_PASSWORD = "Portal@98765"


async def open_portal_account(client: AsyncClient, admin: dict, name: str,
                              login_id: str) -> tuple[int, dict]:
    """Create a customer with portal access; returns (customer_id, login row)."""
    customer_id = await create_customer(client, admin, name=name, credit_limit="5000")
    response = await client.post(
        "/api/v1/customer-logins",
        headers=admin,
        json={
            "customer_id": customer_id,
            "login_id": login_id,
            "temporary_password": PORTAL_PASSWORD,
        },
    )
    assert response.status_code == 201, response.text
    return customer_id, response.json()["data"]


async def portal_token(client: AsyncClient, login_id: str,
                       password: str = PORTAL_PASSWORD) -> dict:
    response = await client.post(
        "/api/v1/portal/auth/login",
        json={"login_id": login_id, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


class TestTheTwoRealmsCannotBeConfused:
    async def test_a_customer_token_is_refused_by_every_staff_route(
        self, client: AsyncClient
    ) -> None:
        """The attack this phase exists to stop, checked against the real route table.

        Not a sample of endpoints — every GET the application exposes outside the two
        public login paths. A route added later is covered the day it is added.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "عميل الاختراق", "0500000001")
        customer = await portal_token(client, "0500000001")

        from main import app

        # Read the list from the generated spec rather than by walking `app.routes`:
        # the routers are wrapped once included, so the walk silently found nothing
        # and the test passed while probing zero endpoints. The spec is what the
        # application itself declares it serves, and it cannot quietly come back empty
        # — hence the floor on `checked` below.
        public = {"/api/v1/auth/login", "/api/v1/auth/refresh",
                  "/api/v1/portal/auth/login", "/api/v1/portal/auth/refresh"}
        checked, leaked = 0, []
        for path, operations in app.openapi()["paths"].items():
            if "get" not in operations or not path.startswith("/api/v1/"):
                continue
            if path in public or path.startswith("/api/v1/portal/"):
                continue
            if "{" in path:  # needs an id; the id-less routes are enough of a net
                continue
            checked += 1
            response = await client.get(path, headers=customer)
            if response.status_code != 401:
                leaked.append(f"{path} -> {response.status_code}")

        assert checked >= 15, f"only probed {checked} staff routes — net too small"
        assert not leaked, (
            "a customer's token was accepted by staff routes, which is the whole "
            f"hole this phase closes: {leaked[:10]}"
        )

    async def test_a_staff_token_is_refused_by_the_portal(
        self, client: AsyncClient
    ) -> None:
        """The mirror. An employee's token must not read a customer's portal either —
        not because staff are untrusted, but because a principal should only ever be
        interpreted by the realm that issued it."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        response = await client.get("/api/v1/portal/me", headers=admin)
        assert response.status_code == 401, response.text

    async def test_a_token_minted_without_a_realm_is_refused(self) -> None:
        """Tokens from before the claim existed carry none. Accepting them as staff
        would leave the door open for exactly as long as one lived."""
        import jwt

        from app.core.config import get_settings

        settings = get_settings()
        legacy = jwt.encode(
            {"sub": "1", "role": "admin", "type": "access"},
            settings.SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )
        with pytest.raises(AppException):
            decode_token(legacy, expected_type="access", expected_realm="staff")

    async def test_a_customer_token_cannot_be_decoded_as_staff(self) -> None:
        """At the primitive itself, below any route."""
        token = create_access_token("7", "customer", realm="customer")
        with pytest.raises(AppException):
            decode_token(token, expected_type="access", expected_realm="staff")
        # And it is a perfectly valid token in its own realm.
        assert decode_token(token, expected_type="access", expected_realm="customer")[
            "sub"
        ] == "7"


class TestOneCustomerCannotReachAnother:
    async def test_the_portal_reports_only_the_signed_in_customer(
        self, client: AsyncClient
    ) -> None:
        """No portal route takes a customer id, so the only thing to verify is that
        the identity comes from the token — and that two tokens differ."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        first_id, _ = await open_portal_account(client, admin, "بقالة أ", "0500000002")
        second_id, _ = await open_portal_account(client, admin, "بقالة ب", "0500000003")

        first = await portal_token(client, "0500000002")
        second = await portal_token(client, "0500000003")

        me_first = (await client.get("/api/v1/portal/me", headers=first)).json()["data"]
        me_second = (await client.get("/api/v1/portal/me", headers=second)).json()["data"]
        assert me_first["customer_id"] == first_id
        assert me_second["customer_id"] == second_id
        assert me_first["name"] != me_second["name"]

    def test_no_portal_route_accepts_a_customer_id(self) -> None:
        """Structural, not behavioural.

        As long as identity is only ever taken from the token there is nothing to
        tamper with. A route that grows a `customer_id` parameter — in the path, the
        query or the body — reintroduces the question of who may pass which value,
        and this check is here so that has to be a deliberate decision.
        """
        import inspect

        from app.api.v1 import portal

        offenders = []
        for name, function in vars(portal).items():
            if not callable(function) or not hasattr(function, "__annotations__"):
                continue
            if not inspect.iscoroutinefunction(function):
                continue
            if not name.startswith("portal_"):
                continue  # office-side routes legitimately name a customer
            for parameter in inspect.signature(function).parameters:
                if "customer_id" in parameter:
                    offenders.append(f"{name}({parameter})")
        assert not offenders, (
            f"portal routes take a customer id from the caller: {offenders}"
        )


class TestPortalResponsesCarryNoCommercialTerms:
    def test_no_portal_schema_exposes_a_price_or_a_limit(self) -> None:
        """What a customer is charged is theirs; how we price and rate them is not.

        Phase 2 will show a catalogue with no prices at all. This check is written now,
        while the schemas are few, so the rule is already in place when they multiply.
        Past invoices carry their own amounts and will use their own schemas, named so
        they are exempt deliberately rather than by accident.
        """
        from app.api.schemas import portal as portal_schemas
        from pydantic import BaseModel

        forbidden = ("price", "cost", "credit_limit", "price_tier", "margin")

        # Two exemptions, both deliberate and both narrow.
        #
        # `Invoice*` carries what the customer was charged, which is theirs.
        #
        # `CatalogItemOut` carries a before/after pair, but *only* on a line that is
        # actively discounted, and both numbers are that customer's own tier price —
        # nothing their invoices do not already show. A markdown with no number is not
        # an offer, so the alternative was a feature that could not work. The fields
        # are listed one by one rather than the class being waved through, so a third
        # price appearing here still fails.
        catalogue_allowed = {"price_before", "price_now"}

        offenders = []
        for name, klass in vars(portal_schemas).items():
            if not (isinstance(klass, type) and issubclass(klass, BaseModel)):
                continue
            if klass is BaseModel or name.startswith("Invoice"):
                continue
            for field in klass.model_fields:
                if name == "CatalogItemOut" and field in catalogue_allowed:
                    continue
                if any(word in field.lower() for word in forbidden):
                    offenders.append(f"{name}.{field}")
        assert not offenders, f"commercial terms exposed to customers: {offenders}"


class TestTheTemporaryPasswordGate:
    """`get_current_customer` is the dependency every data route will take.

    Phase 0 has no data route to hang it on, so it is exercised directly here rather
    than left to be trusted on sight — a gate nothing has ever run is a gate nobody
    knows the state of. `/portal/me` and the password change itself deliberately take
    the permissive `get_signed_in_customer`, because a customer reopening the portal
    mid-change has to be able to load the screen that lets them finish.
    """

    @staticmethod
    async def _call_gate(db_session, token: str):
        from fastapi.security import HTTPAuthorizationCredentials

        from app.api.deps import get_current_customer, get_signed_in_customer

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        customer = await get_signed_in_customer(credentials, db_session)
        return await get_current_customer(customer, db_session)

    async def test_a_customer_on_a_temporary_password_is_held_at_the_gate(
        self, client: AsyncClient, db_session
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة البوابة", "0500000012")
        signed_in = (await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000012", "password": PORTAL_PASSWORD},
        )).json()["data"]

        with pytest.raises(AppException) as refused:
            await self._call_gate(db_session, signed_in["access_token"])
        assert refused.value.status_code == 403

        # The two permissive routes still answer, or the customer could never finish.
        headers = {"Authorization": f"Bearer {signed_in['access_token']}"}
        assert (await client.get("/api/v1/portal/me", headers=headers)).status_code == 200

        changed = await client.post(
            "/api/v1/portal/auth/change-password",
            headers=headers,
            json={"current_password": PORTAL_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200, changed.text

        # And the gate opens once the temporary password is gone. The expiry is a test
        # artefact: this session already read the login row above and would answer from
        # its identity map, whereas a real request arrives with a session of its own.
        db_session.expire_all()
        customer = await self._call_gate(db_session, signed_in["access_token"])
        assert customer.name == "بقالة البوابة"


class TestSigningIn:
    async def test_a_temporary_password_must_be_changed(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة التغيير", "0500000004")

        signed_in = (await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000004", "password": PORTAL_PASSWORD},
        )).json()["data"]
        assert signed_in["customer"]["must_change_password"] is True

        headers = {"Authorization": f"Bearer {signed_in['access_token']}"}
        changed = await client.post(
            "/api/v1/portal/auth/change-password",
            headers=headers,
            json={"current_password": PORTAL_PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200, changed.text

        again = (await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000004", "password": NEW_PASSWORD},
        )).json()["data"]
        assert again["customer"]["must_change_password"] is False

    async def test_a_wrong_password_and_an_unknown_login_answer_alike(
        self, client: AsyncClient
    ) -> None:
        """Neither response may reveal whether an account exists."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة التعداد", "0500000005")

        wrong = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000005", "password": "definitely-wrong"},
        )
        unknown = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0599999999", "password": "definitely-wrong"},
        )
        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["message"] == unknown.json()["message"]

    async def test_repeated_failures_lock_the_account(
        self, client: AsyncClient
    ) -> None:
        """Five wrong tries is a bad morning; a sixth is a script."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة القفل", "0500000006")

        for _ in range(5):
            await client.post(
                "/api/v1/portal/auth/login",
                json={"login_id": "0500000006", "password": "wrong"},
            )
        locked = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000006", "password": PORTAL_PASSWORD},
        )
        assert locked.status_code == 429, locked.text

    async def test_the_office_can_let_a_locked_customer_back_in(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, account = await open_portal_account(client, admin, "بقالة الفك", "0500000007")
        for _ in range(5):
            await client.post(
                "/api/v1/portal/auth/login",
                json={"login_id": "0500000007", "password": "wrong"},
            )

        reset = await client.put(
            f"/api/v1/customer-logins/{account['id']}",
            headers=admin,
            json={"temporary_password": "Reset@12345"},
        )
        assert reset.status_code == 200, reset.text
        assert reset.json()["data"]["is_locked"] is False

        signed_in = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0500000007", "password": "Reset@12345"},
        )
        assert signed_in.status_code == 200, signed_in.text

    async def test_suspending_access_takes_effect_on_the_next_request(
        self, client: AsyncClient
    ) -> None:
        """Not at the end of the token's life. A customer cut off must be cut off now."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        _, account = await open_portal_account(client, admin, "بقالة الإيقاف", "0500000008")
        headers = await portal_token(client, "0500000008")
        assert (await client.get("/api/v1/portal/me", headers=headers)).status_code == 200

        suspended = await client.put(
            f"/api/v1/customer-logins/{account['id']}",
            headers=admin,
            json={"is_active": False},
        )
        assert suspended.status_code == 200, suspended.text
        # Same token, still unexpired.
        assert (await client.get("/api/v1/portal/me", headers=headers)).status_code == 401


class TestWhoMayOpenAnAccount:
    async def test_a_salesman_cannot_mint_a_login_for_his_own_customer(
        self, client: AsyncClient
    ) -> None:
        """Separation of duties: the rep who holds the relationship is not the one who
        grants the access."""
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        customer_id = await create_customer(client, admin, name="بقالة المندوب")
        salesman = await login(client, "salesman", TEST_SALES_PASSWORD)

        refused = await client.post(
            "/api/v1/customer-logins",
            headers=salesman,
            json={
                "customer_id": customer_id,
                "login_id": "0500000009",
                "temporary_password": PORTAL_PASSWORD,
            },
        )
        assert refused.status_code == 403, refused.text

    async def test_a_customer_cannot_open_accounts_for_anyone(
        self, client: AsyncClient
    ) -> None:
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة الفضول", "0500000010")
        other_id = await create_customer(client, admin, name="بقالة الهدف")
        customer = await portal_token(client, "0500000010")

        refused = await client.post(
            "/api/v1/customer-logins",
            headers=customer,
            json={
                "customer_id": other_id,
                "login_id": "0500000011",
                "temporary_password": PORTAL_PASSWORD,
            },
        )
        assert refused.status_code == 401, refused.text
