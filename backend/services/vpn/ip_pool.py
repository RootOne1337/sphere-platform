# backend/services/vpn/ip_pool.py  TZ-06 SPLIT-2
from __future__ import annotations

import ipaddress
import time
from typing import Optional


class IPPoolAllocator:
    """
    Manages a pool of VPN IP addresses stored in a Redis Sorted Set.
    - ZADD NX: idempotent initialization (won't re-add existing IPs)
    - ZPOPMIN: atomic O(1) allocation
    - ZADD: return IPs to pool
    Supports 10.100.0.0/16 = 65534 addresses by default.
    """

    POOL_KEY = "vpn:ip_pool:{org_id}"

    def __init__(self, redis, subnet: str = "10.100.0.0/16") -> None:
        self.redis = redis
        self.network = ipaddress.ip_network(subnet, strict=False)

    async def initialize_pool(self, org_id: str, count: int = 1000) -> int:
        """
        Pre-populate the pool with the first `count` host IPs from the subnet.
        Uses ZADD NX so existing IPs are never overwritten (idempotent).
        Returns the number of newly added IPs.
        """
        pool_key = self.POOL_KEY.format(org_id=org_id)
        ips = [str(host) for host in list(self.network.hosts())[:count]]
        added = 0
        async with self.redis.pipeline() as pipe:
            for i, ip in enumerate(ips):
                # NX = only add if member does not yet exist
                pipe.zadd(pool_key, {ip: i}, nx=True)
            results = await pipe.execute()
        added = sum(1 for r in results if r)
        return added

    async def allocate_ip(self, org_id: str) -> Optional[str]:
        """Atomically pop the lowest-score (next free) IP from the pool."""
        pool_key = self.POOL_KEY.format(org_id=org_id)
        result = await self.redis.zpopmin(pool_key, 1)
        if not result:
            return None
        ip = result[0][0]
        return ip.decode() if isinstance(ip, bytes) else ip

    async def release_ip(self, org_id: str, ip: str) -> None:
        """Return IP to pool with current timestamp as score."""
        pool_key = self.POOL_KEY.format(org_id=org_id)
        await self.redis.zadd(pool_key, {ip: time.time()})

    async def pool_size(self, org_id: str) -> int:
        """Number of free IPs available for this org."""
        return await self.redis.zcard(self.POOL_KEY.format(org_id=org_id))

    async def is_low(self, org_id: str, threshold: int = 10) -> bool:
        """Returns True when available IPs drop below `threshold`."""
        size = await self.pool_size(org_id)
        return size < threshold
