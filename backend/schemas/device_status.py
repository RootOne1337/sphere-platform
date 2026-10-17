# backend/schemas/device_status.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3. Live device status schemas.
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

VPN_OBSERVATION_MAX_AGE_SECONDS = 120


class DeviceLiveStatus(BaseModel):
    device_id: str
    status: Literal["online", "offline", "busy", "error", "connecting"] = "offline"
    adb_connected: bool = False
    battery: int | None = Field(default=None, ge=0, le=100)
    cpu_usage: float | None = Field(default=None, ge=0.0, le=100.0)
    ram_usage_mb: int | None = None
    screen_on: bool | None = None
    vpn_active: bool | None = Field(default=None, strict=True)
    vpn_observed_at: datetime | None = Field(default=None, description="Server receipt time of an explicit Android VPN report; independent of heartbeat")
    vpn_observed_session_id: str | None = Field(default=None, max_length=100)
    vpn_observation_state: Literal["fresh", "stale", "unknown"] = "unknown"
    vpn_observation_max_age_seconds: int = VPN_OBSERVATION_MAX_AGE_SECONDS
    android_version: str | None = None
    agent_version: str | None = Field(default=None, min_length=1, max_length=100)
    agent_version_code: int | None = Field(default=None, ge=1, le=2_147_483_647)
    last_heartbeat: datetime | None = None
    # Set by the first accepted pong for the current WebSocket session. Unlike
    # ConnectionManager.connected_at this survives worker changes via Redis.
    connected_since: datetime | None = None
    ws_session_id: str | None = None    # ID WebSocket сессии агента
    current_task_id: uuid.UUID | None = None

    def with_current_vpn_observation(self, as_of: datetime | None = None) -> DeviceLiveStatus:
        """Project freshness at read time without changing retained Redis evidence.

        A reported Android service flag is not a router handshake or an IP/traffic
        probe. Legacy flags with no receipt/session remain unknown. Cache TTL can
        be renewed by unrelated telemetry, so each report has its own clock.
        """
        now = as_of or datetime.now(timezone.utc)
        state: Literal["fresh", "stale", "unknown"] = "unknown"
        active = None
        if (
            self.status in ("online", "busy") and self.ws_session_id
            and self.vpn_observed_session_id == self.ws_session_id
            and self.vpn_active is not None
            and self.vpn_observed_at is not None and self.vpn_observed_at.tzinfo is not None
            and self.last_heartbeat is not None and self.last_heartbeat.tzinfo is not None
        ):
            heartbeat_age = (now - self.last_heartbeat).total_seconds()
            vpn_age = (now - self.vpn_observed_at).total_seconds()
            if 0 <= heartbeat_age < VPN_OBSERVATION_MAX_AGE_SECONDS and vpn_age >= 0:
                if vpn_age < VPN_OBSERVATION_MAX_AGE_SECONDS:
                    state, active = "fresh", self.vpn_active
                else:
                    state = "stale"
        return self.model_copy(update={
            "vpn_active": active,
            "vpn_observation_state": state,
            "vpn_observation_max_age_seconds": VPN_OBSERVATION_MAX_AGE_SECONDS,
        })


class BulkStatusRequest(BaseModel):
    device_ids: list[str] = Field(min_length=1, max_length=500)


class DeviceStatusItem(BaseModel):
    device_id: str
    status: DeviceLiveStatus | None


class FleetStatusResponse(BaseModel):
    total: int
    online: int
    busy: int
    connecting: int = 0
    offline: int
    devices: dict[str, DeviceLiveStatus | None]


class FleetSummaryResponse(BaseModel):
    total: int
    online: int
    busy: int
    connecting: int = 0
    offline: int
