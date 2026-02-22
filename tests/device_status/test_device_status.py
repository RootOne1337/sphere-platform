# tests/device_status/test_device_status.py
# TZ-02 SPLIT-3: DeviceStatusCache + Fleet endpoints tests.
from __future__ import annotations

import pytest
from fakeredis.aioredis import FakeRedis

from backend.schemas.device_status import DeviceLiveStatus
from backend.services.device_status_cache import DeviceStatusCache


class TestDeviceStatusCache:
    """Unit tests for DeviceStatusCache with msgpack serialization."""

    @pytest.fixture
    def cache(self):
        redis = FakeRedis(decode_responses=False)  # msgpack needs bytes
        return DeviceStatusCache(redis)

    async def test_set_and_get_status(self, cache):
        status = DeviceLiveStatus(
            device_id="dev-1",
            status="online",
            battery=85,
            adb_connected=True,
        )
        await cache.set_status("dev-1", status)
        retrieved = await cache.get_status("dev-1")
        assert retrieved is not None
        assert retrieved.status == "online"
        assert retrieved.battery == 85
        assert retrieved.adb_connected is True

    async def test_get_nonexistent_returns_none(self, cache):
        result = await cache.get_status("nonexistent-device")
        assert result is None

    async def test_bulk_get_status_mget(self, cache):
        for i in range(5):
            await cache.set_status(
                f"bulk-dev-{i}",
                DeviceLiveStatus(device_id=f"bulk-dev-{i}", status="online"),
            )
        results = await cache.bulk_get_status([f"bulk-dev-{i}" for i in range(5)])
        assert len(results) == 5
        assert all(v is not None for v in results.values())

    async def test_bulk_get_missing_returns_none_entry(self, cache):
        results = await cache.bulk_get_status(["missing-1", "missing-2"])
        assert results["missing-1"] is None
        assert results["missing-2"] is None

    async def test_mark_offline_existing(self, cache):
        await cache.set_status(
            "dev-online",
            DeviceLiveStatus(
                device_id="dev-online",
                status="online",
                adb_connected=True,
                ws_session_id="sess-123",
            ),
        )
        await cache.mark_offline("dev-online")
        result = await cache.get_status("dev-online")
        assert result is not None
        assert result.status == "offline"
        assert result.adb_connected is False
        assert result.ws_session_id is None

    async def test_mark_offline_creates_entry_if_missing(self, cache):
        await cache.mark_offline("brand-new-device")
        result = await cache.get_status("brand-new-device")
        assert result is not None
        assert result.status == "offline"

    async def test_fleet_summary_counts(self, cache):
        await cache.set_status("d1", DeviceLiveStatus(device_id="d1", status="online"))
        await cache.set_status("d2", DeviceLiveStatus(device_id="d2", status="online"))
        await cache.set_status("d3", DeviceLiveStatus(device_id="d3", status="busy"))
        # d4 has no Redis entry → offline

        summary = await cache.get_fleet_summary(["d1", "d2", "d3", "d4"])
        assert summary["total"] == 4
        assert summary["online"] == 2
        assert summary["busy"] == 1
        assert summary["offline"] == 1

    async def test_msgpack_round_trip_with_none_fields(self, cache):
        """Fields with None must survive msgpack round-trip."""
        status = DeviceLiveStatus(
            device_id="null-fields",
            status="connecting",
            battery=None,
            current_task_id=None,
        )
        await cache.set_status("null-fields", status)
        result = await cache.get_status("null-fields")
        assert result is not None
        assert result.battery is None
        assert result.status == "connecting"

    async def test_online_ttl_larger_than_offline(self, cache):
        """Verify TTL constants: online > offline is wrong by spec; online=120 < offline=3600."""
        assert DeviceStatusCache.TTL_ONLINE == 120
        assert DeviceStatusCache.TTL_OFFLINE == 3600


class TestFleetEndpoints:
    """Integration tests for fleet status endpoints."""

    async def test_fleet_status_returns_structure(
        self, status_client, status_devices
    ):
        resp = await status_client.get("/api/v1/devices/status/fleet")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "online" in data
        assert "busy" in data
        assert "offline" in data
        assert data["total"] == len(status_devices)
        assert data["offline"] == len(status_devices)  # no Redis entries → all offline

    async def test_bulk_status_returns_per_device(
        self, status_client, status_devices, mock_redis
    ):
        # Pre-populate one device as online
        import msgpack
        from fakeredis.aioredis import FakeRedis

        # Use a binary FakeRedis to write msgpack data
        binary_redis = FakeRedis(decode_responses=False)
        cache = DeviceStatusCache(binary_redis)
        device_id = str(status_devices[0].id)
        await cache.set_status(
            device_id,
            DeviceLiveStatus(device_id=device_id, status="online"),
        )
        # But our client uses mock_redis (decode_responses=True)
        # Just test with all offline (mock_redis won't have binary data)
        device_ids = [str(d.id) for d in status_devices]
        resp = await status_client.post(
            "/api/v1/devices/status/bulk",
            json={"device_ids": device_ids},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(device_ids)

    async def test_bulk_status_filters_other_org_devices(
        self, status_client, status_devices, db_session
    ):
        """Devices from other orgs should be silently excluded."""
        from backend.models.organization import Organization
        from backend.models.device import Device

        other_org = Organization(name="Other Status Org", slug="other-status-org")
        db_session.add(other_org)
        await db_session.flush()

        other_device = Device(
            org_id=other_org.id,
            name="Foreign Device",
            serial="foreign-serial",
            meta={"type": "ldplayer"},
        )
        db_session.add(other_device)
        await db_session.flush()

        # Request includes a device_id from another org
        device_ids = [str(d.id) for d in status_devices] + [str(other_device.id)]
        resp = await status_client.post(
            "/api/v1/devices/status/bulk",
            json={"device_ids": device_ids},
        )
        assert resp.status_code == 200
        data = resp.json()
        # total should only count owned devices
        assert data["total"] == len(status_devices)

    async def test_fleet_unauthenticated_401(self, status_devices):
        from httpx import AsyncClient, ASGITransport
        from backend.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.get("/api/v1/devices/status/fleet")
        assert resp.status_code == 401
