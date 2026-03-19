# backend/websocket/event_publisher.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-5. EventPublisher — фасад для публикации fleet событий.
# Используется по всему бэкенду для отправки реал-тайм уведомлений.
from __future__ import annotations

import structlog

from backend.schemas.events import EventType, FleetEvent

logger = structlog.get_logger()


class EventPublisher:
    """
    Фасад для публикации событий fleet.
    Публикует одновременно в Redis PubSub (для других воркеров) и локально (EventsManager).
    """

    def __init__(self, pubsub_publisher, events_manager) -> None:
        self.pubsub = pubsub_publisher
        self.events_manager = events_manager

    async def emit(self, event: FleetEvent) -> None:
        # Опубликовать в Redis → EventsManager на каждом воркере получит через PubSub
        pubsub_ok = False
        try:
            if self.pubsub:
                await self.pubsub.broadcast_org_event(
                    event.org_id, event.model_dump(mode="json")
                )
                pubsub_ok = True
        except Exception as e:
            logger.warning("PubSub emit failed", error=str(e))

        # Доставить локально ТОЛЬКО если PubSub не работает (fallback).
        # Когда PubSub работает, EventsManager получит событие через _listen_loop.
        if not pubsub_ok:
            try:
                await self.events_manager.publish_event(event)
            except Exception as e:
                logger.warning("Local event publish failed", error=str(e))

    async def device_online(self, device_id: str, org_id: str) -> None:
        await self.emit(FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            device_id=device_id,
            org_id=org_id,
            payload={"status": "online"},
        ))

    async def device_offline(self, device_id: str, org_id: str) -> None:
        await self.emit(FleetEvent(
            event_type=EventType.DEVICE_OFFLINE,
            device_id=device_id,
            org_id=org_id,
            payload={"status": "offline"},
        ))

    async def command_completed(
        self,
        device_id: str,
        org_id: str,
        command_id: str,
        result: dict,
    ) -> None:
        await self.emit(FleetEvent(
            event_type=EventType.COMMAND_COMPLETED,
            device_id=device_id,
            org_id=org_id,
            payload={"command_id": command_id, "result": result},
        ))

    async def command_failed(
        self,
        device_id: str,
        org_id: str,
        command_id: str,
        error: str,
    ) -> None:
        await self.emit(FleetEvent(
            event_type=EventType.COMMAND_FAILED,
            device_id=device_id,
            org_id=org_id,
            payload={"command_id": command_id, "error": error},
        ))

    async def task_progress(
        self,
        device_id: str,
        org_id: str,
        task_id: str,
        progress: int,
    ) -> None:
        await self.emit(FleetEvent(
            event_type=EventType.TASK_PROGRESS,
            device_id=device_id,
            org_id=org_id,
            payload={"task_id": task_id, "progress": progress},
        ))

    # ── TZ-11: События аккаунтов ─────────────────────────────────────────

    async def account_banned(
        self,
        device_id: str,
        org_id: str,
        account_id: str,
        reason: str | None = None,
    ) -> None:
        """Аккаунт забанен в игре."""
        await self.emit(FleetEvent(
            event_type=EventType.ACCOUNT_BANNED,
            device_id=device_id,
            org_id=org_id,
            payload={"account_id": account_id, "reason": reason},
        ))

    async def account_captcha(
        self,
        device_id: str,
        org_id: str,
        account_id: str,
    ) -> None:
        """Аккаунт требует решения капчи."""
        await self.emit(FleetEvent(
            event_type=EventType.ACCOUNT_CAPTCHA,
            device_id=device_id,
            org_id=org_id,
            payload={"account_id": account_id},
        ))

    async def account_assigned(
        self,
        device_id: str,
        org_id: str,
        account_id: str,
        session_id: str | None = None,
    ) -> None:
        """Аккаунт назначен на устройство."""
        await self.emit(FleetEvent(
            event_type=EventType.ACCOUNT_ASSIGNED,
            device_id=device_id,
            org_id=org_id,
            payload={"account_id": account_id, "session_id": session_id},
        ))

    async def account_released(
        self,
        device_id: str,
        org_id: str,
        account_id: str,
        reason: str | None = None,
    ) -> None:
        """Аккаунт освобождён от устройства."""
        await self.emit(FleetEvent(
            event_type=EventType.ACCOUNT_RELEASED,
            device_id=device_id,
            org_id=org_id,
            payload={"account_id": account_id, "reason": reason},
        ))

    async def game_crashed(
        self,
        device_id: str,
        org_id: str,
        account_id: str | None = None,
        error: str | None = None,
    ) -> None:
        """Игра крашнулась на устройстве."""
        await self.emit(FleetEvent(
            event_type=EventType.GAME_CRASHED,
            device_id=device_id,
            org_id=org_id,
            payload={"account_id": account_id, "error": error},
        ))


# Синглтон
_event_publisher: EventPublisher | None = None


def get_event_publisher() -> EventPublisher | None:
    return _event_publisher


def init_event_publisher(pubsub_publisher, events_manager) -> EventPublisher:
    global _event_publisher
    _event_publisher = EventPublisher(pubsub_publisher, events_manager)
    return _event_publisher
