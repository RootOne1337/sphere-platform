"""Cache identity must cover the resolved per-account command payload."""

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from backend.models.game_account import GameAccount
from backend.models.script import ScriptVersion
from backend.models.task import Task
from backend.services.task_queue import TaskQueue
from backend.services.task_service import TaskService


async def test_dispatched_hash_identifies_resolved_account_payload(world):
    w = world
    queue = TaskQueue(w.redis)
    async with w.sessions() as db:
        version = await db.get(ScriptVersion, w.version.id)
        version.dag = {"entry_node": "n1", "nodes": [{"id": "n1", "action": {
            "type": "type_text", "text": "{{account.login}}"}}]}
        account = GameAccount(org_id=w.org_a.id, game="audit", login="resolved-account",
                              password_encrypted="synthetic-unused")
        db.add(account)
        await db.flush()
        task = Task(org_id=w.org_a.id, device_id=w.dev_a.id, script_id=w.script.id,
                    script_version_id=w.version.id, input_params={"account_id": str(account.id)})
        db.add(task)
        await db.commit()
        await queue.enqueue(str(task.id), str(w.dev_a.id), str(w.org_a.id))
        cache = AsyncMock()
        cache.get_all_tracked_device_ids.return_value = [str(w.dev_a.id)]
        cache.get_status.side_effect = lambda device_id: SimpleNamespace(status="online") if device_id == str(w.dev_a.id) else None
        cache.bulk_get_status.side_effect = lambda ids: {
            device_id: SimpleNamespace(status="online") if device_id == str(w.dev_a.id) else None for device_id in ids
        }
        publisher = AsyncMock()
        publisher.send_command_live.return_value = True
        await TaskService(db, queue, status_cache=cache, publisher=publisher).dispatch_pending_tasks()
        payload = publisher.send_command_live.call_args.args[1]["payload"]
        assert payload["dag"]["nodes"][0]["action"]["text"] == "resolved-account"
        expected = hashlib.sha256(json.dumps(payload["dag"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        assert payload["dag_hash"] == expected
