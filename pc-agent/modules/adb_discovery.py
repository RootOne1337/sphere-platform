# pc-agent/modules/adb_discovery.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-5. ADB device discovery via TCP scan + adb connect.
# Реализован в PC Agent (Python) и вызывается бэкендом через WebSocket RPC (TZ-08).
from __future__ import annotations

import asyncio
import ipaddress
import logging

logger = logging.getLogger(__name__)


class ADBDiscovery:
    """
    Сканирует подсеть на наличие ADB-устройств и возвращает список найденных.

    Алгоритм:
    1. TCP connect к каждому host:port с timeout.
    2. При успехе — adb connect для получения device info.
    3. Параллельно с asyncio.Semaphore(256) для контроля нагрузки.

    /24 (256 хостов × 2 порта) выполняется за ≤ 15 секунд при timeout=500ms.
    """

    DEFAULT_SEMAPHORE = 256

    async def scan_subnet(
        self,
        subnet: str,
        port_range: list[int],
        timeout_ms: int,
    ) -> list[dict]:
        """
        Scan subnet for ADB devices.

        Args:
            subnet: CIDR notation, e.g. '192.168.1.0/24'
            port_range: [low, high] inclusive, e.g. [5554, 5584]
            timeout_ms: TCP connect timeout in milliseconds

        Returns:
            List of dicts with keys: ip, port, model, android_version
        """
        network = ipaddress.ip_network(subnet, strict=False)
        hosts = list(network.hosts())
        low_port, high_port = port_range[0], port_range[1]
        ports = list(range(low_port, high_port + 1))

        timeout_s = timeout_ms / 1000
        semaphore = asyncio.Semaphore(self.DEFAULT_SEMAPHORE)

        tasks = [
            self._try_connect(str(host), port, timeout_s, semaphore)
            for host in hosts
            for port in ports
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)
        found = [r for r in results if isinstance(r, dict)]
        logger.info(
            "ADB scan %s ports %s-%s: %d found of %d probed",
            subnet,
            low_port,
            high_port,
            len(found),
            len(tasks),
        )
        return found

    async def _try_connect(
        self,
        ip: str,
        port: int,
        timeout_s: float,
        sem: asyncio.Semaphore,
    ) -> dict | None:
        async with sem:
            try:
                # TCP reachability check
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout_s,
                )
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

                # ADB connect to verify ADB protocol
                proc = await asyncio.create_subprocess_exec(
                    "adb",
                    "connect",
                    f"{ip}:{port}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)

                if b"connected" in stdout or b"already connected" in stdout:
                    info = await self._get_device_info(ip, port)
                    return {"ip": ip, "port": port, **info}

            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                pass
            except Exception as exc:
                logger.debug("Unexpected error probing %s:%s: %s", ip, port, exc)

        return None

    async def _get_device_info(self, ip: str, port: int) -> dict:
        """Retrieve model and android_version via adb shell getprop."""
        target = f"{ip}:{port}"

        async def get_prop(name: str) -> str | None:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "adb",
                    "-s",
                    target,
                    "shell",
                    "getprop",
                    name,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
                return out.decode(errors="replace").strip() or None
            except Exception:
                return None

        return {
            "model": await get_prop("ro.product.model"),
            "android_version": await get_prop("ro.build.version.release"),
        }
