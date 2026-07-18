"""Password hashing (bcrypt) and JWT creation/validation helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import AppException

TokenType = Literal["access", "refresh"]


def hash_password(plain_password: str) -> str:
    hashed: bytes = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), hashed_password.encode("utf-8")
        )
    except ValueError:
        # Malformed stored hash — treat as authentication failure, never crash.
        return False


# A fixed bcrypt hash with no matching plaintext. Used so a login attempt for a
# nonexistent username still pays the same bcrypt cost as a real one, closing a
# timing side-channel that could otherwise reveal whether a username exists.
_DUMMY_HASH = hash_password("no-such-user-timing-safety-placeholder")


def verify_password_or_dummy(plain_password: str, hashed_password: str | None) -> bool:
    return verify_password(plain_password, hashed_password or _DUMMY_HASH)


def _create_token(
    subject: str, role: str, token_type: TokenType, expires_delta: timedelta
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, role: str) -> str:
    settings = get_settings()
    return _create_token(
        subject, role, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(subject: str, role: str) -> str:
    settings = get_settings()
    return _create_token(
        subject, role, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Decode and validate a JWT, enforcing the expected token type (access vs refresh)."""
    settings = get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.ExpiredSignatureError as exc:
        raise AppException(
            401, "انتهت صلاحية الجلسة، يرجى تسجيل الدخول من جديد."
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise AppException(401, "رمز الدخول غير صالح.") from exc

    if payload.get("type") != expected_type:
        raise AppException(401, "رمز الدخول غير صالح.")
    return payload
