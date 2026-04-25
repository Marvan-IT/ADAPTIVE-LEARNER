"""
Authentication business logic.

Design decisions:
- Student record is created immediately at registration (not deferred to OTP
  verification) so that display_name / preferences are persisted even if the
  user takes a long time to verify.  Login is blocked until email_verified=True.
- OTPs are 6-digit codes hashed with bcrypt before storage.  Bcrypt is
  acceptable here because OTP verification happens only once per login flow.
- Refresh tokens use SHA-256 for fast DB lookups (raw token has 384-bit entropy,
  making preimage attacks computationally infeasible).
- Token reuse detection: if a revoked refresh token is presented, ALL active
  tokens for that user are immediately revoked (RFC 6749 §10.5 pattern).
"""

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from passlib.context import CryptContext
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.email import send_otp_email
from auth.jwt import create_access_token, create_refresh_token, hash_token
from auth.models import OtpCode, RefreshToken, User
from auth.schemas import LoginResponse, RegisterRequest, UserResponse
from config import (
    ACCOUNT_LOCKOUT_MINUTES,
    MAX_FAILED_LOGIN_ATTEMPTS,
    OTP_EXPIRE_MINUTES,
    OTP_RESEND_COOLDOWN_SECONDS,
)
from db.models import Student

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
logger = logging.getLogger(__name__)


# ── Password validation ────────────────────────────────────────────────────


def validate_password(password: str) -> None:
    """Enforce password complexity.  Raises ValueError with a user-readable message."""
    errors = []
    if len(password) < 8:
        errors.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        errors.append("one uppercase letter")
    if not re.search(r"[a-z]", password):
        errors.append("one lowercase letter")
    if not re.search(r"[0-9]", password):
        errors.append("one number")
    if errors:
        raise ValueError(f"Password must contain: {', '.join(errors)}")


# ── Public service functions ───────────────────────────────────────────────


async def register(db: AsyncSession, req: RegisterRequest) -> User:
    """Create an unverified user + linked Student record, then send an email OTP.

    The Student record is created immediately so that display_name / preferences
    are persisted even if verification is delayed.  Login is blocked until the
    OTP is verified (email_verified=False).
    """
    validate_password(req.password)

    # Normalise and deduplicate email
    email = req.email.lower()

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise ValueError("EMAIL_TAKEN")

    user = User(
        email=email,
        password_hash=pwd_context.hash(req.password),
        role="student",
    )
    db.add(user)
    await db.flush()  # populate user.id

    student = Student(
        display_name=req.display_name,
        age=req.age,
        preferred_language=req.preferred_language,
        preferred_style=req.preferred_style,
        interests=req.interests,
        user_id=user.id,
    )
    db.add(student)
    await db.flush()

    await _generate_and_send_otp(db, user, "email_verify")
    logger.info("[auth.register] New user registered: %s", email)
    return user


async def verify_otp(db: AsyncSession, email: str, otp: str, purpose: str) -> User:
    """Verify an OTP code.

    For email_verify purpose: marks user.email_verified = True.
    Returns the User on success; raises ValueError with an error code on failure.
    """
    user = await _get_user_by_email(db, email)
    if not user:
        # Do not reveal that the email doesn't exist
        raise ValueError("INVALID_OTP")

    result = await db.execute(
        select(OtpCode)
        .where(
            OtpCode.user_id == user.id,
            OtpCode.purpose == purpose,
            OtpCode.used_at.is_(None),
        )
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    otp_record = result.scalar_one_or_none()

    if not otp_record:
        raise ValueError("INVALID_OTP")
    if otp_record.expires_at < datetime.now(timezone.utc):
        raise ValueError("OTP_EXPIRED")
    if not pwd_context.verify(otp, otp_record.code_hash):
        raise ValueError("INVALID_OTP")

    # Mark OTP consumed
    otp_record.used_at = datetime.now(timezone.utc)

    if purpose == "email_verify":
        user.email_verified = True
        logger.info("[auth.verify_otp] Email verified for user: %s", user.email)

    await db.flush()
    return user


async def create_tokens_for_user(
    db: AsyncSession,
    user: User,
    user_agent: str = "",
    ip_address: str = "",
) -> LoginResponse:
    """Issue a fresh access + refresh token pair for an already-authenticated user.

    Used for auto-login after OTP verification (so the frontend gets tokens
    immediately without requiring a separate /login call).
    """
    student_id = await _get_student_id(db, user)

    access_token = create_access_token(str(user.id), user.role, student_id)
    raw_refresh, _ = create_refresh_token()

    rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        user_agent=user_agent[:500] if user_agent else None,
        ip_address=ip_address[:45] if ip_address else None,
    )
    db.add(rt)
    await db.flush()

    return LoginResponse(
        access_token=access_token,
        refresh_token=raw_refresh,
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            email_verified=user.email_verified,
            student_id=UUID(student_id) if student_id else None,
        ),
    )


