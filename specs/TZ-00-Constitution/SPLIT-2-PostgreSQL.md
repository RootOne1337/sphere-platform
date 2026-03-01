# SPLIT-2 — PostgreSQL: Схема БД, Alembic Миграции

**ТЗ-родитель:** TZ-00-Constitution  
**Ветка:** `stage/0-constitution`  
**Задача:** `SPHERE-002`  
**Исполнитель:** Backend Lead  
**Оценка:** 1 рабочий день  
**Блокирует:** TZ-00 SPLIT-3, SPLIT-4, SPLIT-5 (внутри этапа)
**Обеспечивает:** Схему БД для всех 10 параллельных потоков (TZ-01..TZ-11)

---

## Цель Сплита

Создать полную схему PostgreSQL (35+ таблиц) через Alembic миграции. Настроить async SQLAlchemy engine. После выполнения — все сервисы могут работать с БД с правильными моделями и индексами.

---

## Предусловия

- [ ] SPLIT-1 выполнен (PostgreSQL контейнер запущен)
- [ ] `alembic` установлен (`pip install alembic`)
- [ ] `DATABASE_URL` заполнена в `.env.local`

---

## Шаг 1 — SQLAlchemy Async Engine

```python
# backend/database/engine.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from backend.core.config import settings

engine = create_async_engine(
    settings.POSTGRES_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT,
    pool_pre_ping=True,       # проверять соединение перед использованием
    echo=settings.DEBUG,      # SQL логи только в dev
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # объекты живут после commit
)

class Base(DeclarativeBase):
    pass

# Dependency для FastAPI
async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # FIX: авто-коммит убран. Каждый write-endpoint ОБЯЗАН явно вызвать
            # await db.commit() после изменений. Это предотвращает молчаливое
            # сохранение случайных .add() в GET-запросах и делает транзакции явными.
            # Пример в write-endpoint:
            #   async def create_device(..., db: AsyncSession = Depends(get_db)):
            #       db.add(new_device)
            #       await db.commit()
            #       await db.refresh(new_device)
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def get_db_session(
    org_id: str | None = None,
) -> AsyncGenerator[AsyncSession, None]:
    """
    HIGH-6: Async context manager для фоновых задач, которые не могут использовать FastAPI Depends().
    MED-4: если передан org_id — автоматически устанавливает RLS-контекст.

    Usage (TZ-04 SPLIT-4 _execute_waves, TZ-02 SPLIT-3 sync_device_status_to_db):
        async with get_db_session(org_id=str(batch.org_id)) as db:
            await db.get(TaskBatch, batch_id)
    """
    async with AsyncSessionLocal() as session:
        if org_id:
            await session.execute(
                text(f"SET LOCAL app.current_org_id = '{org_id}'")
            )
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

```bash
alembic init --template async alembic

# alembic/env.py — важные настройки:
```

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import async_engine_from_config
from alembic import context
from backend.database.engine import Base
# Импортировать ВСЕ модели чтобы Alembic их видел:
from backend.models import *  # noqa: F401, F403

config = context.config
fileConfig(config.config_file_name)
target_metadata = Base.metadata

def run_migrations_online():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
    )
    
    async def run_async_migrations():
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()
    
    asyncio.run(run_async_migrations())

def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,      # автодетект изменения типов
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()
```

---

## Шаг 3 — Базовые модели

```python
# backend/models/base_model.py
import uuid
from datetime import datetime
from sqlalchemy import DateTime, func
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base

class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class UUIDMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4
    )
```

---

## Шаг 4 — Модели (все 35+)

