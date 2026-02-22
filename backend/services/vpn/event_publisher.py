# backend/services/vpn/event_publisher.py  TZ-06 stub
# TZ-03 (WebSocket Layer) provides the real implementation at merge time.
from __future__ import annotations

import structlog

logger = structlog.get_logger()


class EventPublisher:
    """
    Sends commands to devices via WebSocket pub/sub.
    Stub until TZ-03 merge; always returns False (device appears offline).
    """

    async def send_command_to_device(
        self, device_id: str, command: dict
    ) -> bool:
        """
        Publish a command JSON to a specific device over WebSocket.
        Returns True if device was online and received the command.
        """
        logger.debug(
            "send_command_to_device (stub)",
            device_id=device_id,
            command_type=command.get("type"),
        )
        return False
