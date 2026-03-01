# backend/services/location_service.py
# ВЛАДЕЛЕЦ: TZ-02. CRUD + управление привязкой устройств к локациям.
from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import case, func, select
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
            total_devices=total,
            online_devices=online,
        )

    async def _get_location(self, location_id: uuid.UUID, org_id: uuid.UUID) -> Location:
        loc = await self.db.get(Location, location_id)
        if not loc or loc.org_id != org_id:
            raise HTTPException(status_code=404, detail="Location not found")
        return loc

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_location(
        self, org_id: uuid.UUID, data: CreateLocationRequest
    ) -> LocationResponse:
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

        # Валидация родительской локации
        if data.parent_location_id:
            parent = await self.db.get(Location, data.parent_location_id)
            if not parent or parent.org_id != org_id:
                raise HTTPException(status_code=404, detail="Parent location not found")

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

    async def get_location_stats(self, org_id: uuid.UUID) -> list[LocationResponse]:
        """Все локации организации с агрегатами total/online устройств."""
        stmt = (
            select(
                Location.id,
                Location.name,
                Location.description,
                Location.color,
                Location.address,
                Location.latitude,
                Location.longitude,
                Location.parent_location_id,
                func.count(Device.id).label("total"),
                func.sum(
                    case((Device.last_status == DeviceStatus.ONLINE, 1), else_=0)
                ).label("online_count"),
            )
            .outerjoin(
                device_location_members,
                device_location_members.c.location_id == Location.id,
            )
            .outerjoin(Device, Device.id == device_location_members.c.device_id)
            .where(Location.org_id == org_id)
            .group_by(
                Location.id,
                Location.name,
                Location.description,
                Location.color,
                Location.address,
                Location.latitude,
                Location.longitude,
                Location.parent_location_id,
            )
            .order_by(Location.name)
        )
        rows = (await self.db.execute(stmt)).all()

        result: list[LocationResponse] = []
        for row in rows:
            result.append(
                LocationResponse(
                    id=row.id,
                    name=row.name,
                    description=row.description,
                    color=row.color,
                    address=row.address,
                    latitude=row.latitude,
                    longitude=row.longitude,
                    parent_location_id=row.parent_location_id,
                    org_id=org_id,
                    total_devices=row.total or 0,
                    online_devices=row.online_count or 0,
                )
            )
        return result

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_location(
        self,
        location_id: uuid.UUID,
        org_id: uuid.UUID,
        data: UpdateLocationRequest,
    ) -> LocationResponse:
        loc = await self._get_location(location_id, org_id)

        if data.name is not None and data.name != loc.name:
            dup = (
                await self.db.execute(
                    select(Location).where(
                        Location.org_id == org_id,
                        Location.name == data.name,
                        Location.id != location_id,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Location '{data.name}' already exists in this organisation",
                )
            loc.name = data.name

        if data.description is not None:
            loc.description = data.description
        if data.color is not None:
            loc.color = data.color
        if data.address is not None:
            loc.address = data.address
        if data.latitude is not None:
            loc.latitude = data.latitude
        if data.longitude is not None:
            loc.longitude = data.longitude
        if data.parent_location_id is not None:
            if data.parent_location_id == location_id:
                raise HTTPException(
                    status_code=400, detail="Location cannot be its own parent"
                )
            parent = await self.db.get(Location, data.parent_location_id)
            if not parent or parent.org_id != org_id:
                raise HTTPException(status_code=404, detail="Parent location not found")
            loc.parent_location_id = data.parent_location_id

        await self.db.flush()
        return self._to_response(loc)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_location(self, location_id: uuid.UUID, org_id: uuid.UUID) -> None:
        loc = await self._get_location(location_id, org_id)
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