```python
# backend/models/organization.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import String
from sqlalchemy.orm import mapped_column, Mapped, relationship
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class Organization(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "organizations"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    
    users: Mapped[list["User"]] = relationship(back_populates="org")
    devices: Mapped[list["Device"]] = relationship(back_populates="org")


# backend/models/user.py
import uuid
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped, relationship
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class User(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "users"
    
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(50), default="viewer", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    org: Mapped["Organization"] = relationship(back_populates="users")
    api_keys: Mapped[list["APIKey"]] = relationship(back_populates="user")


# backend/models/device.py
from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Enum as SAEnum, String, ForeignKey, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import TimestampMixin

class DeviceStatus(str, PyEnum):
    OFFLINE     = "offline"
    ONLINE      = "online"
    BUSY        = "busy"
    CONNECTING  = "connecting"
    ERROR       = "error"

class Device(Base, TimestampMixin):
    __tablename__ = "devices"
    __table_args__ = (
        Index("ix_devices_org_status", "org_id", "status"),
        Index("ix_devices_group", "group_id"),
    )
    
    id: Mapped[str] = mapped_column(String(100), primary_key=True)   # "ld:0", "sphere_abc123"
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(50), nullable=False)    # ldplayer|physical|remote
    status: Mapped[DeviceStatus] = mapped_column(
        SAEnum(DeviceStatus, name="devicestatus"), default=DeviceStatus.OFFLINE
    )
    ip_address: Mapped[str | None] = mapped_column(String(45))
    adb_port: Mapped[int | None]
    android_version: Mapped[str | None] = mapped_column(String(20))
    device_model: Mapped[str | None] = mapped_column(String(100))
    workstation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("workstations.id"))
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("device_groups.id"))
    # MED-1: ARRAY(String) вместо JSONB — еффективнее для GIN-индекса на фиксированных строковых данных
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}", default=list)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# backend/models/script.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import String, Text, Boolean, Integer, ForeignKey, ARRAY, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped, relationship

class Script(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "scripts"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String(50)), server_default="{}", default=list)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("script_versions.id", use_alter=True, name="fk_script_current_version"),
        nullable=True,
    )
    versions: Mapped[list["ScriptVersion"]] = relationship(
        back_populates="script",
        foreign_keys="[ScriptVersion.script_id]",
        order_by="ScriptVersion.version_number.desc()",
    )

class ScriptVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "script_versions"

    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    dag: Mapped[dict] = mapped_column(JSONB)           # Полный DAG JSON
    dag_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 для дедупликации
    changelog: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    script: Mapped["Script"] = relationship(back_populates="versions", foreign_keys=[script_id])


# backend/models/task.py
from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Enum as SAEnum, String, Text, Integer, ForeignKey, DateTime, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class TaskStatus(str, PyEnum):
    PENDING   = "pending"
    RUNNING   = "running"
    PAUSED    = "paused"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"
    TIMEOUT   = "timeout"

class Task(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_org_status_priority", "org_id", "status", "priority"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"), index=True)
    script_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("script_versions.id"))
    device_id: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="taskstatus"), default=TaskStatus.PENDING, index=True
    )
    priority: Mapped[int] = mapped_column(Integer, default=5)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_node: Mapped[str | None] = mapped_column(String(64))   # ID текущего DAG узла
    progress: Mapped[int] = mapped_column(Integer, default=0)      # 0–100
    result: Mapped[dict | None] = mapped_column(JSONB)
    error_msg: Mapped[str | None] = mapped_column(Text)
    logs: Mapped[list[dict]] = mapped_column(JSONB, server_default="[]", default=list)
    webhook_url: Mapped[str | None] = mapped_column(String(2048))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("task_batches.id"), index=True)


# backend/models/task_batch.py
from __future__ import annotations
import uuid
from enum import Enum as PyEnum
from sqlalchemy import Enum as SAEnum, String, Integer, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class TaskBatchStatus(str, PyEnum):
    RUNNING   = "running"
    COMPLETED = "completed"
    FAILED    = "failed"
    CANCELLED = "cancelled"

class TaskBatch(Base, UUIDMixin, TimestampMixin):  # FIX: класс отсутствовал — SyntaxError был здесь
    __tablename__ = "task_batches"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    script_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("scripts.id"))
    name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[TaskBatchStatus] = mapped_column(
        SAEnum(TaskBatchStatus, name="taskbatchstatus"), default=TaskBatchStatus.RUNNING
    )
    total_devices: Mapped[int] = mapped_column(Integer)
    wave_size: Mapped[int] = mapped_column(Integer)
    wave_delay_ms: Mapped[int] = mapped_column(Integer)
    jitter_ms: Mapped[int] = mapped_column(Integer, default=0)
    completed: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    webhook_url: Mapped[str | None] = mapped_column(String(2048))


# backend/models/vpn_peer.py
from __future__ import annotations
import uuid
from datetime import datetime
from enum import Enum as PyEnum
from sqlalchemy import Enum as SAEnum, String, Boolean, ForeignKey, DateTime, LargeBinary
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

from sqlalchemy import LargeBinary

class VPNPeerStatus(str, PyEnum):
    FREE     = "free"
    ASSIGNED = "assigned"
    ERROR    = "error"

class VPNPeer(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "vpn_peers"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    device_id: Mapped[str | None] = mapped_column(String(100), index=True)  # NULL = свободный
    assigned_ip: Mapped[str] = mapped_column(String(15))       # x.x.x.x
    public_key: Mapped[str] = mapped_column(String(44))
    private_key_encrypted: Mapped[bytes] = mapped_column(LargeBinary)  # Зашифровано Fernet
    psk_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    obfuscation_params: Mapped[dict] = mapped_column(JSONB)    # AWGObfuscationParams
    status: Mapped[VPNPeerStatus] = mapped_column(
        SAEnum(VPNPeerStatus, name="vpnpeerstatus"), default=VPNPeerStatus.FREE
    )
    last_handshake_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    vpn_active: Mapped[bool] = mapped_column(Boolean, default=False)


# backend/models/webhook.py
from __future__ import annotations
import uuid
from sqlalchemy import String, Text, Boolean, ForeignKey, ARRAY
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class Webhook(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "webhooks"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    events: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    secret_hash: Mapped[str] = mapped_column(String(255), nullable=False)  # sha256(secret)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
```

