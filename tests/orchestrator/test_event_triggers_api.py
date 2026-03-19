# tests/orchestrator/test_event_triggers_api.py
# ВЛАДЕЛЕЦ: TZ-11+ Event Triggers — enterprise-уровень интеграционных тестов.
# Покрытие: CRUD, toggle, пагинация, фильтрация, org-isolation, валидация.
# Каждый тест работает через HTTP (authenticated_client) → FastAPI → SQLite in-memory.
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.event_trigger import EventTrigger
from backend.models.organization import Organization
from backend.models.pipeline import Pipeline
from backend.models.user import User


# ══════════════════════════════════════════════════════════════════════════════
#  Переопределение test_user с валидной RBAC-ролью
# ══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def test_user(db_session: AsyncSession, test_org):
    """Тестовый пользователь с ролью org_admin (имеет pipeline:read/write)."""
    user = User(
        org_id=test_org.id,
        email="test@sphere.local",
        password_hash="$2b$12$placeholder_hash",
        role="org_admin",
    )
    db_session.add(user)
    await db_session.flush()
    return user


# ══════════════════════════════════════════════════════════════════════════════
#  Фикстуры
# ══════════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def test_pipeline(db_session: AsyncSession, test_org, test_user) -> Pipeline:
    """Тестовый pipeline для привязки триггеров."""
    pipeline = Pipeline(
        org_id=test_org.id,
        name="Тестовый Pipeline для триггеров",
        description="Pipeline для тестов EventTrigger",
        steps=[
            {
                "id": "step_1",
                "name": "Задержка",
                "type": "delay",
                "params": {"delay_ms": 100},
                "on_success": None,
                "on_failure": None,
                "timeout_ms": 5000,
                "retries": 0,
            },
        ],
        input_schema={},
        global_timeout_ms=300_000,
        max_retries=0,
        tags=["test"],
        created_by_id=test_user.id,
    )
    db_session.add(pipeline)
    await db_session.flush()
    return pipeline


@pytest_asyncio.fixture
async def second_pipeline(db_session: AsyncSession, test_org, test_user) -> Pipeline:
    """Второй pipeline для тестов обновления pipeline_id."""
    pipeline = Pipeline(
        org_id=test_org.id,
        name="Второй Pipeline",
        description="Для тестов PATCH",
        steps=[
            {
                "id": "step_1",
                "name": "Задержка",
                "type": "delay",
                "params": {"delay_ms": 50},
                "on_success": None,
                "on_failure": None,
                "timeout_ms": 5000,
                "retries": 0,
            },
        ],
        input_schema={},
        global_timeout_ms=60_000,
        max_retries=0,
        tags=["test"],
        created_by_id=test_user.id,
    )
    db_session.add(pipeline)
    await db_session.flush()
    return pipeline


@pytest_asyncio.fixture
async def test_trigger(
    db_session: AsyncSession, test_org, test_pipeline,
) -> EventTrigger:
    """Готовый EventTrigger для тестов GET/PATCH/DELETE/Toggle."""
    trigger = EventTrigger(
        org_id=test_org.id,
        name="Тестовый триггер: account.banned",
        description="Реакция на бан аккаунта",
        event_type_pattern="account.banned",
        pipeline_id=test_pipeline.id,
        input_params_template={"device_id": "{device_id}"},
        cooldown_seconds=30,
        max_triggers_per_hour=50,
    )
    db_session.add(trigger)
    await db_session.flush()
    return trigger


@pytest_asyncio.fixture
async def other_org_trigger(db_session: AsyncSession, test_user) -> EventTrigger:
    """EventTrigger из ДРУГОЙ организации — для проверки org-isolation."""
    other_org = Organization(name="Other Org", slug="other-org")
    db_session.add(other_org)
    await db_session.flush()

    pipeline = Pipeline(
        org_id=other_org.id,
        name="Pipeline другой орг",
        description="не наш",
        steps=[
            {
                "id": "step_1",
                "name": "Нопер",
                "type": "delay",
                "params": {"delay_ms": 10},
                "on_success": None,
                "on_failure": None,
                "timeout_ms": 5000,
                "retries": 0,
            },
        ],
        input_schema={},
        global_timeout_ms=60_000,
        max_retries=0,
        tags=[],
        created_by_id=test_user.id,
    )
    db_session.add(pipeline)
    await db_session.flush()

    trigger = EventTrigger(
        org_id=other_org.id,
        name="Чужой триггер",
        event_type_pattern="task.failed",
        pipeline_id=pipeline.id,
        input_params_template={},
    )
    db_session.add(trigger)
    await db_session.flush()
    return trigger


# ══════════════════════════════════════════════════════════════════════════════
#  LIST — GET /event-triggers
# ══════════════════════════════════════════════════════════════════════════════


