"""Atomic per-device admission for ten exact renewable direct peers.

Only authenticated signaling constructs bindings. A SET alone would bound each
peer's TTL but permit an unbounded fleet on one APK across backend workers.
The same Redis-clock ZSET admits, expires and releases exact nonces atomically.
"""
from __future__ import annotations

from typing import Any

from backend.websocket.direct_probe_protocol import SESSION_MS

SHARED_PEER_MIN_AGENT_CODE = 10269
MAX_DEVICE_PEERS = 10

_ACQUIRE = """
local clock = redis.call('TIME')
local now = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if redis.call('EXISTS', KEYS[1]) ~= 0 or redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then return 0 end
redis.call('SET', KEYS[1], ARGV[1], 'PX', ARGV[3])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[3]), ARGV[2])
redis.call('PEXPIRE', KEYS[2], ARGV[3])
return 1
"""
_RENEW = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] or redis.call('PTTL', KEYS[1]) <= 0 then return 0 end
local clock = redis.call('TIME')
local now = tonumber(clock[1])*1000 + math.floor(tonumber(clock[2])/1000)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now)
if not redis.call('ZSCORE', KEYS[2], ARGV[2]) then return 0 end
redis.call('PEXPIRE', KEYS[1], ARGV[3])
redis.call('ZADD', KEYS[2], now + tonumber(ARGV[3]), ARGV[2])
redis.call('PEXPIRE', KEYS[2], ARGV[3])
return 1
"""
_RELEASE = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('DEL', KEYS[1])
redis.call('ZREM', KEYS[2], ARGV[2])
if redis.call('ZCARD', KEYS[2]) == 0 then redis.call('DEL', KEYS[2]) end
return 1
"""


class SharedPeerLease:
    def __init__(self, redis: Any, namespace: str) -> None:
        self.redis, self.namespace = redis, namespace

    def key(self, device: str, session: str) -> str:
        return f"{self.namespace}:shared:{{{device}}}:peer:{session}"

    def index(self, device: str) -> str:
        return f"{self.namespace}:shared:{{{device}}}:sessions"

    async def acquire(self, binding: dict, encoded: str) -> bool:
        return bool(await self.redis.eval(_ACQUIRE, 2, self.key(binding["device"], binding["session"]),
            self.index(binding["device"]), encoded, binding["session"], SESSION_MS, MAX_DEVICE_PEERS))

    async def renew(self, binding: dict, encoded: str) -> bool:
        return bool(await self.redis.eval(_RENEW, 2, self.key(binding["device"], binding["session"]),
            self.index(binding["device"]), encoded, binding["session"], SESSION_MS))

    async def release(self, binding: dict, encoded: str) -> bool:
        return bool(await self.redis.eval(_RELEASE, 2, self.key(binding["device"], binding["session"]),
            self.index(binding["device"]), encoded, binding["session"]))