---

## Шаг 5 — Иммутабельный Audit Log

```python
# backend/models/audit_log.py
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base

class AuditLog(Base):  # FIX: класс отсутствовал — SyntaxError был здесь
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_org_time", "org_id", "timestamp"),
    )
    
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    org_id: Mapped[uuid.UUID | None]
    user_id: Mapped[uuid.UUID | None]
    api_key_id: Mapped[uuid.UUID | None]
    ip_address: Mapped[str | None] = mapped_column(String(45))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    old_values: Mapped[dict | None] = mapped_column(JSONB)
    new_values: Mapped[dict | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    # Нет updated_at — только INSERT разрешён
```

```sql
-- infrastructure/postgres/audit_log_policies.sql
-- После первой миграции выполнить вручную:
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY audit_insert_only ON audit_logs FOR INSERT WITH CHECK (true);
CREATE POLICY audit_no_update ON audit_logs FOR UPDATE USING (false);
CREATE POLICY audit_no_delete ON audit_logs FOR DELETE USING (false);
```

---

## Шаг 5.1 — Недостающие таблицы (stub-модели)

> Несколько таблиц упомянуты через FK в моделях выше, но нигде полностью не описаны.
> Они подробно раскрываются в соответствующих TZ, но создаются в TZ-00 SPLIT-2,
> чтобы Alembic мог cгенерировать правильную initial_schema миграцию.

