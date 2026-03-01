# TZ-12 SPLIT-3 — Модель событий агента: обратная связь, детекция банов и управление аккаунтами

> **Статус:** Draft  
> **Приоритет:** P0 (критическая подсистема)  
> **Зависимости:** TZ-07 (Android Agent), TZ-04 (Task Engine), SPLIT-1 (Lifecycle)

---

## 1. Мотивация

**Текущие ограничения:**
- Агент отправляет только 4 типа сообщений: `pong` (телеметрия), `task_progress`, `command_result`, `auth`
- **Нет механизма отправки игровых состояний** (бан, капча, вылет из аккаунта, ошибка входа)
- **Нет таблиц аккаунтов** — система не знает, какой аккаунт на каком устройстве
- **События не персистируются** — Redis TTL 10 мин, потом теряются навсегда
- **EventType** имеет 12 значений, но 4 из них — заглушки (STREAM_STARTED/STOPPED, COMMAND_STARTED, ALERT_TRIGGERED)
- **Нет реакции на события** — система write-only: агент шлёт, бэкенд пробрасывает в браузер, никто не анализирует

**Целевое состояние:**
- Агент детектирует игровые состояния (бан, капча, заморозка, успешный вход) и шлёт **структурированные события**
- Бэкенд **персистирует** все события в БД с полной историей
- **Оркестратор реагирует** на события: бан → стоп скрипт → пометить аккаунт → взять следующий
- Полное управление **пулом аккаунтов**: привязка к устройствам, статусы, ротация
- **n8n триггеры** на любые события для кастомных workflow

---

## 2. Новые сущности базы данных

### 2.1 Таблица game_accounts — Пул аккаунтов

```python
class AccountStatus(str, Enum):
    """Статус игрового аккаунта."""
    IDLE = "idle"               # Свободен, готов к использованию
    IN_USE = "in_use"           # Активно используется на устройстве
    BANNED = "banned"           # Заблокирован (перманентно)
    SUSPENDED = "suspended"     # Временная блокировка
    CAPTCHA = "captcha"         # Требуется ручное решение капчи
    COOLDOWN = "cooldown"       # Кулдаун после использования
    ERROR = "error"             # Ошибка входа / невалидные данные
    RETIRED = "retired"         # Выведен из оборота вручную


class GameAccount(Base, UUIDMixin, TimestampMixin):
    """Игровой аккаунт для автоматизации."""
    __tablename__ = "game_accounts"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    
    # Идентификация
    game_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="ID игры: blackrussia, gta5rp, etc.")
    login: Mapped[str] = mapped_column(String(256), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False, comment="AES-256-GCM encrypted")
    
    # Статус
    status: Mapped[AccountStatus] = mapped_column(
        SQLAlchemyEnum(AccountStatus), default=AccountStatus.IDLE, nullable=False, index=True
    )
    status_reason: Mapped[str | None] = mapped_column(Text, comment="Причина текущего статуса")
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    
    # Привязка к устройству
    device_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("devices.id"), nullable=True, index=True,
        comment="Устройство, на котором аккаунт сейчас залогинен"
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Метаданные
    level: Mapped[int | None] = mapped_column(Integer, comment="Уровень персонажа (из игры)")
    balance: Mapped[float | None] = mapped_column(Float, comment="Баланс в игре")
    meta: Mapped[dict] = mapped_column(JSONB, default=dict, comment="Произвольные данные (сервер, персонаж, итд.)")
    
    # Кулдаун
    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), comment="Нельзя использовать до этого времени"
    )
    
    # Статистика
    total_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_bans: Mapped[int] = mapped_column(Integer, default=0)
    last_ban_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # RLS
    __table_args__ = (
        UniqueConstraint("org_id", "game_id", "login", name="uq_account_per_game"),
        Index("ix_game_accounts_status_game", "org_id", "game_id", "status"),
    )
```

### 2.2 Таблица device_events — Персистентное хранилище событий