async def login(
    db: AsyncSession,
    email: str,
    password: str,
    user_agent: str = "",
    ip_address: str = "",
) -> LoginResponse:
    """Authenticate a user by email + password and return JWT tokens.

    Error codes (raised as ValueError):
      INVALID_CREDENTIALS  — email not found or wrong password
      ACCOUNT_DISABLED     — user.is_active is False
      EMAIL_NOT_VERIFIED   — user has not verified their email yet
      ACCOUNT_LOCKED:<N>   — account locked; N = minutes remaining
    """
    user = await _get_user_by_email(db, email)
    if not user:
        raise ValueError("INVALID_CREDENTIALS")

    if not user.is_active:
        raise ValueError("ACCOUNT_DISABLED")

    # Check lockout
    if user.locked_until and user.locked_until > datetime.now(timezone.utc):
        remaining = int(
            (user.locked_until - datetime.now(timezone.utc)).total_seconds() / 60
        ) + 1
        raise ValueError(f"ACCOUNT_LOCKED:{remaining}")

    if not pwd_context.verify(password, user.password_hash):
        user.failed_login_attempts += 1
        if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
            user.locked_until = datetime.now(timezone.utc) + timedelta(
                minutes=ACCOUNT_LOCKOUT_MINUTES
            )
            logger.warning(
                "[auth.login] Account locked after %d failed attempts: %s",
                user.failed_login_attempts,
                user.email,
            )
        await db.flush()
        raise ValueError("INVALID_CREDENTIALS")

    if not user.email_verified:
        raise ValueError("EMAIL_NOT_VERIFIED")

    # Reset failure counter on successful credential check
    user.failed_login_attempts = 0
    user.locked_until = None

    response = await create_tokens_for_user(db, user, user_agent, ip_address)
    logger.info("[auth.login] Successful login: %s", user.email)
    return response