```python
# backend/models/workstation.py
from __future__ import annotations
import uuid
from sqlalchemy import String, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class Workstation(Base, UUIDMixin, TimestampMixin):
    """Хост-машина с LDPlayer/ADB. Полная модель — TZ-08 SPLIT-5."""
    __tablename__ = "workstations"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hostname: Mapped[str | None] = mapped_column(String(255))
    agent_version: Mapped[str | None] = mapped_column(String(50))
    is_online: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", default=dict)


# backend/models/ldplayer_instance.py
# FIX: stub-модель обязательна — без неё Alembic не создаст таблицу ldplayer_instances,
# а rls_policies.sql упадёт с ошибкой «relation "ldplayer_instances" does not exist».
# Полная модель с дополнительными полями — TZ-08 SPLIT-2.
from __future__ import annotations
import uuid
from sqlalchemy import String, Integer, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class LDPlayerInstance(Base, UUIDMixin, TimestampMixin):
    """Экземпляр LDPlayer на воркстанции. Полная модель — TZ-08 SPLIT-2."""
    __tablename__ = "ldplayer_instances"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    workstation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workstations.id"), index=True)
    instance_index: Mapped[int] = mapped_column(Integer, nullable=False)  # LDPlayer index (0, 1, 2...)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), default="stopped")  # running|stopped|creating|error
    adb_port: Mapped[int | None] = mapped_column(Integer)  # 5555, 5557, ...
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)  # заблокирован задачей
    meta: Mapped[dict] = mapped_column(JSONB, server_default="{}", default=dict)


# backend/models/device_group.py
from __future__ import annotations
import uuid
from sqlalchemy import String, Text, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class DeviceGroup(Base, UUIDMixin, TimestampMixin):
    """Группа устройств. Полная модель — TZ-02 SPLIT-2."""
    __tablename__ = "device_groups"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("device_groups.id"))


# backend/models/refresh_token.py  (TZ-01 владеет, но stub создаётся здесь для Alembic)
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, String, ForeignKey
from sqlalchemy.orm import mapped_column, Mapped
from backend.database.engine import Base
from .base_model import UUIDMixin

class RefreshToken(Base, UUIDMixin):
    """Opaque refresh tokens. Полная логика — TZ-01 SPLIT-1."""
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_revoked: Mapped[bool] = mapped_column(Boolean, default=False)


# backend/models/api_key.py  (TZ-01 SPLIT-4 владеет, stub здесь для Alembic + TZ-03 agent auth)
from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, String, Text, ForeignKey, ARRAY
from sqlalchemy.orm import mapped_column, Mapped, relationship
from backend.database.engine import Base
from .base_model import UUIDMixin, TimestampMixin

class APIKey(Base, UUIDMixin, TimestampMixin):
    """
    API-ключи для сервисных аккаунтов (n8n, PC Agent, внешние интеграции).
    Полная логика создания/отзыва — TZ-01 SPLIT-4.
    
    ВАЖНО: поле `type` различает:
      - "user"  — обычный API-ключ пользователя (n8n, внешние интеграции)
      - "agent" — долгоживущий токен PC Agent (TZ-08)
                  проверяется в backend/api/ws/agent/router.py через authenticate_agent_token()
    """
    __tablename__ = "api_keys"

    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(20), nullable=False)   # "sphr_prod_a1b2" — для отображения
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # SHA-256
    type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # "user" | "agent"
    permissions: Mapped[list[str]] = mapped_column(ARRAY(String), server_default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped["User"] = relationship(back_populates="api_keys", foreign_keys=[user_id])
```

---

## Шаг 5.2 — backend/models/**init**.py

> **КРИТИЧНО:** Без `__init__.py` строчка `from backend.models import *` в `alembic/env.py`
> не импортирует ни одну модель — Alembic не видит таблицы и генерирует пустую миграцию.

```python
# backend/models/__init__.py
# Импортируем ВСЕ модели явно — Alembic autogenerate увидит все таблицы
from backend.models.base_model import TimestampMixin, UUIDMixin
from backend.models.organization import Organization
from backend.models.user import User
from backend.models.api_key import APIKey
from backend.models.workstation import Workstation
from backend.models.ldplayer_instance import LDPlayerInstance  # FIX: stub для RLS + Alembic
from backend.models.device_group import DeviceGroup
from backend.models.device import Device, DeviceStatus
from backend.models.script import Script, ScriptVersion
from backend.models.task import Task, TaskStatus
from backend.models.task_batch import TaskBatch, TaskBatchStatus
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus
from backend.models.webhook import Webhook
from backend.models.audit_log import AuditLog
from backend.models.refresh_token import RefreshToken

__all__ = [
    "Organization", "User", "APIKey", "Workstation", "LDPlayerInstance", "DeviceGroup",
    "Device", "DeviceStatus", "Script", "ScriptVersion", "Task", "TaskStatus",
    "TaskBatch", "TaskBatchStatus", "VPNPeer", "VPNPeerStatus", "Webhook",
    "AuditLog", "RefreshToken",
]
```

