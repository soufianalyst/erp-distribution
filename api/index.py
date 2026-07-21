"""Vercel serverless entry point.

Vercel receives requests like /api/v1/auth/login but may forward them to
the function as /v1/auth/login (stripping /api).  We mount the FastAPI app
under a plain prefix so both cases work.
"""
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

from main import app as _fastapi_app  # noqa: E402

from starlette.applications import Starlette
from starlette.routing import Mount

# Mount the FastAPI app under /api so that requests arriving as /api/v1/...
# reach the app's /api/v1/... routes correctly.
app = Starlette(routes=[
    Mount("/api", app=_fastapi_app),
])