```python
class DeviceEventSeverity(str, Enum):
    """Уровень важности события."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class DeviceEvent(Base, UUIDMixin):
    """Персистентное событие от устройства / агента.
    
    Каждое событие иммутабельно (append-only).
    Хранится в БД + дублируется в Redis для real-time доставки.
    """
    __tablename__ = "device_events"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    
    # Классификация
    event_type: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True,
        comment="Тип события: account.banned, game.crashed, script.completed, etc."
    )
    severity: Mapped[DeviceEventSeverity] = mapped_column(
        SQLAlchemyEnum(DeviceEventSeverity), default=DeviceEventSeverity.INFO
    )
    
    # Контекст
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("game_accounts.id"), nullable=True)
    script_id: Mapped[UUID | None] = mapped_column(ForeignKey("scripts.id"), nullable=True)
    
    # Данные
    message: Mapped[str] = mapped_column(Text, nullable=False, comment="Человекочитаемое описание")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, comment="Структурированные данные события")
    
    # Время
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
        comment="Когда произошло (время агента)"
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        comment="Когда получено бэкендом"
    )
    
    __table_args__ = (
        Index("ix_device_events_org_type_time", "org_id", "event_type", "occurred_at"),
        Index("ix_device_events_account", "account_id", "occurred_at"),
    )
```

### 2.3 Таблица account_sessions — История сессий аккаунта

```python
class AccountSession(Base, UUIDMixin):
    """Сессия использования аккаунта на устройстве.
    
    Одна сессия = один непрерывный период работы аккаунта.
    """
    __tablename__ = "account_sessions"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    account_id: Mapped[UUID] = mapped_column(ForeignKey("game_accounts.id"), nullable=False, index=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), nullable=False)
    task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    end_reason: Mapped[str | None] = mapped_column(
        String(32), comment="completed, banned, crashed, timeout, manual_stop"
    )
    
    # Метрики сессии
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    nodes_executed: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
```

---

## 3. Расширенная модель событий агента

### 3.1 Каталог типов событий

| Тип события | Severity | Триггер | Реакция оркестратора |
|-------------|----------|---------|---------------------|
| `account.logged_in` | info | Успешный вход в игру | Обновить account.status = IN_USE |
| `account.login_failed` | error | Неверный пароль / ошибка входа | Пометить ERROR, попробовать следующий |
| `account.banned` | critical | Детекция бана в игре | STOP скрипт → status=BANNED → ротация |
| `account.suspended` | warning | Временная блокировка | PAUSE → status=SUSPENDED → cooldown |
| `account.captcha` | warning | Всплыла капча | PAUSE → уведомление оператору |
| `account.kicked` | warning | Кик с сервера | Retry login или ротация |
| `account.level_up` | info | Повышение уровня | Обновить account.level |
| `account.balance_changed` | info | Изменение баланса | Обновить account.balance |
| `game.crashed` | error | Игра вылетела | Restart app + retry |
| `game.update_required` | critical | Версия игры устарела | STOP всё + уведомление |
| `script.checkpoint` | debug | DAG дошёл до контрольной точки | Логирование для аналитики |
| `agent.low_storage` | warning | < 500MB свободного места | Очистка кеша + уведомление |
| `agent.error` | error | Необработанная ошибка агента | Логирование + уведомление |

### 3.2 Протокол: Agent → Backend

Новый тип WS-сообщения `agent_event`:

```json
{
    "type": "agent_event",
    "event_type": "account.banned",
    "severity": "critical",
    "occurred_at": 1740700000.123,
    "task_id": "ce44ef91-...",
    "account_id": "a1b2c3d4-...",
    "message": "Обнаружен бан аккаунта: текст 'Ваш аккаунт заблокирован' на экране",
    "payload": {
        "detection_method": "screen_text",
        "matched_text": "Ваш аккаунт заблокирован",
        "screenshot_ref": "s3://screenshots/ban_2025_01_15_12_30.png",
        "node_id": "check_ban_screen",
        "game_id": "blackrussia"
    }
}
```

### 3.3 Как агент детектирует состояния

Детекция реализуется через **DAG condition-ноды** и новый тип действия `emit_event`:

```json
{
    "id": "check_ban",
    "action": "find_on_screen",
    "params": {
        "text": "заблокирован|banned|suspended",
        "regex": true,
        "save_to": "ban_detected"
    },
    "on_success": "emit_ban_event",
    "on_failure": "continue_script"
},
{
    "id": "emit_ban_event",
    "action": "emit_event",
    "params": {
        "event_type": "account.banned",
        "severity": "critical",
        "message": "Бан обнаружен по тексту на экране",
        "include_screenshot": true,
        "stop_dag": true
    },
    "on_success": "__end__"
}
```

