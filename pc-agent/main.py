# pc-agent/main.py
# PC Agent — stub для TZ-08 PC Agent
# Детальная реализация: TZ-08 SPLIT-1 (Architecture)
#
# Ответственности:
#   - Управление LDPlayer инстансами на Windows-воркстанции
#   - WebSocket-соединение с backend (TZ-08 SPLIT-2)
#   - ADB-мост для команд с устройств (TZ-08 SPLIT-4)
#   - Телеметрия воркстанции (TZ-08 SPLIT-3)
#   - Topology reporting (TZ-08 SPLIT-5)
from __future__ import annotations

import asyncio
import logging
import sys

logger = logging.getLogger("sphere.pc-agent")


async def main() -> None:
    logger.info("Sphere PC Agent starting up (stub — TZ-08 implementation pending)")
    # TZ-08 SPLIT-1: инициализация агента
    # TZ-08 SPLIT-2: WebSocket connect to backend/api/ws/agent/
    # TZ-08 SPLIT-3: Telemetry collection loop
    # TZ-08 SPLIT-4: ADB bridge initialization
    # TZ-08 SPLIT-5: Topology discovery and reporting
    await asyncio.sleep(0)
    logger.info("PC Agent stub completed")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    asyncio.run(main())
