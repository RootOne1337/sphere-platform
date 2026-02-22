"""
Pydantic-модели PC Agent.
Используются ldplayer.py, telemetry.py, topology.py.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# SPLIT-2: LDPlayer
# ---------------------------------------------------------------------------

class InstanceStatus(str, Enum):
    STOPPED = "stopped"
    RUNNING = "running"
    STARTING = "starting"
    ERROR = "error"


class LDPlayerInstance(BaseModel):
    index: int
    name: str
    status: InstanceStatus
    pid: int | None = None
    adb_port: int | None = None  # базовый + index * 2


# ---------------------------------------------------------------------------
# SPLIT-3: Telemetry
# ---------------------------------------------------------------------------

class NetworkStats(BaseModel):
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int


class DiskStats(BaseModel):
    path: str
    total_gb: float
    used_gb: float
    free_gb: float
    percent: float


class WorkstationTelemetry(BaseModel):
    workstation_id: str
    timestamp: float
    cpu_percent: float
    cpu_count: int
    ram_total_mb: int
    ram_used_mb: int
    ram_percent: float
    disk: list[DiskStats]
    network: NetworkStats
    ldplayer_instances_running: int


# ---------------------------------------------------------------------------
# SPLIT-5: Topology
# ---------------------------------------------------------------------------

class InstanceRegistration(BaseModel):
    index: int
    name: str
    adb_port: int
    android_serial: str | None = None  # e.g. "127.0.0.1:5554"


class WorkstationRegistration(BaseModel):
    workstation_id: str
    hostname: str
    os_version: str
    ip_address: str
    instances: list[InstanceRegistration]
    agent_version: str
