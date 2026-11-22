# backend/schemas/auth.py
# ВЛАДЕЛЕЦ: TZ-01. Pydantic schemas для auth endpoints.
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from backend.core.audit_identity import TASK_AGENT_RESULT, TASK_EXECUTION_REQUESTED
from backend.core.rbac import Role
from backend.middleware.request_id import REQUEST_ID_PATTERN

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
    refresh_token: str | None = None  # Возвращается в теле для сред без cookie (tunnel/proxy)
    user: UserResponse | None = None


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


# Forward reference в TokenResponse → UserResponse: пересборка модели после определения UserResponse
TokenResponse.model_rebuild()


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

_AUDIT_STATUS_VALUES = frozenset({
    "success", "succeeded", "ok", "completed", "failed", "failure", "error", "rejected",
    "warning", "degraded", "partial", "unknown",
})
_AUDIT_ROLES = frozenset(role.value for role in Role)
_AUDITED_ROLE_ACTIONS = frozenset({"user.create", "user.role_change"})
_AUDITED_VPN_ACTIONS = frozenset({"vpn.profile.created", "vpn.profile.revision_created", "vpn.profile.archived"})


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

    @field_validator("old_value", "new_value", mode="before")
    @classmethod
    def project_diff(cls, value: Any, info: ValidationInfo) -> dict[str, str] | None:
        # Legacy JSON can include credentials or other arbitrary snapshots. Only
        # publish fields with action-specific semantics and a closed value domain.
        if (info.data.get("action") not in _AUDITED_ROLE_ACTIONS or info.data.get("resource_type") != "user"
                or not isinstance(value, dict)):
            return None
        role = value.get("role")
        return {"role": role} if isinstance(role, str) and role in _AUDIT_ROLES else None

    @field_validator("meta", mode="before")
    @classmethod
    def project_metadata(cls, value: Any, info: ValidationInfo) -> dict[str, str | int]:
        if not isinstance(value, dict):
            return {}
        visible: dict[str, str | int] = {}
        status = value.get("status")
        if isinstance(status, str) and len(status) <= 9 and status.lower() in _AUDIT_STATUS_VALUES:
            visible["status"] = status
        for key, lower, upper in (("http_status", 100, 599), ("duration_ms", 0, 2**31 - 1)):
            raw = value.get(key)
            if type(raw) is int and lower <= raw <= upper:
                visible[key] = raw
        for key, pattern in (("request_id", REQUEST_ID_PATTERN), ("trace_id", r"[0-9a-fA-F]{32}")):
            raw = value.get(key)
            if isinstance(raw, str) and len(raw) <= 64 and re.fullmatch(pattern, raw):
                visible[key] = raw
        action = info.data.get("action")
        if info.data.get("resource_type") == "task" and action in {TASK_EXECUTION_REQUESTED, TASK_AGENT_RESULT}:
            fields = ("device_id", "receipt_id", "requested_by") if action == TASK_AGENT_RESULT else ("device_id",)
            for field in fields:
                raw = value.get(field)
                if isinstance(raw, str) and len(raw) == 36:
                    try:
                        visible[field] = str(uuid.UUID(raw))
                    except ValueError:
                        pass
            outcome = value.get("agent_outcome")
            if action == TASK_AGENT_RESULT and isinstance(outcome, str) and outcome in {
                "completed", "failed", "cancelled", "unknown",
            }:
                visible["agent_outcome"] = outcome
        if action in _AUDITED_VPN_ACTIONS and info.data.get("resource_type") == "vpn_profile":
            revision = value.get("revision")
            if type(revision) is int and 1 <= revision < 2**31:
                visible["revision"] = revision
            revision_id = value.get("revision_id")
            if isinstance(revision_id, str) and len(revision_id) == 36:
                try:
                    visible["revision_id"] = str(uuid.UUID(revision_id))
                except ValueError:
                    pass
        return visible


# ── Pagination ────────────────────────────────────────────────────────────────

class PaginatedResponse(BaseModel):
    items: list
    total: int
    page: int
    per_page: int
    pages: int