---

## Шаг 6 — RLS для Multi-Tenancy (org_id изоляция)

> **КРИТИЧНО:** Без RLS один баг в коде → утечка данных другой организации.

```sql
-- infrastructure/postgres/rls_policies.sql
-- Выполнить ПОСЛЕ initial_schema миграции

-- Функция для получения org_id текущего сеанса
CREATE OR REPLACE FUNCTION current_org_id() RETURNS uuid AS $$
  SELECT current_setting('app.current_org_id', true)::uuid;
$$ LANGUAGE sql STABLE;

-- ── Users ────────────────────────────────────────────────────────────────
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY users_tenant_isolation ON users
    USING (org_id = current_org_id());
CREATE POLICY users_insert ON users
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Devices ──────────────────────────────────────────────────────────────
ALTER TABLE devices ENABLE ROW LEVEL SECURITY;
CREATE POLICY devices_tenant_isolation ON devices
    USING (org_id = current_org_id());
CREATE POLICY devices_insert ON devices
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Scripts ──────────────────────────────────────────────────────────────
ALTER TABLE scripts ENABLE ROW LEVEL SECURITY;
CREATE POLICY scripts_tenant_isolation ON scripts
    USING (org_id = current_org_id());

-- ── Tasks ────────────────────────────────────────────────────────────────
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY tasks_tenant_isolation ON tasks
    USING (org_id = current_org_id());

-- ── Device Groups ────────────────────────────────────────────────────────
ALTER TABLE device_groups ENABLE ROW LEVEL SECURITY;
CREATE POLICY device_groups_tenant_isolation ON device_groups
    USING (org_id = current_org_id());
-- ── Task Batches ─────────────────────────────────────────────────────────────
ALTER TABLE task_batches ENABLE ROW LEVEL SECURITY;
CREATE POLICY task_batches_tenant_isolation ON task_batches
    USING (org_id = current_org_id());
CREATE POLICY task_batches_insert ON task_batches
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Script Versions (изоляция через scripts.org_id) ──────────────────────────
ALTER TABLE script_versions ENABLE ROW LEVEL SECURITY;
CREATE POLICY script_versions_tenant_isolation ON script_versions
    USING (script_id IN (SELECT id FROM scripts WHERE org_id = current_org_id()));

-- ── VPN Peers ────────────────────────────────────────────────────────────────
ALTER TABLE vpn_peers ENABLE ROW LEVEL SECURITY;
CREATE POLICY vpn_peers_tenant_isolation ON vpn_peers
    USING (org_id = current_org_id());
CREATE POLICY vpn_peers_insert ON vpn_peers
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Webhooks ─────────────────────────────────────────────────────────────────
ALTER TABLE webhooks ENABLE ROW LEVEL SECURITY;
CREATE POLICY webhooks_tenant_isolation ON webhooks
    USING (org_id = current_org_id());
CREATE POLICY webhooks_insert ON webhooks
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── Workstations (FIX: не имели RLS → любой мог видеть чужие воркстанции) ───
ALTER TABLE workstations ENABLE ROW LEVEL SECURITY;
CREATE POLICY workstations_tenant_isolation ON workstations
    USING (org_id = current_org_id());
CREATE POLICY workstations_insert ON workstations
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ── LDPlayer Instances (FIX: аналогично workstations — не имели RLS) ─────────
ALTER TABLE ldplayer_instances ENABLE ROW LEVEL SECURITY;
CREATE POLICY ldplayer_instances_tenant_isolation ON ldplayer_instances
    USING (org_id = current_org_id());
CREATE POLICY ldplayer_instances_insert ON ldplayer_instances
    FOR INSERT WITH CHECK (org_id = current_org_id());

-- ВАЖНО: Superuser (роль sphere) обходит RLS.
-- Application user должен быть НЕ superuser.
-- В FastAPI middleware перед query:
--   await session.execute(text("SET app.current_org_id = :org_id"), {"org_id": str(user.org_id)})
```

