"""SQL evidence for every production writer of recoverable account passwords."""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr
from sqlalchemy import select, text

from backend.core.config import settings
from backend.models.game_account import GameAccount
from backend.models.script import ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.schemas.game_accounts import (
    CreateGameAccountRequest,
    ImportAccountItem,
    UpdateGameAccountRequest,
)
from backend.services.game_account_service import GameAccountService
from backend.services.orchestrator.orchestration_engine import OrchestrationEngine
from backend.services.task_service import TaskService

PASSWORD = "audit-plaintext-storage-marker"


@pytest.fixture(autouse=True)
def storage_key(account_credential_key):
    return account_credential_key


@pytest.mark.parametrize("writer", ["create", "update", "import", "orchestrator"])
async def test_account_writers_do_not_persist_plaintext(world, writer):
    login = "audit-storage-" + uuid.uuid4().hex
    async with world.sessions() as db:
        svc = GameAccountService(db)
        if writer in {"create", "update"}:
            result = await svc.create_account(world.org_a.id, CreateGameAccountRequest(
                game="audit", login=login, password=PASSWORD if writer == "create" else "audit-old"))
            if writer == "update":
                await svc.update_account(result.id, world.org_a.id, UpdateGameAccountRequest(password=PASSWORD))
        elif writer == "import":
            result = await svc.import_accounts(world.org_a.id, [ImportAccountItem(
                game="audit", login=login, password=PASSWORD)])
            assert result.created == 1 and not result.errors
        else:
            config = SimpleNamespace(org_id=world.org_a.id, nick_generation_enabled=False,
                registration_script_id=world.script.id, default_target_level=5,
                registration_timeout_seconds=120)
            with patch("backend.services.nick_generator.NickGenerator.generate", AsyncMock(return_value=login)):
                await OrchestrationEngine()._create_registration_task(db, config, world.dev_a)
        await db.commit()
        account = await db.scalar(select(GameAccount).where(
            GameAccount.org_id == world.org_a.id, GameAccount.login == login))
        revealed = await svc.get_account(account.id, world.org_a.id, show_password=True)
        expected = revealed.password if writer == "orchestrator" else PASSWORD
        assert revealed.password == expected and expected
        version = await db.get(ScriptVersion, world.version.id)
        version.dag = {"entry_node": "n1", "nodes": [{"id": "n1", "action": {
            "type": "type_text", "text": "{{account.password}}"}}]}
        if writer != "orchestrator":
            await TaskService(db).create_task(world.script.id, world.dev_a.id, world.org_a.id,
                                              account_id=account.id)
        await db.commit()
    async with world.sessions() as raw:
        # text() bypasses all ORM result processors: this is the stored SQL value.
        stored = await raw.scalar(text("SELECT password_encrypted FROM game_accounts WHERE id=:id"),
                                  {"id": account.id})
        assert stored != expected, "Raw PostgreSQL exposes the reusable account password"
        assert stored == "", "The legacy plaintext must be erased in the same transaction"
        ciphertext = await raw.scalar(text("SELECT password_ciphertext FROM game_accounts WHERE id=:id"),
                                      {"id": account.id})
        assert ciphertext and expected not in ciphertext
    # The agent still gets the original password, never the encryption token.
    async with world.sessions() as dispatch:
        publisher = AsyncMock()
        cache = AsyncMock()
        cache.bulk_get_status.side_effect = lambda ids: {
            device: SimpleNamespace(status="online") if device == str(world.dev_a.id) else None for device in ids}
        await TaskService(dispatch, status_cache=cache, publisher=publisher).dispatch_pending_tasks()
        payload = publisher.send_command_live.call_args.args[1]["payload"]
        assert payload["dag"]["nodes"][0]["action"]["text"] == expected
        task = await dispatch.scalar(select(Task).where(Task.device_id == world.dev_a.id))
        assert expected not in str(task.input_params)


@pytest.mark.parametrize("key", ["", "malformed-audit-key"])
async def test_missing_or_invalid_key_prevents_api_plaintext_fallback(world, monkeypatch, key):
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(key))
    headers = world.auth(world.users["org_admin"])
    body = {"game": "audit", "login": "audit-key-failure", "password": PASSWORD}
    for path, data in [("", body), ("/import", {"accounts": [body]})]:
        response = await world.client.post("/api/v1/game-accounts" + path, headers=headers, json=data)
        assert response.status_code == 503
        assert PASSWORD not in response.text
    async with world.sessions() as db:
        assert not (await db.scalars(select(GameAccount).where(GameAccount.org_id == world.org_a.id))).all()


async def test_legacy_account_remains_visible_but_cannot_be_revealed_or_dispatched(world):
    async with world.sessions() as db:
        account = GameAccount(org_id=world.org_a.id, game="audit", login="audit-legacy", password_encrypted=PASSWORD)
        db.add(account)
        await db.flush()
        task = await TaskService(db).create_task(world.script.id, world.dev_a.id, world.org_a.id, account_id=account.id)
        await db.commit()
    headers = world.auth(world.users["org_admin"])
    normal = await world.client.get(f"/api/v1/game-accounts/{account.id}", headers=headers)
    reveal = await world.client.get(f"/api/v1/game-accounts/{account.id}?show_password=true", headers=headers)
    assert normal.status_code == 200 and PASSWORD not in normal.text
    assert reveal.status_code == 503 and PASSWORD not in reveal.text
    async with world.sessions() as db:
        publisher = AsyncMock()
        cache = AsyncMock()
        cache.bulk_get_status.side_effect = lambda ids: {
            device: SimpleNamespace(status="online") if device == str(world.dev_a.id) else None for device in ids}
        await TaskService(db, status_cache=cache, publisher=publisher).dispatch_pending_tasks()
        publisher.send_command_live.assert_not_called()
        assert (await db.get(Task, task.id)).status == TaskStatus.QUEUED
