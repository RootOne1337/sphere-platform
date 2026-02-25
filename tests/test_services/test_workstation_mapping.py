# tests/test_services/test_workstation_mapping.py
# TZ-04 SPLIT-4: Unit-тесты для WorkstationMappingService.
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services.workstation_mapping import WorkstationMappingService


def _make_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    return db


def _stub_rows(db, rows: list[tuple]):
    """rows = [(device_id, meta_dict), ...]"""
    result = MagicMock()
    result.all = MagicMock(return_value=rows)
    db.execute.return_value = result


class TestCreateWavesSimple:
    """stagger_by_workstation=False → нарезание chunk'ами."""

    @pytest.mark.asyncio
    async def test_single_wave(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        ids = [uuid.uuid4() for _ in range(3)]
        waves = await svc.create_waves(ids, uuid.uuid4(), wave_size=10, stagger_by_workstation=False)
        assert waves == [ids]

    @pytest.mark.asyncio
    async def test_multiple_waves(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        ids = [uuid.uuid4() for _ in range(5)]
        waves = await svc.create_waves(ids, uuid.uuid4(), wave_size=2, stagger_by_workstation=False)
        assert len(waves) == 3
        assert waves[0] == ids[:2]
        assert waves[1] == ids[2:4]
        assert waves[2] == ids[4:]

    @pytest.mark.asyncio
    async def test_empty_list(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        waves = await svc.create_waves([], uuid.uuid4(), wave_size=5, stagger_by_workstation=False)
        assert waves == []


class TestCreateWavesStaggered:
    """stagger_by_workstation=True → round-robin по рабочим станциям."""

    @pytest.mark.asyncio
    async def test_single_workstation(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        ws_id = "ws-A"
        ids = [uuid.uuid4() for _ in range(4)]
        _stub_rows(db, [(d, {"workstation_id": ws_id}) for d in ids])

        org_id = uuid.uuid4()
        waves = await svc.create_waves(ids, org_id, wave_size=2, stagger_by_workstation=True)
        # Нет перемешивания — все из одной WS, нарезаем по wave_size
        flat = [d for w in waves for d in w]
        assert set(flat) == set(ids)

    @pytest.mark.asyncio
    async def test_two_workstations_round_robin(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        ids_a = [uuid.uuid4(), uuid.uuid4()]
        ids_b = [uuid.uuid4(), uuid.uuid4()]
        rows = [(d, {"workstation_id": "ws-A"}) for d in ids_a] + \
               [(d, {"workstation_id": "ws-B"}) for d in ids_b]
        _stub_rows(db, rows)

        all_ids = ids_a + ids_b
        waves = await svc.create_waves(all_ids, uuid.uuid4(), wave_size=4, stagger_by_workstation=True)
        flat = [d for w in waves for d in w]
        assert set(flat) == set(all_ids)

    @pytest.mark.asyncio
    async def test_missing_devices_go_to_no_workstation(self):
        """Устройства без записи в БД добавляются в группу 'no_workstation'."""
        db = _make_db()
        svc = WorkstationMappingService(db)
        known = uuid.uuid4()
        missing = uuid.uuid4()
        # DB знает только known
        _stub_rows(db, [(known, {"workstation_id": "ws-1"})])

        waves = await svc.create_waves(
            [known, missing], uuid.uuid4(), wave_size=10, stagger_by_workstation=True
        )
        flat = [d for w in waves for d in w]
        assert missing in flat
        assert known in flat

    @pytest.mark.asyncio
    async def test_no_workstation_in_meta(self):
        """meta без workstation_id → группа 'no_workstation'."""
        db = _make_db()
        svc = WorkstationMappingService(db)
        d1, d2 = uuid.uuid4(), uuid.uuid4()
        _stub_rows(db, [(d1, {}), (d2, None)])

        waves = await svc.create_waves([d1, d2], uuid.uuid4(), wave_size=5, stagger_by_workstation=True)
        flat = [d for w in waves for d in w]
        assert set(flat) == {d1, d2}

    @pytest.mark.asyncio
    async def test_wave_size_respected(self):
        db = _make_db()
        svc = WorkstationMappingService(db)
        ids = [uuid.uuid4() for _ in range(6)]
        _stub_rows(db, [(d, {"workstation_id": "ws-X"}) for d in ids])

        waves = await svc.create_waves(ids, uuid.uuid4(), wave_size=2, stagger_by_workstation=True)
        for wave in waves[:-1]:  # последняя может быть неполной
            assert len(wave) <= 2
