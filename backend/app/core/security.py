"""Password hashing (bcrypt) and JWT creation/validation helpers."""

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt

from app.core.config import get_settings
from app.core.exceptions import AppException

TokenType = Literal["access", "refresh"]

# Which world a token belongs to. Staff are rows in `users`; customers are rows in
# `customer_logins` pointing at `customers` — two separate tables whose ids collide
# freely. Without this claim a token is just `{"sub": 7}`, and the dependency that
# reads it decides what 7 means: customer 7's token would resolve to *user* 7 and
# hand a shop owner whatever role that staff member holds.
#
# Required, never defaulted, on both minting and decoding: a default is exactly how
# a customer token would quietly acquire staff meaning.
TokenRealm = Literal["staff", "customer"]


def hash_password(plain_password: str) -> str:
    """Hash a password with bcrypt and a fresh per-password salt."""
    hashed: bytes = bcrypt.hashpw(plain_password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a password against its hash, returning False on any malformed hash."""
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
    """Verify against a real hash, or a dummy one when the user does not exist.

    Always spending the same bcrypt cost keeps login timing from revealing which
    usernames are registered.
    """
    return verify_password(plain_password, hashed_password or _DUMMY_HASH)


def _create_token(
    subject: str,
    role: str,
    token_type: TokenType,
    expires_delta: timedelta,
    realm: TokenRealm,
) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "role": role,
        "realm": realm,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(subject: str, role: str, *, realm: TokenRealm) -> str:
    """Mint a short-lived access token carrying the subject id, role and realm."""
    settings = get_settings()
    return _create_token(
        subject,
        role,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        realm,
    )


def create_refresh_token(subject: str, role: str, *, realm: TokenRealm) -> str:
    """Mint a longer-lived refresh token used to obtain new access tokens."""
    settings = get_settings()
    return _create_token(
        subject,
        role,
        "refresh",
        timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        realm,
    )


def decode_token(
    token: str, expected_type: TokenType, *, expected_realm: TokenRealm
) -> dict[str, Any]:
    """Decode a JWT, enforcing both the token type and the realm it was minted for.

    Tokens issued before the realm claim existed carry none and are rejected, which
    logs everyone out once. That is the correct trade: accepting a claimless token as
    staff would leave the very hole this exists to close.
    """
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
    if payload.get("realm") != expected_realm:
        # Deliberately the same message as any other bad token: which realm a token
        # belongs to is not something an attacker should learn by probing.
        raise AppException(401, "رمز الدخول غير صالح.")
    return payload