```python
# backend/middleware/tenant_middleware.py
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

async def set_tenant_context(session: AsyncSession, org_id: str) -> None:
    """
    Устанавливает RLS-контекст арендатора для текущей транзакции.
    SET LOCAL сбрасывается АВТОМАТИЧЕСКИ при commit/rollback.
    Благодаря этому "грязных" соединений в пуле не возникает.
    """
    await session.execute(
        text("SET LOCAL app.current_org_id = :org_id"),
        {"org_id": str(org_id)},
    )


# backend/core/dependencies.py — добавить после get_current_user
# Это ОСНОВНАЯ зависимость для всех endpoint-ов с бизнес-данными.
#
# FastAPI кэширует Depends per-request: get_db вернёт ту же сессию что
# уже используется в get_current_user — SET LOCAL применяется до первого
# бизнес-запроса, после чего RLS-фильтр работает автоматически.

async def get_tenant_db(
    db: AsyncSession = Depends(get_db),
    current_user: "User" = Depends(get_current_user),
) -> AsyncSession:
    """
    Session с активным RLS-контекстом арендатора.

    ОБЯЗАТЕЛЕН для всех endpoints, обращающихся к таблицам с RLS.
    Заменяет get_db во всех защищённых роутерах:

        @router.get("/devices")
        async def list_devices(
            db: AsyncSession = Depends(get_tenant_db),   # ← не get_db!
            current_user: User = Depends(get_current_user),
        ):
            ...
    """
    await set_tenant_context(db, current_user.org_id)
    return db
```

> **Почему pool contamination невозможен:** `SET LOCAL` действует до конца текущей
> транзакции. `get_db()` выполняет `commit()` или `rollback()` перед закрытием сессии,
> поэтому в пул возвращается соединение без установленного `app.current_org_id`.
> Если по ошибке `get_tenant_db` не вызвать — `current_org_id` вернёт NULL,
> RLS вернёт пустой результат (защита работает, утечки данных нет).

```

---

## Шаг 7 — Первая миграция

```bash
# Создать baseline миграцию (все таблицы сразу)
alembic revision --autogenerate -m "initial_schema"

# Применить
alembic upgrade head

# Проверить
alembic current   # должен показать текущую ревизию
```

**Правила миграций (обязательны для всех разработчиков):**

```
✅ Имя файла: YYYYMMDD_NNNN_describe_change.py
✅ Каждая миграция имеет downgrade()
✅ Индексы: CREATE INDEX CONCURRENTLY (не блокируют)
✅ Новые колонки: WITH DEFAULT (zero-downtime deploy)
❌ Никогда не редактировать существующие миграции
❌ Никогда не удалять колонки без deprecation периода
```

---

## Шаг 8 — Стратегия Alembic merge heads при параллельной разработке

> При слиянии 10 веток в `develop` каждая ветка может добавить свою миграцию.
> Это создаст несколько `head`-ревизий — Alembic откажется применять без явного merge.

```bash
# Симптом проблемы:
alembic upgrade head
# ERROR: Multiple head revisions are present for given argument 'head'

# Решение 1 — alembic merge (выполнить в ветке develop после merge PR):
alembic merge heads -m "merge_wave_1_migrations"
# Создаст новый файл миграции, объединяющий все heads в один.
# Содержимое: пустой up/down, только объявление зависимостей.

# Решение 2 — явный merge конкретных хэшей:
alembic merge abc123 def456 ghi789 -m "merge_after_wave1_merge"

# Проверить текущее состояние:
alembic heads      # показывает все активные heads
alembic current    # текущая ревизия в БД

