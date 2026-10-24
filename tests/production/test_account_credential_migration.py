"""Real transaction rollback, restart, CLI behavior and key rotation on audit rows."""

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import text

from backend.core.config import settings
from backend.models.game_account import GameAccount
from backend.services.account_credential_migration import process_credential_batch
from backend.services.account_credentials import (
    AccountCredentialUnavailable,
    read_account_password,
    set_account_password,
)


async def legacy_account(world, password, *, account_id=None):
    async with world.sessions() as db:
        account = GameAccount(id=account_id or uuid.uuid4(), org_id=world.org_a.id,
            game="audit", login="audit-" + uuid.uuid4().hex, password_encrypted=password)
        db.add(account)
        await db.commit()
    return account


@pytest.mark.parametrize("password", ["gAAAA-looks-like-a-token", "", "audit-密码-🔐"])
async def test_backfill_preserves_every_legacy_value_and_rerun_is_idempotent(world, account_credential_key, password):
    account = await legacy_account(world, password)
    async with world.sessions() as db, db.begin():
        before = await process_credential_batch(db, org_id=world.org_a.id)
        assert (before.scanned, before.legacy, before.changed) == (1, 1, 0)
    async with world.sessions() as db, db.begin():
        applied = await process_credential_batch(db, apply=True, org_id=world.org_a.id)
        assert applied.changed == 1
    async with world.sessions() as db, db.begin():
        stored = await db.get(GameAccount, account.id)
        first_token = stored.password_ciphertext
        assert stored.password_encrypted == ""
        assert read_account_password(stored) == password
        repeated = await process_credential_batch(db, apply=True, org_id=world.org_a.id)
        assert (repeated.scanned, repeated.legacy, repeated.changed) == (1, 0, 0)
        assert stored.password_ciphertext == first_token


async def test_rotation_reencrypts_all_selected_rows_and_accepts_new_key_alone(world, account_credential_key, monkeypatch):
    account = await legacy_account(world, "audit-rotation")
    async with world.sessions() as db, db.begin():
        await process_credential_batch(db, apply=True, org_id=world.org_a.id)
        foreign = GameAccount(org_id=world.org_b.id, game="audit", login="audit-foreign-rotation")
        set_account_password(foreign, "audit-foreign-password")
        db.add(foreign)
    original_foreign = foreign.password_ciphertext
    new_key = Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(new_key + "," + account_credential_key))
    async with world.sessions() as db, db.begin():
        result = await process_credential_batch(db, apply=True, rotate=True, org_id=world.org_a.id)
        assert result.changed == 1
    monkeypatch.setattr(settings, "ACCOUNT_CREDENTIAL_KEYS", SecretStr(new_key))
    async with world.sessions() as db:
        assert read_account_password(await db.get(GameAccount, account.id)) == "audit-rotation"
        assert (await db.get(GameAccount, foreign.id)).password_ciphertext == original_foreign


@pytest.mark.parametrize("failure", ["corrupt-next-row", "commit", "cancel"])
async def test_failed_batch_retains_plaintext_for_safe_retry_without_partial_migration(world, account_credential_key, failure):
    ids = sorted([uuid.uuid4(), uuid.uuid4()])
    first = await legacy_account(world, "audit-first", account_id=ids[0])
    second = await legacy_account(world, "audit-second", account_id=ids[1])
    if failure == "corrupt-next-row":
        async with world.sessions() as db, db.begin():
            broken = await db.get(GameAccount, second.id)
            broken.password_ciphertext = "invalid-audit-token"
            broken.password_encrypted = ""
        with pytest.raises(AccountCredentialUnavailable):
            async with world.sessions() as db, db.begin():
                await process_credential_batch(db, apply=True, org_id=world.org_a.id)
    elif failure == "commit":
        async with world.sessions() as db:
            await process_credential_batch(db, apply=True, org_id=world.org_a.id)
            with patch.object(db, "commit", AsyncMock(side_effect=ConnectionError("audit commit rejected"))):
                with pytest.raises(ConnectionError):
                    await db.commit()
            await db.rollback()
    else:
        def interrupted(account, password):
            if account.id == second.id:
                raise asyncio.CancelledError()
            set_account_password(account, password)
        with pytest.raises(asyncio.CancelledError):
            async with world.sessions() as db, db.begin():
                with patch("backend.services.account_credential_migration.set_account_password", side_effect=interrupted):
                    await process_credential_batch(db, apply=True, org_id=world.org_a.id)
    async with world.sessions() as db:
        stored = (await db.execute(text("SELECT password_encrypted, password_ciphertext FROM game_accounts WHERE id=:id"),
                                   {"id": first.id})).one()
        assert stored == ("audit-first", None)


async def test_bounded_batches_cover_all_rows_and_restart_validates_committed_rows(world, account_credential_key):
    for value in range(5):
        await legacy_account(world, f"audit-batch-{value}")
    cursor = None
    sizes = []
    while True:
        async with world.sessions() as db, db.begin():
            batch = await process_credential_batch(db, after_id=cursor, limit=2, apply=True, org_id=world.org_a.id)
        sizes.append(batch.scanned)
        cursor = batch.cursor
        if batch.scanned < 2:
            break
    assert sizes == [2, 2, 1]
    async with world.sessions() as db:
        verified = await process_credential_batch(db, org_id=world.org_a.id)
        assert (verified.scanned, verified.legacy, verified.changed) == (5, 0, 0)


async def test_cli_defaults_to_read_only_and_never_prints_credentials(world, account_credential_key):
    marker = "audit-cli-password"
    account = await legacy_account(world, marker)
    environment = os.environ.copy()
    environment["ACCOUNT_CREDENTIAL_KEYS"] = account_credential_key
    command = [sys.executable, "-m", "backend.cli.account_credentials", "--org-id", str(world.org_a.id)]

    def invoke(*arguments):
        result = subprocess.run(command + list(arguments), env=environment,
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True,
            encoding="utf-8", timeout=30)
        assert marker not in result.stdout + result.stderr
        assert account_credential_key not in result.stdout + result.stderr
        return result, json.loads(result.stdout)

    result, summary = invoke()
    assert result.returncode == 1 and summary["legacy_found"] == 1 and summary["changed"] == 0
    async with world.sessions() as db:
        assert (await db.get(GameAccount, account.id)).password_encrypted == marker
    result, summary = invoke("--apply", "--batch-size", "1")
    assert result.returncode == 0 and summary["changed"] == 1
    result, summary = invoke()
    assert result.returncode == 0 and summary["legacy_found"] == 0
    environment["ACCOUNT_CREDENTIAL_KEYS"] = Fernet.generate_key().decode()
    result, summary = invoke("--apply", "--rotate")
    assert result.returncode == 2 and summary["previously_committed_changes"] == 0
    async with world.sessions() as db:
        assert read_account_password(await db.get(GameAccount, account.id)) == marker
