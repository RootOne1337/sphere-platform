"""Refresh rotation must consume each SQL token once, after its row owner commits."""

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect, select, text

from backend.core.exceptions import InvalidTokenError
from backend.models.refresh_token import RefreshToken
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService


async def issue(world):
    async with world.sessions() as db:
        result = await AuthService(db, CacheService())._issue_tokens(world.users["org_admin"])
        row = await db.scalar(select(RefreshToken).where(
            RefreshToken.token_hash == hashlib.sha256(result["refresh_token"].encode()).hexdigest(),
        ))
        return result["refresh_token"], row.id


async def refresh(db, raw):
    try:
        return 200, await AuthService(db, CacheService()).refresh(raw)
    except InvalidTokenError:
        await db.rollback()
        return 401, None


async def wait_for_locks(world, pids):
    async def observe():
        while True:
            async with world.sessions() as db:
                rows = (await db.execute(text(
                    "SELECT pid FROM pg_stat_activity WHERE pid = ANY(:pids) AND wait_event_type = 'Lock'"
                ), {"pids": pids})).scalars().all()
            if set(rows) == set(pids):
                return
            await asyncio.sleep(0.01)
    await asyncio.wait_for(observe(), 4)


async def live_tokens(world):
    async with world.sessions() as db:
        return (await db.scalars(select(RefreshToken).where(
            RefreshToken.user_id == world.users["org_admin"].id,
            RefreshToken.revoked.is_(False),
        ))).all()


@pytest.mark.parametrize("preload", [False, True])
async def test_concurrent_refresh_consumes_one_parent_only_once(world, preload):
    raw, token_id = await issue(world)
    async with world.sessions() as holder, world.sessions() as first, world.sessions() as second:
        await holder.execute(select(RefreshToken).where(RefreshToken.id == token_id).with_for_update())
        pids = [await db.scalar(text("SELECT pg_backend_pid()")) for db in (first, second)]
        cached = [await db.get(RefreshToken, token_id) for db in (first, second)] if preload else []
        pending = [asyncio.create_task(refresh(db, raw)) for db in (first, second)]
        try:
            # Both actual database transactions overlap, independent of Python scheduling.
            await wait_for_locks(world, pids)
            await holder.commit()
            results = await asyncio.wait_for(asyncio.gather(*pending), 4)
        finally:
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        assert all(row is not None for row in cached)
    assert sorted(code for code, _ in results) == [200, 401]
    assert len(await live_tokens(world)) == 1
    winner = next(data for code, data in results if code == 200)
    # Prove the winning child is usable through the HTTP contract, then single-use too.
    child = await world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": winner["refresh_token"]})
    assert child.status_code == 200
    replay = await world.client.post("/api/v1/auth/refresh", headers={"X-Refresh-Token": raw})
    assert replay.status_code == 401


@pytest.mark.parametrize("preload", [False, True])
@pytest.mark.parametrize("change", ["revoke", "expire"])
async def test_refresh_rechecks_committed_revocation_or_expiry_after_wait(world, preload, change):
    raw, token_id = await issue(world)
    async with world.sessions() as holder, world.sessions() as contender:
        row = await holder.scalar(select(RefreshToken).where(RefreshToken.id == token_id).with_for_update())
        pid = await contender.scalar(text("SELECT pg_backend_pid()"))
        cached = await contender.get(RefreshToken, token_id) if preload else None
        if change == "revoke":
            row.revoked = True
            row.revoked_at = datetime.now(timezone.utc)
        else:
            row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await holder.flush()
        pending = asyncio.create_task(refresh(contender, raw))
        try:
            await wait_for_locks(world, [pid])
            await holder.commit()
            code, _ = await asyncio.wait_for(pending, 4)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        # Rejected refresh rolls back and expires ORM attributes; retain identity
        # without starting implicit async database I/O from a synchronous property.
        assert cached is None or inspect(cached).identity == (token_id,)
    assert code == 401
    async with world.sessions() as db:
        rows = (await db.scalars(select(RefreshToken).where(
            RefreshToken.user_id == world.users["org_admin"].id,
        ))).all()
        assert [row.id for row in rows] == [token_id]


async def test_rolled_back_revocation_does_not_consume_refresh(world):
    raw, token_id = await issue(world)
    async with world.sessions() as holder, world.sessions() as contender:
        row = await holder.scalar(select(RefreshToken).where(RefreshToken.id == token_id).with_for_update())
        row.revoked = True
        await holder.flush()
        pid = await contender.scalar(text("SELECT pg_backend_pid()"))
        pending = asyncio.create_task(refresh(contender, raw))
        try:
            await wait_for_locks(world, [pid])
            await holder.rollback()
            code, _ = await asyncio.wait_for(pending, 4)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
    assert code == 200
    assert len(await live_tokens(world)) == 1


async def test_failed_rotation_commit_rolls_back_parent_and_child(world, monkeypatch):
    raw, token_id = await issue(world)
    async with world.sessions() as db:
        async def fail_commit():
            await db.flush()
            raise RuntimeError("isolated commit failure before durability")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="isolated commit failure"):
            await AuthService(db, CacheService()).refresh(raw)
        await db.rollback()
    assert [row.id for row in await live_tokens(world)] == [token_id]
    async with world.sessions() as db:
        assert (await refresh(db, raw))[0] == 200
    assert len(await live_tokens(world)) == 1
