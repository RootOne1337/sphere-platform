# backend/schemas/events.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-5. Fleet event types and schema.
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    DEVICE_ONLINE = "device.online"
    DEVICE_OFFLINE = "device.offline"
    DEVICE_STATUS_CHANGE = "device.status_change"
    COMMAND_STARTED = "command.started"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    TASK_PROGRESS = "task.progress"
    VPN_ASSIGNED = "vpn.assigned"
    VPN_FAILED = "vpn.failed"
    ALERT_TRIGGERED = "alert.triggered"
    STREAM_STARTED = "stream.started"
    STREAM_STOPPED = "stream.stopped"


class FleetEvent(BaseModel):
    event_type: EventType
    device_id: str | None = None
    org_id: str
    payload: dict = Field(default_factory=dict)
    # MED-6+LOW-2: datetime.utcnow() deprecated since Python 3.12 — использовать timezone.utc
    ts: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
