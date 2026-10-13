from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import get_settings
from app.core.errors import Unauthorized

logger = logging.getLogger("byg.security")
_hasher = PasswordHasher()
_ephemeral_secret: str | None = None
ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def _secret() -> str:
    global _ephemeral_secret
    settings = get_settings()
    if settings.secret_key:
        return settings.secret_key
    if settings.env == "production":
        raise RuntimeError("SECRET_KEY must be set in production")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_urlsafe(48)
        logger.warning("SECRET_KEY not set: using an ephemeral secret; sessions end when the process restarts")
    return _ephemeral_secret


def create_access_token(user_id: str, token_version: int) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload = {
        "sub": user_id,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.access_token_minutes)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, _secret(), algorithms=[ALGORITHM], options={"require": ["exp", "sub"]})
    except jwt.ExpiredSignatureError as exc:
        raise Unauthorized("Your session has expired. Please sign in again.", code="token_expired") from exc
    except jwt.PyJWTError as exc:
        raise Unauthorized("Invalid authentication token.", code="invalid_token") from exc


def validate_password_strength(password: str) -> list[str]:
    problems = []
    if len(password) < 10:
        problems.append("Use at least 10 characters.")
    if password.lower() == password or password.upper() == password:
        problems.append("Mix upper and lower case letters.")
    if not any(c.isdigit() for c in password):
        problems.append("Include at least one digit.")
    return problems
