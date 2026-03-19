# -*- coding: utf-8 -*-
"""
Фабрика идентичностей виртуальных агентов.

Генерирует устойчивые (детерминистические) идентичности для виртуальных
агентов нагрузочного теста. Один и тот же index всегда порождает одну и
ту же идентичность — это позволяет воспроизводить прогоны.
"""
from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Sequence

# Пул реалистичных моделей устройств
_DEFAULT_MODELS: list[str] = [
    "G576D", "HD1910", "ASUS_I003DD", "SM-G998B", "Pixel_7",
    "SM-A536B", "Pixel_6a", "OnePlus_9", "Redmi_Note_12", "Xperia_5_IV",
]

_ANDROID_VERSIONS: list[str] = ["11", "12", "13", "14"]

_MEMORY_VARIANTS_MB: list[int] = [3072, 4096, 6144, 8192]

_SCREEN_VARIANTS: list[tuple[int, int]] = [
    (1080, 2340),
    (1080, 2400),
    (1440, 3200),
    (720, 1600),
]


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    """Устойчивая идентичность виртуального агента.

    Все поля неизменяемы (frozen) — генерируются один раз при создании.
    """

    index: int
    device_id: str
    serial: str
    fingerprint: str
    model: str
    android_version: str
    agent_version: str
    screen_w: int
    screen_h: int
    memory_mb: int
    api_key: str


class IdentityFactory:
    """Фабрика для массовой генерации идентичностей агентов.

    Параметры:
        org_id: UUID организации для теста.
        serial_prefix: Префикс серийного номера (по умолчанию ``LOAD``).
        agent_version: Версия агента (по умолчанию ``2.1.0``).
        api_key_prefix: Префикс API-ключа (по умолчанию ``sphr_load_``).
        models: Пул моделей устройств.
        seed: Начальное число для детерминистической генерации.
    """

    def __init__(
        self,
        org_id: str,
        serial_prefix: str = "LOAD",
        agent_version: str = "2.1.0",
        api_key_prefix: str = "sphr_load_",
        models: Sequence[str] | None = None,
        seed: int = 0,
        shared_api_key: str | None = None,
    ) -> None:
        self._org_id = org_id
        self._prefix = serial_prefix
        self._agent_version = agent_version
        self._api_key_prefix = api_key_prefix
        self._models = list(models or _DEFAULT_MODELS)
        self._seed = seed
        self._shared_api_key = shared_api_key

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def create(self, index: int) -> AgentIdentity:
        """Создать идентичность для агента с данным индексом.

        Детерминистическая функция: один и тот же *index* всегда даёт
        одинаковый результат.
        """
        # Детерминистический UUID на основе seed + index
        ns = uuid.UUID(int=self._seed)
        device_id = str(uuid.uuid5(ns, f"device-{index}"))

        serial = f"{self._prefix}-{index:05d}"
        fingerprint = hashlib.sha256(
            f"{self._org_id}:{serial}:{self._seed}".encode()
        ).hexdigest()[:32]

        model = self._models[index % len(self._models)]
        android_ver = _ANDROID_VERSIONS[index % len(_ANDROID_VERSIONS)]
        screen_w, screen_h = _SCREEN_VARIANTS[index % len(_SCREEN_VARIANTS)]
        memory_mb = _MEMORY_VARIANTS_MB[index % len(_MEMORY_VARIANTS_MB)]
        api_key = self._shared_api_key or f"{self._api_key_prefix}{index:05d}"

        return AgentIdentity(
            index=index,
            device_id=device_id,
            serial=serial,
            fingerprint=fingerprint,
            model=model,
            android_version=android_ver,
            agent_version=self._agent_version,
            screen_w=screen_w,
            screen_h=screen_h,
            memory_mb=memory_mb,
            api_key=api_key,
        )

    def create_batch(self, start: int, count: int) -> list[AgentIdentity]:
        """Создать пакет идентичностей ``[start, start+count)``."""
        return [self.create(i) for i in range(start, start + count)]
