"""
FastAPI router for authentication endpoints.

All routes are under /api/v1/auth.

Rate limiting is applied via slowapi (shared limiter from api.rate_limiter).
Error codes from service layer are mapped to appropriate HTTP status codes here;
the service layer only raises ValueError with a code string.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import service
from auth.dependencies import get_current_user
from auth.models import User
from auth.schemas import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    RefreshRequest,
    RegisterRequest,
    ResendOtpRequest,
    ResetPasswordRequest,
    UserResponse,
    VerifyOtpRequest,
)
from db.connection import get_db
from db.models import Student

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Import the shared slowapi limiter so auth endpoints respect the same
# rate-limiting budget as the rest of the API.
from api.rate_limiter import limiter


# ── Registration ───────────────────────────────────────────────────────────


@limiter.limit("5/minute")
@router.post("/register", status_code=201)
async def register(
    request: Request,
    req: RegisterRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new student account and send an email verification OTP.

    The account is created immediately but login is blocked until the OTP is
    verified.  Responds 409 if the email is already registered.
    """
    try:
        await service.register(db, req)
        await db.commit()
    except ValueError as exc:
        msg = str(exc)
        if msg == "EMAIL_TAKEN":
            raise HTTPException(
                status_code=409, detail="This email is already registered"
            )
        raise HTTPException(status_code=400, detail=msg)
    return {
        "message": (
            "Registration successful. "
            "Please check your email for the verification code."
        )
    }


# ── OTP verification + auto-login ─────────────────────────────────────────


@limiter.limit("10/minute")
@router.post("/verify-otp")
async def verify_otp(
    request: Request,
    req: VerifyOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify the 6-digit OTP for email verification or password reset.

    For email_verify: returns access + refresh tokens (auto-login).
    For password_reset: returns a success message (no tokens).
    """
    try:
        user = await service.verify_otp(db, req.email, req.otp, req.purpose)
        if req.purpose == "password_reset":
            await db.commit()
            return {"message": "OTP verified"}
        response = await service.create_tokens_for_user(
            db,
            user,
            request.headers.get("user-agent", ""),
            request.client.host if request.client else "",
        )
        await db.commit()
        return response
    except ValueError as exc:
        msg = str(exc)
        if msg == "INVALID_OTP":
            raise HTTPException(status_code=400, detail="Invalid verification code")
        if msg == "OTP_EXPIRED":
            raise HTTPException(
                status_code=400,
                detail="Verification code has expired. Please request a new one.",
            )
        raise HTTPException(status_code=400, detail=msg)


# ── Login ──────────────────────────────────────────────────────────────────


@limiter.limit("10/minute")
@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    req: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate with email + password and return JWT tokens."""
    try:
        response = await service.login(
            db,
            req.email,
            req.password,
            request.headers.get("user-agent", ""),
            request.client.host if request.client else "",
        )
        await db.commit()
        return response
    except ValueError as exc:
        msg = str(exc)
        if msg == "INVALID_CREDENTIALS":
            raise HTTPException(
                status_code=401, detail="Invalid email or password"
            )
        if msg == "EMAIL_NOT_VERIFIED":
            raise HTTPException(
                status_code=403, detail="Please verify your email address first"
            )
        if msg == "ACCOUNT_DISABLED":
            raise HTTPException(status_code=403, detail="Account is disabled")
        if msg.startswith("ACCOUNT_LOCKED:"):
            minutes = msg.split(":")[1]
            raise HTTPException(
                status_code=429,
                detail=f"Account locked due to too many failed attempts. "
                       f"Try again in {minutes} minute(s).",
            )
        raise HTTPException(status_code=400, detail=msg)


# ── Token refresh ──────────────────────────────────────────────────────────


@limiter.limit("30/minute")
@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Exchange a valid refresh token for a new access + refresh token pair.

    Implements rotation: the old token is revoked and a new one is issued.
    Presenting a previously-revoked token triggers a full session wipe.
    """
    try:
        response = await service.refresh_tokens(
            db,
            req.refresh_token,
            request.headers.get("user-agent", ""),
            request.client.host if request.client else "",
        )
        await db.commit()
        return response
    except ValueError as exc:
        msg = str(exc)
        if msg in ("INVALID_TOKEN", "TOKEN_EXPIRED", "TOKEN_REUSE_DETECTED"):
            raise HTTPException(
                status_code=401, detail="Invalid or expired refresh token"
            )
        raise HTTPException(status_code=400, detail=msg)


# ── Current user ───────────────────────────────────────────────────────────


@limiter.limit("60/minute")
@router.get("/me", response_model=UserResponse)
async def me(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the authenticated user's profile."""
    student_id = None
    if user.role == "student":
        result = await db.execute(
            select(Student.id).where(Student.user_id == user.id)
        )
        student_id = result.scalar_one_or_none()

    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
        email_verified=user.email_verified,
        student_id=student_id,
    )


