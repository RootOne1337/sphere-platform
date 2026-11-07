# backend/services/bulk_service.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-4. Bulk operations on devices with per-device result reporting.
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.bulk import (
    BulkActionItemResult,
    BulkActionRequest,
    BulkActionResponse,
    BulkActionType,
)
from backend.services.cache_service import CacheService
from backend.services.device_service import DeviceService
from backend.services.group_service import GroupService

logger = logging.getLogger(__name__)


class BulkActionService:
    """
    Выполняет атомарные массовые операции с устройствами.

    Устройства не из своей org → success=False, error="Device not found" (не 403).
    Один failed device не отменяет остальные (asyncio.gather isolates errors).
    """

    CONCURRENCY = 50  # max parallel operations

    def __init__(
        self,
        db: AsyncSession,
        device_svc: DeviceService,
        group_svc: GroupService,
        cache: CacheService,
    ) -> None:
        self.db = db
        self.device_svc = device_svc
        self.group_svc = group_svc
        self.cache = cache

    async def execute(
        self, request: BulkActionRequest, org_id: uuid.UUID
    ) -> BulkActionResponse:
        owned_set = set(await self.device_svc.filter_owned(request.device_ids, org_id))

        # Two semaphores:
        # - concurrency_sem: overall max parallel operations (50)
        # - db_sem: serialize DB-modifying operations (SET_GROUP, SET_TAGS)
        #   because shared SQLAlchemy AsyncSession cannot handle concurrent flush.
        concurrency_sem = asyncio.Semaphore(self.CONCURRENCY)
        db_sem = asyncio.Semaphore(1)

        _DB_ACTIONS = {BulkActionType.SET_GROUP, BulkActionType.SET_TAGS}

        async def execute_one(device_id: str) -> BulkActionItemResult:
            if device_id not in owned_set:
                return BulkActionItemResult(
                    device_id=device_id,
                    success=False,
                    error="Device not found",
                )
            async with concurrency_sem:
                try:
                    if request.action in _DB_ACTIONS:
                        async with db_sem:
                            await self._dispatch(
                                request.action, device_id, request.params, org_id
                            )
                    else:
                        await self._dispatch(
                            request.action, device_id, request.params, org_id
                        )
                    return BulkActionItemResult(device_id=device_id, success=True)
                except Exception as exc:
                    logger.warning(
                        "Bulk action %s failed for %s: %s",
                        request.action,
                        device_id,
                        exc,
                    )
                    return BulkActionItemResult(
                        device_id=device_id,
                        success=False,
                        error=str(exc)[:200],
                    )

        tasks = [execute_one(did) for did in request.device_ids]
        results: list[BulkActionItemResult] = list(await asyncio.gather(*tasks))

        succeeded = sum(1 for r in results if r.success)
        return BulkActionResponse(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            results=results,
        )

    async def _dispatch(
        self,
        action: BulkActionType,
        device_id: str,
        params: dict,
        org_id: uuid.UUID,
    ) -> None:
        match action:
            case BulkActionType.REBOOT:
                await self._reboot_device(device_id, org_id)
            case BulkActionType.CONNECT_ADB:
                await self._connect_adb(device_id, org_id)
            case BulkActionType.DISCONNECT_ADB:
                await self._disconnect_adb(device_id, org_id)
            case BulkActionType.SET_GROUP:
                group_id = uuid.UUID(params["group_id"])
                await self.group_svc.move_single(str(device_id), group_id, org_id)
            case BulkActionType.SET_TAGS:
                tags = params.get("tags", [])
                await self.group_svc.set_device_tags(str(device_id), tags, org_id)
            case BulkActionType.SEND_COMMAND:
                await self._send_command(device_id, params, org_id)

    # ── Action implementations ──────────────────────────────────────────────

    async def _reboot_device(self, device_id: str, org_id: uuid.UUID) -> None:
        """Issue reboot over the live Android command channel and require an agent receipt."""
        from backend.websocket.pubsub_router import get_pubsub_publisher

        publisher = get_pubsub_publisher()
        if publisher is None:
            raise RuntimeError("Device command transport is unavailable")

        try:
            result = await publisher.send_command_wait_result(
                device_id,
                {
                    "type": "REBOOT",
                    "command_id": f"interactive_{uuid.uuid4()}",
                    "payload": {},
                    "signed_at": int(time.time()),
                    "ttl_seconds": 15,
                },
                timeout=10.0,
                live_only=True,
                accept_progress=True,
            )
        except HTTPException as exc:
            if exc.status_code == 504:
                raise RuntimeError("Reboot outcome unknown: device did not acknowledge") from exc
            if exc.status_code == 503:
                raise RuntimeError("Device is offline or command transport is unavailable") from exc
            raise RuntimeError("Device reboot command failed") from exc

        if result.get("status") == "failed":
            raise RuntimeError("Agent rejected reboot command")
        if result.get("status") not in {"completed", "received", "running"}:
            raise RuntimeError("Agent returned an invalid reboot receipt")

    async def _connect_adb(self, device_id: str, org_id: uuid.UUID) -> None:
        """TZ-03 stub: write adb_connect command to Redis."""
        key = f"cmd:adb_connect:{device_id}"
        await self.cache.set(
            key,
            f'{{"type":"adb_connect","device_id":"{device_id}"}}',
            ttl=30,
        )

    async def _disconnect_adb(self, device_id: str, org_id: uuid.UUID) -> None:
        """TZ-03 stub: write adb_disconnect command to Redis."""
        key = f"cmd:adb_disconnect:{device_id}"
        await self.cache.set(
            key,
            f'{{"type":"adb_disconnect","device_id":"{device_id}"}}',
            ttl=30,
        )

    async def _send_command(
        self, device_id: str, params: dict, org_id: uuid.UUID
    ) -> None:
        """TZ-03 stub: generic command dispatch."""
        import json

        command_type = params["command_type"]
        key = f"cmd:{command_type}:{device_id}"
        await self.cache.set(key, json.dumps({"type": command_type, "device_id": device_id, **params}), ttl=30)
