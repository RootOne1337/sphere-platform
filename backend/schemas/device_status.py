# backend/schemas/device_status.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-3. Live device status schemas.
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.vpn.runtime import APP_VPN_OBSERVATION_MAX_AGE_SECONDS, AppVpnObservation

VPN_OBSERVATION_MAX_AGE_SECONDS = 120
DEVICE_HEARTBEAT_MAX_AGE_SECONDS = 120


class DeviceLiveStatus(BaseModel):
    device_id: str
    status: Literal["online", "offline", "busy", "error", "connecting"] = "offline"
    adb_connected: bool = False
    battery: int | None = Field(default=None, ge=0, le=100)
    cpu_usage: float | None = Field(default=None, ge=0.0, le=100.0)
    ram_usage_mb: int | None = None
    screen_on: bool | None = None
    vpn_active: bool | None = Field(default=None, strict=True)
    app_vpn: AppVpnObservation | None = None
    vpn_observed_at: datetime | None = Field(default=None, description="Server receipt time of an explicit Android VPN report; independent of heartbeat")
    vpn_observed_session_id: str | None = Field(default=None, max_length=100)
    vpn_observation_state: Literal["fresh", "stale", "unknown"] = "unknown"
    vpn_observation_max_age_seconds: int = VPN_OBSERVATION_MAX_AGE_SECONDS
    android_version: str | None = None
    agent_version: str | None = Field(default=None, min_length=1, max_length=100)
    agent_version_code: int | None = Field(default=None, ge=1, le=2_147_483_647)
    file_exchange_version: Literal[1] | None = None
    last_heartbeat: datetime | None = None
    # Set by the first accepted pong for the current WebSocket session. Unlike
    # ConnectionManager.connected_at this survives worker changes via Redis.
    connected_since: datetime | None = None
    ws_session_id: str | None = None    # ID WebSocket сессии агента
    current_task_id: uuid.UUID | None = None

    def has_fresh_presence(self, as_of: datetime) -> bool:
        heartbeat = self.last_heartbeat
        return bool(
            self.status in ("online", "busy") and self.ws_session_id
            and heartbeat is not None and heartbeat.tzinfo is not None
            and 0 <= (as_of - heartbeat).total_seconds() < DEVICE_HEARTBEAT_MAX_AGE_SECONDS
        )

    def with_current_vpn_observation(self, as_of: datetime | None = None) -> DeviceLiveStatus:
        """Project freshness at read time without changing retained Redis evidence.

        A reported Android service flag is not a router handshake or an IP/traffic
        probe. Legacy flags with no receipt/session remain unknown. Cache TTL can
        be renewed by unrelated telemetry, so each report has its own clock.
        """
        now = as_of or datetime.now(timezone.utc)
        state: Literal["fresh", "stale", "unknown"] = "unknown"
        active = None
        observation = self.app_vpn
        if observation and observation.ws_session_id == self.ws_session_id:
            # The app-scoped provider runs outside the legacy manager. Prefer
            # its own phase over a legacy false flag emitted on every pong.
            state = observation.freshness(self.ws_session_id, self.has_fresh_presence(now), now)
            if state == "fresh":
                phase = observation.snapshot.phase
                if phase in {"TRANSPORT_READY", "AWAITING_HANDSHAKE", "HANDSHAKE_CONFIRMED"}:
                    active = True
                elif phase in {"IDLE", "DISCONNECTED_CONFIRMED", "PAUSED_GUARD_HELD"}:
                    active = False
                else:
                    state = "unknown"
            return self.model_copy(update={
                "vpn_active": active,
                "vpn_observation_state": state,
                "vpn_observed_at": observation.received_at,
                "vpn_observation_max_age_seconds": APP_VPN_OBSERVATION_MAX_AGE_SECONDS,
            })
        if (
            self.has_fresh_presence(now) and self.vpn_observed_session_id == self.ws_session_id
            and self.vpn_active is not None
            and self.vpn_observed_at is not None and self.vpn_observed_at.tzinfo is not None
        ):
            vpn_age = (now - self.vpn_observed_at).total_seconds()
            if vpn_age >= 0:
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