async def refresh_tokens(
    db: AsyncSession,
    raw_refresh: str,
    user_agent: str = "",
    ip_address: str = "",
) -> LoginResponse:
    """Rotate a refresh token and issue a new access + refresh pair.

    Implements refresh token rotation with reuse detection:
    - If the presented token has already been revoked, ALL active tokens for
      that user are revoked (indicates possible token theft).

    Error codes:
      INVALID_TOKEN        — token not found in DB
      TOKEN_REUSE_DETECTED — revoked token presented; all tokens wiped
      TOKEN_EXPIRED        — token past its expiry
    """
    token_hash = hash_token(raw_refresh)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()

    if not rt:
        raise ValueError("INVALID_TOKEN")

    if rt.revoked_at:
        # Token reuse — revoke every active token for this user
        await db.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == rt.user_id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(timezone.utc))
        )
        await db.flush()
        logger.warning(
            "[auth.refresh] Token reuse detected for user_id=%s — all tokens revoked",
            rt.user_id,
        )
        raise ValueError("TOKEN_REUSE_DETECTED")

    if rt.expires_at < datetime.now(timezone.utc):
        raise ValueError("TOKEN_EXPIRED")

    # Revoke the old token
    rt.revoked_at = datetime.now(timezone.utc)

    # Load user
    user_result = await db.execute(select(User).where(User.id == rt.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.is_active:
        raise ValueError("INVALID_TOKEN")

    student_id = await _get_student_id(db, user)

    access_token = create_access_token(str(user.id), user.role, student_id)
    new_raw_refresh, _ = create_refresh_token()

    new_rt = RefreshToken(
        user_id=user.id,
        token_hash=hash_token(new_raw_refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=30),
        user_agent=user_agent[:500] if user_agent else None,
        ip_address=ip_address[:45] if ip_address else None,
    )
    db.add(new_rt)
    await db.flush()  # populate new_rt.id

    # Link old token to its replacement for audit trail
    rt.replaced_by = new_rt.id
    await db.flush()

    return LoginResponse(
        access_token=access_token,
        refresh_token=new_raw_refresh,
        user=UserResponse(
            id=user.id,
            email=user.email,
            role=user.role,
            is_active=user.is_active,
            email_verified=user.email_verified,
            student_id=UUID(student_id) if student_id else None,
        ),
    )


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Send a password-reset OTP.

    Always returns without error to prevent email enumeration attacks.
    """
    user = await _get_user_by_email(db, email)
    if not user or not user.is_active:
        return  # Silent — do not reveal whether the email exists
    await _generate_and_send_otp(db, user, "password_reset")


async def reset_password(
    db: AsyncSession, email: str, otp: str, new_password: str
) -> None:
    """Verify OTP and set a new password.  Revokes all refresh tokens."""
    validate_password(new_password)
    user = await verify_otp(db, email, otp, "password_reset")
    user.password_hash = pwd_context.hash(new_password)

    # Revoke all active refresh tokens so any stolen sessions are terminated
    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.flush()
    logger.info("[auth.reset_password] Password reset for user: %s", user.email)


async def resend_otp(db: AsyncSession, email: str, purpose: str) -> None:
    """Re-send an OTP, enforcing a cooldown to prevent abuse.

    Error codes:
      OTP_COOLDOWN:<N> — N seconds must pass before requesting another code
    """
    user = await _get_user_by_email(db, email)
    if not user:
        return  # Silent

    result = await db.execute(
        select(OtpCode)
        .where(OtpCode.user_id == user.id, OtpCode.purpose == purpose)
        .order_by(OtpCode.created_at.desc())
        .limit(1)
    )
    last_otp = result.scalar_one_or_none()
    if last_otp:
        elapsed = (
            datetime.now(timezone.utc) - last_otp.created_at
        ).total_seconds()
        if elapsed < OTP_RESEND_COOLDOWN_SECONDS:
            remaining = int(OTP_RESEND_COOLDOWN_SECONDS - elapsed)
            raise ValueError(f"OTP_COOLDOWN:{remaining}")

    await _generate_and_send_otp(db, user, purpose)


async def logout(db: AsyncSession, raw_refresh: str) -> None:
    """Revoke a single refresh token (client-initiated logout)."""
    token_hash = hash_token(raw_refresh)
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    rt = result.scalar_one_or_none()
    if rt and not rt.revoked_at:
        rt.revoked_at = datetime.now(timezone.utc)
        await db.flush()
        logger.info("[auth.logout] Refresh token revoked for user_id=%s", rt.user_id)


# ── Internal helpers ───────────────────────────────────────────────────────


async def _get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def _get_student_id(db: AsyncSession, user: User) -> str | None:
    """Return the student UUID string for a student-role user, else None."""
    if user.role != "student":
        return None
    result = await db.execute(
        select(Student.id).where(Student.user_id == user.id)
    )
    student_id_val = result.scalar_one_or_none()
    return str(student_id_val) if student_id_val else None


async def _generate_and_send_otp(
    db: AsyncSession, user: User, purpose: str
) -> None:
    """Invalidate any existing OTPs for the user+purpose, create a new one, and email it."""
    # Invalidate all unused OTPs for this purpose (prevents reuse of old codes)
    await db.execute(
        update(OtpCode)
        .where(
            OtpCode.user_id == user.id,
            OtpCode.purpose == purpose,
            OtpCode.used_at.is_(None),
        )
        .values(used_at=datetime.now(timezone.utc))
    )

    # Generate a zero-padded 6-digit code via cryptographically secure RNG
    otp = f"{secrets.randbelow(1_000_000):06d}"

    otp_record = OtpCode(
        user_id=user.id,
        code_hash=pwd_context.hash(otp),
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
    )
    db.add(otp_record)
    await db.flush()

    await send_otp_email(user.email, otp, purpose)
