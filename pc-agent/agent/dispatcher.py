"""
CommandDispatcher — маршрутизатор входящих команд от бэкенда.
SPHERE-042/044  TZ-08 SPLIT-2 + SPLIT-4
"""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from .adb_bridge import AdbBridgeManager
    from .client import AgentWebSocketClient
    from .ldplayer import LDPlayerManager


class CommandDispatcher:
    def __init__(
        self,
        ldplayer_mgr: "LDPlayerManager",
        adb_bridge: "AdbBridgeManager",
        ws_client: "AgentWebSocketClient | None" = None,
    ) -> None:
        self._ldplayer = ldplayer_mgr
        self._adb = adb_bridge
        self.ws_client = ws_client  # устанавливается после создания WS клиента

    async def dispatch(self, msg: dict) -> None:
        """Роутинг входящего сообщения по полю `type`."""
        cmd_type = msg.get("type")
        payload = msg.get("payload", {})
        command_id = msg.get("command_id", "")

        if not cmd_type:
            logger.warning(f"Сообщение без type: {msg}")
            return

        try:
            result = await self._handle(cmd_type, payload)
            if command_id and self.ws_client:
                await self.ws_client.send({
                    "command_id": command_id,
                    "status": "completed",
                    "result": result,
                })
        except Exception as exc:
            logger.error(f"Команда {cmd_type!r} упала: {exc!r}")
            if command_id and self.ws_client:
                await self.ws_client.send({
                    "command_id": command_id,
                    "status": "failed",
                    "error": str(exc),
                })

    async def _handle(self, cmd_type: str, payload: dict) -> object:
        match cmd_type:
            # ---- LDPlayer ------------------------------------------------
            case "ld_list":
                instances = await self._ldplayer.list_instances()
                return [inst.model_dump() for inst in instances]

            case "ld_launch":
                await self._ldplayer.launch(int(payload["index"]))
                return {"launched": True}

            case "ld_quit":
                await self._ldplayer.quit(int(payload["index"]))
                return {"stopped": True}

            case "ld_reboot":
                await self._ldplayer.reboot(int(payload["index"]))
                return {"rebooted": True}

            case "ld_create":
                idx = await self._ldplayer.create(str(payload["name"]))
                return {"index": idx}

            case "ld_install_apk":
                await self._ldplayer.install_apk(
                    int(payload["index"]), str(payload["apk_path"])
                )
                return {"installed": True}

            case "ld_run_app":
                await self._ldplayer.run_app(
                    int(payload["index"]), str(payload["package_name"])
                )
                return {"started": True}

            case "ld_exec":
                output = await self._ldplayer.exec_command(
                    int(payload["index"]), str(payload["command"])
                )
                return {"output": output}

            # ---- ADB -------------------------------------------------------
            case "adb_devices":
                devices = await self._adb.list_devices()
                return {"devices": devices}

            case "adb_shell":
                output = await self._adb.shell(
                    int(payload["port"]), str(payload["command"])
                )
                return {"output": output}

            case "adb_install":
                result = await self._adb.install(
                    int(payload["port"]), str(payload["apk_path"])
                )
                return {"result": result}

            case "adb_push":
                result = await self._adb.push(
                    int(payload["port"]),
                    str(payload["local"]),
                    str(payload["remote"]),
                )
                return {"result": result}

            case "adb_pull":
                result = await self._adb.pull(
                    int(payload["port"]),
                    str(payload["remote"]),
                    str(payload["local"]),
                )
                return {"result": result}

            case "adb_sync":
                await self._adb.sync_connections()
                return {"connected": list(self._adb._connected_ports)}

            # ---- System ----------------------------------------------------
            case "ping":
                return {"pong": True}

            case _:
                logger.warning(f"Неизвестный тип команды: {cmd_type!r}")
                return None