# ПРАВИЛА для разработчиков:
# 1. Каждый этап (TZ-01..TZ-11) создаёт РОВНО ОДНУ миграцию с depends_on = "initial_schema"
# 2. Имя: alembic revision --autogenerate -m "tz_NN_add_XXX_tables"
# 3. НЕ менять down_revision вручную — Alembic сам разрулит при merge heads
```

```python
# Пример: правильная миграция от разработчика TZ-01 (auth)
# alembic/versions/20260221_0002_tz_01_auth_tables.py
revision = "0002_tz01_auth"
down_revision = "0001_initial_schema"   # ← TZ-00 SPLIT-2 baseline
branch_labels = None
depends_on = None

def upgrade() -> None:
    # TZ-01 добавляет только свои таблицы (api_keys) — refresh_tokens уже в initial_schema
    op.create_table("api_keys", ...)
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

def downgrade() -> None:
    op.drop_index("ix_api_keys_key_hash", "api_keys")
    op.drop_table("api_keys")
```

---

## Шаг 9 — backend/requirements.txt

```
fastapi==0.109.2
uvicorn[standard]==0.27.1
sqlalchemy[asyncio]==2.0.28
asyncpg==0.29.0
alembic==1.13.1
pydantic==2.6.3
pydantic-settings==2.2.1
pyjwt[crypto]==2.8.0
bcrypt==4.1.2
redis[asyncio]==5.0.3
aiohttp==3.9.3
prometheus-client==0.20.0
slowapi==0.1.9
apscheduler==3.10.4
structlog==24.1.0
pytest==8.0.2
pytest-asyncio==0.23.5
httpx==0.27.0
bandit==1.7.7
ruff==0.3.0
mypy==1.8.0
# MED-2: добавлены отсутствующие пакеты
msgpack>=1.0.7          # TZ-02 DeviceStatusCache (бинарная сериализация 5x компактнее JSON)
circuitbreaker>=2.0.0   # TZ-06 WG Router circuit breaker
qrcode[pil]>=7.4        # TZ-06 генерация VPN QR-кода
pyotp>=2.9.0            # TZ-01 MFA TOTP
minio>=7.2.0            # TZ-04 хранение скриншотов устройств
fakeredis>=2.21.0       # тесты: in-memory Redis mock без Docker
pytest-mock>=3.12.0     # тесты: mock/patch для внешних зависимостей
```

---

## Шаг 9.1 — Стратегия Enum-миграций

> **MED-3:** `ALTER TYPE ... ADD VALUE` нельзя выполнять внутри транзакции (PostgreSQL < 12).

```python
# alembic/versions/XXX_add_taskstatus_paused.py
def upgrade():
    # ДО: выполняется вне транзакции (connection.execute, не op.execute)
    connection = op.get_bind()
    connection.execution_options(isolation_level="AUTOCOMMIT")
    connection.execute(sa.text("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'paused'"))
    # После ALTER TYPE: вернуть isolation_level обратно

def downgrade():
    # PostgreSQL не поддерживает DROP VALUE — downgrade требует пересоздания таблиц.
    pass  # документируем невозможность автоматического отката
```

---

## Шаг 10 — tests/conftest.py (Канонический — все ветки наследуют)

> **PROC-2:** Единый `conftest.py` для всего проекта. Разработчики TZ-01..11 **НЕ КОПИРУЮТ** этот файл — только используют фикстуры через `import` или наследование `conftest`-стека pytest.

```python
# tests/conftest.py — КАНОНИЧНЫЙ (все ветки наследуют, НЕ КОПИРОВАТЬ)
import uuid
import pytest
import pytest_asyncio
import fakeredis
from unittest.mock import AsyncMock
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from backend.database.engine import Base
from backend.websocket.pubsub_router import PubSubPublisher
from backend.services.device_status_cache import CacheService

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"
TEST_ORG = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")

