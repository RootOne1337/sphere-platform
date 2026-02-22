# backend/services/workstation_mapping.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-4. Распределение устройств по волнам с учётом workstation.
#
# Цель: равномерная нагрузка — первая волна не перегружает одну рабочую станцию.
# Алгоритм: round-robin по workstation-группам.
# Device.meta['workstation_id'] — ключ для группировки (если workstation_id null — группа "no_ws").
from __future__ import annotations

import uuid
from collections import deque

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.device import Device

logger = structlog.get_logger()


class WorkstationMappingService:
    """
    Распределяет устройства из батча по волнам с учётом рабочих станций.

    stagger_by_workstation=False → простое нарезание chunk'ами по wave_size.
    stagger_by_workstation=True  → round-robin по workstation для равномерного распределения.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_waves(
        self,
        device_ids: list[uuid.UUID],
        org_id: uuid.UUID,
        wave_size: int,
        stagger_by_workstation: bool,
    ) -> list[list[uuid.UUID]]:
        if not stagger_by_workstation:
            return [
                device_ids[i : i + wave_size]
                for i in range(0, len(device_ids), wave_size)
            ]

        # Получить mapping device_id → workstation_id из Device.meta
        stmt = (
            select(Device.id, Device.meta)
            .where(
                Device.id.in_(device_ids),
                Device.org_id == org_id,
            )
        )
        rows = (await self.db.execute(stmt)).all()

        # Группировать по workstation_id (из JSONB meta)
        ws_to_devices: dict[str, deque[uuid.UUID]] = {}
        found_ids: set[uuid.UUID] = set()

        for device_id, meta in rows:
            found_ids.add(device_id)
            ws_id = (meta or {}).get("workstation_id") or "no_workstation"
            ws_str = str(ws_id)
            if ws_str not in ws_to_devices:
                ws_to_devices[ws_str] = deque()
            ws_to_devices[ws_str].append(device_id)

        # Устройства без записи в БД — добавить в no_workstation группу
        missing = set(device_ids) - found_ids
        if missing:
            logger.warning("batch.missing_devices", count=len(missing))
            if "no_workstation" not in ws_to_devices:
                ws_to_devices["no_workstation"] = deque()
            ws_to_devices["no_workstation"].extend(missing)

        # Round-robin по workstation-группам
        ws_queues = list(ws_to_devices.values())
        waves: list[list[uuid.UUID]] = []
        current_wave: list[uuid.UUID] = []

        while any(ws_queues):
            for ws_queue in ws_queues:
                if ws_queue:
                    current_wave.append(ws_queue.popleft())
                    if len(current_wave) >= wave_size:
                        waves.append(current_wave)
                        current_wave = []

        if current_wave:
            waves.append(current_wave)

        logger.info(
            "batch.waves_created",
            total_devices=len(device_ids),
            waves=len(waves),
            wave_size=wave_size,
        )
        return waves