**Новое действие DagRunner: `emit_event`**

```kotlin
// DagRunner.kt — новый action handler
"emit_event" -> {
    val eventType = params.str("event_type") ?: error("emit_event: event_type required")
    val severity = params.str("severity") ?: "info"
    val message = params.str("message") ?: eventType
    val includeScreenshot = params.bool("include_screenshot") == true
    val stopDag = params.bool("stop_dag") == true

    val payload = buildJsonObject {
        // Копируем все params кроме служебных
        params.forEach { (k, v) ->
            if (k !in setOf("event_type", "severity", "message", "include_screenshot", "stop_dag")) {
                put(k, v)
            }
        }
        // Скриншот
        if (includeScreenshot) {
            val screenshotBase64 = adbExecutor.takeScreenshot()
            if (screenshotBase64 != null) {
                put("screenshot_base64", JsonPrimitive(screenshotBase64))
            }
        }
        // Контекст DAG
        put("node_id", JsonPrimitive(nodeId))
        put("dag_node_index", JsonPrimitive(nodesExecuted))
    }

    // Отправить событие через WebSocket
    wsClient.sendJson(buildJsonObject {
        put("type", JsonPrimitive("agent_event"))
        put("event_type", JsonPrimitive(eventType))
        put("severity", JsonPrimitive(severity))
        put("occurred_at", JsonPrimitive(System.currentTimeMillis() / 1000.0))
        put("task_id", JsonPrimitive(commandId))
        put("message", JsonPrimitive(message))
        put("payload", payload)
    })

    if (stopDag) {
        Timber.w("[DAG] emit_event stop_dag=true, stopping DAG")
        cancelRequested = true
    }
    
    ActionResult.Success(mapOf("event_sent" to eventType))
}
```

---

## 4. Backend: обработка и реакция на события

### 4.1 Обработчик agent_event

```python
# backend/api/ws/android/router.py

async def handle_agent_event(
    device_id: str,
    org_id: str,
    msg: dict,
    db: AsyncSession,
    event_publisher: EventPublisher,
) -> None:
    """Обработка структурированного события от агента.
    
    1. Валидация и персистенция в device_events
    2. Обновление связанных сущностей (аккаунт, устройство)
    3. Публикация FleetEvent для real-time доставки
    4. Вызов EventReactor для автоматических реакций
    """
    event_type = msg.get("event_type", "unknown")
    severity = msg.get("severity", "info")
    
    # 1. Персистенция
    device_event = DeviceEvent(
        org_id=UUID(org_id),
        device_id=UUID(device_id),
        event_type=event_type,
        severity=DeviceEventSeverity(severity),
        task_id=UUID(msg["task_id"]) if msg.get("task_id") else None,
        account_id=UUID(msg["account_id"]) if msg.get("account_id") else None,
        message=msg.get("message", event_type),
        payload=msg.get("payload", {}),
        occurred_at=datetime.fromtimestamp(msg.get("occurred_at", 0), tz=timezone.utc),
    )
    db.add(device_event)
    
    # 2. Скриншот → S3 (если есть)
    screenshot_b64 = msg.get("payload", {}).get("screenshot_base64")
    if screenshot_b64:
        s3_key = f"events/{org_id}/{device_id}/{device_event.id}.png"
        await upload_to_s3(s3_key, base64.b64decode(screenshot_b64))
        device_event.payload["screenshot_url"] = s3_key
        del device_event.payload["screenshot_base64"]  # Не хранить base64 в JSONB
    
    await db.flush()

    # 3. Публикация real-time event
    await event_publisher.emit(FleetEvent(
        event_type=EventType.DEVICE_STATUS_CHANGE,
        device_id=device_id,
        org_id=org_id,
        payload={
            "agent_event_type": event_type,
            "severity": severity,
            "message": device_event.message,
            "event_id": str(device_event.id),
        }
    ))

    # 4. Автоматическая реакция
    await event_reactor.handle(device_event, db)
    
    await db.commit()
```

### 4.2 EventReactor — движок автоматических реакций