# ── Password reset flow ────────────────────────────────────────────────────


@limiter.limit("3/minute")
@router.post("/forgot-password")
async def forgot_password(
    request: Request,
    req: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Send a password-reset OTP.

    Always returns 200 — success is indistinguishable from a missing email to
    prevent email enumeration attacks.
    """
    await service.forgot_password(db, req.email)
    await db.commit()
    return {
        "message": (
            "If an account with that email exists, "
            "we have sent a password reset code."
        )
    }


@limiter.limit("5/minute")
@router.post("/reset-password")
async def reset_password(
    request: Request,
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
):
    """Verify the reset OTP and set a new password.

    All active refresh tokens are revoked so any stolen sessions are
    terminated immediately.
    """
    try:
        await service.reset_password(db, req.email, req.otp, req.new_password)
        await db.commit()
        return {
            "message": (
                "Password reset successful. "
                "You can now log in with your new password."
            )
        }
    except ValueError as exc:
        msg = str(exc)
        if msg == "INVALID_OTP":
            raise HTTPException(status_code=400, detail="Invalid verification code")
        if msg == "OTP_EXPIRED":
            raise HTTPException(
                status_code=400, detail="Verification code has expired"
            )
        raise HTTPException(status_code=400, detail=msg)


# ── OTP resend ─────────────────────────────────────────────────────────────


@limiter.limit("3/minute")
@router.post("/resend-otp")
async def resend_otp(
    request: Request,
    req: ResendOtpRequest,
    db: AsyncSession = Depends(get_db),
):
    """Re-send an OTP code (email_verify or password_reset).

    Enforces a 60-second cooldown between requests.
    """
    try:
        await service.resend_otp(db, req.email, req.purpose)
        await db.commit()
        return {
            "message": "A new verification code has been sent to your email."
        }
    except ValueError as exc:
        msg = str(exc)
        if msg.startswith("OTP_COOLDOWN:"):
            seconds = msg.split(":")[1]
            raise HTTPException(
                status_code=429,
                detail=f"Please wait {seconds} second(s) before requesting a new code.",
            )
        raise HTTPException(status_code=400, detail=msg)


# ── Logout ─────────────────────────────────────────────────────────────────


@limiter.limit("30/minute")
@router.post("/logout")
async def logout(
    request: Request,
    req: RefreshRequest,
    db: AsyncSession = Depends(get_db),
):
    """Revoke the provided refresh token (client-initiated logout).

    The access token is short-lived (15 min) so it becomes invalid naturally.
    The client must discard it from memory on logout.
    """
    await service.logout(db, req.refresh_token)
    await db.commit()
    return {"message": "Logged out successfully"}


# ── Change password ─────────────────────────────────────────────────────────


@limiter.limit("5/minute")
@router.post("/change-password")
async def change_password(
    request: Request,
    req: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Change the authenticated user's password.

    Verifies the current password before accepting the new one.  The new
    password is validated against the same complexity rules as registration.
    All active refresh tokens remain valid — the client is responsible for
    clearing any locally cached credentials.
    """
    # Verify current password against the stored bcrypt hash
    if not service.pwd_context.verify(req.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")

    # Reject if new password is the same as the current one
    if service.pwd_context.verify(req.new_password, user.password_hash):
        raise HTTPException(status_code=400, detail="New password must be different from current password")

    # Validate new password complexity (raises ValueError with a readable message)
    try:
        service.validate_password(req.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Hash and persist the new password
    user.password_hash = service.pwd_context.hash(req.new_password)
    db.add(user)
    await db.commit()

    logger.info("[change-password] user_id=%s password changed", user.id)
    return {"message": "Password changed successfully"}
