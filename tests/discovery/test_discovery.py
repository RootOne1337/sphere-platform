# tests/discovery/test_discovery.py
# TZ-02 SPLIT-5: Network Discovery tests.
from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from backend.schemas.discovery import DiscoverRequest


class TestDiscoverRequestSchema:
    """Unit tests: schema validation for DiscoverRequest."""

    def test_valid_subnet_24(self):
        req = DiscoverRequest(
            subnet="192.168.1.0/24",
            workstation_id=uuid.uuid4(),
        )
        assert req.subnet == "192.168.1.0/24"

    def test_subnet_normalized(self):
        req = DiscoverRequest(
            subnet="192.168.1.100/24",  # host bits → stripped
            workstation_id=uuid.uuid4(),
        )
        assert req.subnet == "192.168.1.0/24"

    def test_subnet_too_large_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            DiscoverRequest(
                subnet="10.0.0.0/8",  # 16M hosts > 65536
                workstation_id=uuid.uuid4(),
            )
        assert "65536" in str(exc_info.value)

    def test_subnet_slash_16_accepted(self):
        req = DiscoverRequest(
            subnet="10.0.0.0/16",  # exactly 65536 hosts
            workstation_id=uuid.uuid4(),
        )
        assert "/16" in req.subnet

    def test_invalid_subnet_rejected(self):
        with pytest.raises(ValidationError):
            DiscoverRequest(subnet="not-a-subnet", workstation_id=uuid.uuid4())

    def test_port_range_defaults(self):
        req = DiscoverRequest(subnet="192.168.1.0/24", workstation_id=uuid.uuid4())
        assert req.port_range == [5554, 5584]

    def test_port_range_invalid_order_rejected(self):
        with pytest.raises(ValidationError):
            DiscoverRequest(
                subnet="192.168.1.0/24",
                workstation_id=uuid.uuid4(),
                port_range=[5584, 5554],  # high < low
            )

    def test_timeout_ms_bounds(self):
        with pytest.raises(ValidationError):
            DiscoverRequest(
                subnet="192.168.1.0/24",
                workstation_id=uuid.uuid4(),
                timeout_ms=50,  # < 100
            )

    def test_auto_register_default_true(self):
        req = DiscoverRequest(subnet="192.168.1.0/24", workstation_id=uuid.uuid4())
        assert req.auto_register is True


class TestDiscoveryScanEndpoint:
    """Integration tests for /discovery/scan endpoint."""

    async def test_scan_returns_empty_when_no_devices_found(
        self, disc_client, disc_workstation
    ):
        """TZ-08 stub returns empty list → found=0, registered=0."""
        resp = await disc_client.post(
            "/api/v1/discovery/scan",
            json={
                "subnet": "192.168.99.0/24",
                "workstation_id": str(disc_workstation.id),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] == 0
        assert data["registered"] == 0
        assert data["devices"] == []
        assert data["duration_ms"] >= 0

    async def test_scan_reports_scanned_count(self, disc_client, disc_workstation):
        resp = await disc_client.post(
            "/api/v1/discovery/scan",
            json={
                "subnet": "192.168.1.0/24",
                "port_range": [5554, 5584],
                "workstation_id": str(disc_workstation.id),
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # 256 hosts × (5584 - 5554 + 1) = 256 × 31 = 7936
        assert data["scanned"] == 256 * 31

    async def test_large_subnet_rejected_422(self, disc_client, disc_workstation):
        resp = await disc_client.post(
            "/api/v1/discovery/scan",
            json={
                "subnet": "10.0.0.0/8",
                "workstation_id": str(disc_workstation.id),
            },
        )
        assert resp.status_code == 422

    async def test_viewer_cannot_scan(self, disc_org, db_session, mock_redis):
        """discovery requires device:write."""
        from collections.abc import AsyncGenerator
        from unittest.mock import patch

        from httpx import ASGITransport, AsyncClient

        from backend.core.security import create_access_token
        from backend.main import app
        from backend.models.user import User

        viewer = User(
            org_id=disc_org.id,
            email="viewer_disc@sphere.local",
            password_hash="$2b$12$placeholder_hash",
            role="viewer",
        )
        db_session.add(viewer)
        await db_session.flush()

        token, _ = create_access_token(
            subject=str(viewer.id),
            org_id=str(disc_org.id),
            role=viewer.role,
        )

        async def _override_get_db() -> AsyncGenerator:
            yield db_session

        async def _fake_get_redis():
            return mock_redis

        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_redis] = _fake_get_redis

        try:
            with patch("backend.services.cache_service.get_redis", _fake_get_redis):
                async with AsyncClient(
                    transport=ASGITransport(app=app),
                    base_url="http://testserver",
                    headers={"Authorization": f"Bearer {token}"},
                ) as client:
                    resp = await client.post(
                        "/api/v1/discovery/scan",
                        json={
                            "subnet": "192.168.1.0/24",
                            "workstation_id": str(uuid.uuid4()),
                        },
                    )
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 403

    async def test_unauthenticated_401(self):
        from httpx import ASGITransport, AsyncClient

        from backend.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            resp = await client.post(
                "/api/v1/discovery/scan",
                json={
                    "subnet": "192.168.1.0/24",
                    "workstation_id": str(uuid.uuid4()),
                },
            )
        assert resp.status_code == 401

    async def test_already_registered_device_detected(
        self, disc_client, disc_workstation, db_session, disc_org
    ):
        """If a device with matching serial exists, already_registered=True."""
        from unittest.mock import AsyncMock
        from unittest.mock import patch as mock_patch

        from backend.models.device import Device

        serial = "192.168.99.50:5555"
        existing = Device(
            org_id=disc_org.id,
            name="Already Registered",
            serial=serial,
            meta={"type": "physical"},
        )
        db_session.add(existing)
        await db_session.flush()

        # Mock the stub to return this device
        mock_devices = [{"ip": "192.168.99.50", "port": 5555, "model": "Pixel", "android_version": "12"}]

        with mock_patch(
            "backend.services.discovery_service.DiscoveryService._discover_devices_via_agent",
            new=AsyncMock(return_value=mock_devices),
        ):
            resp = await disc_client.post(
                "/api/v1/discovery/scan",
                json={
                    "subnet": "192.168.99.0/24",
                    "workstation_id": str(disc_workstation.id),
                    "auto_register": False,
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] == 1
        device = data["devices"][0]
        assert device["already_registered"] is True
        assert device["registered_id"] == str(existing.id)


# Fix missing import in viewer test
from backend.database.engine import get_db  # noqa: E402
from backend.database.redis_client import get_redis  # noqa: E402
