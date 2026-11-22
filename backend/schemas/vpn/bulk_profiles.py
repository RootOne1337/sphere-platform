"""Bounded catalog batches. Each item retains its own durable request identity."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.schemas.vpn.catalog import VPNProfileImportRequest, VPNProfileSaveResponse
from backend.schemas.vpn.profile import VPNProfileIssue


class VPNProfileBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    items: list[VPNProfileImportRequest] = Field(min_length=1, max_length=100, repr=False)

    @field_validator("items")
    @classmethod
    def distinct_requests(cls, items):
        if len({item.request_id for item in items}) != len(items):
            raise ValueError("duplicate_import_request_id")
        return items


class VPNProfileBatchInspectionItem(BaseModel):
    request_id: uuid.UUID
    config_valid: bool
    issues: list[VPNProfileIssue]


class VPNProfileBatchInspection(BaseModel):
    items: list[VPNProfileBatchInspectionItem]
    config_valid: bool
    persisted: Literal[False] = False
    apply_allowed: Literal[False] = False
    execution_confirmed: Literal[False] = False


class VPNProfileBatchSaveResponse(BaseModel):
    items: list[VPNProfileSaveResponse]
    persisted: Literal[True] = True
    apply_allowed: Literal[False] = False
    execution_confirmed: Literal[False] = False


class VPNProfileBatchStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    request_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)

    @field_validator("request_ids")
    @classmethod
    def distinct_requests(cls, items):
        if len(set(items)) != len(items):
            raise ValueError("duplicate_import_request_id")
        return items


class VPNProfileBatchStatusItem(BaseModel):
    request_id: uuid.UUID
    receipt: VPNProfileSaveResponse | None


class VPNProfileBatchStatusResponse(BaseModel):
    items: list[VPNProfileBatchStatusItem]
