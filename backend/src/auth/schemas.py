"""
Pydantic v2 schemas for the authentication module.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=5, le=120)
    preferred_language: str = Field(default="en")
    preferred_style: str = Field(
        default="default",
        pattern="^(default|pirate|astronaut|gamer)$",
    )
    interests: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Interests for metaphor personalization (max 20 entries, 50 chars each)",
    )

    @model_validator(mode="after")
    def _clean_interests(self) -> "RegisterRequest":
        seen: set[str] = set()
        cleaned: list[str] = []
        for entry in self.interests:
            trimmed = entry.strip()[:50]
            if trimmed and trimmed not in seen:
                seen.add(trimmed)
                cleaned.append(trimmed)
        self.interests = cleaned
        return self


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    purpose: str = Field(default="email_verify", pattern="^(email_verify|password_reset)$")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    role: str
    is_active: bool
    email_verified: bool
    student_id: UUID | None = None

    model_config = {"from_attributes": True}


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str = Field(..., min_length=6, max_length=6)
    new_password: str = Field(..., min_length=8, max_length=128)


class ResendOtpRequest(BaseModel):
    email: EmailStr
    purpose: str = Field(..., pattern="^(email_verify|password_reset)$")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)
