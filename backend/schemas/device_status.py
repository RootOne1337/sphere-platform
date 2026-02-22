# backend/schemas/device_status.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3. Live device status schemas.
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class DeviceLiveStatus(BaseModel):
    device_id: str
    status: Literal["online", "offline", "busy", "error", "connecting"] = "offline"
    adb_connected: bool = False
    battery: int | None = Field(default=None, ge=0, le=100)
    cpu_usage: float | None = Field(default=None, ge=0.0, le=100.0)
    ram_usage_mb: int | None = None
    screen_on: bool | None = None
    vpn_active: bool | None = None
    android_version: str | None = None
    last_heartbeat: datetime | None = None
    ws_session_id: str | None = None    # ID WebSocket сессии агента
    current_task_id: uuid.UUID | None = None


class BulkStatusRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)


class DeviceStatusItem(BaseModel):
    device_id: str
    status: DeviceLiveStatus | None


class FleetStatusResponse(BaseModel):
    total: int
    online: int
    busy: int
    offline: int
    devices: dict[str, DeviceLiveStatus | None]


class FleetSummaryResponse(BaseModel):
    total: int
    online: int
    busy: int
    offline: int
