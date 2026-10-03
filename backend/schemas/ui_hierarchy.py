"""Bounded, read-only Android UI Automator snapshot contract."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UiBounds(BaseModel):
    left: int
    top: int
    right: int
    bottom: int


class UiHierarchyNode(BaseModel):
    id: int
    parent_id: int | None
    depth: int
    xpath: str
    attributes: dict[str, str]
    bounds: UiBounds | None


class UiHierarchyResponse(BaseModel):
    device_id: str
    snapshot_id: str
    requested_at: datetime
    completed_at: datetime
    source: Literal["android_uiautomator_root"] = "android_uiautomator_root"
    width: int = Field(ge=1, le=16384)
    height: int = Field(ge=1, le=16384)
    rotation: int = Field(ge=0, le=3)
    nodes: list[UiHierarchyNode] = Field(max_length=4096)
