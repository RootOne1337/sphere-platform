"""Explicit application bindings and optimistic per-profile automation writes."""

import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.schemas.application_profiles import ProfileKey

_MAX_REVISION = 2_147_483_647


class DeviceApplicationBindingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    application_profile_id: uuid.UUID | None
    application_server_key: ProfileKey | None
    expected_revision: int = Field(ge=0, le=_MAX_REVISION, strict=True)

    @model_validator(mode="after")
    def validate_binding(self) -> "DeviceApplicationBindingUpdate":
        if (self.application_profile_id is None) != (self.application_server_key is None):
            raise ValueError("application profile and server key must be provided or cleared together")
        return self


class DeviceApplicationBindingResponse(BaseModel):
    device_id: uuid.UUID
    application_profile_id: uuid.UUID | None
    application_server_key: ProfileKey | None
    revision: int


class ApplicationAutomationPolicyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    application_profile_id: uuid.UUID
    revision: int = 0
    registration_enabled: bool = False
    registration_script_id: uuid.UUID | None = None
    max_concurrent_registrations: int = 3
    registration_timeout_seconds: int = 600
    farming_enabled: bool = False
    farming_script_id: uuid.UUID | None = None
    max_concurrent_farming: int = 10
    farming_session_duration_seconds: int = 3600
    default_target_level: int = 3
    cooldown_between_sessions_minutes: int = 30


class ApplicationAutomationPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0, le=_MAX_REVISION, strict=True)
    registration_enabled: bool | None = Field(None, strict=True)
    registration_script_id: uuid.UUID | None = None
    max_concurrent_registrations: int | None = Field(None, ge=1, le=100, strict=True)
    registration_timeout_seconds: int | None = Field(None, ge=60, le=7200, strict=True)
    farming_enabled: bool | None = Field(None, strict=True)
    farming_script_id: uuid.UUID | None = None
    max_concurrent_farming: int | None = Field(None, ge=1, le=500, strict=True)
    farming_session_duration_seconds: int | None = Field(None, ge=300, le=86400, strict=True)
    default_target_level: int | None = Field(None, ge=1, le=100, strict=True)
    cooldown_between_sessions_minutes: int | None = Field(None, ge=0, le=1440, strict=True)

    @model_validator(mode="after")
    def validate_changes(self) -> "ApplicationAutomationPolicyUpdate":
        fields = self.model_fields_set - {"expected_revision"}
        if not fields:
            raise ValueError("expected at least one policy field")
        if any(getattr(self, key) is None for key in fields - {"registration_script_id", "farming_script_id"}):
            raise ValueError("only script IDs can be cleared")
        return self
