"""Pydantic schemas (DTOs) for the authentication module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.domain.models.user import UserRole


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    # bcrypt only uses the first 72 bytes, so cap password length there.
    password: str = Field(min_length=8, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    full_name: str
    role: UserRole
    # Explicit overrides (null = the role's default permissions apply).
    permissions: list[str] | None
    # Permissions actually in force, resolved from the role or the overrides.
    effective_permissions: list[str]
    is_active: bool
    created_at: datetime


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    full_name: str = Field(min_length=3, max_length=100)
    password: str = Field(min_length=8, max_length=72)
    role: UserRole = UserRole.SALES


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=3, max_length=100)
    password: str | None = Field(default=None, min_length=8, max_length=72)
    role: UserRole | None = None
    is_active: bool | None = None
    # Custom permission set replacing the role defaults (omit to leave unchanged).
    permissions: list[str] | None = None
    # True resets the user back to their role's default permissions.
    reset_permissions: bool = False


class PermissionItemOut(BaseModel):
    code: str
    label: str


class PermissionGroupOut(BaseModel):
    group: str
    permissions: list[PermissionItemOut]
