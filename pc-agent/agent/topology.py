"""
TopologyReporter — регистрация воркстанции и инстансов на сервере.
SPHERE-045  TZ-08 SPLIT-5
"""
from __future__ import annotations

import platform
import socket
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

from loguru import logger

from .config import config
from .models import InstanceRegistration, WorkstationRegistration

if TYPE_CHECKING:
    from .client import AgentWebSocketClient
    from .ldplayer import LDPlayerManager

AGENT_VERSION = "1.0.0"


class TopologyReporter:
    """Отправляет полную топологию сразу после WS-аутентификации."""

    def __init__(
        self,
        ws_client: "AgentWebSocketClient",
        ldplayer: "LDPlayerManager",
    ) -> None:
        self._ws = ws_client
        self._ldplayer = ldplayer

    async def report_on_connect(self) -> None:
        """Вызывается сразу после успешного подключения — отправляет WorkstationRegistration."""
        try:
            reg = await self._build_registration()
            await self._ws.send({
                "type": "workstation_register",
                "payload": reg.model_dump(),
            })
            logger.info(
                f"Топология отправлена: {len(reg.instances)} инстансов "
                f"на {reg.hostname} ({reg.ip_address})"
            )
        except Exception as exc:
            logger.error(f"Ошибка отправки топологии: {exc!r}")

    async def _build_registration(self) -> WorkstationRegistration:
        instances_raw = await self._ldplayer.list_instances()
        instances = [
            InstanceRegistration(
                index=inst.index,
                name=inst.name,
                adb_port=inst.adb_port or (5554 + inst.index * 2),
                android_serial=(
                    f"127.0.0.1:{inst.adb_port}" if inst.adb_port else None
                ),
            )
            for inst in instances_raw
        ]
        return WorkstationRegistration(
            workstation_id=config.workstation_id,
            hostname=socket.gethostname(),
            os_version=platform.version(),
            ip_address=self._get_local_ip(),
            instances=instances,
            agent_version=AGENT_VERSION,
        )

    @staticmethod
    def _get_local_ip() -> str:
        """Определить IP воркстанции; fallback → 127.0.0.1."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"


# ---------------------------------------------------------------------------
# In-memory registry (используется диспетчером для маршрутизации)
# ---------------------------------------------------------------------------

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
