# tests/test_ws/test_events.py
# TZ-03 SPLIT-5: Tests for EventsManager, FleetEvent schema, EventPublisher.
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.api.ws.events.router import EventsManager, FrontendConnection
from backend.schemas.events import EventType, FleetEvent
from backend.websocket.event_publisher import EventPublisher


class TestFleetEvent:
    """Unit tests for FleetEvent schema."""

    def test_event_serialization(self):
        event = FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            device_id="dev-1",
            org_id="org-1",
            payload={"status": "online"},
        )
        data = event.model_dump(mode="json")
        assert data["event_type"] == "device.online"
        assert data["device_id"] == "dev-1"
        assert data["org_id"] == "org-1"
        assert "ts" in data

    def test_event_ts_is_utc_aware(self):
        from datetime import timezone
        event = FleetEvent(
            event_type=EventType.DEVICE_OFFLINE,
            org_id="org-1",
        )
        assert event.ts.tzinfo is not None
        assert event.ts.tzinfo == timezone.utc

    def test_all_event_types_defined(self):
        expected = {
            "device.online", "device.offline", "device.status_change",
            "command.started", "command.completed", "command.failed",
            "task.progress", "vpn.assigned", "vpn.failed",
            "alert.triggered", "stream.started", "stream.stopped",
        }
        actual = {e.value for e in EventType}
        assert actual == expected


class TestEventsManager:
    """Unit tests for EventsManager."""

    @pytest.fixture
    def manager(self):
        return EventsManager()

    def _make_conn(self, org_id: str, filters: set | None = None) -> FrontendConnection:
        ws = AsyncMock()
        ws.send_json = AsyncMock()
        return FrontendConnection(ws, org_id, filters or set())

    async def test_add_and_remove_client(self, manager):
        conn = self._make_conn("org-1")
        await manager.add_client("org-1", conn)
        assert manager.client_count("org-1") == 1

        await manager.remove_client("org-1", conn)
        assert manager.client_count("org-1") == 0

    async def test_publish_event_sends_to_org_clients(self, manager):
        conn1 = self._make_conn("org-1")
        conn2 = self._make_conn("org-1")
        await manager.add_client("org-1", conn1)
        await manager.add_client("org-1", conn2)

        event = FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            device_id="dev-1",
            org_id="org-1",
        )
        await manager.publish_event(event)

        conn1.ws.send_json.assert_called_once()
        conn2.ws.send_json.assert_called_once()

    async def test_publish_event_cross_org_isolation(self, manager):
        """Событие должно получить только клиент своей org."""
        conn_org1 = self._make_conn("org-1")
        conn_org2 = self._make_conn("org-2")
        await manager.add_client("org-1", conn_org1)
        await manager.add_client("org-2", conn_org2)

        event = FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            org_id="org-1",
        )
        await manager.publish_event(event)

        conn_org1.ws.send_json.assert_called_once()
        conn_org2.ws.send_json.assert_not_called()

    async def test_publish_event_respects_filters(self, manager):
        """Клиент с фильтром ['device.online'] не получает command.completed."""
        conn = self._make_conn("org-1", filters={"device.online"})
        await manager.add_client("org-1", conn)

        # Событие вне фильтра
        event_cmd = FleetEvent(
            event_type=EventType.COMMAND_COMPLETED,
            org_id="org-1",
        )
        await manager.publish_event(event_cmd)
        conn.ws.send_json.assert_not_called()

        # Событие в фильтре
        event_online = FleetEvent(
            event_type=EventType.DEVICE_ONLINE,
            org_id="org-1",
        )
        await manager.publish_event(event_online)
        conn.ws.send_json.assert_called_once()

    async def test_publish_event_empty_filter_receives_all(self, manager):
        """Пустой фильтр {} = получать все события."""
        conn = self._make_conn("org-1", filters=set())
        await manager.add_client("org-1", conn)

        for event_type in [EventType.DEVICE_ONLINE, EventType.COMMAND_COMPLETED, EventType.TASK_PROGRESS]:
            await manager.publish_event(FleetEvent(event_type=event_type, org_id="org-1"))

        assert conn.ws.send_json.call_count == 3

    async def test_dead_socket_removed_automatically(self, manager):
        """Сломанный WebSocket автоматически удаляется из списка."""
        conn = self._make_conn("org-1")
        conn.ws.send_json.side_effect = Exception("broken pipe")

        await manager.add_client("org-1", conn)
        assert manager.client_count("org-1") == 1

        # Публикация обнаружит мёртвый сокет и удалит его
        event = FleetEvent(event_type=EventType.DEVICE_ONLINE, org_id="org-1")
        await manager.publish_event(event)
        assert manager.client_count("org-1") == 0

    async def test_client_count_for_empty_org(self, manager):
        assert manager.client_count("nonexistent-org") == 0


