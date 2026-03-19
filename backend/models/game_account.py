# backend/models/game_account.py
# ВЛАДЕЛЕЦ: TZ-10 Game Account Management.
# Модель игрового аккаунта — ядро фарминг-платформы.
# Хранит учётные данные, статус, привязку к устройству, статистику банов/сессий,
# а также игровую специфику: сервер, никнейм, баланс (рубли/BC), VIP, законопослушность.
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database.engine import Base
from backend.models.base_model import TimestampMixin, UUIDMixin


class AccountStatus(str, enum.Enum):
    """Статусы игрового аккаунта."""

    # Рабочие
    free = "free"                    # Свободен, готов к назначению
    in_use = "in_use"               # Назначен устройству, используется
    cooldown = "cooldown"           # На кулдауне после сессии
    pending_registration = "pending_registration"  # Ожидает регистрации (авто-создание)

    # Проблемные
    banned = "banned"               # Заблокирован в игре
    captcha = "captcha"             # Требует решения капчи
    phone_verify = "phone_verify"   # Требует верификации телефона

    # Административные
    disabled = "disabled"           # Отключён администратором
    archived = "archived"           # Архивирован (мягкое удаление)


class GenderEnum(str, enum.Enum):
    """Пол персонажа при регистрации."""

    male = "male"
    female = "female"


class VipType(str, enum.Enum):
    """Тип VIP-подписки в игре."""

    none = "none"
    silver = "silver"
    gold = "gold"
    platinum = "platinum"
    diamond = "diamond"


class GameAccount(Base, UUIDMixin, TimestampMixin):
    """
    Игровой аккаунт.

    Хранит логин/пароль, привязку к устройству, статус,
    статистику банов и сессий, игровую специфику (сервер, никнейм,
    двойной баланс, VIP, законопослушность, регистрационные данные),
    а также произвольные метаданные.
    Все аккаунты изолированы по org_id (Row Level Security).
    """

    __tablename__ = "game_accounts"

    # --- Организационная принадлежность ---
    org_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # --- Идентификация аккаунта ---
    game: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True,
        comment="Название игры / приложения",
    )
    login: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Логин / email / username",
    )
    password_encrypted: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="Пароль (в открытом виде — шифрование на уровне приложения)",
    )

    # --- Игровой сервер и персонаж ---
    server_name: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Название сервера (например RED, MOSCOW, KAZAN)",
    )
    nickname: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="Игровой никнейм персонажа (Имя_Фамилия)",
    )
    gender: Mapped[GenderEnum | None] = mapped_column(
        Enum(GenderEnum, name="gender_enum", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
        comment="Пол персонажа при регистрации",
    )

    # --- Статус ---
    status: Mapped[AccountStatus] = mapped_column(
        Enum(AccountStatus, name="account_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=AccountStatus.free,
        server_default="free",
        index=True,
    )
    status_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Причина текущего статуса (бан-причина, описание ошибки итд)",
    )
    status_changed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Время последней смены статуса",
    )

    # --- Привязка к устройству ---
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("devices.id", ondelete="SET NULL"),
        nullable=True,
        comment="Устройство, на котором аккаунт используется в данный момент",
    )
    assigned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Когда аккаунт был назначен на текущее устройство",
    )

    # --- Игровая статистика ---
    level: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Текущий уровень персонажа",
    )
    target_level: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Целевой уровень прокачки (когда level >= target_level — аккаунт считается докачанным)",
    )
    experience: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True,
        comment="Текущий опыт персонажа (EXP)",
    )
    balance_rub: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Баланс игровых рублей",
    )
    balance_bc: Mapped[float | None] = mapped_column(
        Float, nullable=True,
        comment="Баланс BC (донат-валюта)",
    )
    last_balance_update: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    # --- VIP и законопослушность ---
    vip_type: Mapped[VipType | None] = mapped_column(
        Enum(VipType, name="vip_type_enum", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
        comment="Тип VIP-подписки",
    )
    vip_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Дата окончания VIP-подписки",
    )
    lawfulness: Mapped[int | None] = mapped_column(
        Integer, nullable=True,
        comment="Уровень законопослушности (0–100)",
    )

    # --- Статистика банов ---
    total_bans: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    last_ban_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    ban_reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
    )

    # --- Статистика сессий ---
    total_sessions: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    last_session_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="До какого времени аккаунт на кулдауне",
    )

    # --- Регистрационные данные ---
    registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
        comment="Дата регистрации аккаунта в игре",
    )
    registration_ip: Mapped[str | None] = mapped_column(
        String(45), nullable=True,
        comment="IP-адрес, с которого был зарегистрирован аккаунт",
    )
    registration_location: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Локация спавна при регистрации",
    )
    registration_provider: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Провайдер регистрации (manual / auto / guest)",
    )

    # --- Мета-данные ---
    meta: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default="{}",
        comment="Произвольные данные: токены, куки, дополнительные поля",
    )

    # --- Relationships ---
    device = relationship("Device", foreign_keys=[device_id], lazy="selectin")

    # --- Индексы ---
    __table_args__ = (
        # Уникальность: один логин на игру внутри организации
        Index(
            "ix_game_accounts_org_game_login",
            "org_id", "game", "login",
            unique=True,
        ),
        # Быстрый поиск свободных аккаунтов по игре
        Index(
            "ix_game_accounts_org_game_status",
            "org_id", "game", "status",
        ),
        # Поиск по устройству
        Index(
            "ix_game_accounts_device_id",
            "device_id",
            postgresql_where="device_id IS NOT NULL",
        ),
        # Поиск по серверу внутри организации
        Index(
            "ix_game_accounts_org_server",
            "org_id", "server_name",
            postgresql_where="server_name IS NOT NULL",
        ),
        # Фильтрация по прогрессу прокачки
        Index(
            "ix_game_accounts_level_target",
            "org_id", "level", "target_level",
            postgresql_where="target_level IS NOT NULL",
        ),
    )

    @property
    def is_leveled(self) -> bool:
        """Аккаунт достиг целевого уровня (докачался)."""
        if self.level is None or self.target_level is None:
            return False
        return self.level >= self.target_level

    def __repr__(self) -> str:
        srv = f"@{self.server_name}" if self.server_name else ""
        return f"<GameAccount {self.game}:{self.login}{srv} [{self.status.value}]>"
