# backend/services/nick_generator.py
# ВЛАДЕЛЕЦ: TZ-13 Orchestration Pipeline.
# Генератор уникальных никнеймов для игровых аккаунтов.
# Формат по умолчанию: "Имя_Фамилия" (латиницей).
# Проверка уникальности — через БД (game_accounts.nickname).
from __future__ import annotations

import random
import string
from typing import Sequence

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.game_account import GameAccount

logger = structlog.get_logger()

# ── Базы имён (латиница, реалистичные русские имена) ──────────────────────

MALE_FIRST_NAMES: list[str] = [
    "Aleksandr", "Andrey", "Anton", "Artem", "Boris", "Daniil", "Denis",
    "Dmitriy", "Eduard", "Egor", "Evgeniy", "Fedor", "Filipp", "Georgiy",
    "Gleb", "Igor", "Ilya", "Ivan", "Kirill", "Konstantin", "Leonid",
    "Maksim", "Mark", "Matvey", "Mihail", "Nikita", "Nikolay", "Oleg",
    "Pavel", "Petr", "Roman", "Ruslan", "Semen", "Sergey", "Stanislav",
    "Stepan", "Timofey", "Timur", "Vadim", "Valentin", "Valeriy",
    "Vasiliy", "Viktor", "Vitaliy", "Vladimir", "Vladislav", "Vyacheslav",
    "Yaroslav", "Yuriy", "Zakhar",
]

FEMALE_FIRST_NAMES: list[str] = [
    "Aleksandra", "Alina", "Anastasiya", "Anna", "Daria", "Diana",
    "Ekaterina", "Elena", "Eva", "Galina", "Irina", "Karina", "Kseniya",
    "Larisa", "Lilia", "Lyudmila", "Marina", "Mariya", "Nadezhda",
    "Natalya", "Nina", "Oksana", "Olga", "Polina", "Sofiya", "Svetlana",
    "Tamara", "Tatyana", "Valentina", "Valeriya", "Veronika", "Viktoriya",
    "Yuliya", "Zinaida",
]

LAST_NAMES: list[str] = [
    "Ivanov", "Petrov", "Sidorov", "Kuznetsov", "Smirnov", "Popov",
    "Volkov", "Sokolov", "Lebedev", "Kozlov", "Novikov", "Morozov",
    "Pavlov", "Egorov", "Orlov", "Andreev", "Makarov", "Nikolaev",
    "Markov", "Fedorov", "Alekseev", "Baranov", "Belov", "Bogdanov",
    "Borisov", "Vasilev", "Vinogradov", "Voronov", "Golubev", "Gromov",
    "Davydov", "Denisov", "Zakharov", "Zaitsev", "Ilyin", "Kalinin",
    "Karpov", "Klimov", "Komarov", "Kovalev", "Krylov", "Lazarev",
    "Litvinov", "Lobanov", "Loginov", "Lukin", "Medvedev", "Melnikov",
    "Nikitin", "Osipov", "Panov", "Polyakov", "Romanov", "Ryabov",
    "Savelyev", "Savin", "Seleznev", "Sergeev", "Sorokin", "Tarasov",
    "Tikhonov", "Titov", "Ushakov", "Filatov", "Frolov", "Tsvetkov",
    "Chernov", "Shestakov", "Shirokov", "Yakovlev",
]


class NickGenerator:
    """
    Генератор уникальных никнеймов.

    Стратегия:
    1. Генерируем ник по шаблону (Имя_Фамилия)
    2. Проверяем уникальность в БД (game_accounts.nickname)
    3. Если занят — добавляем 2-3 случайных цифры
    4. До 50 попыток, потом ошибка
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def generate(
        self,
        org_id: str,
        pattern: str = "{first_name}_{last_name}",
        gender: str | None = None,
        max_attempts: int = 50,
    ) -> str:
        """
        Генерирует уникальный никнейм.

        Args:
            org_id: ID организации (проверка уникальности в рамках org).
            pattern: Шаблон: {first_name}, {last_name}, {digits}.
            gender: 'male' / 'female' / None (случайный).
            max_attempts: Максимум попыток генерации.

        Returns:
            Уникальный никнейм.

        Raises:
            RuntimeError: Если не удалось сгенерировать уникальный ник за max_attempts попыток.
        """
        for attempt in range(max_attempts):
            nick = self._render_pattern(pattern, gender)

            # Добавляем цифры после 5-й попытки для увеличения вариативности
            if attempt >= 5:
                nick += str(random.randint(10, 999))

            if await self._is_unique(org_id, nick):
                logger.info(
                    "nick_generator.success",
                    nickname=nick,
                    attempts=attempt + 1,
                )
                return nick

        raise RuntimeError(
            f"Не удалось сгенерировать уникальный ник за {max_attempts} попыток. "
            f"Шаблон: {pattern}, org_id: {org_id}"
        )

    async def generate_batch(
        self,
        org_id: str,
        count: int,
        pattern: str = "{first_name}_{last_name}",
        gender: str | None = None,
    ) -> list[str]:
        """Генерация пакета уникальных никнеймов."""
        nicks: list[str] = []
        for _ in range(count):
            nick = await self.generate(org_id, pattern, gender)
            nicks.append(nick)
        return nicks

    async def is_nickname_available(self, org_id: str, nickname: str) -> bool:
        """Проверить доступность конкретного никнейма."""
        return await self._is_unique(org_id, nickname)

    def _render_pattern(self, pattern: str, gender: str | None = None) -> str:
        """Рендерит шаблон в конкретный ник."""
        if gender == "female":
            first_names = FEMALE_FIRST_NAMES
        elif gender == "male":
            first_names = MALE_FIRST_NAMES
        else:
            first_names = MALE_FIRST_NAMES + FEMALE_FIRST_NAMES

        first_name = random.choice(first_names)
        last_name = random.choice(LAST_NAMES)
        digits = "".join(random.choices(string.digits, k=3))

        return (
            pattern
            .replace("{first_name}", first_name)
            .replace("{last_name}", last_name)
            .replace("{digits}", digits)
        )

    async def _is_unique(self, org_id: str, nickname: str) -> bool:
        """Проверяет уникальность никнейма в рамках организации."""
        result = await self._db.execute(
            select(func.count())
            .select_from(GameAccount)
            .where(
                GameAccount.org_id == org_id,
                GameAccount.nickname == nickname,
            )
        )
        count = result.scalar_one()
        return count == 0
