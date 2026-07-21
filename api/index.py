"""Vercel serverless entry point — imports the FastAPI app directly."""
import sys
from pathlib import Path

# Add backend/ to Python path so `app.*` imports resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from main import app  # noqa: E402

# Vercel expects an ASGI app named `app` at module level.
