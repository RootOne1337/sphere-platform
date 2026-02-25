# backend/services/device_service.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-1. Device CRUD + live status service.
from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models.device import Device, DeviceStatus
from backend.models.device_group import DeviceGroup
from backend.schemas.devices import (
    CreateDeviceRequest,
    DeviceResponse,
    DeviceStatusResponse,
    UpdateDeviceRequest,
)
from backend.services.cache_service import CacheService


class DeviceService:
    def __init__(self, db: AsyncSession, cache: CacheService) -> None:
        self.db = db
        self.cache = cache

    # ── Internal helpers ─────────────────────────────────────────────────────

    async def _get_device(self, device_id: uuid.UUID, org_id: uuid.UUID) -> Device:
        """Загрузить устройство + groups; бросить 404 если не найдено или другой org."""
        stmt = (
            select(Device)
            .options(selectinload(Device.groups))
            .where(Device.id == device_id, Device.org_id == org_id)
        )
        device = (await self.db.execute(stmt)).scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail="Device not found")
        return device

    def _to_response(self, device: Device, live_status: str | None = None) -> DeviceResponse:
        meta: dict[str, Any] = device.meta or {}

        ws_id_raw = meta.get("workstation_id")
        ws_id = uuid.UUID(ws_id_raw) if ws_id_raw else None

        group_ids = [g.id for g in (device.groups or [])]

        db_status = device.last_status
        status_str = db_status.value if isinstance(db_status, DeviceStatus) else str(db_status)

        return DeviceResponse(
            id=device.id,
            name=device.name,
            serial=device.serial,
            type=meta.get("type"),
            status=live_status or status_str,
            is_active=device.is_active,
            ip_address=meta.get("ip_address"),
            adb_port=meta.get("adb_port"),
            android_version=device.android_version,
            device_model=device.model,
            workstation_id=ws_id,
            group_ids=group_ids,
            tags=device.tags or [],
            notes=device.notes,
            created_at=device.created_at,
            updated_at=device.updated_at,
        )

    async def _reload_with_groups(self, device_id: uuid.UUID) -> Device:
        """Перезагрузить устройство из БД вместе с группами."""
        stmt = (
            select(Device)
            .options(selectinload(Device.groups))
            .where(Device.id == device_id)
        )
        return (await self.db.execute(stmt)).scalar_one()

    # ── Create ───────────────────────────────────────────────────────────────

    async def create_device(self, org_id: uuid.UUID, data: CreateDeviceRequest) -> DeviceResponse:
        # Проверить уникальность serial в рамках org
        if data.serial:
            dup = (
                await self.db.execute(
                    select(Device).where(
                        Device.org_id == org_id,
                        Device.serial == data.serial,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Device with serial '{data.serial}' already exists in this organisation",
                )

        meta: dict[str, Any] = {"type": data.type}
        if data.ip_address is not None:
            meta["ip_address"] = data.ip_address
        if data.adb_port is not None:
            meta["adb_port"] = data.adb_port
        if data.workstation_id is not None:
            meta["workstation_id"] = str(data.workstation_id)

        device = Device(
            org_id=org_id,
            name=data.name,
            serial=data.serial,
            android_version=data.android_version,
            model=data.device_model,
            tags=data.tags or [],
            notes=data.notes,
            meta=meta,
        )
        self.db.add(device)
        await self.db.flush()  # получить device.id до group assignment

        # M2M group assignment
        if data.group_id:
            group = await self.db.get(DeviceGroup, data.group_id)
            if not group or group.org_id != org_id:
                raise HTTPException(status_code=404, detail="Group not found")
            device = await self._reload_with_groups(device.id)
            device.groups.append(group)
            await self.db.flush()
        else:
            device = await self._reload_with_groups(device.id)

        return self._to_response(device)

    # ── List ─────────────────────────────────────────────────────────────────

    async def list_devices(
        self,
        org_id: uuid.UUID,
        status: str | None = None,
        group_id: uuid.UUID | None = None,
        type_filter: str | None = None,
        search: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[DeviceResponse], int]:
        base_conditions = [Device.org_id == org_id]

        if status:
            try:
                base_conditions.append(Device.last_status == DeviceStatus(status))
            except ValueError:
                pass  # неизвестный статус → пустой список (forward compat)

        stmt = (
            select(Device)
            .options(selectinload(Device.groups))
            .where(*base_conditions)
        )
        count_stmt = (
            select(func.count())
            .select_from(Device)
            .where(*base_conditions)
        )

        if group_id:
            stmt = stmt.where(Device.groups.any(DeviceGroup.id == group_id))
            count_stmt = count_stmt.where(Device.groups.any(DeviceGroup.id == group_id))

        if search:
            like = f"%{search}%"
            search_cond = or_(
                Device.name.ilike(like),
                Device.serial.ilike(like),
            )
            stmt = stmt.where(search_cond)
            count_stmt = count_stmt.where(search_cond)

        total = (await self.db.execute(count_stmt)).scalar_one()
        rows = (
            await self.db.execute(
                stmt.order_by(Device.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).scalars().all()

        return [self._to_response(d) for d in rows], total

    # ── Get one ──────────────────────────────────────────────────────────────

    async def get_device(self, device_id: uuid.UUID, org_id: uuid.UUID) -> DeviceResponse:
        device = await self._get_device(device_id, org_id)
        return self._to_response(device)

    # ── Update ───────────────────────────────────────────────────────────────

    async def update_device(
        self,
        device_id: uuid.UUID,
        org_id: uuid.UUID,
        data: UpdateDeviceRequest,
    ) -> DeviceResponse:
        device = await self._get_device(device_id, org_id)

        if data.name is not None:
            device.name = data.name

        if data.serial is not None and data.serial != device.serial:
            dup = (
                await self.db.execute(
                    select(Device).where(
                        Device.org_id == org_id,
                        Device.serial == data.serial,
                        Device.id != device_id,
                    )
                )
            ).scalar_one_or_none()
            if dup:
                raise HTTPException(
                    status_code=409,
                    detail=f"Device with serial '{data.serial}' already exists in this organisation",
                )
            device.serial = data.serial

        if data.android_version is not None:
            device.android_version = data.android_version
        if data.device_model is not None:
            device.model = data.device_model
        if data.tags is not None:
            device.tags = data.tags
        if data.notes is not None:
            device.notes = data.notes
        if data.is_active is not None:
            device.is_active = data.is_active

        # Обновить meta fields (только если явно переданы)
        meta = dict(device.meta or {})
        if data.type is not None:
            meta["type"] = data.type
        if data.ip_address is not None:
            meta["ip_address"] = data.ip_address
        if data.adb_port is not None:
            meta["adb_port"] = data.adb_port
        if data.workstation_id is not None:
            meta["workstation_id"] = str(data.workstation_id)
        device.meta = meta

        # Group assignment: заменить текущие группы
        if data.group_id is not None:
            group = await self.db.get(DeviceGroup, data.group_id)
            if not group or group.org_id != org_id:
                raise HTTPException(status_code=404, detail="Group not found")
            device.groups = [group]

        await self.db.flush()
        # Обновить client-side значение updated_at после server-side onupdate.
        # _to_response — синхронный метод; без refresh SQLAlchemy пытается lazy-load
        # обновлённого атрибута вне greenlet-контекста и падает с MissingGreenlet.
        await self.db.refresh(device, ["updated_at", "created_at"])
        return self._to_response(device)

    # ── Delete ───────────────────────────────────────────────────────────────

    async def delete_device(self, device_id: uuid.UUID, org_id: uuid.UUID) -> None:
        device = await self._get_device(device_id, org_id)
        await self.db.delete(device)

    # ── Status (live Redis) ──────────────────────────────────────────────────

    async def get_device_with_live_status(
        self, device_id: uuid.UUID, org_id: uuid.UUID
    ) -> DeviceStatusResponse:
        """Объединяет DB данные с live статусом из Redis (TTL=90s)."""
        device = await self._get_device(device_id, org_id)
        live = await self.cache.get_device_status(str(org_id), str(device_id))
        base = self._to_response(device)
        return DeviceStatusResponse(**base.model_dump(), live=live)

    # ── ADB Connect ──────────────────────────────────────────────────────────

    async def connect_adb(self, device_id: uuid.UUID, org_id: uuid.UUID) -> None:
        """
        Инициировать ADB подключение через PC Agent.

        TZ-03 stub: команда записывается в Redis (PC Agent читает через pub/sub).
        Когда TZ-03 будет готов — заменить на publisher.send_command_to_device().
        MED-9: PubSubPublisher инжектируется как зависимость (не глобальный синглтон).
        """
        device = await self._get_device(device_id, org_id)
        ws_id = (device.meta or {}).get("workstation_id")
        if not ws_id:
            raise HTTPException(
                status_code=400,
                detail="Device has no workstation assigned",
            )

        # TZ-03 stub: write command to Redis, PC Agent will poll
        command_key = f"cmd:adb_connect:{device_id}"
        await self.cache.set(
            command_key,
            f'{{"type":"adb_connect","device_id":"{device_id}","workstation_id":"{ws_id}"}}',
            ttl=30,
        )

    # ── Screenshot ───────────────────────────────────────────────────────────

    # ── Ownership helpers (used by SPLIT-3 fleet + SPLIT-4 bulk) ────────────

    async def filter_owned(
        self, device_ids: list[str], org_id: uuid.UUID
    ) -> list[str]:
        """Return subset of device_ids that belong to org_id."""
        uuids: list[uuid.UUID] = []
        for did in device_ids:
            try:
                uuids.append(uuid.UUID(did))
            except ValueError:
                continue
        if not uuids:
            return []
        stmt = select(Device.id).where(
            Device.id.in_(uuids), Device.org_id == org_id
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        return [str(r) for r in rows]

    async def get_all_device_ids(self, org_id: uuid.UUID) -> list[str]:
        """Return all device IDs for the given org."""
        stmt = select(Device.id).where(Device.org_id == org_id, Device.is_active.is_(True))
        rows = (await self.db.execute(stmt)).scalars().all()
        return [str(r) for r in rows]

    async def bulk_soft_delete(
        self, device_ids: list[str], org_id: uuid.UUID
    ) -> int:
        """Delete all owned devices from the list. Returns count deleted."""
        uuids: list[uuid.UUID] = []
        for did in device_ids:
            try:
                uuids.append(uuid.UUID(did))
            except ValueError:
                continue
        if not uuids:
            return 0
        stmt = (
            select(Device)
            .where(Device.id.in_(uuids), Device.org_id == org_id)
        )
        devices = (await self.db.execute(stmt)).scalars().all()
        for device in devices:
            await self.db.delete(device)
        await self.db.flush()
        return len(devices)

    # ── Screenshot ───────────────────────────────────────────────────────────

    async def request_screenshot(self, device_id: uuid.UUID, org_id: uuid.UUID) -> dict:
        """
        Запросить скриншот устройства через PC Agent.
        TZ-03 stub: команда записывается в Redis.
        """
        device = await self._get_device(device_id, org_id)
        ws_id = (device.meta or {}).get("workstation_id")
        if not ws_id:
            raise HTTPException(
                status_code=400,
                detail="Device has no workstation assigned",
            )

        command_key = f"cmd:screenshot:{device_id}"
        await self.cache.set(
            command_key,
            f'{{"type":"screenshot","device_id":"{device_id}"}}',
            ttl=30,
        )
        return {"status": "screenshot_requested", "device_id": str(device_id)}
