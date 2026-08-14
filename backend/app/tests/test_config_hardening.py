"""Tests for the production-hardening guard in app.core.config.get_settings.

Runs in a subprocess: get_settings() is @lru_cache'd and read at main.py's
module scope, so it can't be re-exercised with different env vars inside the
main test process without interfering with every other test's app instance.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]

_CHECK_SCRIPT = "from app.core.config import get_settings; get_settings(); print('OK')"


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _CHECK_SCRIPT],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


SAFE_PRODUCTION_ENV = {
    "DEBUG": "false",
    "SECRET_KEY": "a-real-randomly-generated-production-secret-key-value",
    "FIRST_ADMIN_PASSWORD": "a-real-chosen-admin-password",
    "AUTO_CREATE_TABLES": "false",
}


def _run_production(**overrides: str) -> subprocess.CompletedProcess[str]:
    """A safe production environment, with one thing deliberately put back wrong."""
    return _run({**SAFE_PRODUCTION_ENV, **overrides})


class TestSecretKeyGuard:
    def test_refuses_insecure_default_secret_when_debug_false(self) -> None:
        result = _run_production(
            SECRET_KEY="dev-only-secret-key-change-me-in-production-0123456789"
        )
        assert result.returncode != 0
        assert "SECRET_KEY" in result.stderr

    def test_allows_insecure_default_secret_when_debug_true(self) -> None:
        result = _run(
            {
                "DEBUG": "true",
                "SECRET_KEY": "dev-only-secret-key-change-me-in-production-0123456789",
            }
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_allows_a_fully_configured_production_environment(self) -> None:
        result = _run_production()
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout


class TestAdminPasswordGuard:
    """The default admin password is printed in .env.example and in this repo.

    A weak signing key is a silent weakness; a public admin password is an
    unlocked front door to every screen, so it fails startup the same way.
    """

    def test_refuses_the_documented_default_when_debug_false(self) -> None:
        result = _run_production(FIRST_ADMIN_PASSWORD="Admin@1234")
        assert result.returncode != 0
        assert "FIRST_ADMIN_PASSWORD" in result.stderr

    def test_allows_the_default_in_debug(self) -> None:
        result = _run({"DEBUG": "true", "FIRST_ADMIN_PASSWORD": "Admin@1234"})
        assert result.returncode == 0
        assert "OK" in result.stdout


class TestAutoCreateTablesGuard:
    """Not hypothetical: this exact setting hid a schema drift during development.

    It creates missing tables and never alters existing ones, so the app starts
    happily against a database no migration ever produced and the mismatch only
    surfaces later as a failing insert.
    """

    def test_refuses_auto_create_when_debug_false(self) -> None:
        result = _run_production(AUTO_CREATE_TABLES="true")
        assert result.returncode != 0
        assert "AUTO_CREATE_TABLES" in result.stderr

    def test_allows_auto_create_in_debug(self) -> None:
        result = _run({"DEBUG": "true", "AUTO_CREATE_TABLES": "true"})
        assert result.returncode == 0


class TestTheGuardReportsEverythingAtOnce:
    def test_all_three_problems_are_listed_together(self) -> None:
        """One restart per problem is how a deployment checklist gets abandoned."""
        result = _run(
            {
                "DEBUG": "false",
                "SECRET_KEY": "dev-only-secret-key-change-me-in-production-0123456789",
                "FIRST_ADMIN_PASSWORD": "Admin@1234",
                "AUTO_CREATE_TABLES": "true",
            }
        )
        assert result.returncode != 0
        for expected in ("SECRET_KEY", "FIRST_ADMIN_PASSWORD", "AUTO_CREATE_TABLES"):
            assert expected in result.stderr, f"{expected} missing from the report"


class TestTheDatabaseUrlIsNormalisedForAsyncpg:
    """A hosting provider's URL must work when pasted in verbatim.

    Render and Heroku hand out `postgres://`; asyncpg answers only to
    `postgresql+asyncpg://`. Nobody rewrites that by hand at 2am while a deploy is
    down, and the failure names the wrong thing when they forget:

        Can't load plugin: sqlalchemy.dialects:postgres
    """

    def test_it_accepts_every_form_a_provider_hands_out(self) -> None:
        from app.core.config import async_database_url

        expected = "postgresql+asyncpg://u:p@host:5432/db"
        assert async_database_url("postgres://u:p@host:5432/db") == expected
        assert async_database_url("postgresql://u:p@host:5432/db") == expected
        # Already correct — returned untouched rather than mangled into
        # postgresql+asyncpg+asyncpg://
        assert async_database_url(expected) == expected

    def test_it_rewrites_only_the_scheme(self) -> None:
        """The credentials and host survive, including a password containing the
        substring it matches on."""
        from app.core.config import async_database_url

        url = "postgres://user:postgres://weird@db.internal:5432/erp"
        assert async_database_url(url) == (
            "postgresql+asyncpg://user:postgres://weird@db.internal:5432/erp"
        )

    def test_anything_else_is_left_alone(self) -> None:
        """SQLite drives the test suite; it must pass through untouched."""
        from app.core.config import async_database_url

        assert async_database_url("sqlite+aiosqlite:///:memory:") == (
            "sqlite+aiosqlite:///:memory:"
        )

    def test_both_readers_use_the_one_definition(self) -> None:
        """Structural: the rewrite existed in two copies and they disagreed.

        The app engine handled `postgresql://` and so did Alembic, and neither handled
        `postgres://` — so a deploy could migrate and then fail to serve, or the reverse,
        depending on which URL form was configured.
        """
        import pathlib

        backend = pathlib.Path(__file__).resolve().parents[2]
        for relative in ("app/db/session.py", "alembic/env.py"):
            source = (backend / relative).read_text(encoding="utf-8")
            assert "async_database_url" in source, f"{relative} must use the shared helper"
            assert 'replace("postgresql://' not in source, (
                f"{relative} has its own copy of the rewrite again"
            )
