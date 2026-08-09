"""A brake on sign-in attempts, above the per-account lockout.

The lockout answers "someone is guessing at *this* shop". It is blind to the attack
that matters more once a portal faces the internet: one common password tried against
a thousand different login ids, which never trips any single account's counter and
costs a bcrypt hash every time.
"""

from httpx import AsyncClient

from app.core import rate_limit
from app.tests.conftest import TEST_ADMIN_PASSWORD, login
from app.tests.test_portal_identity import open_portal_account


class TestSignInIsRateLimited:
    async def test_a_flood_of_attempts_is_refused(self, client: AsyncClient) -> None:
        """Twenty in a minute, then 429 — before the password is even checked."""
        statuses = []
        for _ in range(25):
            response = await client.post(
                "/api/v1/portal/auth/login",
                json={"login_id": "0509999999", "password": "wrong"},
            )
            statuses.append(response.status_code)

        assert 429 in statuses, "the flood was never refused"
        # Everything before the limit answers the ordinary way — an unknown login is
        # still a 401, so the limiter is not masking the enumeration-safe response.
        assert statuses[0] == 401
        # And once it trips, it stays tripped for the rest of the window.
        assert statuses[-1] == 429

    async def test_it_catches_spraying_across_many_accounts(
        self, client: AsyncClient
    ) -> None:
        """The case the per-account lockout cannot see.

        Each login id is tried only twice — far under the five-attempt lockout — so
        without this limiter the attacker would never be stopped.
        """
        statuses = []
        for index in range(25):
            response = await client.post(
                "/api/v1/portal/auth/login",
                json={"login_id": f"05000{index:05d}", "password": "Common@12345"},
            )
            statuses.append(response.status_code)

        assert 429 in statuses, (
            "one password sprayed across many shops was never throttled"
        )

    async def test_staff_sign_in_is_guarded_too(self, client: AsyncClient) -> None:
        """Staff accounts have no lockout of their own, so this is their only brake."""
        statuses = []
        for _ in range(25):
            response = await client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "definitely-wrong"},
            )
            statuses.append(response.status_code)
        assert 429 in statuses

    async def test_the_limit_does_not_block_ordinary_use(
        self, client: AsyncClient
    ) -> None:
        """A real shop signing in, mistyping once, and signing in again must pass.

        A limiter that fires on normal behaviour gets switched off, so the threshold
        has to leave clear headroom for a person at a keyboard.
        """
        admin = await login(client, "admin", TEST_ADMIN_PASSWORD)
        await open_portal_account(client, admin, "بقالة الاستخدام", "0507000001")

        wrong = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0507000001", "password": "oops"},
        )
        assert wrong.status_code == 401

        from app.tests.test_portal_identity import PORTAL_PASSWORD

        good = await client.post(
            "/api/v1/portal/auth/login",
            json={"login_id": "0507000001", "password": PORTAL_PASSWORD},
        )
        assert good.status_code == 200, good.text

    async def test_the_window_slides(self, client: AsyncClient) -> None:
        """Counters are per source, so a different caller is unaffected by a flood.

        Exercised through the module rather than the client, since the test transport
        presents one address for everyone.
        """
        rate_limit.reset()

        class FakeRequest:
            def __init__(self, ip: str) -> None:
                self.headers = {"x-forwarded-for": ip}
                self.client = None

        noisy = FakeRequest("10.0.0.1")
        quiet = FakeRequest("10.0.0.2")

        for _ in range(20):
            rate_limit.enforce(noisy, "portal-login")

        from app.core.exceptions import AppException

        try:
            rate_limit.enforce(noisy, "portal-login")
        except AppException as refused:
            assert refused.status_code == 429
        else:
            raise AssertionError("the noisy caller was not refused")

        # The quiet one is untouched.
        rate_limit.enforce(quiet, "portal-login")
