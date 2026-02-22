"""
topology.py — реестр инстансов LDPlayer + устройств ADB на воркстанции.
Детальная реализация — TZ-08 SPLIT-5.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class InstanceInfo:
    instance_id: int
    name: str
    adb_serial: Optional[str] = None
    adb_port: Optional[int] = None
    running: bool = False


class TopologyRegistry:
    """In-memory реестр инстансов. Обновляется при каждом опросе LDPlayer."""

    def __init__(self) -> None:
        self._instances: dict[int, InstanceInfo] = {}

    def update(self, instances: list[InstanceInfo]) -> None:
        self._instances = {inst.instance_id: inst for inst in instances}

    def get(self, instance_id: int) -> Optional[InstanceInfo]:
        return self._instances.get(instance_id)

    def all(self) -> list[InstanceInfo]:
        return list(self._instances.values())

    def to_dict(self) -> list[dict]:
        return [
            {
                "instance_id": inst.instance_id,
                "name": inst.name,
                "adb_serial": inst.adb_serial,
                "adb_port": inst.adb_port,
                "running": inst.running,
            }
            for inst in self._instances.values()
        ]