```python
# backend/services/event_reactor.py

class EventReactor:
    """Реактор на события агента.
    
    Содержит набор правил (handlers) для каждого типа события.
    Каждый handler может: обновить аккаунт, остановить таск, 
    назначить новый аккаунт, отправить уведомление.
    """
    
    def __init__(self, task_service, account_service, notification_service):
        self._handlers: dict[str, Callable] = {
            "account.banned": self._on_account_banned,
            "account.suspended": self._on_account_suspended,
            "account.captcha": self._on_account_captcha,
            "account.login_failed": self._on_account_login_failed,
            "account.logged_in": self._on_account_logged_in,
            "account.kicked": self._on_account_kicked,
            "account.level_up": self._on_account_level_up,
            "account.balance_changed": self._on_account_balance_changed,
            "game.crashed": self._on_game_crashed,
            "game.update_required": self._on_game_update_required,
        }

    async def handle(self, event: DeviceEvent, db: AsyncSession) -> None:
        handler = self._handlers.get(event.event_type)
        if handler:
            await handler(event, db)

    async def _on_account_banned(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Реакция на бан аккаунта:
        1. Пометить аккаунт как BANNED
        2. Завершить сессию
        3. Остановить текущий таск
        4. Ротация: назначить следующий свободный аккаунт
        5. Уведомление оператору
        """
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                account.status = AccountStatus.BANNED
                account.status_reason = event.message
                account.status_changed_at = datetime.now(timezone.utc)
                account.total_bans += 1
                account.last_ban_at = datetime.now(timezone.utc)
                account.device_id = None  # Открепить от устройства

        # Завершить активную сессию
        await self._end_account_session(event, db, reason="banned")

        # Остановить таск
        if event.task_id:
            await self.task_service.cancel_task(event.task_id, reason="account_banned")

        # Уведомление
        await self.notification_service.notify(
            org_id=event.org_id,
            level="critical",
            title=f"Аккаунт забанен на устройстве {event.device_id}",
            body=event.message,
        )

    async def _on_account_suspended(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Временная блокировка: пауза + cooldown."""
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                account.status = AccountStatus.SUSPENDED
                account.status_reason = event.message
                # Кулдаун 2 часа по умолчанию
                cooldown_hours = event.payload.get("cooldown_hours", 2)
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=cooldown_hours)

        if event.task_id:
            await self.task_service.pause_task(event.task_id, reason="account_suspended")

    async def _on_account_captcha(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Капча: пауза + уведомление оператору для ручного решения."""
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                account.status = AccountStatus.CAPTCHA

        if event.task_id:
            await self.task_service.pause_task(event.task_id, reason="captcha_required")

        await self.notification_service.notify(
            org_id=event.org_id,
            level="warning",
            title=f"Капча на устройстве {event.device_id}",
            body="Требуется ручное решение капчи",
            action_url=f"/devices/{event.device_id}/stream",  # Ссылка на стрим
        )

    async def _on_account_logged_in(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Успешный вход: обновить привязку аккаунта."""
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                account.status = AccountStatus.IN_USE
                account.device_id = event.device_id
                account.assigned_at = datetime.now(timezone.utc)
                account.total_sessions += 1

        # Создать новую сессию
        session = AccountSession(
            org_id=event.org_id,
            account_id=event.account_id,
            device_id=event.device_id,
            task_id=event.task_id,
            started_at=event.occurred_at,
        )
        db.add(session)

    async def _on_account_kicked(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Кик с сервера: попытка переподключения."""
        await self._end_account_session(event, db, reason="kicked")
        # Оркестратор решит: retry или ротация

    async def _on_account_level_up(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Повышение уровня: обновить метаданные."""
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                account.level = event.payload.get("new_level", (account.level or 0) + 1)

    async def _on_account_balance_changed(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Изменение баланса: обновить метаданные."""
        if event.account_id:
            account = await db.get(GameAccount, event.account_id)
            if account:
                new_balance = event.payload.get("balance")
                if new_balance is not None:
                    account.balance = float(new_balance)

    async def _on_game_crashed(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Вылет игры: пометить ошибку, оркестратор решит restart."""
        await self._end_account_session(event, db, reason="crashed")

    async def _on_game_update_required(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Обновление игры: остановить ВСЕ таски для этой игры."""
        await self.notification_service.notify(
            org_id=event.org_id,
            level="critical",
            title="Требуется обновление игры",
            body=f"Игра требует обновления на устройстве {event.device_id}",
        )

    async def _end_account_session(
        self, event: DeviceEvent, db: AsyncSession, reason: str,
    ) -> None:
        """Завершить активную сессию аккаунта."""
        if not event.account_id:
            return
        session = await db.scalar(
            select(AccountSession)
            .where(AccountSession.account_id == event.account_id)
            .where(AccountSession.ended_at.is_(None))
            .order_by(AccountSession.started_at.desc())
        )
        if session:
            session.ended_at = datetime.now(timezone.utc)
            session.end_reason = reason
            session.duration_seconds = int(
                (session.ended_at - session.started_at).total_seconds()
            )
```

