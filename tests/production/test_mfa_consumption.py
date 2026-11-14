"""MFA challenges must be consumed exactly once before issuing SQL credentials."""

import asyncio
import json
import uuid

import pyotp
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select

from backend.core.exceptions import InvalidCredentialsError, InvalidTokenError
from backend.models.refresh_token import RefreshToken
from backend.models.user import User
from backend.services.auth_service import AuthService
from backend.services.cache_service import CacheService


async def challenge(world):
    secret = pyotp.random_base32()
    async with world.sessions() as db:
        user = await db.get(User, world.users["org_admin"].id)
        user.mfa_enabled = True
        user.mfa_secret = secret
        await db.commit()
    state = uuid.uuid4().hex
    await CacheService().set(f"mfa:state:v2:{state}", json.dumps({"user_id": str(user.id), "org_id": str(user.org_id)}), ttl=300)
    return state, pyotp.TOTP(secret).now()


async def issued_count(world):
    async with world.sessions() as db:
        return await db.scalar(select(func.count()).select_from(RefreshToken).where(
            RefreshToken.user_id == world.users["org_admin"].id,
        ))


async def complete(db, cache, state, code):
    try:
        await AuthService(db, cache).complete_mfa_login(state, code)
        return 200
    except InvalidTokenError:
        await db.rollback()
        return 401


async def test_concurrent_valid_mfa_submissions_issue_one_session(world):
    state, code = await challenge(world)
    both_read = asyncio.Event()
    reads = 0

    class OverlapCache(CacheService):
        async def get(self, key):
            nonlocal reads
            value = await super().get(key)
            reads += 1
            if reads == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), 3)
            return value

    cache = OverlapCache()
    async with world.sessions() as first, world.sessions() as second:
        results = await asyncio.wait_for(asyncio.gather(
            complete(first, cache, state, code), complete(second, cache, state, code),
        ), 4)
    assert sorted(results) == [200, 401]
    assert await issued_count(world) == 1
    assert await world.redis.get(f"mfa:state:v2:{state}") is None


async def test_mfa_state_expiring_after_read_cannot_issue_tokens(world):
    state, code = await challenge(world)

    class ExpiringCache(CacheService):
        async def get(self, key):
            value = await super().get(key)
            await world.redis.pexpire(key, 1)

            async def expire():
                while await world.redis.exists(key):
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(expire(), 1)
            return value

    async with world.sessions() as db:
        assert await complete(db, ExpiringCache(), state, code) == 401
    assert await issued_count(world) == 0


async def test_invalid_totp_does_not_consume_valid_challenge(world):
    state, code = await challenge(world)
    async with world.sessions() as db:
        with pytest.raises(InvalidCredentialsError):
            await AuthService(db, CacheService()).complete_mfa_login(state, "not-a-code")
        await db.rollback()
    assert await issued_count(world) == 0
    async with world.sessions() as db:
        assert await complete(db, CacheService(), state, code) == 200
    assert await issued_count(world) == 1


async def test_redis_failure_during_consumption_does_not_issue_tokens(world):
    state, code = await challenge(world)

    class FailedConsume(CacheService):
        async def delete(self, key):
            # Unknown Redis outcome: the write happened, its response was lost.
            await super().delete(key)
            raise RedisConnectionError("isolated lost consumption response")

    async with world.sessions() as db:
        with pytest.raises(RedisConnectionError, match="isolated lost consumption"):
            await AuthService(db, FailedConsume()).complete_mfa_login(state, code)
        await db.rollback()
    assert await issued_count(world) == 0
    async with world.sessions() as db:
        assert await complete(db, CacheService(), state, code) == 401


async def test_sql_commit_failure_after_consumption_requires_a_new_challenge(world, monkeypatch):
    state, code = await challenge(world)
    async with world.sessions() as db:
        async def fail_commit():
            await db.flush()
            raise RuntimeError("isolated SQL commit failure")
        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="isolated SQL commit failure"):
            await AuthService(db, CacheService()).complete_mfa_login(state, code)
        await db.rollback()
    assert await issued_count(world) == 0
    async with world.sessions() as db:
        assert await complete(db, CacheService(), state, code) == 401
