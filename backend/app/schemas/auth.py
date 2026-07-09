"""Pydantic schemas for authentication (signup, login, token, user)."""

from datetime import datetime

from pydantic import BaseModel, EmailStr


class SignupRequest(BaseModel):
    """What the client POSTs to /auth/signup."""
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    """What the client POSTs to /auth/login."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """What /auth/login returns: the signed JWT + its type."""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """
    Public view of a user — deliberately excludes hashed_password.
    Built directly from the SQLAlchemy User object (from_attributes).
    """
    id: int
    email: EmailStr
    created_at: datetime

    class Config:
        from_attributes = True