---

## 5. Сервис управления аккаунтами

### 5.1 AccountService

```python
# backend/services/account_service.py

class AccountService:
    """Управление пулом игровых аккаунтов.
    
    Ответственности:
    - CRUD аккаунтов (с шифрованием паролей)
    - Назначение аккаунтов на устройства
    - Ротация при бане/ошибке
    - Кулдаун-менеджмент
    - Статистика и аналитика
    """

    async def assign_account(
        self,
        device_id: UUID,
        game_id: str,
        org_id: UUID,
        db: AsyncSession,
        *,
        exclude_ids: list[UUID] | None = None,
        strategy: str = "round_robin",
    ) -> GameAccount | None:
        """Назначить свободный аккаунт на устройство.
        
        Стратегии:
        - round_robin: самый давно не использовавшийся
        - least_bans: с наименьшим количеством банов
        - random: случайный из пула
        
        Returns: GameAccount или None если пул исчерпан.
        """
        now = datetime.now(timezone.utc)
        
        query = (
            select(GameAccount)
            .where(GameAccount.org_id == org_id)
            .where(GameAccount.game_id == game_id)
            .where(GameAccount.status == AccountStatus.IDLE)
            .where(
                or_(
                    GameAccount.cooldown_until.is_(None),
                    GameAccount.cooldown_until <= now,
                )
            )
        )
        
        if exclude_ids:
            query = query.where(GameAccount.id.notin_(exclude_ids))

        if strategy == "round_robin":
            query = query.order_by(GameAccount.assigned_at.asc().nullsfirst())
        elif strategy == "least_bans":
            query = query.order_by(GameAccount.total_bans.asc())
        else:  # random
            query = query.order_by(func.random())

        query = query.with_for_update(skip_locked=True).limit(1)
        
        account = await db.scalar(query)
        if not account:
            return None

        account.status = AccountStatus.IN_USE
        account.device_id = device_id
        account.assigned_at = now
        account.status_changed_at = now
        
        return account

    async def release_account(
        self,
        account_id: UUID,
        db: AsyncSession,
        *,
        cooldown_minutes: int = 0,
    ) -> None:
        """Освободить аккаунт после использования."""
        account = await db.get(GameAccount, account_id)
        if not account:
            return
        
        account.status = AccountStatus.COOLDOWN if cooldown_minutes > 0 else AccountStatus.IDLE
        account.device_id = None
        account.status_changed_at = datetime.now(timezone.utc)
        
        if cooldown_minutes > 0:
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=cooldown_minutes)

    async def rotate_account(
        self,
        device_id: UUID,
        current_account_id: UUID,
        game_id: str,
        org_id: UUID,
        db: AsyncSession,
        *,
        ban_current: bool = False,
    ) -> GameAccount | None:
        """Ротация: заменить текущий аккаунт на новый.
        
        1. Пометить текущий аккаунт (banned/idle)
        2. Назначить следующий из пула
        """
        current = await db.get(GameAccount, current_account_id)
        if current:
            if ban_current:
                current.status = AccountStatus.BANNED
                current.total_bans += 1
                current.last_ban_at = datetime.now(timezone.utc)
            else:
                current.status = AccountStatus.IDLE
            current.device_id = None
        
        return await self.assign_account(
            device_id=device_id,
            game_id=game_id,
            org_id=org_id,
            db=db,
            exclude_ids=[current_account_id],
        )

    async def get_pool_stats(
        self, org_id: UUID, game_id: str, db: AsyncSession,
    ) -> dict:
        """Статистика пула аккаунтов."""
        rows = await db.execute(
            select(GameAccount.status, func.count())
            .where(GameAccount.org_id == org_id)
            .where(GameAccount.game_id == game_id)
            .group_by(GameAccount.status)
        )
        stats = dict(rows.all())
        return {
            "total": sum(stats.values()),
            "idle": stats.get(AccountStatus.IDLE, 0),
            "in_use": stats.get(AccountStatus.IN_USE, 0),
            "banned": stats.get(AccountStatus.BANNED, 0),
            "suspended": stats.get(AccountStatus.SUSPENDED, 0),
            "cooldown": stats.get(AccountStatus.COOLDOWN, 0),
            "error": stats.get(AccountStatus.ERROR, 0),
        }
```

