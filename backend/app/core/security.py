"""
Auth crypto utilities: password hashing and JWT creation/verification.

Two independent concerns live here:
  1. Passwords  -> bcrypt (one-way hash, never reversible)
  2. Sessions   -> JWT (signed token proving identity on every request)
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt

from app.config import settings


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------
def hash_password(password: str) -> str:
    """
    Hash a plaintext password with bcrypt (salt generated automatically).

    Returns the hash as a string safe to store in users.hashed_password.
    Note: bcrypt only uses the first 72 bytes of the password.
    """
    hashed: bytes = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check a login attempt against a stored hash.

    We never decrypt — bcrypt re-hashes `plain_password` with the salt baked
    into `hashed_password` and compares. Returns True on match.
    """
    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )


# ---------------------------------------------------------------------------
# JWTs
# ---------------------------------------------------------------------------
def create_access_token(subject: str, expires_minutes: Optional[int] = None) -> str:
    """
    Create a signed JWT identifying `subject` (the user's id, as a string).

    Payload:
      sub -> who the token belongs to
      exp -> when it stops working (PyJWT enforces this on decode)
    """
    minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expire = datetime.now(timezone.utc) + timedelta(minutes=minutes)

    payload = {
        "sub": str(subject),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> Optional[str]:
    """
    Verify a JWT's signature + expiry and return its `sub` (user id string).

    Returns None if the token is expired, tampered with, or otherwise invalid,
    so callers can turn that into a 401 without catching exceptions themselves.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
