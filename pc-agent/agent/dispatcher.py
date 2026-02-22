"""
CommandDispatcher — маршрутизатор входящих команд от бэкенда.
Детальная реализация — TZ-08 SPLIT-2.
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from .ldplayer import LDPlayerManager
    from .adb_bridge import AdbBridgeManager


class CommandDispatcher:
    def __init__(
        self,
        ldplayer_mgr: "LDPlayerManager",
        adb_bridge: "AdbBridgeManager",
    ) -> None:
        self._ldplayer = ldplayer_mgr
        self._adb = adb_bridge

        self._handlers = {
            "ldplayer.start": self._handle_ldplayer_start,
            "ldplayer.stop": self._handle_ldplayer_stop,
            "ldplayer.list": self._handle_ldplayer_list,
            "adb.forward": self._handle_adb_forward,
            "ping": self._handle_ping,
        }

    async def dispatch(self, msg: dict) -> None:
        """Роутинг входящего сообщения по полю `type`."""
        msg_type = msg.get("type")
        if not msg_type:
            logger.warning(f"Сообщение без type: {msg}")
            return

        handler = self._handlers.get(msg_type)
        if handler is None:
            logger.warning(f"Неизвестный тип команды: {msg_type!r}")
            return

        try:
            await handler(msg)
        except Exception as exc:
            logger.error(f"Ошибка обработки команды {msg_type!r}: {exc!r}")

    # ------------------------------------------------------------------
    # Handlers (stubs — full impl in SPLIT-2 / SPLIT-4)
    # ------------------------------------------------------------------

    async def _handle_ldplayer_start(self, msg: dict) -> None:
        instance_id = msg.get("instance_id")
        logger.info(f"CMD ldplayer.start instance={instance_id}")
        # TODO: TZ-08 SPLIT-2
        await asyncio.sleep(0)

    async def _handle_ldplayer_stop(self, msg: dict) -> None:
        instance_id = msg.get("instance_id")
        logger.info(f"CMD ldplayer.stop instance={instance_id}")
        # TODO: TZ-08 SPLIT-2
        await asyncio.sleep(0)

    async def _handle_ldplayer_list(self, msg: dict) -> None:
        logger.info("CMD ldplayer.list")
        # TODO: TZ-08 SPLIT-2
        await asyncio.sleep(0)

    async def _handle_adb_forward(self, msg: dict) -> None:
        device_serial = msg.get("device_serial")
        local_port = msg.get("local_port")
        remote_port = msg.get("remote_port")
        logger.info(
            f"CMD adb.forward serial={device_serial} "
            f"local={local_port} remote={remote_port}"
        )
        # TODO: TZ-08 SPLIT-4
        await asyncio.sleep(0)

    async def _handle_ping(self, msg: dict) -> None:
        logger.debug("CMD ping — pong")
        # ответ отправляется через ws_client; здесь только логируем
        await asyncio.sleep(0)