---

## 6. REST API эндпоинты

### 6.1 Аккаунты

```
POST   /api/v1/accounts                    — Создать аккаунт (bulk import)
GET    /api/v1/accounts                    — Список аккаунтов (фильтры: game_id, status)
GET    /api/v1/accounts/{id}               — Детали аккаунта + история сессий
PATCH  /api/v1/accounts/{id}               — Обновить метаданные
DELETE /api/v1/accounts/{id}               — Удалить аккаунт
POST   /api/v1/accounts/{id}/assign        — Назначить на устройство
POST   /api/v1/accounts/{id}/release       — Освободить
POST   /api/v1/accounts/import             — Bulk-импорт из CSV/JSON
GET    /api/v1/accounts/pool-stats         — Статистика пула по играм
```

### 6.2 События

```
GET    /api/v1/events                       — Список событий (фильтры: device_id, event_type, severity, date range)
GET    /api/v1/events/{id}                  — Детали события
GET    /api/v1/events/stats                 — Аналитика: количество по типам за период
GET    /api/v1/devices/{id}/events          — События конкретного устройства
GET    /api/v1/accounts/{id}/events         — События конкретного аккаунта
```

---

## 7. Расширение EventType (backend/schemas/events.py)

```python
class EventType(str, Enum):
    # Существующие
    DEVICE_ONLINE = "device.online"
    DEVICE_OFFLINE = "device.offline"
    DEVICE_STATUS_CHANGE = "device.status_change"
    COMMAND_COMPLETED = "command.completed"
    COMMAND_FAILED = "command.failed"
    TASK_PROGRESS = "task.progress"
    VPN_ASSIGNED = "vpn.assigned"
    VPN_FAILED = "vpn.failed"
    
    # Новые: аккаунты
    ACCOUNT_BANNED = "account.banned"
    ACCOUNT_SUSPENDED = "account.suspended"
    ACCOUNT_CAPTCHA = "account.captcha"
    ACCOUNT_LOGGED_IN = "account.logged_in"
    ACCOUNT_LOGIN_FAILED = "account.login_failed"
    ACCOUNT_ROTATED = "account.rotated"
    
    # Новые: игра
    GAME_CRASHED = "game.crashed"
    GAME_UPDATE_REQUIRED = "game.update_required"
    
    # Новые: агент
    AGENT_EVENT = "agent.event"  # Обобщённый тип от агента
    ALERT_TRIGGERED = "alert.triggered"
```

---

## 8. n8n интеграция

### 8.1 Расширение EventTrigger ноды

Существующая `EventTrigger` нода в `n8n-nodes/` должна подписаться на новые типы:

```typescript
// n8n-nodes/nodes/EventTrigger/EventTrigger.node.ts
{
    displayName: 'Event Types',
    name: 'eventTypes',
    type: 'multiOptions',
    options: [
        // Существующие...
        { name: 'Account Banned', value: 'account.banned' },
        { name: 'Account Suspended', value: 'account.suspended' },
        { name: 'Account Captcha', value: 'account.captcha' },
        { name: 'Game Crashed', value: 'game.crashed' },
        { name: 'Account Rotated', value: 'account.rotated' },
    ],
}
```

### 8.2 Пример n8n Workflow: Автоматическая ротация при бане

```
[EventTrigger: account.banned]
    → [DevicePool: получить свободный аккаунт]
    → [ExecuteScript: запуск логин-скрипта с новым аккаунтом]
    → [IF: аккаунт успешно залогинен]
        → YES: [ExecuteScript: запуск основного скрипта]
        → NO:  [Slack Notification: "Пул аккаунтов исчерпан"]
```

---

## 9. Frontend: Dashboard событий

