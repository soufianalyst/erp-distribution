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


class TestSecretKeyGuard:
    def test_refuses_insecure_default_secret_when_debug_false(self) -> None:
        result = _run(
            {
                "DEBUG": "false",
                "SECRET_KEY": "dev-only-secret-key-change-me-in-production-0123456789",
            }
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

    def test_allows_real_secret_when_debug_false(self) -> None:
        result = _run(
            {
                "DEBUG": "false",
                "SECRET_KEY": "a-real-randomly-generated-production-secret-key-value",
            }
        )
        assert result.returncode == 0
        assert "OK" in result.stdout
