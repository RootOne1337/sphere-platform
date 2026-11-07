"""Bounded metadata from the authenticated Android control connection."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

Counter = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]
Phase = Literal[
    "IDLE", "APPLYING", "TRANSPORT_READY", "AWAITING_HANDSHAKE", "HANDSHAKE_CONFIRMED",
    "PAUSED_GUARD_HELD", "UNKNOWN_GUARD_HELD", "FAILED_GUARD_HELD", "GUARD_UNCONFIRMED",
    "DISCONNECTED_CONFIRMED", "REVOKED_GUARD_HELD", "RECONCILIATION_REQUIRED",
    "STATUS_UNKNOWN", "OPERATION_REJECTED", "OUTCOME_UNKNOWN", "CONSENT_REQUIRED",
]


class AppVpnSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    requestId: str | None = None
    sessionId: str | None = None
    profileRevisionId: str | None = None
    phase: Phase = "IDLE"
    reason: str | None = Field(default=None, max_length=128, pattern=r"^[a-z][a-z0-9_]+$")
    nativeVersion: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_.+\-]+$")
    handshakeEpochSeconds: Counter | None = None
    rxBytes: Counter | None = None
    txBytes: Counter | None = None
    sampledAtEpochMs: Counter
    providerPid: int = Field(strict=True, ge=1, le=2**31 - 1)
    trafficMode: Literal["selected_apps", "all_apps_except_control"] | None = None

    @field_validator("requestId", "sessionId", "profileRevisionId")
    @classmethod
    def canonical_id(cls, value: str | None) -> str | None:
        if value is not None and not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
            raise ValueError("invalid_identity")
        return value


class AppVpnObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot: AppVpnSnapshot
    received_at: datetime
    ws_session_id: str = Field(min_length=1, max_length=100)

    def freshness(self, current_session: str | None, online: bool, now: datetime | None = None) -> Literal["unknown", "fresh", "stale"]:
        now = now or datetime.now(timezone.utc)
        if not online or current_session != self.ws_session_id:
            return "unknown"
        if self.received_at.tzinfo is None:
            return "unknown"
        receipt_age = (now - self.received_at).total_seconds()
        sample_age = now.timestamp() - self.snapshot.sampledAtEpochMs / 1000
        if not 0 <= receipt_age < 15:
            return "stale"
        if not -5 <= sample_age < 15:
            return "stale"  # Heartbeat/status read never renews the native sample.
        return "fresh"


class AppVpnDevice(BaseModel):
    device_id: str
    name: str
    model: str | None
    android_version: str | None
    status: str
    agent_version: str | None
    last_heartbeat: datetime | None
    observation: AppVpnObservation | None
    freshness: Literal["unknown", "fresh", "stale"]


class AppVpnDevicePage(BaseModel):
    items: list[AppVpnDevice]
    total: int
    page: int
    page_size: int
    as_of: datetime


def parse_app_vpn_report(message: object) -> AppVpnSnapshot | None:
    try:
        if not isinstance(message, dict) or message.keys() != {"type", "schema_version", "snapshot"}:
            return None
        if message["type"] != "app_vpn_status" or type(message["schema_version"]) is not int or message["schema_version"] != 1:
            return None
        if len(json.dumps(message, allow_nan=False).encode()) > 8192:
            return None
        return AppVpnSnapshot.model_validate(message["snapshot"])
    except (ValidationError, ValueError, TypeError, RecursionError):
        return None
