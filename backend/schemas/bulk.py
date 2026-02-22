# backend/schemas/bulk.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-4. Bulk action schemas.
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator


class BulkActionType(str, Enum):
    REBOOT = "reboot"
    CONNECT_ADB = "connect_adb"
    DISCONNECT_ADB = "disconnect_adb"
    SET_GROUP = "set_group"
    SET_TAGS = "set_tags"
    SEND_COMMAND = "send_command"


class BulkActionRequest(BaseModel):
    action: BulkActionType
    device_ids: list[str] = Field(min_length=1, max_length=500)
    params: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_params(self) -> "BulkActionRequest":
        if self.action == BulkActionType.SET_GROUP:
            if "group_id" not in self.params:
                raise ValueError("params.group_id required for set_group action")
        if self.action == BulkActionType.SEND_COMMAND:
            if "command_type" not in self.params:
                raise ValueError("params.command_type required for send_command action")
        return self


class BulkActionItemResult(BaseModel):
    device_id: str
    success: bool
    error: str | None = None


class BulkActionResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BulkActionItemResult]


class BulkDeleteRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)


class BulkDeleteResponse(BaseModel):
    deleted: int