### 9.1 Компоненты

| Компонент | Описание |
|-----------|----------|
| `EventsTimeline` | Хронологический таймлайн событий с фильтрами |
| `AccountPoolDashboard` | Визуализация: idle/in_use/banned/cooldown pie chart |
| `AccountTable` | DataTable аккаунтов с действиями (assign/release/retire) |
| `BanAlertBanner` | Real-time уведомление при бане |
| `AccountImportDialog` | Массовый импорт аккаунтов из CSV |

### 9.2 Real-time обновления

Через существующий `events` WebSocket — фронтенд уже подписан. Новые типы событий будут приходить автоматически через `EventsManager`.

---

## 10. Безопасность

### 10.1 Шифрование паролей аккаунтов

```python
# AES-256-GCM с ключом из переменной окружения
ACCOUNT_ENCRYPTION_KEY = os.environ["ACCOUNT_ENCRYPTION_KEY"]  # 32 bytes, base64

def encrypt_password(plaintext: str) -> str:
    """Шифрование пароля аккаунта AES-256-GCM."""
    key = base64.b64decode(ACCOUNT_ENCRYPTION_KEY)
    nonce = os.urandom(12)
    cipher = AESGCM(key)
    ct = cipher.encrypt(nonce, plaintext.encode(), None)
    return base64.b64encode(nonce + ct).decode()

def decrypt_password(ciphertext: str) -> str:
    """Расшифровка пароля аккаунта."""
    key = base64.b64decode(ACCOUNT_ENCRYPTION_KEY)
    data = base64.b64decode(ciphertext)
    nonce, ct = data[:12], data[12:]
    cipher = AESGCM(key)
    return cipher.decrypt(nonce, ct, None).decode()
```

### 10.2 RLS для аккаунтов

```sql
ALTER TABLE game_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY game_accounts_org_policy ON game_accounts
    USING (org_id = current_setting('app.current_org_id')::uuid);
```

### 10.3 Ограничения

- Пароли аккаунтов **никогда** не возвращаются в API ответах
- Скриншоты банов хранятся в S3 с TTL 30 дней
- device_events: автоматическая partition по месяцам для быстрых запросов

---

## 11. Таблица изменений

| Компонент | Файл | Что менять |
|-----------|------|-----------|
| Backend | `models/game_account.py` | NEW: GameAccount, AccountSession models |
| Backend | `models/device_event.py` | NEW: DeviceEvent model |
| Backend | `services/account_service.py` | NEW: AccountService (CRUD, assign, rotate) |
| Backend | `services/event_reactor.py` | NEW: EventReactor (автореакции на события) |
| Backend | `api/v1/accounts/router.py` | NEW: REST API аккаунтов |
| Backend | `api/v1/events/router.py` | NEW: REST API событий |
| Backend | `api/ws/android/router.py` | + handle_agent_event() |
| Backend | `schemas/events.py` | + новые EventType значения |
| Backend | `alembic/versions/` | Миграция: game_accounts, device_events, account_sessions |
| Android | `DagRunner.kt` | + emit_event action handler |
| Android | `CommandDispatcher.kt` | + обработка dag_payload ответов |
| n8n | `EventTrigger.node.ts` | + новые типы событий |
| Frontend | `components/events/` | NEW: EventsTimeline, AccountPoolDashboard |
| Frontend | `components/accounts/` | NEW: AccountTable, AccountImportDialog |

---

## 12. Критерии готовности

- [ ] Таблицы game_accounts, device_events, account_sessions созданы с RLS
- [ ] Пароли аккаунтов шифруются AES-256-GCM
- [ ] Агент отправляет agent_event через WebSocket
- [ ] emit_event — новый тип действия в DagRunner
- [ ] EventReactor обрабатывает все 10+ типов событий
- [ ] Автоматическая ротация аккаунтов при бане
- [ ] AccountService: assign/release/rotate с FOR UPDATE SKIP LOCKED
- [ ] device_events персистируются в БД (append-only)
- [ ] Скриншоты банов сохраняются в S3
- [ ] REST API: CRUD аккаунтов + события с фильтрами
- [ ] n8n EventTrigger поддерживает новые типы
- [ ] Frontend: EventsTimeline + AccountPoolDashboard
- [ ] Тесты: EventReactor unit tests, AccountService integration tests
