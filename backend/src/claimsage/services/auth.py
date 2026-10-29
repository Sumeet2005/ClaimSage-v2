"""Password hashing and JWT access-token utilities."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from claimsage.core.config import get_settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    """Return a secure Argon2 password hash."""
    if len(password) < 12:
        raise ValueError("Passwords must contain at least 12 characters.")

    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a password against its stored hash."""
    return password_hash.verify(password, hashed_password)


def create_access_token(employee_id: UUID) -> str:
    """Create a short-lived JWT for an authenticated employee."""
    settings = get_settings()
    secret = settings.jwt_secret_key.get_secret_value()

    if len(secret) < 32:
        raise ValueError(
            "Configure JWT_SECRET_KEY with at least 32 characters before issuing tokens."
        )

    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": str(employee_id),
        "iat": now,
        "exp": expires_at,
        "iss": "claimsage-api",
        "aud": "claimsage",
    }

    return jwt.encode(
        payload,
        secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> UUID:
    """Validate a JWT and return its employee ID."""
    settings = get_settings()
    secret = settings.jwt_secret_key.get_secret_value()

    if len(secret) < 32:
        raise ValueError("JWT_SECRET_KEY is not configured securely.")

    payload = jwt.decode(
        token,
        secret,
        algorithms=[settings.jwt_algorithm],
        issuer="claimsage-api",
        audience="claimsage",
        options={"require": ["sub", "iat", "exp", "iss", "aud"]},
    )

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("Invalid employee identity.")

    try:
        return UUID(subject)
    except ValueError as exc:
        raise jwt.InvalidTokenError("Invalid employee identity.") from exc