class TestListEventTriggers:
    """Тесты получения списка EventTrigger'ов с фильтрацией и пагинацией."""

    @pytest.mark.asyncio
    async def test_list_empty(self, authenticated_client):
        """Пустой список если триггеров нет."""
        resp = await authenticated_client.get("/api/v1/event-triggers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
        assert data["page"] == 1

    @pytest.mark.asyncio
    async def test_list_with_triggers(self, authenticated_client, test_trigger):
        """Один триггер возвращается в списке."""
        resp = await authenticated_client.get("/api/v1/event-triggers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Тестовый триггер: account.banned"
        assert data["items"][0]["event_type_pattern"] == "account.banned"
        assert data["items"][0]["is_active"] is True

    @pytest.mark.asyncio
    async def test_list_filter_by_active(
        self, authenticated_client, test_trigger, db_session,
    ):
        """Фильтр is_active=false не возвращает активные триггеры."""
        resp = await authenticated_client.get(
            "/api/v1/event-triggers?is_active=false",
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_filter_by_pattern(
        self, authenticated_client, test_trigger,
    ):
        """Фильтр event_type_pattern возвращает совпадения."""
        resp = await authenticated_client.get(
            "/api/v1/event-triggers?event_type_pattern=account.banned",
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Несовпадающий паттерн
        resp2 = await authenticated_client.get(
            "/api/v1/event-triggers?event_type_pattern=task.failed",
        )
        assert resp2.status_code == 200
        assert resp2.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_filter_by_pipeline_id(
        self, authenticated_client, test_trigger, test_pipeline,
    ):
        """Фильтр pipeline_id возвращает только привязанные триггеры."""
        resp = await authenticated_client.get(
            f"/api/v1/event-triggers?pipeline_id={test_pipeline.id}",
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

        # Чужой pipeline_id
        fake_id = uuid.uuid4()
        resp2 = await authenticated_client.get(
            f"/api/v1/event-triggers?pipeline_id={fake_id}",
        )
        assert resp2.status_code == 200
        assert resp2.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_list_pagination(
        self, authenticated_client, db_session, test_org, test_pipeline,
    ):
        """Пагинация: per_page=2, page=2 возвращает оставшиеся."""
        # Создаём 5 триггеров
        for i in range(5):
            t = EventTrigger(
                org_id=test_org.id,
                name=f"Триггер #{i}",
                event_type_pattern=f"event.type.{i}",
                pipeline_id=test_pipeline.id,
                input_params_template={},
            )
            db_session.add(t)
        await db_session.flush()

        resp = await authenticated_client.get(
            "/api/v1/event-triggers?per_page=2&page=1",
        )
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2
        assert data["pages"] == 3

        resp2 = await authenticated_client.get(
            "/api/v1/event-triggers?per_page=2&page=3",
        )
        data2 = resp2.json()
        assert len(data2["items"]) == 1  # Последний элемент

    @pytest.mark.asyncio
    async def test_list_org_isolation(
        self, authenticated_client, test_trigger, other_org_trigger,
    ):
        """Триггеры другой организации НЕ видны."""
        resp = await authenticated_client.get("/api/v1/event-triggers")
        data = resp.json()
        # Видим только свой триггер
        assert data["total"] == 1
        trigger_ids = [item["id"] for item in data["items"]]
        assert str(other_org_trigger.id) not in trigger_ids


# ══════════════════════════════════════════════════════════════════════════════
#  CREATE — POST /event-triggers
# ══════════════════════════════════════════════════════════════════════════════


class TestCreateEventTrigger:
    """Тесты создания EventTrigger'а."""

    @pytest.mark.asyncio
    async def test_create_success(self, authenticated_client, test_pipeline):
        """Успешное создание триггера с полным набором параметров."""
        payload = {
            "name": "Триггер на бан",
            "description": "Перезапуск при бане аккаунта",
            "event_type_pattern": "account.banned",
            "pipeline_id": str(test_pipeline.id),
            "input_params_template": {
                "device_id": "{device_id}",
                "account_id": "{account_id}",
            },
            "cooldown_seconds": 120,
            "max_triggers_per_hour": 30,
        }
        resp = await authenticated_client.post(
            "/api/v1/event-triggers", json=payload,
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["name"] == "Триггер на бан"
        assert data["event_type_pattern"] == "account.banned"
        assert data["pipeline_id"] == str(test_pipeline.id)
        assert data["cooldown_seconds"] == 120
        assert data["max_triggers_per_hour"] == 30
        assert data["is_active"] is True  # По умолчанию активен
        assert data["total_triggers"] == 0  # Ещё не срабатывал
        assert data["last_triggered_at"] is None
        # UUID валиден
        uuid.UUID(data["id"])

    @pytest.mark.asyncio
    async def test_create_minimal(self, authenticated_client, test_pipeline):
        """Создание с минимальным набором полей (defaults)."""
        payload = {
            "name": "Минимальный триггер",
            "event_type_pattern": "task.*",
            "pipeline_id": str(test_pipeline.id),
        }
        resp = await authenticated_client.post(
            "/api/v1/event-triggers", json=payload,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["cooldown_seconds"] == 60  # дефолт
        assert data["max_triggers_per_hour"] == 100  # дефолт
        assert data["input_params_template"] == {}
        assert data["description"] is None

    @pytest.mark.asyncio
    async def test_create_pipeline_not_found(self, authenticated_client):
        """404 если pipeline_id не существует."""
        payload = {
            "name": "Несуществующий pipeline",
            "event_type_pattern": "game.*",
            "pipeline_id": str(uuid.uuid4()),
        }
        resp = await authenticated_client.post(
            "/api/v1/event-triggers", json=payload,
        )
        assert resp.status_code == 404
        assert "Pipeline" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_create_validation_errors(self, authenticated_client, test_pipeline):
        """422 при невалидных данных (пустое имя, отсутствие обязательных полей)."""
        # Пустое имя
        resp = await authenticated_client.post(
            "/api/v1/event-triggers",
            json={
                "name": "",
                "event_type_pattern": "x",
                "pipeline_id": str(test_pipeline.id),
            },
        )
        assert resp.status_code == 422

        # Без pipeline_id
        resp2 = await authenticated_client.post(
            "/api/v1/event-triggers",
            json={"name": "OK", "event_type_pattern": "x"},
        )
        assert resp2.status_code == 422

        # Отрицательный cooldown
        resp3 = await authenticated_client.post(
            "/api/v1/event-triggers",
            json={
                "name": "Bad cooldown",
                "event_type_pattern": "x",
                "pipeline_id": str(test_pipeline.id),
                "cooldown_seconds": -1,
            },
        )
        assert resp3.status_code == 422

    @pytest.mark.asyncio
    async def test_create_other_org_pipeline_rejected(
        self, authenticated_client, other_org_trigger,
    ):
        """Нельзя создать триггер с pipeline'ом чужой организации."""
        # other_org_trigger.pipeline_id — pipeline из другой орг
        payload = {
            "name": "Кросс-орг триггер",
            "event_type_pattern": "cross.*",
            "pipeline_id": str(other_org_trigger.pipeline_id),
        }
        resp = await authenticated_client.post(
            "/api/v1/event-triggers", json=payload,
        )
        assert resp.status_code == 404  # «Pipeline не найден» (для этого юзера)


# ══════════════════════════════════════════════════════════════════════════════
#  GET BY ID — GET /event-triggers/{trigger_id}
# ══════════════════════════════════════════════════════════════════════════════


class TestGetEventTrigger:
    """Тесты получения EventTrigger по ID."""

    @pytest.mark.asyncio
    async def test_get_success(self, authenticated_client, test_trigger):
        """Получение триггера по ID."""
        resp = await authenticated_client.get(
            f"/api/v1/event-triggers/{test_trigger.id}",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(test_trigger.id)
        assert data["name"] == "Тестовый триггер: account.banned"

    @pytest.mark.asyncio
    async def test_get_not_found(self, authenticated_client):
        """404 при несуществующем ID."""
        fake_id = uuid.uuid4()
        resp = await authenticated_client.get(
            f"/api/v1/event-triggers/{fake_id}",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_other_org_trigger_hidden(
        self, authenticated_client, other_org_trigger,
    ):
        """Триггер другой организации возвращает 404."""
        resp = await authenticated_client.get(
            f"/api/v1/event-triggers/{other_org_trigger.id}",
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  UPDATE — PATCH /event-triggers/{trigger_id}
# ══════════════════════════════════════════════════════════════════════════════


class TestUpdateEventTrigger:
    """Тесты обновления EventTrigger'а через PATCH."""

    @pytest.mark.asyncio
    async def test_update_name(self, authenticated_client, test_trigger):
        """Обновление имени триггера."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{test_trigger.id}",
            json={"name": "Обновлённое имя"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Обновлённое имя"

    @pytest.mark.asyncio
    async def test_update_pattern(self, authenticated_client, test_trigger):
        """Обновление паттерна события."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{test_trigger.id}",
            json={"event_type_pattern": "account.*"},
        )
        assert resp.status_code == 200
        assert resp.json()["event_type_pattern"] == "account.*"

    @pytest.mark.asyncio
    async def test_update_cooldown_and_rate_limit(
        self, authenticated_client, test_trigger,
    ):
        """Обновление cooldown и max_triggers_per_hour."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{test_trigger.id}",
            json={"cooldown_seconds": 300, "max_triggers_per_hour": 10},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cooldown_seconds"] == 300
        assert data["max_triggers_per_hour"] == 10

    @pytest.mark.asyncio
    async def test_update_pipeline_id(
        self, authenticated_client, test_trigger, second_pipeline,
    ):
        """Обновление pipeline_id на другой pipeline своей организации."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{test_trigger.id}",
            json={"pipeline_id": str(second_pipeline.id)},
        )
        assert resp.status_code == 200
        assert resp.json()["pipeline_id"] == str(second_pipeline.id)

    @pytest.mark.asyncio
    async def test_update_pipeline_id_cross_org_rejected(
        self, authenticated_client, test_trigger, other_org_trigger,
    ):
        """Нельзя сменить pipeline_id на pipeline другой организации."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{test_trigger.id}",
            json={"pipeline_id": str(other_org_trigger.pipeline_id)},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_not_found(self, authenticated_client):
        """404 при обновлении несуществующего триггера."""
        fake_id = uuid.uuid4()
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{fake_id}",
            json={"name": "X"},
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_other_org_rejected(
        self, authenticated_client, other_org_trigger,
    ):
        """PATCH на триггер другой организации → 404."""
        resp = await authenticated_client.patch(
            f"/api/v1/event-triggers/{other_org_trigger.id}",
            json={"name": "Хак"},
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  DELETE — DELETE /event-triggers/{trigger_id}
# ══════════════════════════════════════════════════════════════════════════════


class TestDeleteEventTrigger:
    """Тесты удаления EventTrigger'а."""

    @pytest.mark.asyncio
    async def test_delete_success(self, authenticated_client, test_trigger):
        """Удаление триггера → 204, повторный GET → 404."""
        resp = await authenticated_client.delete(
            f"/api/v1/event-triggers/{test_trigger.id}",
        )
        assert resp.status_code == 204

        resp2 = await authenticated_client.get(
            f"/api/v1/event-triggers/{test_trigger.id}",
        )
        assert resp2.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(self, authenticated_client):
        """404 при удалении несуществующего триггера."""
        fake_id = uuid.uuid4()
        resp = await authenticated_client.delete(
            f"/api/v1/event-triggers/{fake_id}",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_other_org_rejected(
        self, authenticated_client, other_org_trigger,
    ):
        """Удаление триггера другой организации → 404."""
        resp = await authenticated_client.delete(
            f"/api/v1/event-triggers/{other_org_trigger.id}",
        )
        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  TOGGLE — POST /event-triggers/{trigger_id}/toggle
# ══════════════════════════════════════════════════════════════════════════════


class TestToggleEventTrigger:
    """Тесты включения/выключения EventTrigger'а."""

    @pytest.mark.asyncio
    async def test_toggle_deactivate(self, authenticated_client, test_trigger):
        """Выключение активного триггера."""
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{test_trigger.id}/toggle?active=false",
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    @pytest.mark.asyncio
    async def test_toggle_activate(self, authenticated_client, test_trigger):
        """Включение после выключения."""
        # Сначала выключаем
        await authenticated_client.post(
            f"/api/v1/event-triggers/{test_trigger.id}/toggle?active=false",
        )
        # Включаем обратно
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{test_trigger.id}/toggle?active=true",
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_idempotent(self, authenticated_client, test_trigger):
        """Повторный toggle(active=true) на уже активном — идемпотентен."""
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{test_trigger.id}/toggle?active=true",
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

    @pytest.mark.asyncio
    async def test_toggle_not_found(self, authenticated_client):
        """404 при toggle несуществующего триггера."""
        fake_id = uuid.uuid4()
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{fake_id}/toggle?active=true",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_other_org_rejected(
        self, authenticated_client, other_org_trigger,
    ):
        """Toggle триггера другой организации → 404."""
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{other_org_trigger.id}/toggle?active=false",
        )
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_toggle_missing_active_param(
        self, authenticated_client, test_trigger,
    ):
        """422 если не передан обязательный параметр active."""
        resp = await authenticated_client.post(
            f"/api/v1/event-triggers/{test_trigger.id}/toggle",
        )
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  Pipeline Toggle API — POST /pipelines/{pipeline_id}/toggle
#  ПРИМЕЧАНИЕ: Интеграционные тесты pipeline toggle через HTTP ограничены
#  из-за MissingGreenlet (async SQLAlchemy + lazy-loaded relationships в SQLite).
#  Unit-тесты toggle на сервисном уровне — в test_pipeline_toggle.py.
# ══════════════════════════════════════════════════════════════════════════════


class TestPipelineToggleAPI:
    """Интеграционные тесты для API эндпоинта toggle pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_toggle_not_found(self, authenticated_client):
        """404 при toggle несуществующего pipeline."""
        fake_id = uuid.uuid4()
        resp = await authenticated_client.post(
            f"/api/v1/pipelines/{fake_id}/toggle?active=true",
        )
        assert resp.status_code == 404
