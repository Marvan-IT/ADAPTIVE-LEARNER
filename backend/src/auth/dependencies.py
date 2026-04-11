"""
FastAPI dependency functions for authentication and authorization.

Usage in route handlers:
    from auth.dependencies import get_current_user, require_admin, require_student

    @router.get("/me")
    async def me(user: User = Depends(get_current_user)):
        ...

    @router.delete("/admin-only")
    async def admin_action(user: User = Depends(require_admin)):
        ...
"""

import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.jwt import decode_access_token
from auth.models import User
from db.connection import get_db

logger = logging.getLogger(__name__)

# Auto-error=False so we can return a clean 401 instead of FastAPI's default 403
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate Bearer JWT and return the authenticated User.

    Raises HTTP 401 if:
    - No Authorization header is present
    - Token is malformed, expired, or has an invalid signature
    - User is not found or is inactive
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or account disabled",
        )

    return user


def require_role(*roles: str):
    """Dependency factory that restricts access to specific roles.

    Example:
        @router.post("/admin/action")
        async def action(user: User = Depends(require_role("admin"))):
            ...
    """
    async def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return user

    return _check_role


# Convenience aliases
require_admin = require_role("admin")
require_student = require_role("student")
