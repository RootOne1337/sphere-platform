# backend/services/device_registration_service.py
# ВЛАДЕЛЕЦ: TZ-12 Agent Discovery. Автоматическая регистрация устройств.
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.security import create_access_token, create_refresh_token
from backend.models.device import Device, DeviceStatus
from backend.schemas.device_register import DeviceRegisterRequest, DeviceRegisterResponse


class DeviceRegistrationService:
    """
    Сервис автоматической регистрации устройств.

    Идемпотентность: если устройство с таким fingerprint уже существует —
    возвращаем его device_id + новые JWT токены (re-enrollment).
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def register_device(
        self,
        org_id: uuid.UUID,
        data: DeviceRegisterRequest,
    ) -> DeviceRegisterResponse:
        """
        Зарегистрировать новое устройство или re-enroll существующее.

        1. Ищем устройство по fingerprint в рамках org
        2. Если найдено → re-enrollment (обновляем meta, возвращаем новые токены)
        3. Если нет → создаём новое устройство
        4. Генерируем JWT для агента (sub = device_id, role = "device")
        """
        # Поиск по fingerprint (идемпотентность)
        existing = await self._find_by_fingerprint(org_id, data.fingerprint)

        if existing:
            # Re-enrollment: обновляем метаданные
            await self._update_device_meta(existing, data)
            await self.db.flush()
            return self._build_response(existing, is_new=False)

        # Новая регистрация
        device = await self._create_device(org_id, data)
        await self.db.flush()
        return self._build_response(device, is_new=True)

    async def _find_by_fingerprint(
        self,
        org_id: uuid.UUID,
        fingerprint: str,
    ) -> Device | None:
        """Найти устройство по fingerprint в рамках организации."""
        stmt = select(Device).where(
            Device.org_id == org_id,
            Device.meta["fingerprint"].as_string() == fingerprint,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def _create_device(
        self,
        org_id: uuid.UUID,
        data: DeviceRegisterRequest,
    ) -> Device:
        """Создать новое устройство в БД."""
        name = data.name or self._generate_device_name(data)

        meta: dict[str, Any] = {
            "type": data.device_type,
            "fingerprint": data.fingerprint,
            "auto_registered": True,
        }
        if data.workstation_id:
            meta["workstation_id"] = data.workstation_id
        if data.instance_index is not None:
            meta["instance_index"] = data.instance_index
        if data.location:
            meta["location"] = data.location
        # Пользовательские meta — мерж с системными (системные имеют приоритет)
        user_meta = data.meta or {}
        meta = {**user_meta, **meta}

        device = Device(
            org_id=org_id,
            name=name,
            serial=None,
            android_version=data.android_version,
            model=data.model,
            tags=["auto-registered"],
            notes=None,
            meta=meta,
            last_status=DeviceStatus.OFFLINE,
        )
        self.db.add(device)
        return device

    async def _update_device_meta(self, device: Device, data: DeviceRegisterRequest) -> None:
        """Обновить метаданные существующего устройства при re-enrollment."""
        meta = dict(device.meta or {})
        if data.android_version:
            device.android_version = data.android_version
        if data.model:
            device.model = data.model
        if data.workstation_id:
            meta["workstation_id"] = data.workstation_id
        if data.instance_index is not None:
            meta["instance_index"] = data.instance_index
        if data.location:
            meta["location"] = data.location
        # Обновляем мета
        meta["last_re_enrollment"] = True
        device.meta = meta
        device.is_active = True

    def _build_response(self, device: Device, is_new: bool) -> DeviceRegisterResponse:
        """Сформировать ответ с JWT токенами для агента."""
        # JWT: sub = device_id, role = "device" (специальная роль для агентов)
        access_token, _ = create_access_token(
            subject=str(device.id),
            org_id=str(device.org_id),
            role="device",
        )
        refresh_token = create_refresh_token()

        # server_url из единого источника: Settings.SERVER_PUBLIC_URL
        server_url = settings.SERVER_PUBLIC_URL.rstrip("/")

        return DeviceRegisterResponse(
            device_id=device.id,
            name=device.name,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            server_url=server_url,
            is_new=is_new,
            created_at=device.created_at,
        )

    @staticmethod
    def _generate_device_name(data: DeviceRegisterRequest) -> str:
        """
        Автоматическая генерация имени устройства.

        Шаблон: {location}-{type_short}-{index:03d}
        Например: msk-ld-042, fra-ph-001
        """
        type_short = {
            "ldplayer": "ld",
            "physical": "ph",
            "remote": "rm",
            "genymotion": "gm",
            "nox": "nx",
        }.get(data.device_type, "dv")

        location = data.location or "auto"
        index = data.instance_index if data.instance_index is not None else 0

        return f"{location}-{type_short}-{index:03d}"
