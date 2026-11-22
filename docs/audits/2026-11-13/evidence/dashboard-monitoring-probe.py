"""Read the real dashboard and monitoring handlers with synthetic SQL and Redis inputs."""

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
os.environ['JWT_SECRET_KEY'] = 'audit-dashboard-fixture-only-20261114'
os.environ['POSTGRES_URL'] = 'postgresql+asyncpg://127.0.0.1:1/sphere_audit_20261114'
os.environ['REDIS_URL'] = 'redis://127.0.0.1:1/0'

from backend.core.rbac import has_permission
from backend.services.device_status_cache import DeviceStatusCache
from backend.services.fleet_coverage import read_fleet_coverage


async def observe():
    devices = importlib.import_module('backend.api.v1.devices.router')
    monitoring = importlib.import_module('backend.api.v1.monitoring.router')
    org_id = UUID(int=1)
    ids = [str(UUID(int=2)), str(UUID(int=3))]
    user = SimpleNamespace(org_id=org_id)
    svc = SimpleNamespace(get_all_device_ids=AsyncMock(return_value=ids))
    summary = await devices.get_fleet_status(current_user=user, svc=svc, status_cache=DeviceStatusCache(None))
    transaction = AsyncMock()
    rows = [SimpleNamespace(id=UUID(device_id), total=len(ids)) for device_id in ids]
    db = SimpleNamespace(begin_nested=lambda: transaction,
                         execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows)))
    coverage = await read_fleet_coverage(db, None, org_id, vpn_allowed=False)
    assert summary.total == 2 and summary.offline == 2
    assert coverage.inventory.counts == {'total': 2}
    assert coverage.presence.state == 'unavailable' and coverage.presence.counts is None
    assert coverage.vpn_assignment.state == 'forbidden'

    redis = SimpleNamespace(ping=AsyncMock(return_value=True), info=AsyncMock(side_effect=[
        {'instantaneous_ops_per_sec': 50}, {'used_memory': 2 * 1024 * 1024}, {'connected_clients': 2},
    ]))
    with patch.object(monitoring, '_read_container_memory_bytes', return_value=(1048576, 2097152)), patch.object(
        monitoring, '_read_network_counters', return_value=(2048, 4096)
    ), patch.object(monitoring, '_read_linux_load_per_cpu', return_value=0.5):
        metrics = await monitoring.get_monitoring_metrics(redis_conn=redis, _principal=user)
    assert metrics['redis']['status'] == 'HEALTHY' and metrics['network']['activeTunnels'] is None
    permissions = [permission for permission in ('monitoring:read', 'device:read', 'vpn:read')
                   if has_permission('script_runner', permission)]
    assert permissions == ['monitoring:read', 'device:read']
    return {'dashboard_summary': summary.model_dump(), 'fleet_coverage': coverage.model_dump(mode='json'),
            'monitoring_metrics': metrics, 'script_runner_permissions_checked': permissions}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(observe()), ensure_ascii=True, indent=2))
