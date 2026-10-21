"""Tenant-owned runtime pages never read another tenant's cache entry."""
from unittest.mock import AsyncMock, patch

from backend.services.device_status_cache import DeviceStatusCache


async def test_runtime_listing_scopes_devices_before_bulk_cache_read(world):
    cached = AsyncMock(return_value={})
    with patch.object(DeviceStatusCache, "bulk_get_status", cached):
        response = await world.client.get("/api/v1/vpn/runtime", headers=world.auth(world.users["viewer"]))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] == 2
    assert {row["device_id"] for row in data["items"]} == {str(world.dev_a.id), str(world.dev_a2.id)}
    assert set(cached.await_args.args[0]) == {str(world.dev_a.id), str(world.dev_a2.id)}
    assert all(row["freshness"] == "unknown" and row["observation"] is None for row in data["items"])


async def test_runtime_search_is_literal_and_pages_do_not_repeat(world):
    with patch.object(DeviceStatusCache, "bulk_get_status", AsyncMock(return_value={})):
        first = await world.client.get("/api/v1/vpn/runtime?page_size=1", headers=world.auth(world.users["viewer"]))
        second = await world.client.get("/api/v1/vpn/runtime?page_size=1&page=2", headers=world.auth(world.users["viewer"]))
        wildcard = await world.client.get("/api/v1/vpn/runtime?search=%25", headers=world.auth(world.users["viewer"]))
    assert first.status_code == second.status_code == wildcard.status_code == 200
    assert first.json()["items"][0]["device_id"] != second.json()["items"][0]["device_id"]
    assert wildcard.json()["items"] == []
