# backend/schemas/auth.py
# ВЛАДЕЛЕЦ: TZ-01. Pydantic schemas для auth endpoints.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ── Login ────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class MFALoginRequest(BaseModel):
    state_token: str
    code: str = Field(min_length=6, max_length=8)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int | None = None


class MFARequiredResponse(BaseModel):
    mfa_required: bool = True
    state_token: str


# ── MFA Setup ────────────────────────────────────────────────────────────────

class MFASetupResponse(BaseModel):
    qr_code: str  # base64-encoded PNG
    secret: str   # показывается однажды (для ручного ввода)


class MFAVerifySetupRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


# ── Users ────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: uuid.UUID
    org_id: uuid.UUID
    email: str
    role: str
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreateUserRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="viewer", pattern=r"^(super_admin|org_owner|org_admin|device_manager|script_runner|viewer|api_user)$")


class UpdateRoleRequest(BaseModel):
    role: str = Field(pattern=r"^(super_admin|org_owner|org_admin|device_manager|script_runner|viewer|api_user)$")


# ── API Keys ─────────────────────────────────────────────────────────────────

class CreateAPIKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    permissions: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    key_type: str = Field(default="user", pattern=r"^(user|agent)$")


class APIKeyCreatedResponse(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    raw_key: str    # показывается ОДИН РАЗ
    permissions: list[str]
    expires_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class APIKeyResponse(BaseModel):
    """Список API ключей (raw_key НЕ включается)."""
    id: uuid.UUID
    name: str
    key_prefix: str
    permissions: list[str]
    is_active: bool
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Audit Log ─────────────────────────────────────────────────────────────────

class AuditLogResponse(BaseModel):
    id: uuid.UUID
    created_at: datetime
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    ip_address: str | None = None
    old_value: dict | None = None
    new_value: dict | None = None
    meta: dict = {}

    model_config = {"from_attributes": True}


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
