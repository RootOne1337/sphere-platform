from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas.vpn.profile import AppTrafficPolicy, VPNProfilePreflightRequest


class VPNProfileImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)

    request_id: uuid.UUID
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)
    profile: VPNProfilePreflightRequest = Field(repr=False)

    @field_validator("name")
    @classmethod
    def valid_name(cls, name: str) -> str:
        name = name.strip()
        if not name or any(ord(c) < 32 for c in name):
            raise ValueError("invalid_profile_name")
        return name


class VPNProfileAppendRequest(VPNProfileImportRequest):
    expected_revision: int = Field(ge=1, le=2**31 - 2)


class VPNProfileArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=1, le=2**31 - 1)


class VPNProfileMetadata(BaseModel):
    name: str
    description: str
    provider_id: str
    protocol: str
    protocol_version: str
    schema_version: int
    traffic_policy: AppTrafficPolicy
    endpoint: str
    features: list[str]
    apply_allowed: Literal[False] = False


class VPNProfileRevisionResponse(VPNProfileMetadata):
    id: uuid.UUID
    profile_id: uuid.UUID
    revision: int
    request_id: uuid.UUID
    created_at: datetime


class VPNProfileResponse(VPNProfileMetadata):
    id: uuid.UUID
    revision_id: uuid.UUID
    current_revision: int
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class VPNProfilePage(BaseModel):
    items: list[VPNProfileResponse]
    total: int
    page: int
    page_size: int


class VPNProfileRevisionPage(BaseModel):
    items: list[VPNProfileRevisionResponse]
    total: int
    page: int
    page_size: int


class VPNProfileSaveResponse(BaseModel):
    profile_id: uuid.UUID
    revision_id: uuid.UUID
    revision: int
    request_id: uuid.UUID
    persisted: Literal[True] = True
    apply_allowed: Literal[False] = False
    execution_confirmed: Literal[False] = False
