"""Bounded global discovery; actual task reads/writes always run under tenant RLS."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from backend.database.tenant import bind_tenant_context
from backend.services.task_service import TaskService

logger = structlog.get_logger()
PAGE_SIZE = 64
CONCURRENCY = 8
DEVICE_TIMEOUT_SECONDS = 15
DISCOVERY_TIMEOUT_SECONDS = 5


class _PresenceSnapshot:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    async def bulk_get_status(self, ids: list[str]) -> dict[str, Any]:
        return {value: self.values.get(value) for value in ids}


class TaskDispatchWorker:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions
        # Separate rotating cursors keep offline devices from hiding later work.
        # Restart may revisit a page; SQL assignment/cancellation leases fence it.
        self._cursors: dict[str, uuid.UUID | None] = {"assign": None, "cancel": None}

    async def _discover(self, kind: str) -> list[tuple[uuid.UUID, uuid.UUID]]:
        async with asyncio.timeout(DISCOVERY_TIMEOUT_SECONDS), self.sessions() as db:
            query = text("SELECT * FROM sphere_auth.task_dispatch_work(:kind, :after)")
            rows = list((await db.execute(query, {"kind": kind, "after": self._cursors[kind]})).all())
            if not rows and self._cursors[kind] is not None:
                rows = list((await db.execute(query, {"kind": kind, "after": None})).all())
        return [(row[0], row[1]) for row in rows]

    def _advance(self, kind: str, candidates: list[tuple[uuid.UUID, uuid.UUID]]) -> None:
        self._cursors[kind] = candidates[-1][0] if len(candidates) == PAGE_SIZE else None

    async def poll(self, *, status_cache: Any, publisher: Any) -> None:
        if publisher is None:
            return
        # Cancellation does not depend on presence: a stale cache must not stop it.
        cancellations = await self._discover("cancel")
        await self._deliver(cancellations, "cancel", None, publisher)
        self._advance("cancel", cancellations)
        if status_cache is None:
            return
        candidates = await self._discover("assign")
        if not candidates:
            self._advance("assign", candidates)
            return
        # No SQL session/connection is held during Redis or transport I/O.
        async with asyncio.timeout(2):
            presence = await status_cache.bulk_get_status([str(device) for device, _ in candidates])
        online = [(device, tenant) for device, tenant in candidates
                  if (value := presence.get(str(device))) is not None and value.status in ("online", "busy")]
        await self._deliver(online, "assign", _PresenceSnapshot(presence), publisher)
        self._advance("assign", candidates)

    async def _deliver(
        self, candidates: list[tuple[uuid.UUID, uuid.UUID]], kind: str, cache: Any, publisher: Any,
    ) -> None:
        async def one(device: uuid.UUID, tenant: uuid.UUID) -> None:
            try:
                async with asyncio.timeout(DEVICE_TIMEOUT_SECONDS):
                    async with self.sessions() as db:
                        await bind_tenant_context(db, str(tenant))
                        service = TaskService(db, status_cache=cache, publisher=publisher)
                        if kind == "cancel":
                            await service.dispatch_pending_cancellations(org_id=tenant, device_id=device)
                        else:
                            await service.dispatch_pending_tasks(
                                org_id=tenant, device_id=device, include_cancellations=False,
                            )
            except Exception as exc:
                # An uncertain commit/send remains durable intent. Do not infer
                # completion or immediately replay a potentially delivered effect.
                logger.warning("task_dispatcher.device_retry_pending", device_id=str(device),
                               work_kind=kind, error_type=type(exc).__name__)

        for offset in range(0, len(candidates), CONCURRENCY):
            await asyncio.gather(*(one(*item) for item in candidates[offset:offset + CONCURRENCY]))
