"""Run current registry and inspector read handlers with synthetic inventory and presence."""

import asyncio
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from backend.schemas.device_status import DeviceLiveStatus
from backend.schemas.devices import DeviceResponse, UpdateDeviceRequest
from backend.services.device_service import DeviceService
from backend.services.device_status_cache import DeviceStatusCache
from backend.services.group_service import GroupService

DEVICE = UUID(int=1)
ORG = UUID(int=2)
NOW = datetime.now(timezone.utc)
ACTOR = SimpleNamespace(org_id=ORG)


def inventory():
    return DeviceResponse(id=DEVICE, name="Fixture Android", status="online", is_active=True,
                          created_at=NOW, updated_at=NOW)


def synthetic_service():
    return SimpleNamespace(
        list_device_status_candidates=AsyncMock(return_value=[(DEVICE, "online")]),
        get_devices_by_ids=AsyncMock(side_effect=lambda *_: [inventory()]),
        get_device=AsyncMock(side_effect=lambda *_: inventory()),
    )


async def project(router, cache):
    service = synthetic_service()
    with patch.object(router.DeviceViewers, "counts", new=AsyncMock(return_value=None)):
        listing = await router.list_devices(status=None, group_id=None, location_id=None, type_filter=None,
                                            search=None, live_status=None, page=1, per_page=100,
                                            current_user=ACTOR, svc=service, status_cache=cache)
    detail = await router.get_device(device_id=DEVICE, current_user=ACTOR, svc=service, status_cache=cache)
    return listing, detail


async def main():
    router = importlib.import_module("backend.api.v1.devices.router")
    live = DeviceLiveStatus(device_id=str(DEVICE), status="online", last_heartbeat=NOW,
                            ws_session_id="fixture", vpn_observed_session_id="fixture",
                            vpn_observed_at=NOW, vpn_active=True).with_current_vpn_observation()
    cache = SimpleNamespace(redis=object(), bulk_get_status=AsyncMock(return_value={str(DEVICE): live}),
                            get_status=AsyncMock(return_value=live))
    listing, detail = await project(router, cache)
    row = listing.items[0].model_dump(mode="json")
    assert row["vpn_active"] is True and row["vpn_observation_state"] == "fresh"
    assert "vpn_assigned" not in row and row["adb_connected"] is False

    missing_listing, missing_detail = await project(router, DeviceStatusCache(None))
    assert missing_listing.items[0].status == "unknown" and missing_detail.status == "online"
    assert missing_detail.last_heartbeat is None

    empty_redis = SimpleNamespace(mget=AsyncMock(return_value=[None]), get=AsyncMock(return_value=None))
    empty_listing, empty_detail = await project(router, DeviceStatusCache(empty_redis))
    assert empty_listing.presence_available and empty_listing.items[0].status == "offline"
    assert empty_detail.status == "online" and empty_detail.last_heartbeat is None

    group_a, group_b, group_c = (SimpleNamespace(id=UUID(int=n), org_id=ORG) for n in (3, 4, 5))
    member = SimpleNamespace(id=DEVICE, groups=[group_a, group_b])
    groups_before = [str(item.id) for item in member.groups]
    synthetic_result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [member]))
    database = SimpleNamespace(get=AsyncMock(return_value=group_c), execute=AsyncMock(return_value=synthetic_result), flush=AsyncMock())
    moved = await GroupService(database).move_devices_to_group([str(DEVICE)], group_c.id, ORG)
    groups_after = [str(item.id) for item in member.groups]
    assert moved == 1 and groups_after == [str(group_c.id)]

    device_service = DeviceService(SimpleNamespace(flush=AsyncMock(), refresh=AsyncMock()), None)
    registered = SimpleNamespace(id=DEVICE, name="Fixture Android", last_status="online", is_active=True,
                                 serial="fixture-serial", meta={}, groups=[], locations=[], android_version=None,
                                 model=None, tags=[], notes=None, server_name="RED", created_at=NOW, updated_at=NOW)
    with patch.object(device_service, "_get_device", new=AsyncMock(return_value=registered)):
        kept = await device_service.update_device(DEVICE, ORG, UpdateDeviceRequest(server_name=None))
        cleared = await device_service.update_device(DEVICE, ORG, UpdateDeviceRequest(server_name=""))
    assert kept.server_name == "RED" and cleared.server_name is None
    assert kept.serial == "fixture-serial" and "android_id" not in kept.model_dump()

    print(json.dumps({
        "fresh_presence": {"list": row, "detail": detail.model_dump(mode="json")},
        "redis_client_absent": {"list_status": missing_listing.items[0].status,
                                "presence_available": missing_listing.presence_available,
                                "detail_status": missing_detail.status, "detail_heartbeat": missing_detail.last_heartbeat},
        "redis_device_key_absent": {"list_status": empty_listing.items[0].status,
                                    "presence_available": empty_listing.presence_available,
                                    "detail_status": empty_detail.status, "detail_heartbeat": empty_detail.last_heartbeat},
        "group_assignment": {"before": groups_before, "after": groups_after, "moved": moved},
        "game_server_clear": {"explicit_null_result": kept.server_name, "empty_string_result": cleared.server_name},
        "device_identifiers": {"serial": kept.serial, "android_id_in_contract": "android_id" in kept.model_dump()},
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
