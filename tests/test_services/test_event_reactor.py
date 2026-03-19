# tests/test_services/test_event_reactor.py
# Тесты для EventReactor: process_event, _check_event_triggers, _render_trigger_params.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.models.game_account import AccountStatus
from backend.services.event_reactor import (
    ACCOUNT_STATUS_REACTIONS,
    SESSION_END_REASONS,
    EventReactor,
)


def _make_db():
    """Фиктивная AsyncSession."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.execute = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


def _make_event(
    event_type: str = "test.event",
    account_id: uuid.UUID | None = None,
    device_id: uuid.UUID | None = None,
) -> MagicMock:
    """Создать мок DeviceEvent."""
    event = MagicMock()
    event.id = uuid.uuid4()
    event.event_type = event_type
    event.account_id = account_id
    event.device_id = device_id or uuid.uuid4()
    event.data = {}
    event.processed = False
    return event


class TestAccountStatusReactions:
    """Проверяем что маппинг event_type → AccountStatus корректен."""

    def test_banned_maps_to_banned(self):
        assert ACCOUNT_STATUS_REACTIONS["account.banned"] == AccountStatus.banned

    def test_captcha_maps_to_captcha(self):
        assert ACCOUNT_STATUS_REACTIONS["account.captcha"] == AccountStatus.captcha

    def test_phone_verify_maps_to_phone_verify(self):
        assert ACCOUNT_STATUS_REACTIONS["account.phone_verify"] == AccountStatus.phone_verify

    def test_error_maps_to_disabled(self):
        assert ACCOUNT_STATUS_REACTIONS["account.error"] == AccountStatus.disabled

    def test_unknown_event_not_in_reactions(self):
        assert "game.started" not in ACCOUNT_STATUS_REACTIONS


class TestSessionEndReasons:
    """Проверяем маппинг event_type → причина завершения сессии."""

    def test_banned(self):
        assert SESSION_END_REASONS["account.banned"] == "banned"

    def test_device_offline(self):
        assert SESSION_END_REASONS["device.offline"] == "device_offline"

    def test_game_crashed(self):
        assert SESSION_END_REASONS["game.crashed"] == "error"


class TestRenderTriggerParams:
    """Тесты подстановки плейсхолдеров в шаблон input_params_template."""

    def test_simple_replacement(self):
        template = {"device": "{device_id}", "type": "{event_type}"}
        device_id = uuid.uuid4()
        event = _make_event(event_type="account.banned")

        result = EventReactor._render_trigger_params(template, device_id, event)

        assert result["device"] == str(device_id)
        assert result["type"] == "account.banned"

    def test_nested_dict(self):
        template = {"outer": {"inner": "{account_id}"}}
        device_id = uuid.uuid4()
        account_id = uuid.uuid4()
        event = _make_event(account_id=account_id)

        result = EventReactor._render_trigger_params(template, device_id, event)

        assert result["outer"]["inner"] == str(account_id)

    def test_list_values(self):
        template = {"ids": ["{device_id}", "{event_id}"]}
        device_id = uuid.uuid4()
        event = _make_event()

        result = EventReactor._render_trigger_params(template, device_id, event)

        assert result["ids"][0] == str(device_id)
        assert result["ids"][1] == str(event.id)

    def test_empty_account_id(self):
        template = {"acc": "{account_id}"}
        device_id = uuid.uuid4()
        event = _make_event(account_id=None)

        result = EventReactor._render_trigger_params(template, device_id, event)

        assert result["acc"] == ""

    def test_non_string_values_preserved(self):
        template = {"count": 42, "flag": True, "data": None}
        device_id = uuid.uuid4()
        event = _make_event()

        result = EventReactor._render_trigger_params(template, device_id, event)

        assert result["count"] == 42
        assert result["flag"] is True
        assert result["data"] is None


class TestPendingRegistrationStatus:
    """Проверяем что pending_registration добавлен в AccountStatus."""

    def test_pending_registration_exists(self):
        assert hasattr(AccountStatus, "pending_registration")
        assert AccountStatus.pending_registration.value == "pending_registration"

    def test_all_statuses_count(self):
        # 8 оригинальных + 1 pending_registration = 9
        assert len(AccountStatus) == 9


class TestEventReactorProcessEvent:
    """Smoke-тест для process_event (проверяем что вызывается без ошибок)."""

    @pytest.mark.asyncio
    async def test_process_event_saves_event(self):
        """process_event должен создать DeviceEvent и вызвать flush."""
        db = _make_db()

        # Мок: _check_event_triggers ничего не делает
        reactor = EventReactor(db)
        reactor._check_event_triggers = AsyncMock()

        org_id = uuid.uuid4()
        device_id = uuid.uuid4()

        with patch("backend.services.event_reactor.DeviceEvent") as MockEvent:
            mock_event_instance = MagicMock()
            mock_event_instance.data = {}
            mock_event_instance.processed = False
            mock_event_instance.id = uuid.uuid4()
            MockEvent.return_value = mock_event_instance

            await reactor.process_event(
                org_id=org_id,
                device_id=device_id,
                event_type="test.info",
                severity="info",
                message="Тестовое событие",
            )

            # Проверяем что event добавлен в сессию
            db.add.assert_called_once_with(mock_event_instance)
            # Проверяем что flush вызван минимум 2 раза (add + processed)
            assert db.flush.call_count >= 2
            # Проверяем что _check_event_triggers вызван
            reactor._check_event_triggers.assert_called_once()
