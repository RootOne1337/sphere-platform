# backend/services/vpn/ip_pool.py  TZ-06 SPLIT-2
from __future__ import annotations

import ipaddress
import time
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.vpn_peer import VPNPeer, VPNPeerStatus


class IPPoolAllocator:
    """
    PostgreSQL reservations are authoritative for VPN lifecycle operations.
    Legacy Redis free-list methods remain for cache diagnosis only.
    - ZADD NX: idempotent initialization (won't re-add existing IPs)
    - ZPOPMIN: atomic O(1) allocation
    - ZADD: return IPs to pool
    Supports 10.100.0.0/16 = 65534 addresses by default.
    """

    POOL_KEY = "vpn:ip_pool:{org_id}"

    def __init__(self, redis, subnet: str = "10.100.0.0/16") -> None:
        self.redis = redis
        self.network = ipaddress.ip_network(subnet, strict=False)

    async def reserve_ip(self, db: AsyncSession) -> str | None:
        """Choose an address inside the caller's short intent transaction.

        The global unique index protects held addresses, including unknown
        outcomes. The transaction lock avoids selecting the same candidate in
        concurrent PostgreSQL requests, including different organizations.
        """
        if self.network.version != 4 or self.network.num_addresses > 65536:
            raise ValueError("VPN allocation requires an IPv4 subnet of /16 or smaller")
        if db.get_bind().dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(736743829104)"))
        held = await self._held_addresses(db)
        return next((str(ip) for ip in self.network.hosts() if str(ip) not in held), None)

    async def _held_addresses(self, db: AsyncSession) -> set[str]:
        addresses = await db.scalars(select(VPNPeer.tunnel_ip).where(
            VPNPeer.status != VPNPeerStatus.FREE, VPNPeer.tunnel_ip.isnot(None),
        ))
        return {str(ipaddress.ip_address(ip)) for ip in addresses}

    async def capacity(self, db: AsyncSession) -> tuple[int, int]:
        """Global configured capacity/free count; independent of Redis contents."""
        if self.network.version != 4 or self.network.num_addresses > 65536:
            raise ValueError("VPN allocation requires an IPv4 subnet of /16 or smaller")
        held = await self._held_addresses(db)
        total = self.network.num_addresses - (2 if self.network.prefixlen < 31 else 0)
        occupied = sum(ipaddress.ip_address(ip) in self.network for ip in held)
        return total, max(0, total - occupied)

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
