# backend/services/group_service.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-2. Device Group & Tags management.
from __future__ import annotations

import hashlib
import uuid
from asyncio import sleep
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import case, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.device import Device, DeviceStatus, device_group_members
from backend.models.device_group import DeviceGroup
from backend.models.schedule import Schedule
from backend.schemas.groups import (
    CreateGroupRequest,
    GroupMembershipOperation,
    GroupMembershipResult,
    GroupResponse,
    UpdateGroupRequest,
)

_MEMBERSHIP_LOCK_WAIT_SECONDS = 1.0
_MEMBERSHIP_LOCK_RETRY_SECONDS = 0.025


class GroupService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Internal ─────────────────────────────────────────────────────────────

    def _to_response(
        self,
        group: DeviceGroup,
        total: int = 0,
        online: int = 0,
    ) -> GroupResponse:
        return GroupResponse(
            id=group.id,
            name=group.name,
            description=group.description,
            color=group.color,
            parent_group_id=group.parent_group_id,
            org_id=group.org_id,
            total_devices=total,
            online_devices=online,
        )

    async def _get_group(
        self, group_id: uuid.UUID, org_id: uuid.UUID, *, for_update: bool = False,
    ) -> DeviceGroup:
        query = select(DeviceGroup).where(DeviceGroup.id == group_id, DeviceGroup.org_id == org_id)
        if for_update:
            query = query.with_for_update()
        group = await self.db.scalar(query.execution_options(populate_existing=True))
        if not group:
            raise HTTPException(status_code=404, detail="Group not found")
        return group

    async def _fence_writes(self, org_id: uuid.UUID, *, wait: bool = False) -> None:
        """Serialize group writes through commit without device I/O.

        All API writers use this same transaction-scoped key. SQLite is only the
        unit-test adapter; concurrency acceptance requires actual PostgreSQL.
        """
        if self.db.get_bind().dialect.name != "postgresql":
            return
        key = int.from_bytes(hashlib.sha256(
            f"sphere:group-writes:v1:{org_id}".encode()
        ).digest()[:8], "big", signed=True)
        statement = text("SELECT pg_try_advisory_xact_lock(:key)")
        deadline = monotonic() + _MEMBERSHIP_LOCK_WAIT_SECONDS
        while not await self.db.scalar(statement, {"key": key}):
            remaining = deadline - monotonic()
            if not wait or remaining <= 0:
                raise HTTPException(status_code=409, detail="Groups are being modified; refresh and retry")
            await sleep(min(remaining, _MEMBERSHIP_LOCK_RETRY_SECONDS))

    async def _validate_parent(
        self, org_id: uuid.UUID, parent_id: uuid.UUID | None, group_id: uuid.UUID | None = None,
    ) -> None:
        if parent_id is None:
            return  # Explicit clearing also repairs a pre-existing corrupt chain.
        if parent_id == group_id:
            raise HTTPException(status_code=400, detail="Group cannot be its own parent")
        # Scalar projection avoids stale ORM ancestry and one query per ancestor.
        rows = (await self.db.execute(select(DeviceGroup.id, DeviceGroup.parent_group_id)
                                      .where(DeviceGroup.org_id == org_id))).all()
        parents: dict[uuid.UUID, uuid.UUID | None] = {row.id: row.parent_group_id for row in rows}
        if parent_id not in parents:
            raise HTTPException(status_code=404, detail="Parent group not found")
        visited: set[uuid.UUID] = set()
        current: uuid.UUID | None = parent_id
        while current is not None:
            if current == group_id or current in visited or current not in parents:
                raise HTTPException(status_code=400, detail="Parent would create or inherit an invalid group hierarchy")
            visited.add(current)
            current = parents[current]

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_group(
        self, org_id: uuid.UUID, data: CreateGroupRequest
    ) -> GroupResponse:
        await self._fence_writes(org_id)
        await self._validate_parent(org_id, data.parent_group_id)
        # Check name uniqueness within org
        dup = (
            await self.db.execute(
                select(DeviceGroup).where(
                    DeviceGroup.org_id == org_id, DeviceGroup.name == data.name
                )
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Group '{data.name}' already exists in this organisation",
            )

        group = DeviceGroup(
            org_id=org_id,
            name=data.name,
            description=data.description,
            color=data.color,
            parent_group_id=data.parent_group_id,
        )
        self.db.add(group)
        await self.db.flush()
        return self._to_response(group)

    # ── List (with stats) ────────────────────────────────────────────────────

    async def get_group_stats(self, org_id: uuid.UUID) -> list[GroupResponse]:
        """Groups with online/total device counters via a single aggregate query."""
        stmt = (
            select(
                DeviceGroup.id,
                DeviceGroup.name,
                DeviceGroup.color,
                DeviceGroup.description,
                DeviceGroup.parent_group_id,
                func.count(Device.id).label("total"),
                func.sum(
                    case((Device.last_status == DeviceStatus.ONLINE, 1), else_=0)
                ).label("online_count"),
            )
            .outerjoin(
                device_group_members,
                device_group_members.c.group_id == DeviceGroup.id,
            )
            .outerjoin(Device, Device.id == device_group_members.c.device_id)
            .where(DeviceGroup.org_id == org_id)
            .group_by(
                DeviceGroup.id,
                DeviceGroup.name,
                DeviceGroup.color,
                DeviceGroup.description,
                DeviceGroup.parent_group_id,
            )
            .order_by(DeviceGroup.name)
        )
        rows = (await self.db.execute(stmt)).all()

        result: list[GroupResponse] = []
        for row in rows:
            result.append(
                GroupResponse(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    color=row.color,
                    parent_group_id=row.parent_group_id,
                    org_id=org_id,
                    total_devices=row.total or 0,
                    online_devices=row.online_count or 0,
                )
            )
        return result

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_group(
        self,
        group_id: uuid.UUID,
        org_id: uuid.UUID,
        data: UpdateGroupRequest,
    ) -> GroupResponse:
        await self._get_group(group_id, org_id)  # Do not expose contention for a foreign target.
        await self._fence_writes(org_id)
        group = await self._get_group(group_id, org_id)
        if "parent_group_id" in data.model_fields_set:
            await self._validate_parent(org_id, data.parent_group_id, group_id)

        if data.name is not None and data.name != group.name:
            dup = (
                await self.db.execute(
                    select(DeviceGroup).where(
                        DeviceGroup.org_id == org_id,
                        DeviceGroup.name == data.name,
                        DeviceGroup.id != group_id,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Group '{data.name}' already exists in this organisation",
                )
            group.name = data.name

        if "description" in data.model_fields_set:
            group.description = data.description
        if "color" in data.model_fields_set:
            group.color = data.color
        if "parent_group_id" in data.model_fields_set:
            group.parent_group_id = data.parent_group_id

        await self.db.flush()
        return self._to_response(group)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_group(self, group_id: uuid.UUID, org_id: uuid.UUID) -> None:
        await self._get_group(group_id, org_id)
        await self._fence_writes(org_id)
        # The group row lock also serializes PostgreSQL's schedule FK check.
        group = await self._get_group(group_id, org_id, for_update=True)
        if await self.db.scalar(select(Schedule.id).where(Schedule.group_id == group_id).limit(1)):
            raise HTTPException(status_code=409, detail="Group is used by schedules")
        await self.db.delete(group)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            cause = getattr(exc.orig, "__cause__", None)
            if getattr(cause, "constraint_name", None) != "schedules_group_id_fkey":
                raise
            raise HTTPException(status_code=409, detail="Group is used by schedules") from exc

    # ── Device memberships ──────────────────────────────────────────────────

    async def change_device_memberships(
        self,
        device_ids: list[uuid.UUID],
        group_id: uuid.UUID | None,
        org_id: uuid.UUID,
        operation: GroupMembershipOperation,
        *,
        active_only: bool = True,
    ) -> list[GroupMembershipResult]:
        if group_id is not None:
            await self._get_group(group_id, org_id)
        await self._fence_writes(org_id, wait=True)
        target = await self._get_group(group_id, org_id) if group_id is not None else None
        stmt = (
            select(Device)
            .options(selectinload(Device.groups))
            .where(Device.id.in_(device_ids), Device.org_id == org_id)
            .order_by(Device.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if active_only:
            stmt = stmt.where(Device.is_active.is_(True))
        devices = {device.id: device for device in (await self.db.scalars(stmt)).all()}
        results = []
        for device_id in device_ids:
            device = devices.get(device_id)
            if device is None:
                results.append(GroupMembershipResult(device_id=device_id, outcome="device_not_found"))
                continue
            before = {group.id for group in device.groups}
            if operation == "add" and target is not None and target.id not in before:
                device.groups.append(target)
            elif operation == "remove" and target is not None and target.id in before:
                device.groups = [group for group in device.groups if group.id != target.id]
            elif operation == "replace":
                device.groups = [target] if target is not None else []
            changed = before != {group.id for group in device.groups}
            results.append(GroupMembershipResult(device_id=device_id, outcome="changed" if changed else "unchanged"))

        await self.db.flush()
        return results

    async def move_devices_to_group(
        self,
        device_ids: list[str],
        group_id: uuid.UUID | None,
        org_id: uuid.UUID,
    ) -> int:
        """Legacy explicit replacement. Count existing targets, including no-ops."""
        uuids: dict[uuid.UUID, None] = {}
        for device_id in device_ids:
            try:
                uuids[uuid.UUID(device_id)] = None
            except ValueError:
                continue
        results = await self.change_device_memberships(list(uuids), group_id, org_id, "replace", active_only=False)
        return sum(result.outcome != "device_not_found" for result in results)

    # ── Tags ─────────────────────────────────────────────────────────────────

    async def set_device_tags(
        self, device_id: str, tags: list[str], org_id: uuid.UUID
    ) -> None:
        """Replace device tag list (idempotent)."""
        if len(tags) > 20:
            raise HTTPException(status_code=400, detail="Maximum 20 tags per device")

        try:
            dev_uuid = uuid.UUID(device_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Device not found")

        device = (
            await self.db.execute(
                select(Device).where(
                    Device.id == dev_uuid, Device.org_id == org_id
                )
            )
        ).scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")

        device.tags = tags
        await self.db.flush()

    async def list_all_tags(self, org_id: uuid.UUID) -> list[str]:
        """All unique tags in the org (for autocompletion). Python-side aggregation for SQLite compat."""
        stmt = select(Device.tags).where(
            Device.org_id == org_id, Device.is_active.is_(True)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        all_tags: set[str] = set()
        for tags in rows:
            if tags:
                all_tags.update(tags)
        return sorted(all_tags)
