"""Vercel serverless entry point — lives outside /api so Vercel doesn't strip the prefix."""
import os
import sys
from pathlib import Path

_backend = str(Path(__file__).resolve().parent.parent / "backend")
if _backend not in sys.path:
    sys.path.insert(0, _backend)

os.environ.setdefault("DATABASE_URL",
    "postgresql+asyncpg://postgres:Wazvu3-ruwzej-wajsop"
    "@db.bquxudmlyldlgbjfbmrr.supabase.co:5432/postgres")
os.environ.setdefault("SECRET_KEY", "erp-prod-2026-xK9mPq3vLz7wRt5nBj8cFd2gHs4yUe0a")
os.environ.setdefault("CORS_ORIGINS", "*")
os.environ.setdefault("SEED_ON_STARTUP", "false")
os.environ.setdefault("AUTO_CREATE_TABLES", "false")
os.environ.setdefault("FIRST_ADMIN_PASSWORD", "Adm1n@Erp2026!")

from main import app  # noqa: E402
