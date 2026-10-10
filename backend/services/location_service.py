# backend/services/location_service.py
# ВЛАДЕЛЕЦ: TZ-02. CRUD + управление привязкой устройств к локациям.
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.device import Device, DeviceStatus
from backend.models.location import Location, device_location_members
from backend.schemas.locations import (
    CreateLocationRequest,
    LocationResponse,
    UpdateLocationRequest,
)


class LocationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Внутренние хелперы ───────────────────────────────────────────────────

    def _to_response(
        self,
        loc: Location,
        total: int = 0,
        online: int = 0,
    ) -> LocationResponse:
        return LocationResponse(
            id=loc.id,
            name=loc.name,
            description=loc.description,
            color=loc.color,
            address=loc.address,
            latitude=loc.latitude,
            longitude=loc.longitude,
            parent_location_id=loc.parent_location_id,
            org_id=loc.org_id,
            created_at=loc.created_at,
            updated_at=loc.updated_at,
            total_devices=total,
            online_devices=online,
        )

    async def _get_location(self, location_id: uuid.UUID, org_id: uuid.UUID) -> Location:
        loc = await self.db.scalar(
            select(Location).where(Location.id == location_id, Location.org_id == org_id)
            .execution_options(populate_existing=True)
        )
        if not loc:
            raise HTTPException(status_code=404, detail="Location not found")
        return loc

    async def _fence_writes(self, org_id: uuid.UUID) -> None:
        """Keep hierarchy/name/membership writers serialized until commit; fail fast.

        A per-row lock cannot prevent opposing reparents on two different rows.
        This tenant key is distinct from the group key; no device IO is involved.
        """
        if self.db.get_bind().dialect.name == "postgresql":
            key = int.from_bytes(hashlib.sha256(
                f"sphere:location-writes:v1:{org_id}".encode()
            ).digest()[:8], "big", signed=True)
            if not await self.db.scalar(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": key}):
                raise HTTPException(status_code=409, detail="Locations are being modified; refresh and retry")

    async def _validate_parent(self, org_id: uuid.UUID, parent_id: uuid.UUID | None,
                               location_id: uuid.UUID | None = None) -> None:
        if parent_id is None:
            return  # Clearing can repair a legacy invalid chain.
        if parent_id == location_id:
            raise HTTPException(status_code=400, detail="Location cannot be its own parent")
        rows = (await self.db.execute(select(Location.id, Location.parent_location_id)
                                      .where(Location.org_id == org_id))).all()
        parents = {row.id: row.parent_location_id for row in rows}
        if parent_id not in parents:
            raise HTTPException(status_code=404, detail="Parent location not found")
        visited: set[uuid.UUID] = set()
        current: uuid.UUID | None = parent_id
        while current is not None:
            if current == location_id or current in visited or current not in parents:
                raise HTTPException(status_code=400, detail="Parent would create or inherit an invalid location hierarchy")
            visited.add(current)
            current = parents[current]

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_location(
        self, org_id: uuid.UUID, data: CreateLocationRequest
    ) -> LocationResponse:
        await self._fence_writes(org_id)
        await self._validate_parent(org_id, data.parent_location_id)
        # Проверка уникальности имени в пределах организации
        dup = (
            await self.db.execute(
                select(Location).where(
                    Location.org_id == org_id, Location.name == data.name
                )
            )
        ).scalar_one_or_none()
        if dup:
            raise HTTPException(
                status_code=409,
                detail=f"Location '{data.name}' already exists in this organisation",
            )

        loc = Location(
            org_id=org_id,
            name=data.name,
            description=data.description,
            color=data.color,
            address=data.address,
            latitude=data.latitude,
            longitude=data.longitude,
            parent_location_id=data.parent_location_id,
        )
        self.db.add(loc)
        await self.db.flush()
        return self._to_response(loc)

    # ── List (со статистикой online/total) ───────────────────────────────────

    async def get_location_stats(self, org_id: uuid.UUID, location_id: uuid.UUID | None = None) -> list[LocationResponse]:
        """Direct memberships and persisted online status, never descendant totals."""
        stmt = (
            select(Location, func.count(Device.id).label("total"),
                   func.sum(case((Device.last_status == DeviceStatus.ONLINE, 1), else_=0)).label("online_count"))
            .outerjoin(device_location_members, device_location_members.c.location_id == Location.id)
            .outerjoin(Device, (Device.id == device_location_members.c.device_id) & (Device.org_id == org_id))
            .where(Location.org_id == org_id)
            .group_by(Location.id)
            .order_by(Location.name, Location.id)
            .execution_options(populate_existing=True)
        )
        if location_id is not None:
            stmt = stmt.where(Location.id == location_id)
        rows = (await self.db.execute(stmt)).all()
        return [self._to_response(row[0], row.total or 0, row.online_count or 0) for row in rows]

    async def get_location(self, location_id: uuid.UUID, org_id: uuid.UUID) -> LocationResponse:
        rows = await self.get_location_stats(org_id, location_id)
        if not rows:
            raise HTTPException(status_code=404, detail="Location not found")
        return rows[0]

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_location(
        self,
        location_id: uuid.UUID,
        org_id: uuid.UUID,
        data: UpdateLocationRequest,
    ) -> LocationResponse:
        await self._get_location(location_id, org_id)  # Hide foreign-target contention.
        await self._fence_writes(org_id)
        loc = await self._get_location(location_id, org_id)
        if data.expected_updated_at is not None and data.expected_updated_at != loc.updated_at:
            raise HTTPException(status_code=409, detail="Location changed; refresh and confirm again")
        if "parent_location_id" in data.model_fields_set:
            await self._validate_parent(org_id, data.parent_location_id, location_id)
        if data.name is not None and data.name != loc.name:
            dup = await self.db.scalar(select(Location.id).where(
                Location.org_id == org_id, Location.name == data.name, Location.id != location_id))
            if dup:
                raise HTTPException(status_code=409, detail="Location name already exists in this organisation")
        # Validate everything before mutating the ORM object; null is deliberate clearing.
        for field in data.model_fields_set - {"expected_updated_at"}:
            setattr(loc, field, getattr(data, field))
        await self.db.flush()
        return await self.get_location(location_id, org_id)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_location(self, location_id: uuid.UUID, org_id: uuid.UUID, expected_updated_at: datetime | None = None) -> None:
        await self._get_location(location_id, org_id)
        await self._fence_writes(org_id)
        loc = await self._get_location(location_id, org_id)
        if expected_updated_at is not None and expected_updated_at != loc.updated_at:
            raise HTTPException(status_code=409, detail="Location changed; refresh and confirm again")
        await self.db.delete(loc)

    # ── Назначить устройства в локацию (M2M — добавляет, НЕ заменяет) ────────

    async def assign_devices_to_location(
        self,
        device_ids: list[str],
        location_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> int:
        """
        Добавить устройства в локацию (аддитивно — не удаляет из других локаций).
        Возвращает кол-во фактически назначенных устройств.
        """
        await self._get_location(location_id, org_id)
        await self._fence_writes(org_id)
        loc = await self._get_location(location_id, org_id)

        uuids: list[uuid.UUID] = []
        for did in device_ids:
            try:
                uuids.append(uuid.UUID(did))
            except ValueError:
                continue

        stmt = (
            select(Device)
            .options(selectinload(Device.locations))
            .where(Device.id.in_(uuids), Device.org_id == org_id)
        )
        devices = (await self.db.execute(stmt)).scalars().all()

        added = 0
        for device in devices:
            if loc not in device.locations:
                device.locations.append(loc)
                added += 1

        await self.db.flush()
        return added

    # ── Убрать устройства из локации ─────────────────────────────────────────

    async def remove_devices_from_location(
        self,
        device_ids: list[str],
        location_id: uuid.UUID,
        org_id: uuid.UUID,
    ) -> int:
        """Убрать устройства из конкретной локации."""
        await self._get_location(location_id, org_id)
        await self._fence_writes(org_id)
        loc = await self._get_location(location_id, org_id)

        uuids: list[uuid.UUID] = []
        for did in device_ids:
            try:
                uuids.append(uuid.UUID(did))
            except ValueError:
                continue

        stmt = (
            select(Device)
            .options(selectinload(Device.locations))
            .where(Device.id.in_(uuids), Device.org_id == org_id)
        )
        devices = (await self.db.execute(stmt)).scalars().all()

        removed = 0
        for device in devices:
            if loc in device.locations:
                device.locations.remove(loc)
                removed += 1

        await self.db.flush()
        return removed
