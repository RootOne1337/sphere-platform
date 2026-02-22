# backend/schemas/discovery.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-5. Network discovery schemas.
from __future__ import annotations

import ipaddress
import uuid

from pydantic import BaseModel, Field, field_validator


class DiscoverRequest(BaseModel):
    subnet: str = Field(description="e.g. '192.168.1.0/24' or '10.0.0.0/16'")
    port_range: list[int] = Field(
        default=[5554, 5584],
        min_length=2,
        max_length=2,
        description="[low_port, high_port] inclusive",
    )
    timeout_ms: int = Field(default=500, ge=100, le=5000)
    workstation_id: uuid.UUID
    auto_register: bool = True
    group_id: uuid.UUID | None = None

    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v: str) -> str:
        try:
            net = ipaddress.ip_network(v, strict=False)
        except ValueError as exc:
            raise ValueError(str(exc))
        # Security: reject subnets larger than /16 (65536 hosts)
        if net.num_addresses > 65536:
            raise ValueError(
                "Subnet too large. Maximum allowed is /16 (65536 hosts)"
            )
        return str(net)

    @field_validator("port_range")
    @classmethod
    def validate_port_range(cls, v: list[int]) -> list[int]:
        if len(v) != 2:
            raise ValueError("port_range must have exactly 2 elements: [low, high]")
        low, high = v
        if not (1 <= low <= 65535 and 1 <= high <= 65535):
            raise ValueError("Ports must be in range 1-65535")
        if low > high:
            raise ValueError("Low port must be ≤ high port")
        return v


class DiscoveredDevice(BaseModel):
    ip: str
    port: int
    serial: str
    model: str | None = None
    android_version: str | None = None
    already_registered: bool
    registered_id: str | None = None


class DiscoverResponse(BaseModel):
    scanned: int
    found: int
    registered: int
    devices: list[DiscoveredDevice]
    duration_ms: float
