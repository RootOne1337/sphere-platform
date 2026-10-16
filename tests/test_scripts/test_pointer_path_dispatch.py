"""Version admission is enforced by the common durable task dispatcher."""
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.models.task import TaskStatus
from backend.services.task_service import TaskService


@pytest.mark.asyncio
@pytest.mark.parametrize("code", [None, 10280, 10281])
async def test_pointer_path_dispatch_requires_new_agent_and_keeps_queued_task_receipt(code):
    device_id, org_id = uuid.uuid4(), uuid.uuid4()
    device = SimpleNamespace(id=device_id, org_id=org_id)
    task = SimpleNamespace(id=uuid.uuid4(), device_id=device_id, org_id=org_id, script_version_id=uuid.uuid4(),
                           script_id=uuid.uuid4(), status=TaskStatus.QUEUED, cancel_requested_at=None,
                           timeout_seconds=90)
    dag = {"nodes": [{"id": "gesture", "action": {"type": "pointer_path"}}]}
    db = SimpleNamespace(scalars=AsyncMock(return_value=[device_id]), rollback=AsyncMock(), commit=AsyncMock(),
                         scalar=AsyncMock(side_effect=[device, None, task, SimpleNamespace(dag=dag)]),
                         get=AsyncMock(return_value=SimpleNamespace(name="Path fixture")))
    presence = SimpleNamespace(status="online", agent_version_code=code)
    cache = SimpleNamespace(bulk_get_status=AsyncMock(return_value={str(device_id): presence}))
    publisher = SimpleNamespace(send_command_live=AsyncMock(return_value=True))
    service = TaskService(db, status_cache=cache, publisher=publisher)
    service._load_account_for_task = AsyncMock(return_value=None)
    await service.dispatch_pending_tasks(org_id=org_id, device_id=device_id, include_cancellations=False)
    db.commit.assert_awaited_once()
    if code != 10281:
        assert task.status == TaskStatus.FAILED
        assert "no input was sent" in task.error_message
        assert task.finished_at is not None
        publisher.send_command_live.assert_not_awaited()
    else:
        assert task.status == TaskStatus.ASSIGNED
        publisher.send_command_live.assert_awaited_once()
