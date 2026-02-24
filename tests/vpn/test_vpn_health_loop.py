# tests/vpn/test_vpn_health_loop.py
"""
Unit tests for the vpn_health_loop background task.

Enterprise rationale
--------------------
- Distributed Redis lock (SET NX EX) ensures only ONE backend instance runs
  health checks per 60-second cycle in a multi-replica deployment.  Without
  this test, a bug (e.g. wrong lock key or missing NX flag) would cause every
  replica to run full health checks simultaneously → WireGuard server overload.

- Lock released in `finally` block: even if _run_health_checks raises, the
  lock must be freed so the next cycle can run.  A lock leak = health checks
  stop running silently for up to HEALTH_LOCK_TTL=90s.

- loop continues after a non-fatal exception in _run_health_checks
  (silent failure risk: exception in health check must not crash the loop).

- asyncio.CancelledError terminates the loop cleanly (graceful shutdown).

- redis=None branch: loop keeps sleeping without crashing (Redis not yet ready
  on startup, e.g. first few seconds after container start).
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fakeredis.aioredis import FakeRedis

from backend.tasks.vpn_health import HEALTH_LOCK_KEY, vpn_health_loop


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sleep_mock(cancel_on_call: int = 1):
    """
    Returns an AsyncMock for asyncio.sleep that raises CancelledError
    on the Nth call, stopping the infinite loop.
    """
    call_count = 0

    async def _sleep(_t):
        nonlocal call_count
        call_count += 1
        if call_count >= cancel_on_call:
            raise asyncio.CancelledError()

    return _sleep


# ===========================================================================
# Distributed lock
# ===========================================================================

class TestDistributedLock:
    async def test_lock_acquired_and_health_checks_run(self):
        """When no other instance holds the lock, health checks are called."""
        fake_redis = FakeRedis(decode_responses=True)
        health_calls = 0

        async def _mock_health():
            nonlocal health_calls
            health_calls += 1
            raise asyncio.CancelledError()  # stop after first successful run

        with patch("backend.tasks.vpn_health._run_health_checks", _mock_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()

        assert health_calls == 1

    async def test_lock_not_acquired_skips_health_checks(self):
        """When another instance already holds the lock, skip this cycle."""
        fake_redis = FakeRedis(decode_responses=True)
        # Pre-occupy the lock as if another replica holds it
        await fake_redis.set(HEALTH_LOCK_KEY, "other-replica-uuid", nx=True, ex=90)

        health_calls = 0

        async def _mock_health():
            nonlocal health_calls
            health_calls += 1

        # Sleep mock: cancel on second call (first call is the "skip, sleep 60" path)
        with patch("backend.tasks.vpn_health._run_health_checks", _mock_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", side_effect=_make_sleep_mock(cancel_on_call=1)):
                    await vpn_health_loop()

        assert health_calls == 0, "Health checks must not run when lock is held by another instance"

    async def test_lock_released_after_successful_health_check(self):
        """Lock must be deleted after health checks complete (no lock leak)."""
        fake_redis = FakeRedis(decode_responses=True)

        async def _mock_health():
            raise asyncio.CancelledError()  # stop loop

        with patch("backend.tasks.vpn_health._run_health_checks", _mock_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()

        remaining = await fake_redis.get(HEALTH_LOCK_KEY)
        assert remaining is None, (
            "Lock must be released after health check completes — "
            "a leaked lock blocks all future cycles until TTL expires"
        )

    async def test_lock_released_even_when_health_check_raises_exception(self):
        """Lock must be freed in finally block even if health check crashes."""
        fake_redis = FakeRedis(decode_responses=True)
        exception_raised = False
        call_count = 0

        async def _health_sequence():
            """First call: crash. Second call: stop loop cleanly."""
            nonlocal exception_raised, call_count
            call_count += 1
            if call_count == 1:
                exception_raised = True
                raise RuntimeError("WireGuard API timeout")
            # Second call terminates loop via the except-CancelledError-break path
            raise asyncio.CancelledError()

        with patch("backend.tasks.vpn_health._run_health_checks", _health_sequence):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()  # exits cleanly on second iteration

        assert exception_raised, "Health check did not raise the expected exception"
        remaining = await fake_redis.get(HEALTH_LOCK_KEY)
        assert remaining is None, "Lock must be released even after an exception"

    async def test_lock_not_released_when_held_by_different_instance(self):
        """
        Only the instance that acquired the lock should delete it.
        If the lock value changed between acquire and release (TTL expired and
        another replica acquired it), we must NOT delete it.
        """
        fake_redis = FakeRedis(decode_responses=True)

        original_set = fake_redis.set
        set_calls = 0

        async def _patched_set(key, value, *args, **kwargs):
            nonlocal set_calls
            set_calls += 1
            result = await original_set(key, value, *args, **kwargs)
            if set_calls == 1:
                # After our acquire, overwrite the lock value to simulate
                # TTL expiry + another replica acquiring it
                await original_set(HEALTH_LOCK_KEY, "other-replica-new-uuid")
            return result

        fake_redis.set = _patched_set

        async def _mock_health():
            raise asyncio.CancelledError()

        with patch("backend.tasks.vpn_health._run_health_checks", _mock_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()

        # The OTHER replica's lock value must still be there
        remaining = await fake_redis.get(HEALTH_LOCK_KEY)
        assert remaining == "other-replica-new-uuid", (
            "Must not delete a lock that was acquired by a different instance"
        )


# ===========================================================================
# Loop resilience
# ===========================================================================

class TestLoopResilience:
    async def test_exception_in_health_check_does_not_crash_loop(self):
        """
        Non-CancelledError exceptions are logged and the loop continues.
        This is the "silent failure" guard: a VPN API error must not stop
        health monitoring for all future cycles.
        """
        fake_redis = FakeRedis(decode_responses=True)
        call_count = 0

        async def _flaky_health():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("WireGuard API timeout")
            # Second call: stop cleanly
            raise asyncio.CancelledError()

        with patch("backend.tasks.vpn_health._run_health_checks", _flaky_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()

        assert call_count == 2, "Loop must continue after a non-fatal exception"

    async def test_redis_none_does_not_crash_loop(self):
        """redis=None (startup race) → loop sleeps, never crashes."""
        sleep_calls = 0

        async def _mock_sleep(_t):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 1:
                raise asyncio.CancelledError()

        health_mock = AsyncMock()
        with patch("backend.tasks.vpn_health._run_health_checks", health_mock):
            with patch("backend.database.redis_client.redis", None):
                with patch("asyncio.sleep", side_effect=_mock_sleep):
                    await vpn_health_loop()

        health_mock.assert_not_called()
        assert sleep_calls >= 1

    async def test_cancelled_error_exits_cleanly(self):
        """asyncio.CancelledError inside the try block is caught via break — no exception propagates."""
        fake_redis = FakeRedis(decode_responses=True)

        async def _cancel_from_inside():
            """Raise CancelledError from within _run_health_checks so it is caught
            by `except asyncio.CancelledError: break` in the outer try block."""
            raise asyncio.CancelledError()

        with patch("backend.tasks.vpn_health._run_health_checks", _cancel_from_inside):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    # Must return normally (not raise) — graceful shutdown path
                    await vpn_health_loop()

    async def test_every_cycle_uses_unique_lock_value(self):
        """Each cycle generates a fresh UUID as lock value → no replay attacks."""
        fake_redis = FakeRedis(decode_responses=True)
        lock_values: list[str] = []
        original_set = fake_redis.set

        async def _tracking_set(key, value, *args, **kwargs):
            if key == HEALTH_LOCK_KEY:
                lock_values.append(value)
            return await original_set(key, value, *args, **kwargs)

        fake_redis.set = _tracking_set

        call_count = 0

        async def _mock_health():
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError()

        with patch("backend.tasks.vpn_health._run_health_checks", _mock_health):
            with patch("backend.database.redis_client.redis", fake_redis):
                with patch("asyncio.sleep", AsyncMock()):
                    await vpn_health_loop()

        assert len(lock_values) >= 2
        assert len(set(lock_values)) == len(lock_values), (
            "Each cycle must use a unique lock value — reusing the same value "
            "would prevent the 'lock held by different instance' safety check"
        )
