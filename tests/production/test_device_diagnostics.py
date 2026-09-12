"""Default diagnostics must read APK's persistent application journal."""

from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.parametrize("body,expected", [
    ({"lines": 2}, "reconnected\ncommand completed"),
    ({"lines": 1, "mode": "sphere"}, "command completed"),
])
async def test_sphere_diagnostics_returns_bounded_recent_persisted_logs(world, body, expected):
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {
        "status": "completed", "result": {"logs": "started\nreconnected\ncommand completed\n"},
    }
    with patch("backend.websocket.pubsub_router.get_pubsub_publisher", return_value=publisher):
        response = await world.client.post(f"/api/v1/devices/{world.dev_a.id}/logcat",
            headers=world.auth(world.users['org_admin']), json=body)
    assert response.status_code == 200
    command = publisher.send_command_wait_result.await_args.args[1]
    assert command['type'] == 'REQUEST_LOGS'
    assert command['payload'] == {'max_bytes': 64 * 1024}
    assert response.json() == {'logcat': expected}


async def test_system_logcat_mode_keeps_existing_agent_command(world):
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {
        'status': 'completed', 'result': {'logcat': 'system log data\n'},
    }
    with patch('backend.websocket.pubsub_router.get_pubsub_publisher', return_value=publisher):
        response = await world.client.post(f'/api/v1/devices/{world.dev_a.id}/logcat',
            headers=world.auth(world.users['org_admin']), json={'lines': 25, 'mode': 'full'})
    command = publisher.send_command_wait_result.await_args.args[1]
    assert command['type'] == 'UPLOAD_LOGCAT'
    assert command['payload'] == {'lines': 25, 'mode': 'full'}
    assert response.json() == {'logcat': 'system log data\n'}


async def test_failed_persistent_log_request_is_not_reported_as_empty_success(world):
    publisher = AsyncMock()
    publisher.send_command_wait_result.return_value = {'status': 'failed', 'error': 'journal unavailable'}
    with patch('backend.websocket.pubsub_router.get_pubsub_publisher', return_value=publisher):
        response = await world.client.post(f'/api/v1/devices/{world.dev_a.id}/logcat',
            headers=world.auth(world.users['org_admin']), json={'mode': 'sphere'})
    assert response.json() == {'error': 'journal unavailable'}
