"""Small cross-worker counters for active tabs; no identity or video is retained."""
from __future__ import annotations

import asyncio
import re

from redis.exceptions import RedisError

TTL_SECONDS = 45
MAX_VIEWERS = 128

TOUCH = """
local t=redis.call('TIME'); local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
redis.call('ZREMRANGEBYSCORE',KEYS[1],'-inf',now)
if ARGV[2]=='0' then redis.call('ZREM',KEYS[1],ARGV[1]); return 1 end
if not redis.call('ZSCORE',KEYS[1],ARGV[1]) and redis.call('ZCARD',KEYS[1])>=128 then return 0 end
redis.call('ZADD',KEYS[1],now+45000,ARGV[1]); redis.call('EXPIRE',KEYS[1],46); return 1
"""
COUNT = """
local t=redis.call('TIME'); local now=tonumber(t[1])*1000+math.floor(tonumber(t[2])/1000)
local out={}
for i,key in ipairs(KEYS) do out[i]=redis.call('ZCOUNT',key,'('..now,'+inf') end
return out
"""


class DeviceViewers:
    def __init__(self, redis):
        self.redis = redis

    @staticmethod
    def key(org: str, device: str, kind: str) -> str:
        if kind not in {"card", "stream"} or not all(re.fullmatch(r"[0-9a-f-]{36}", v) for v in (org, device)):
            raise ValueError("invalid viewer scope")
        return f"sphere:device-viewers:v1:{{{org}:{device}}}:{kind}"

    async def touch(self, org: str, device: str, kind: str, session: str, active: bool = True) -> bool:
        if not re.fullmatch(r"[0-9a-f]{16,32}", session):
            raise ValueError("invalid viewer session")
        if self.redis is None:
            return False
        try:
            async with asyncio.timeout(0.5):
                return bool(await self.redis.eval(TOUCH, 1, self.key(org, device, kind), session, "1" if active else "0"))
        except (RedisError, TimeoutError):
            return False

    async def counts(self, org: str, devices: list[str]) -> dict[str, dict[str, int]] | None:
        if len(devices) > 300 or len(devices) != len(set(devices)):
            raise ValueError("viewer page budget exceeded")
        if not devices:
            return {}
        if self.redis is None:
            return None
        keys = [self.key(org, device, kind) for device in devices for kind in ("card", "stream")]
        try:
            async with asyncio.timeout(0.5):
                # Redis TIME avoids mixing application-worker wall clocks. One
                # round trip covers the authorized, bounded catalogue page.
                values = await self.redis.eval(COUNT, len(keys), *keys)
            if len(values) != len(keys) or any(type(v) is not int or v not in range(MAX_VIEWERS + 1) for v in values):
                return None
            return {device: {"card": values[i * 2], "stream": values[i * 2 + 1]} for i, device in enumerate(devices)}
        except (RedisError, TimeoutError):
            return None
