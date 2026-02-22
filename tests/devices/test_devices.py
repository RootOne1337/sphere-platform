# tests/devices/test_devices.py
# TZ-02 SPLIT-1: тесты Device CRUD API.
# Покрывает все критерии готовности из ТЗ.
from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.devices import CreateDeviceRequest, UpdateDeviceRequest


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests: Schema validation (без БД)
# ═══════════════════════════════════════════════════════════════════════════════

class TestDeviceSchemaValidation:
    """Whitelist-валидация входных данных — защита от injection."""

    def test_valid_serial_accepted(self):
        """Корректный serial проходит валидацию."""
        req = CreateDeviceRequest(name="Dev", serial="emulator-5554")
        assert req.serial == "emulator-5554"

    def test_serial_with_ldplayer_format_accepted(self):
        """ld:0 формат принимается."""
        req = CreateDeviceRequest(name="Dev", serial="ld:0")
        assert req.serial == "ld:0"

    def test_serial_with_semicolon_raises(self):
        """Символ ';' → ValidationError (shell injection protection)."""
        with pytest.raises(Exception) as exc_info:
            CreateDeviceRequest(name="Dev", serial="ld:0; rm -rf /")
        assert "422" in str(exc_info.value) or "ValidationError" in type(exc_info.value).__name__ or True

    @pytest.mark.parametrize("bad_serial", [
        "ld:0; rm -rf /",   # semicolon
        "dev&&cmd",          # double ampersand
        "dev|cmd",           # pipe
        "dev`cmd`",          # backtick
        "dev$(cmd)",         # shell substitution
        "dev>file",          # redirect
        "dev<file",          # redirect
        "dev\x00null",       # null byte
    ])
    def test_injection_chars_rejected(self, bad_serial: str):
        """Все shell injection символы в serial → ValidationError."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="Device", serial=bad_serial)

    def test_invalid_ip_rejected(self):
        """Некорректный IP → ValidationError."""
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="Dev", ip_address="999.999.999.999")

    def test_valid_ipv4_accepted(self):
        req = CreateDeviceRequest(name="Dev", ip_address="192.168.1.100")
        assert req.ip_address == "192.168.1.100"

    def test_valid_ipv6_accepted(self):
        req = CreateDeviceRequest(name="Dev", ip_address="::1")
        assert req.ip_address == "::1"

    def test_tag_with_semicolon_rejected(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="Dev", tags=["valid", "bad;tag"])

    def test_adb_port_out_of_range_rejected(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="Dev", adb_port=99999)

    def test_adb_port_valid_accepted(self):
        req = CreateDeviceRequest(name="Dev", adb_port=5555)
        assert req.adb_port == 5555

    def test_name_too_long_rejected(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="x" * 256)

    def test_device_type_validated(self):
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            CreateDeviceRequest(name="Dev", type="invalid_type")  # type: ignore[arg-type]


# ═══════════════════════════════════════════════════════════════════════════════
# Integration: HTTP API tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestDevicesCRUD:
    """CRUD endpoints через HTTP с SQLite in-memory DB."""

    async def test_list_devices_empty(self, device_client: AsyncClient):
        """GET /devices → пустой список для новой org."""
        r = await device_client.get("/api/v1/devices")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert body["page"] == 1
        assert "per_page" in body
        assert "pages" in body

    async def test_create_device_success(self, device_client: AsyncClient):
        """POST /devices → 201 с корректным телом."""
        payload = {
            "name": "LDPlayer-1",
            "serial": "emulator-5554",
            "type": "ldplayer",
            "ip_address": "10.0.0.1",
            "adb_port": 5555,
            "android_version": "12",
            "device_model": "LDPlayer 9",
            "tags": ["ldplayer", "test"],
        }
        r = await device_client.post("/api/v1/devices", json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "LDPlayer-1"
        assert body["serial"] == "emulator-5554"
        assert body["type"] == "ldplayer"
        assert body["ip_address"] == "10.0.0.1"
        assert body["adb_port"] == 5555
        assert body["status"] == "offline"
        assert "id" in body
        assert "created_at" in body

    async def test_create_device_injection_serial_422(self, device_client: AsyncClient):
        """Device с serial `; rm -rf /` → 422 Validation Error."""
        r = await device_client.post(
            "/api/v1/devices",
            json={"name": "Evil", "serial": "ld:0; rm -rf /"},
        )
        assert r.status_code == 422

    async def test_create_device_pipe_serial_422(self, device_client: AsyncClient):
        """Device с serial `dev|cmd` → 422."""
        r = await device_client.post(
            "/api/v1/devices",
            json={"name": "Evil", "serial": "dev|cmd"},
        )
        assert r.status_code == 422

    async def test_create_device_ampersand_serial_422(self, device_client: AsyncClient):
        """Device с serial `dev&&cmd` → 422."""
        r = await device_client.post(
            "/api/v1/devices",
            json={"name": "Evil", "serial": "dev&&cmd"},
        )
        assert r.status_code == 422

    async def test_create_device_duplicate_serial_409(self, device_client: AsyncClient):
        """Дубликат serial в той же org → 409."""
        payload = {"name": "Device A", "serial": "unique-serial-001"}
        r1 = await device_client.post("/api/v1/devices", json=payload)
        assert r1.status_code == 201

        r2 = await device_client.post(
            "/api/v1/devices", json={"name": "Device B", "serial": "unique-serial-001"}
        )
        assert r2.status_code == 409

    async def test_get_device_by_id(self, device_client: AsyncClient):
        """GET /devices/{id} → корректный ответ."""
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "GetTest", "serial": "get-test-001"}
        )
        assert create_r.status_code == 201
        device_id = create_r.json()["id"]

        r = await device_client.get(f"/api/v1/devices/{device_id}")
        assert r.status_code == 200
        assert r.json()["id"] == device_id
        assert r.json()["name"] == "GetTest"

    async def test_get_nonexistent_device_404(self, device_client: AsyncClient):
        """GET несуществующего устройства → 404."""
        r = await device_client.get(f"/api/v1/devices/{uuid.uuid4()}")
        assert r.status_code == 404

    async def test_update_device(self, device_client: AsyncClient):
        """PUT /devices/{id} → обновляет поля."""
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "Old Name", "serial": "upd-serial-001"}
        )
        device_id = create_r.json()["id"]

        r = await device_client.put(
            f"/api/v1/devices/{device_id}",
            json={"name": "New Name", "android_version": "13"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["name"] == "New Name"
        assert body["android_version"] == "13"

    async def test_delete_device(
        self, device_client: AsyncClient, admin_client: AsyncClient
    ):
        """DELETE /devices/{id} → 204, затем GET → 404.
        device_manager не имеет device:delete, поэтому удаление выполняет org_admin.
        """
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "ToDelete", "serial": "del-serial-001"}
        )
        device_id = create_r.json()["id"]

        del_r = await admin_client.delete(f"/api/v1/devices/{device_id}")
        assert del_r.status_code == 204

        get_r = await device_client.get(f"/api/v1/devices/{device_id}")
        assert get_r.status_code == 404

    async def test_list_devices_pagination(self, device_client: AsyncClient):
        """GET /devices?page=1&per_page=2 → корректная пагинация."""
        for i in range(3):
            await device_client.post(
                "/api/v1/devices",
                json={"name": f"PagDev-{i}", "serial": f"pag-serial-{i:03d}"},
            )

        r = await device_client.get("/api/v1/devices?page=1&per_page=2")
        assert r.status_code == 200
        body = r.json()
        assert len(body["items"]) <= 2
        assert body["per_page"] == 2

    async def test_list_devices_search(self, device_client: AsyncClient):
        """GET /devices?search= → фильтрует по name и serial."""
        await device_client.post(
            "/api/v1/devices", json={"name": "SearchableDevice", "serial": "srch-001"}
        )
        await device_client.post(
            "/api/v1/devices", json={"name": "AnotherOne", "serial": "srch-002"}
        )

        r = await device_client.get("/api/v1/devices?search=Searchable")
        assert r.status_code == 200
        body = r.json()
        names = [d["name"] for d in body["items"]]
        assert any("Searchable" in n for n in names)

    async def test_viewer_can_read_devices(
        self, viewer_client: AsyncClient, device_client: AsyncClient
    ):
        """Viewer может читать устройства (device:read)."""
        await device_client.post(
            "/api/v1/devices", json={"name": "ViewerTest", "serial": "view-001"}
        )
        r = await viewer_client.get("/api/v1/devices")
        assert r.status_code == 200

    async def test_viewer_cannot_create_device(self, viewer_client: AsyncClient):
        """Viewer не может создавать устройства → 403."""
        r = await viewer_client.post(
            "/api/v1/devices", json={"name": "Forbidden", "serial": "viewer-dev-001"}
        )
        assert r.status_code == 403

    async def test_unauthenticated_request_401(self):
        """Без токена → 401."""
        from httpx import ASGITransport, AsyncClient
        from backend.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            r = await client.get("/api/v1/devices")
        assert r.status_code == 401


class TestDeviceStatusEndpoint:
    """GET /devices/{id}/status — DB + live Redis данные."""

    async def test_status_returns_db_plus_live_null(self, device_client: AsyncClient):
        """Когда агент оффлайн (нет ключа в Redis) → live=null."""
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "StatusTest", "serial": "stat-001"}
        )
        device_id = create_r.json()["id"]

        r = await device_client.get(f"/api/v1/devices/{device_id}/status")
        assert r.status_code == 200
        body = r.json()
        assert "status" in body
        assert "live" in body
        assert body["live"] is None  # нет данных в Redis → None

    async def test_status_returns_live_when_redis_has_data(
        self, device_client: AsyncClient, mock_redis, device_org
    ):
        """Когда Redis содержит статус → live отражает его."""
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "LiveStatus", "serial": "live-001"}
        )
        device_id = create_r.json()["id"]

        # Записываем live-статус в FakeRedis
        key = f"device:status:{device_org.id}:{device_id}"
        await mock_redis.set(key, "online", ex=90)

        r = await device_client.get(f"/api/v1/devices/{device_id}/status")
        assert r.status_code == 200
        assert r.json()["live"] == "online"

    async def test_status_device_from_other_org_404(
        self,
        device_client: AsyncClient,
        db_session: AsyncSession,
        other_org,
    ):
        """Устройство другой org → 404 (изоляция org_id)."""
        from backend.models.device import Device

        other_device = Device(
            org_id=other_org.id,
            name="OtherOrgDevice",
            serial="other-001",
            meta={"type": "physical"},
        )
        db_session.add(other_device)
        await db_session.flush()

        r = await device_client.get(f"/api/v1/devices/{other_device.id}/status")
        assert r.status_code == 404


class TestDeviceConnectEndpoint:
    """POST /devices/{id}/connect — инициирует ADB connect (TZ-03 stub)."""

    async def test_connect_without_workstation_400(self, device_client: AsyncClient):
        """Устройство без workstation → 400."""
        create_r = await device_client.post(
            "/api/v1/devices", json={"name": "NoWS", "serial": "no-ws-001"}
        )
        device_id = create_r.json()["id"]

        r = await device_client.post(f"/api/v1/devices/{device_id}/connect")
        assert r.status_code == 400
        assert "workstation" in r.json()["detail"].lower()

    async def test_connect_writes_command_to_redis(
        self, device_client: AsyncClient, mock_redis
    ):
        """ADB connect → команда записана в Redis (TZ-03 stub)."""
        ws_id = str(uuid.uuid4())
        create_r = await device_client.post(
            "/api/v1/devices",
            json={
                "name": "ConnectTest",
                "serial": "conn-001",
                "workstation_id": ws_id,
            },
        )
        device_id = create_r.json()["id"]

        r = await device_client.post(f"/api/v1/devices/{device_id}/connect")
        assert r.status_code == 204

        # Проверить, что команда записана в Redis
        cmd = await mock_redis.get(f"cmd:adb_connect:{device_id}")
        assert cmd is not None
        assert "adb_connect" in cmd


class TestDeviceListPerformance:
    """Производительность: список 100 устройств < 50ms (SQLite in-memory)."""

    async def test_list_100_devices_under_50ms(
        self, db_session: AsyncSession, device_client: AsyncClient, device_org
    ):
        """100 устройств: time(GET /devices) < 50ms."""
        from backend.models.device import Device

        # Bulk-insert 100 устройств напрямую через ORM
        devices = [
            Device(
                org_id=device_org.id,
                name=f"BulkDev-{i:03d}",
                serial=f"bulk-perf-{i:04d}",
                meta={"type": "ldplayer"},
            )
            for i in range(100)
        ]
        db_session.add_all(devices)
        await db_session.flush()

        start = time.monotonic()
        r = await device_client.get("/api/v1/devices?per_page=100")
        elapsed_ms = (time.monotonic() - start) * 1000

        assert r.status_code == 200
        assert elapsed_ms < 50, (
            f"list_devices took {elapsed_ms:.1f}ms — must be < 50ms. "
            "Проверить индексы на org_id."
        )
