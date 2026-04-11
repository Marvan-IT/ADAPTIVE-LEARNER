"""
JWT utilities for ADA authentication.

- Access tokens: short-lived HS256 JWTs (15 min)
- Refresh tokens: opaque random strings stored hashed in the DB (30 days)

Refresh token hashing uses SHA-256 (fast lookup key) — NOT bcrypt, because
bcrypt is deliberately slow and would add unacceptable latency on every
authenticated request.
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from config import (
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    JWT_ALGORITHM,
    JWT_SECRET_KEY,
)


def create_access_token(
    user_id: str,
    role: str,
    student_id: str | None = None,
) -> str:
    """Encode a short-lived HS256 access JWT.

    Payload fields:
      sub        — user UUID string
      role       — "student" | "admin"
      student_id — student UUID string (None for admin users)
      type       — "access" (allows future differentiation from other token types)
      iat        — issued-at (UTC)
      exp        — expiry (UTC)
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "student_id": student_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=JWT_ACCESS_TOKEN_EXPIRE_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def create_refresh_token() -> tuple[str, str]:
    """Generate a cryptographically random refresh token.

    Returns:
        (raw_token, jti) where:
          raw_token — 48-byte URL-safe base64 string sent to the client
          jti       — UUID4 string (not stored separately; token_hash is the lookup key)

    The caller must hash raw_token with hash_token() before persisting it.
    """
    raw_token = secrets.token_urlsafe(48)
    jti = str(uuid.uuid4())
    return raw_token, jti


def decode_access_token(token: str) -> dict:
    """Decode and validate an access JWT.

    Raises jwt.ExpiredSignatureError, jwt.InvalidTokenError on failure.
    """
    return jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])


def hash_token(token: str) -> str:
    """SHA-256 hex digest of a refresh token for DB storage.

    SHA-256 is appropriate here because:
    - The raw token already has 48 bytes (384 bits) of entropy from secrets.token_urlsafe
    - We need fast constant-time lookup — bcrypt would add ~100ms per request
    - The hash is only exploitable if the DB is compromised AND the attacker
      can brute-force a 384-bit random token, which is computationally infeasible
    """
    return hashlib.sha256(token.encode()).hexdigest()