_test_engine = create_async_engine(TEST_DB_URL, echo=False)
_async_session_factory = async_sessionmaker(
    _test_engine, class_=AsyncSession, expire_on_commit=False
)


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite session — не требует запущенного PostgreSQL."""
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with _async_session_factory() as session:
        yield session
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def mock_redis():
    """Fake Redis — без Docker, полностью in-memory."""
    return fakeredis.aioredis.FakeRedis()


@pytest.fixture
def mock_publisher():
    """Mock PubSubPublisher для тестирования без реального Redis."""
    m = AsyncMock(spec=PubSubPublisher)
    m.send_command_to_device.return_value = True
    return m


@pytest.fixture
def mock_cache():
    """Mock CacheService — возвращает None по умолчанию."""
    return AsyncMock(spec=CacheService)


# ━━━ Фабрики моделей (ORM INSERT) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest_asyncio.fixture
async def test_org(db_session):
    """Тестовая организация — базовая fixture для всех ТЗ."""
    from backend.models.organization import Organization
    org = Organization(id=TEST_ORG, name="test_org", slug="test-org")
    db_session.add(org)
    await db_session.flush()
    return org


@pytest_asyncio.fixture
async def test_user(db_session, test_org):
    """Тестовый пользователь (org_admin) — для auth и RLS."""
    from backend.models.user import User
    user = User(
        id=TEST_USER_ID,
        org_id=test_org.id,
        email="admin@test.org",
        password_hash="$2b$12$fakehashfakehashfakehashfakehashfakehash",
        role="org_admin",
        is_active=True,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def test_device(db_session, test_org):
    """Тестовое устройство — для TZ-02, TZ-03, TZ-04, TZ-05, TZ-06."""
    from backend.models.device import Device
    device = Device(
        id="test:5555",
        org_id=test_org.id,
        name="Test Device",
        type="ldplayer",
    )
    db_session.add(device)
    await db_session.flush()
    return device


@pytest_asyncio.fixture
async def test_script(db_session, test_org):
    """Тестовый скрипт — для TZ-04."""
    from backend.models.script import Script
    script = Script(
        org_id=test_org.id,
        name="Test Script",
        description="test",
    )
    db_session.add(script)
    await db_session.flush()
    return script


@pytest_asyncio.fixture
async def test_vpn_peer(db_session, test_org):
    """Тестовый VPN peer — для TZ-06."""
    from backend.models.vpn_peer import VPNPeer
    peer = VPNPeer(
        org_id=test_org.id,
        assigned_ip="10.100.0.1",
        status="free",
    )
    db_session.add(peer)
    await db_session.flush()
    return peer


# ━━━ HTTP client + auth ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest_asyncio.fixture
async def authenticated_client(db_session, test_user, monkeypatch):
    """
    Async HTTP client с авторизованным пользователем.
    Подменяет get_db и get_current_user — тесты не требуют реального JWT.
    """
    from httpx import AsyncClient, ASGITransport
    from backend.main import app
    from backend.database.engine import get_db
    from backend.core.dependencies import get_current_user

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: test_user

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        yield client

    app.dependency_overrides.clear()


# ━━━ RLS context ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@pytest_asyncio.fixture
async def tenant_session(db_session, test_org):
    """
    Session с установленным RLS контекстом.
    Для SQLite RLS не работает — fixture просто возвращает db_session.
    Для PostgreSQL (CI): выполняет SET LOCAL app.current_org_id.
    """
    # SQLite не поддерживает SET LOCAL — пропускаем
    if "sqlite" in str(db_session.bind.url):
        yield db_session
    else:
        from sqlalchemy import text
        await db_session.execute(
            text(f"SET LOCAL app.current_org_id = '{test_org.id}'")
        )
        yield db_session
```

---

## Критерии готовности

- [ ] `alembic upgrade head` отрабатывает без ошибок
- [ ] `alembic downgrade -1` → `alembic upgrade head` работает корректно
- [ ] Все 35+ таблиц созданы с правильными индексами
- [ ] Audit log — нельзя UPDATE/DELETE через политики RLS
- [ ] **RLS включён** на users, devices, scripts, tasks, device_groups — запросы без org_id возвращают пустой результат
- [ ] **Tenant middleware** устанавливает `app.current_org_id` в начале каждого запроса
- [ ] `make test` проходит с тестами на модели
- [ ] PgBouncer конфиг готов к использованию