class TestEventPublisher:
    """Unit tests for EventPublisher facade."""

    @pytest.fixture
    def pubsub_mock(self):
        ps = AsyncMock()
        ps.broadcast_org_event = AsyncMock(return_value=1)
        return ps

    @pytest.fixture
    def events_manager_mock(self):
        em = AsyncMock()
        em.publish_event = AsyncMock()
        return em

    @pytest.fixture
    def publisher(self, pubsub_mock, events_manager_mock):
        return EventPublisher(pubsub_mock, events_manager_mock)

    async def test_emit_publishes_to_pubsub_only_when_available(
        self, publisher, pubsub_mock, events_manager_mock
    ):
        """When PubSub is available, events go only via PubSub (EventsManager gets it via PubSub listener)."""
        event = FleetEvent(event_type=EventType.DEVICE_ONLINE, org_id="org-1")
        await publisher.emit(event)

        pubsub_mock.broadcast_org_event.assert_called_once()
        events_manager_mock.publish_event.assert_not_called()

    async def test_device_online_helper(self, publisher, pubsub_mock, events_manager_mock):
        await publisher.device_online("dev-1", "org-1")
        pubsub_mock.broadcast_org_event.assert_called_once()
        call_args = pubsub_mock.broadcast_org_event.call_args
        assert call_args.args[0] == "org-1"  # org_id
        event_data = call_args.args[1]
        assert event_data["event_type"] == EventType.DEVICE_ONLINE
        assert event_data["device_id"] == "dev-1"

    async def test_device_offline_helper(self, publisher, pubsub_mock, events_manager_mock):
        await publisher.device_offline("dev-2", "org-1")
        call_args = pubsub_mock.broadcast_org_event.call_args
        event_data = call_args.args[1]
        assert event_data["event_type"] == EventType.DEVICE_OFFLINE

    async def test_command_completed_helper(self, publisher, pubsub_mock, events_manager_mock):
        await publisher.command_completed("dev-1", "org-1", "cmd-123", {"result": "ok"})
        call_args = pubsub_mock.broadcast_org_event.call_args
        event_data = call_args.args[1]
        assert event_data["event_type"] == EventType.COMMAND_COMPLETED
        assert event_data["payload"]["command_id"] == "cmd-123"

    async def test_emit_continues_on_pubsub_failure(
        self, publisher, pubsub_mock, events_manager_mock
    ):
        """Если PubSub упал — локальная доставка всё равно происходит."""
        pubsub_mock.broadcast_org_event.side_effect = Exception("Redis down")

        event = FleetEvent(event_type=EventType.DEVICE_ONLINE, org_id="org-1")
        await publisher.emit(event)  # Не должно бросить исключение

        events_manager_mock.publish_event.assert_called_once()

    async def test_task_progress_helper(self, publisher, pubsub_mock, events_manager_mock):
        await publisher.task_progress("dev-1", "org-1", "task-xyz", 75)
        call_args = pubsub_mock.broadcast_org_event.call_args
        event_data = call_args.args[1]
        assert event_data["event_type"] == EventType.TASK_PROGRESS
        assert event_data["payload"]["progress"] == 75
