# TZ-12 SPLIT-4 — Ядро оркестратора: Pipeline Engine, цепочки скриптов и автоматические реакции

> **Статус:** Draft  
> **Приоритет:** P0 (критическая подсистема)  
> **Зависимости:** SPLIT-1 (Lifecycle), SPLIT-3 (Event Model), TZ-04 (Task Engine), TZ-09 (n8n)

---

## 1. Мотивация

### 1.1 Текущие ограничения

На текущий момент система умеет:
- Запустить **один скрипт** на **одном устройстве** (`TaskService.create_task`)
- Запустить **один скрипт** на **пачке устройств** волнами (`BatchService.start_batch`)

**Чего не хватает:**

| Проблема | Пример |
|----------|--------|
| **Цепочки скриптов** | *"Залогинь аккаунт → прокачай до 5 уровня → включи фарм"* — три скрипта последовательно, с условиями перехода |
| **Условная логика между скриптами** | *"Если бан — ротация аккаунта → повтор входа. Если капча — пауза"* |
| **Взаимодействие с данными** | *"Прочитай ник из БД → подставь в скрипт. Запиши результат обратно в БД"* |
| **Реакция на события** | *"Агент сообщил: game.crashed → перезапустить игру → продолжить скрипт"* |
| **Интеграция с n8n** | *"Вызови n8n workflow для генерации ника → получи результат → подставь в DAG"* |
| **Параллельные потоки** | *"На одном устройстве параллельно: основной скрипт + watchdog проверки"* |

### 1.2 Целевое состояние

**Orchestrator Pipeline** — серверная сущность, описывающая **граф исполнения скриптов** с:
- Последовательными и параллельными шагами
- Условными переходами на основе событий
- Интеграцией с БД, n8n, внешними API
- Автоматическими реакциями на события агента
- Полной отказоустойчивостью и персистенцией состояния

---

## 2. Архитектура Pipeline Engine

### 2.1 Ключевые сущности

```
┌─────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR PIPELINE                        │
│                                                                 │
│  Pipeline (шаблон)                                              │
│    ├── PipelineStep[0]: assign_account (type: action)           │
│    ├── PipelineStep[1]: login_script (type: execute_script)     │
│    ├── PipelineStep[2]: check_login (type: condition)           │
│    │     ├── on_true → step[3]                                  │
│    │     └── on_false → step[7] (rotate_account)                │
│    ├── PipelineStep[3]: farm_script (type: execute_script)      │
│    ├── PipelineStep[4]: wait_event (type: wait_for_event)       │
│    │     ├── on: account.banned → step[7]                       │
│    │     ├── on: account.level_up → step[5]                     │
│    │     └── timeout: 3600s → step[6]                           │
│    ├── PipelineStep[5]: log_level (type: action)                │
│    ├── PipelineStep[6]: stop_farming (type: execute_script)     │
│    └── PipelineStep[7]: rotate_and_retry (type: action)         │
│                                                                 │
│  PipelineRun (инстанс)                                         │
│    ├── run_id, pipeline_id, device_id, status                   │
│    ├── current_step_index                                       │
│    ├── context: { account_id, login, nickname, ... }            │
│    └── step_results: [ {step_id, status, output, duration} ]    │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 Типы шагов (StepType)

| Тип | Описание | Пример |
|-----|----------|--------|
| `execute_script` | Запустить DAG-скрипт на устройстве, дождаться результата | Запуск login.dag |
| `condition` | Проверить условие (Lua/Python выражение или переменную) | `ctx.login_result == "success"` |
| `action` | Серверное действие: обновить БД, отправить HTTP, назначить аккаунт | `assign_account(device, game)` |
| `wait_for_event` | Ждать событие от агента с таймаутом | Ждать `account.banned` до 1 часа |
| `parallel` | Запустить несколько подшагов параллельно | Login + проверка VPN одновременно |
| `delay` | Пауза на заданное время | Подождать 30 секунд |
| `n8n_workflow` | Вызвать n8n workflow через webhook и получить результат | Сгенерировать ник через AI |
| `loop` | Повторить блок шагов N раз или пока условие true | Retry login 3 раза |
| `sub_pipeline` | Запустить другой pipeline как подпроцесс | Переиспользование логина |

---

## 3. Модели данных

### 3.1 Pipeline — Шаблон оркестрации

```python
class Pipeline(Base, UUIDMixin, TimestampMixin):
    """Шаблон оркестрации — граф шагов для исполнения.
    
    Pipeline — это переиспользуемый шаблон. Для запуска создаётся PipelineRun.
    Аналогия: Pipeline = Docker Image, PipelineRun = Docker Container.
    """
    __tablename__ = "pipelines"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    
    # Граф шагов (JSONB — полное описание pipeline)
    steps: Mapped[list[dict]] = mapped_column(JSONB, nullable=False, comment="Массив PipelineStep")
    
    # Входные параметры (schema для валидации)
    input_schema: Mapped[dict] = mapped_column(
        JSONB, default=dict,
        comment="JSON Schema входных параметров: game_id, credentials, etc."
    )
    
    # Глобальные настройки
    global_timeout_ms: Mapped[int] = mapped_column(
        Integer, default=86_400_000, comment="Максимальное время исполнения (мс), дефолт 24 часа"
    )
    max_retries: Mapped[int] = mapped_column(Integer, default=0, comment="Глобальный ретрай всего pipeline")
    
    # Версионирование
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    
    # Связь с играми/тегами для фильтрации
    tags: Mapped[list[str]] = mapped_column(JSONB, default=list)
    
    __table_args__ = (
        Index("ix_pipelines_org_active", "org_id", "is_active"),
    )
```

### 3.2 PipelineStep — JSON-структура шага

```python
# Не отдельная таблица — хранится как JSONB внутри Pipeline.steps
# Валидируется через Pydantic

class StepType(str, Enum):
    EXECUTE_SCRIPT = "execute_script"
    CONDITION = "condition"
    ACTION = "action"
    WAIT_FOR_EVENT = "wait_for_event"
    PARALLEL = "parallel"
    DELAY = "delay"
    N8N_WORKFLOW = "n8n_workflow"
    LOOP = "loop"
    SUB_PIPELINE = "sub_pipeline"


class PipelineStepSchema(BaseModel):
    """Pydantic-схема одного шага pipeline."""
    
    id: str = Field(description="Уникальный ID шага внутри pipeline")
    name: str = Field(description="Человекочитаемое имя")
    type: StepType
    
    # Навигация
    on_success: str | None = Field(None, description="ID следующего шага при успехе")
    on_failure: str | None = Field(None, description="ID следующего шага при ошибке")
    
    # Retry для конкретного шага
    retry: int = Field(0, ge=0, le=50)
    retry_delay_ms: int = Field(5000, description="Задержка между ретраями (мс)")
    timeout_ms: int = Field(300_000, description="Таймаут шага (мс)")
    
    # Параметры (зависят от type)
    params: dict = Field(default_factory=dict)
    
    class Config:
        use_enum_values = True


# Примеры params для каждого StepType:

# execute_script:
#   { "script_id": "uuid", "input_params": {"login": "{{ctx.login}}"}, "wait": true }

# condition:
#   { "expression": "ctx.login_result.success == true", "engine": "python" }
#   { "check": "variable_equals", "key": "login_status", "value": "ok" }

# action:
#   { "action": "assign_account", "game_id": "blackrussia", "strategy": "round_robin" }
#   { "action": "update_account", "set": {"level": "{{ctx.new_level}}"} }
#   { "action": "db_query", "query": "UPDATE ...", "params": {...} }
#   { "action": "http_request", "url": "...", "method": "POST", "body": {...} }

# wait_for_event:
#   { "events": {"account.banned": "on_ban", "account.level_up": "on_level"}, "timeout_ms": 3600000, "on_timeout": "step_x" }

# parallel:
#   { "steps": ["step_a", "step_b"], "wait_all": true }

# delay:
#   { "ms": 30000, "jitter_ms": 5000 }

# n8n_workflow:
#   { "webhook_url": "https://n8n.example.com/webhook/abc", "payload": {"device_id": "{{ctx.device_id}}"}, "wait_response": true }

# loop:
#   { "count": 3, "while": "ctx.retries < 3", "body_steps": ["retry_step"], "break_on": "success" }

# sub_pipeline:
#   { "pipeline_id": "uuid", "input": {"account": "{{ctx.account}}"} }
```

### 3.3 PipelineRun — Исполняющийся инстанс

```python
class PipelineRunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING = "waiting"        # Ожидание события / скрипта
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class PipelineRun(Base, UUIDMixin, TimestampMixin):
    """Запущенный инстанс Pipeline на конкретном устройстве.
    
    Каждый запуск хранит:
    - Текущий шаг (для возобновления после перезагрузки)
    - Весь контекст (переменные, результаты шагов)
    - Полный лог шагов с таймингами
    """
    __tablename__ = "pipeline_runs"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    pipeline_id: Mapped[UUID] = mapped_column(ForeignKey("pipelines.id"), nullable=False, index=True)
    device_id: Mapped[UUID] = mapped_column(ForeignKey("devices.id"), nullable=False, index=True)
    
    status: Mapped[PipelineRunStatus] = mapped_column(
        SQLAlchemyEnum(PipelineRunStatus), default=PipelineRunStatus.QUEUED, nullable=False, index=True
    )
    
    # Текущая позиция исполнения (для resume)
    current_step_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="ID текущего шага в pipeline.steps"
    )
    
    # Контекст — все переменные pipeline (аккаунт, логин, результаты)
    context: Mapped[dict] = mapped_column(
        JSONB, default=dict, comment="Мутабельный контекст исполнения"
    )
    
    # Входные параметры (копия на момент запуска)
    input_params: Mapped[dict] = mapped_column(JSONB, default=dict)
    
    # Снимок pipeline.steps на момент запуска (иммутабельный)
    steps_snapshot: Mapped[list[dict]] = mapped_column(
        JSONB, nullable=False, comment="Копия pipeline.steps — не меняется при обновлении шаблона"
    )
    
    # Лог шагов
    step_logs: Mapped[list[dict]] = mapped_column(
        JSONB, default=list,
        comment="[{step_id, status, started_at, finished_at, output, error}]"
    )
    
    # Связь с аккаунтом (если pipeline работает с аккаунтом)
    account_id: Mapped[UUID | None] = mapped_column(ForeignKey("game_accounts.id"), nullable=True)
    
    # Связь с текущим task (если шаг execute_script в процессе)
    current_task_id: Mapped[UUID | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    
    # Тайминги
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    
    # Retry
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    
    __table_args__ = (
        Index("ix_pipeline_runs_device_status", "device_id", "status"),
        Index("ix_pipeline_runs_org_status", "org_id", "status"),
    )
```

### 3.4 PipelineBatch — Массовый запуск Pipeline

```python
class PipelineBatch(Base, UUIDMixin, TimestampMixin):
    """Массовый запуск одного Pipeline на N устройств.
    
    Аналог TaskBatch, но для pipeline-ов.
    Поддерживает волновую раскатку.
    """
    __tablename__ = "pipeline_batches"

    org_id: Mapped[UUID] = mapped_column(ForeignKey("organizations.id"), nullable=False)
    pipeline_id: Mapped[UUID] = mapped_column(ForeignKey("pipelines.id"), nullable=False)
    
    status: Mapped[str] = mapped_column(String(32), default="running", index=True)
    
    total: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    
    wave_config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_by_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
```

---

## 4. Pipeline Executor — Ядро движка

### 4.1 Архитектура

```
                        ┌─────────────────────────┐
                        │   PipelineScheduler     │
                        │   (фоновый loop)        │
                        └───────────┬─────────────┘
                                    │ pick QUEUED runs
                        ┌───────────▼─────────────┐
                        │   PipelineExecutor      │
                        │   (по одному на run)    │
                        └───┬───────────────┬─────┘
                            │               │
                ┌───────────▼──┐  ┌─────────▼──────────┐
                │ StepExecutors│  │ EventSubscriber    │
                │ (per type)   │  │ (Redis PubSub)     │
                └──────────────┘  └────────────────────┘
```

### 4.2 PipelineExecutor — Основной класс

```python
# backend/services/orchestrator/pipeline_executor.py

class PipelineExecutor:
    """Исполнитель одного PipelineRun.
    
    Принципы:
    1. Персистенция: после каждого шага state сохраняется в БД
    2. Отказоустойчивость: при рестарте бэкенда — run продолжается с current_step_id
    3. Event-driven: wait_for_event подписывается на Redis PubSub
    4. Контекст: все переменные хранятся в run.context (JSONB)
    5. Шаблонизация: параметры шагов поддерживают {{ctx.variable}} подстановки
    """

    def __init__(
        self,
        db_session_maker: async_sessionmaker,
        task_service: TaskService,
        account_service: AccountService,
        event_publisher: EventPublisher,
        redis: Redis,
    ):
        self._session_maker = db_session_maker
        self._task_service = task_service
        self._account_service = account_service
        self._event_publisher = event_publisher
        self._redis = redis
        
        # Реестр обработчиков шагов
        self._step_handlers: dict[str, StepHandler] = {
            "execute_script": ExecuteScriptHandler(task_service),
            "condition": ConditionHandler(),
            "action": ActionHandler(account_service, db_session_maker),
            "wait_for_event": WaitForEventHandler(redis),
            "parallel": ParallelHandler(self),
            "delay": DelayHandler(),
            "n8n_workflow": N8nWorkflowHandler(),
            "loop": LoopHandler(self),
            "sub_pipeline": SubPipelineHandler(self),
        }

    async def execute(self, run_id: UUID) -> None:
        """Главный цикл исполнения pipeline run.
        
        Алгоритм:
        1. Загрузить PipelineRun из БД
        2. Определить текущий шаг (current_step_id или entry)
        3. Выполнить шаг через соответствующий handler
        4. Сохранить результат и context в БД (персистенция)
        5. Определить следующий шаг (on_success / on_failure)
        6. Повторить до конца или ошибки
        """
        async with self._session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if not run or run.status not in (PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING):
                return

            run.status = PipelineRunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(timezone.utc)
            await db.commit()

        steps_map = {s["id"]: s for s in run.steps_snapshot}
        current_step_id = run.current_step_id or run.steps_snapshot[0]["id"]

        while current_step_id:
            async with self._session_maker() as db:
                run = await db.get(PipelineRun, run_id)
                if not run or run.status in (
                    PipelineRunStatus.CANCELLED,
                    PipelineRunStatus.PAUSED,
                    PipelineRunStatus.TIMED_OUT,
                ):
                    return

                step = steps_map.get(current_step_id)
                if not step:
                    run.status = PipelineRunStatus.FAILED
                    run.step_logs = [*run.step_logs, {
                        "step_id": current_step_id,
                        "error": f"Шаг '{current_step_id}' не найден в pipeline",
                    }]
                    await db.commit()
                    return

                # Обновить текущую позицию (для resume)
                run.current_step_id = current_step_id
                await db.commit()

                # Подстановка шаблонов {{ctx.xxx}} в параметры шага
                resolved_params = self._resolve_templates(step.get("params", {}), run.context)

                step_start = datetime.now(timezone.utc)
                handler = self._step_handlers.get(step["type"])
                if not handler:
                    run.status = PipelineRunStatus.FAILED
                    run.step_logs = [*run.step_logs, {
                        "step_id": current_step_id,
                        "error": f"Неизвестный тип шага: {step['type']}",
                    }]
                    await db.commit()
                    return

                # Выполнить шаг с retry
                result = await self._execute_step_with_retry(
                    handler, step, resolved_params, run, db
                )

                step_end = datetime.now(timezone.utc)
                step_log = {
                    "step_id": current_step_id,
                    "type": step["type"],
                    "status": "success" if result.success else "failed",
                    "started_at": step_start.isoformat(),
                    "finished_at": step_end.isoformat(),
                    "duration_ms": int((step_end - step_start).total_seconds() * 1000),
                    "output": result.output,
                }
                if result.error:
                    step_log["error"] = result.error

                run.step_logs = [*run.step_logs, step_log]

                # Обновить контекст
                if result.context_updates:
                    ctx = dict(run.context)
                    ctx.update(result.context_updates)
                    run.context = ctx

                await db.commit()

                # Определить следующий шаг
                if result.next_step_override:
                    current_step_id = result.next_step_override
                elif result.success:
                    current_step_id = step.get("on_success")
                else:
                    current_step_id = step.get("on_failure")

        # Завершение pipeline
        async with self._session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run and run.status == PipelineRunStatus.RUNNING:
                run.status = PipelineRunStatus.COMPLETED
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()

    async def _execute_step_with_retry(
        self,
        handler: "StepHandler",
        step: dict,
        params: dict,
        run: PipelineRun,
        db: AsyncSession,
    ) -> "StepResult":
        """Выполнить шаг с автоматическим ретраем."""
        max_retries = step.get("retry", 0)
        retry_delay_ms = step.get("retry_delay_ms", 5000)
        timeout_ms = step.get("timeout_ms", 300_000)

        for attempt in range(max_retries + 1):
            try:
                result = await asyncio.wait_for(
                    handler.execute(params, run, db),
                    timeout=timeout_ms / 1000,
                )
                if result.success or attempt == max_retries:
                    return result
            except asyncio.TimeoutError:
                if attempt == max_retries:
                    return StepResult(success=False, error=f"Таймаут шага: {timeout_ms}ms")
            except Exception as e:
                if attempt == max_retries:
                    return StepResult(success=False, error=str(e))

            await asyncio.sleep(retry_delay_ms / 1000)

        return StepResult(success=False, error="Исчерпаны попытки ретрая")

    def _resolve_templates(self, params: dict, context: dict) -> dict:
        """Подстановка {{ctx.xxx}} шаблонов в параметры.
        
        Поддерживает:
        - {{ctx.login}} → значение из context["login"]
        - {{ctx.account.level}} → вложенный доступ
        - {{env.SOME_VAR}} → переменные окружения (только whitelist)
        """
        import re
        
        def resolve_value(val):
            if isinstance(val, str):
                def replacer(match):
                    path = match.group(1)
                    parts = path.split(".")
                    obj = {"ctx": context}
                    try:
                        for part in parts:
                            obj = obj[part] if isinstance(obj, dict) else getattr(obj, part)
                        return str(obj) if obj is not None else ""
                    except (KeyError, AttributeError, TypeError):
                        return match.group(0)  # Оставить как есть
                return re.sub(r'\{\{(.+?)\}\}', replacer, val)
            elif isinstance(val, dict):
                return {k: resolve_value(v) for k, v in val.items()}
            elif isinstance(val, list):
                return [resolve_value(v) for v in val]
            return val

        return resolve_value(params)
```

### 4.3 StepHandler — Интерфейс обработчика

```python
# backend/services/orchestrator/step_handlers.py

@dataclass
class StepResult:
    """Результат выполнения одного шага."""
    success: bool
    output: Any = None
    error: str | None = None
    context_updates: dict | None = None       # Обновления для run.context
    next_step_override: str | None = None     # Принудительный переход (для condition)


class StepHandler(ABC):
    """Базовый обработчик шага pipeline."""
    
    @abstractmethod
    async def execute(
        self, params: dict, run: PipelineRun, db: AsyncSession
    ) -> StepResult:
        ...
```

### 4.4 Конкретные обработчики шагов

```python
class ExecuteScriptHandler(StepHandler):
    """Запуск DAG-скрипта на устройстве.
    
    1. Создать Task через TaskService
    2. Подождать завершения (polling или event)
    3. Вернуть результат в context
    """

    def __init__(self, task_service: TaskService):
        self._task_service = task_service

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        script_id = UUID(params["script_id"])
        input_params = params.get("input_params", {})
        wait = params.get("wait", True)

        task = await self._task_service.create_task(
            script_id=script_id,
            device_id=run.device_id,
            org_id=run.org_id,
            priority=params.get("priority", 5),
        )

        if not wait:
            return StepResult(
                success=True,
                output={"task_id": str(task.id)},
                context_updates={"last_task_id": str(task.id)},
            )

        # Ожидание завершения задачи (polling — до переделки на event-driven)
        poll_interval = params.get("poll_interval_ms", 5000) / 1000
        deadline = asyncio.get_event_loop().time() + (params.get("timeout_ms", 300_000) / 1000)

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(poll_interval)
            task = await db.get(Task, task.id)
            await db.refresh(task)

            if task.status == TaskStatus.COMPLETED:
                return StepResult(
                    success=True,
                    output=task.result,
                    context_updates={"last_task_result": task.result},
                )
            elif task.status in (TaskStatus.FAILED, TaskStatus.TIMEOUT, TaskStatus.CANCELLED):
                return StepResult(
                    success=False,
                    error=task.error_message or f"Задача завершилась со статусом {task.status}",
                    output=task.result,
                )

        return StepResult(success=False, error="Таймаут ожидания завершения задачи")


class ConditionHandler(StepHandler):
    """Условный переход.
    
    Поддерживает:
    - expression: Python-выражение с доступом к ctx
    - check: предопределённые проверки (variable_equals, variable_contains, etc.)
    """

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        ctx = run.context

        if "expression" in params:
            # Безопасный eval через ограниченный namespace
            result = self._safe_eval(params["expression"], ctx)
        elif "check" in params:
            result = self._check(params, ctx)
        else:
            return StepResult(success=False, error="condition: нет 'expression' или 'check'")

        # on_true/on_false определяют next_step через навигацию в PipelineExecutor
        return StepResult(
            success=True,
            output={"condition_result": result},
            next_step_override=params.get("on_true") if result else params.get("on_false"),
        )

    def _safe_eval(self, expression: str, ctx: dict) -> bool:
        """Ограниченный eval — только чтение из ctx.
        
        Запрещено: import, exec, eval, open, __builtins__.
        """
        # Whitelist: только чтение значений, сравнения, логические операции
        FORBIDDEN = {"import", "exec", "eval", "open", "__", "compile", "globals", "locals"}
        for word in FORBIDDEN:
            if word in expression:
                raise ValueError(f"Запрещённое слово в выражении: {word}")
        
        safe_globals = {"__builtins__": {}, "ctx": ctx, "len": len, "str": str, "int": int, "bool": bool}
        try:
            return bool(eval(expression, safe_globals))  # noqa: S307
        except Exception as e:
            raise ValueError(f"Ошибка выражения: {e}")

    def _check(self, params: dict, ctx: dict) -> bool:
        check = params["check"]
        key = params.get("key", "")
        value = params.get("value", "")
        
        actual = ctx.get(key)
        
        if check == "variable_equals":
            return str(actual) == str(value)
        elif check == "variable_contains":
            return str(value) in str(actual or "")
        elif check == "variable_exists":
            return key in ctx and ctx[key] is not None
        elif check == "variable_gt":
            return (float(actual or 0)) > float(value)
        elif check == "variable_lt":
            return (float(actual or 0)) < float(value)
        else:
            raise ValueError(f"Неизвестная проверка: {check}")


class ActionHandler(StepHandler):
    """Серверные действия: работа с БД, аккаунтами, HTTP.
    
    Действия:
    - assign_account: назначить свободный аккаунт из пула
    - release_account: освободить аккаунт
    - rotate_account: ротация (забанить текущий + назначить новый)
    - update_account: обновить поля аккаунта
    - set_variable: записать переменную в контекст
    - http_request: HTTP-запрос к внешнему API
    - db_query: выполнить SQL (только whitelist таблиц)
    - notify: отправить уведомление
    """

    def __init__(self, account_service: AccountService, session_maker):
        self._account_service = account_service
        self._session_maker = session_maker

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        action = params.get("action")
        
        if action == "assign_account":
            return await self._assign_account(params, run, db)
        elif action == "release_account":
            return await self._release_account(params, run, db)
        elif action == "rotate_account":
            return await self._rotate_account(params, run, db)
        elif action == "update_account":
            return await self._update_account(params, run, db)
        elif action == "set_variable":
            key = params["key"]
            value = params["value"]
            return StepResult(success=True, context_updates={key: value})
        elif action == "http_request":
            return await self._http_request(params)
        elif action == "notify":
            return await self._notify(params, run)
        else:
            return StepResult(success=False, error=f"Неизвестное действие: {action}")

    async def _assign_account(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        game_id = params.get("game_id", run.context.get("game_id"))
        strategy = params.get("strategy", "round_robin")
        
        account = await self._account_service.assign_account(
            device_id=run.device_id,
            game_id=game_id,
            org_id=run.org_id,
            db=db,
            strategy=strategy,
        )
        
        if not account:
            return StepResult(success=False, error="Пул аккаунтов исчерпан")

        # Дешифровать пароль для передачи в DAG
        from backend.services.crypto_service import decrypt_password
        password = decrypt_password(account.password_encrypted)
        
        return StepResult(
            success=True,
            output={"account_id": str(account.id), "login": account.login},
            context_updates={
                "account_id": str(account.id),
                "account_login": account.login,
                "account_password": password,
                "game_id": game_id,
            },
        )

    async def _rotate_account(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        current_account_id = UUID(run.context.get("account_id", ""))
        game_id = run.context.get("game_id", "")
        ban_current = params.get("ban_current", False)
        
        new_account = await self._account_service.rotate_account(
            device_id=run.device_id,
            current_account_id=current_account_id,
            game_id=game_id,
            org_id=run.org_id,
            db=db,
            ban_current=ban_current,
        )
        
        if not new_account:
            return StepResult(success=False, error="Нет свободных аккаунтов для ротации")

        from backend.services.crypto_service import decrypt_password
        password = decrypt_password(new_account.password_encrypted)
        
        return StepResult(
            success=True,
            output={"new_account_id": str(new_account.id), "login": new_account.login},
            context_updates={
                "account_id": str(new_account.id),
                "account_login": new_account.login,
                "account_password": password,
            },
        )

    async def _http_request(self, params: dict) -> StepResult:
        """HTTP-запрос к внешнему API (n8n, webhook, etc.)."""
        import httpx
        
        url = params["url"]
        method = params.get("method", "GET").upper()
        headers = params.get("headers", {})
        body = params.get("body")
        timeout = params.get("timeout_ms", 15_000) / 1000
        
        # Защита от SSRF: только публичные адреса
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if parsed.hostname in ("localhost", "127.0.0.1", "0.0.0.0", "169.254.169.254"):
            return StepResult(success=False, error="SSRF: запрещённый хост")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.request(method, url, headers=headers, json=body if body else None)
        
        return StepResult(
            success=resp.is_success,
            output={"status_code": resp.status_code, "body": resp.text[:10_000]},
            context_updates={"last_http_response": resp.text[:10_000]} if params.get("save_response") else None,
        )

    async def _notify(self, params: dict, run: PipelineRun) -> StepResult:
        # Заглушка — интеграция с NotificationService
        return StepResult(success=True, output={"notified": True})


class WaitForEventHandler(StepHandler):
    """Ожидание события от агента через Redis PubSub.
    
    Подписывается на канал device:{device_id}:events
    и ждёт указанное событие с таймаутом.
    """

    def __init__(self, redis: Redis):
        self._redis = redis

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        events_map: dict = params.get("events", {})  # {"account.banned": "on_ban_step", ...}
        timeout_ms = params.get("timeout_ms", 60_000)
        on_timeout_step = params.get("on_timeout")

        channel = f"device:{run.device_id}:events"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)

        try:
            deadline = asyncio.get_event_loop().time() + (timeout_ms / 1000)
            while asyncio.get_event_loop().time() < deadline:
                message = await asyncio.wait_for(
                    pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0),
                    timeout=2.0,
                )
                if message and message["type"] == "message":
                    import json
                    data = json.loads(message["data"])
                    event_type = data.get("event_type", "")
                    
                    if event_type in events_map:
                        target_step = events_map[event_type]
                        return StepResult(
                            success=True,
                            output={"event_type": event_type, "event_data": data},
                            context_updates={"last_event": data},
                            next_step_override=target_step,
                        )
            
            # Таймаут
            if on_timeout_step:
                return StepResult(
                    success=True,
                    output={"event_type": "timeout"},
                    next_step_override=on_timeout_step,
                )
            return StepResult(success=False, error=f"Таймаут ожидания события ({timeout_ms}ms)")
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()


class DelayHandler(StepHandler):
    """Пауза с опциональным jitter."""

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        import random
        ms = params.get("ms", 1000)
        jitter = random.randint(0, params.get("jitter_ms", 0))
        await asyncio.sleep((ms + jitter) / 1000)
        return StepResult(success=True, output={"delayed_ms": ms + jitter})


class N8nWorkflowHandler(StepHandler):
    """Вызов n8n workflow через webhook.
    
    1. POST на webhook_url с payload
    2. Если wait_response=true — ждём ответ (синхронный webhook n8n)
    3. Результат сохраняется в context
    """

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        import httpx
        
        webhook_url = params["webhook_url"]
        payload = params.get("payload", {})
        wait_response = params.get("wait_response", True)
        timeout = params.get("timeout_ms", 30_000) / 1000

        # Защита от SSRF
        from urllib.parse import urlparse
        parsed = urlparse(webhook_url)
        if parsed.hostname in ("169.254.169.254",):
            return StepResult(success=False, error="SSRF: запрещённый хост")
        
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, json=payload)
        
        if not resp.is_success:
            return StepResult(
                success=False,
                error=f"n8n webhook вернул {resp.status_code}: {resp.text[:500]}",
            )

        response_data = resp.json() if wait_response else {}
        
        return StepResult(
            success=True,
            output=response_data,
            context_updates={"n8n_response": response_data} if wait_response else None,
        )


class LoopHandler(StepHandler):
    """Цикл: повторить блок шагов N раз или пока условие true.
    
    params:
    - count: фиксированное количество итераций
    - while: Python-выражение (проверяется перед каждой итерацией)
    - body_steps: список ID шагов для выполнения в теле цикла
    - break_on: "success" | "failure" — прервать при первом успехе/неуспехе тела
    - max_iterations: абсолютный лимит (защита от бесконечных циклов)
    """

    def __init__(self, executor: "PipelineExecutor"):
        self._executor = executor

    async def execute(self, params: dict, run: PipelineRun, db: AsyncSession) -> StepResult:
        count = params.get("count")
        while_expr = params.get("while")
        body_step_ids = params.get("body_steps", [])
        break_on = params.get("break_on")
        max_iterations = params.get("max_iterations", 100)

        iteration = 0
        last_result = None

        while iteration < max_iterations:
            # Проверка условия продолжения
            if count is not None and iteration >= count:
                break
            if while_expr:
                condition_handler = ConditionHandler()
                cond_result = await condition_handler.execute(
                    {"expression": while_expr}, run, db
                )
                if not cond_result.output.get("condition_result"):
                    break

            # Выполнить тело цикла
            for step_id in body_step_ids:
                steps_map = {s["id"]: s for s in run.steps_snapshot}
                step = steps_map.get(step_id)
                if not step:
                    continue
                
                resolved_params = self._executor._resolve_templates(
                    step.get("params", {}), run.context
                )
                handler = self._executor._step_handlers.get(step["type"])
                if handler:
                    last_result = await handler.execute(resolved_params, run, db)
                    if last_result.context_updates:
                        ctx = dict(run.context)
                        ctx.update(last_result.context_updates)
                        run.context = ctx

                    if break_on == "success" and last_result.success:
                        return last_result
                    if break_on == "failure" and not last_result.success:
                        return last_result

            iteration += 1
            # Обновить счётчик итераций в контексте
            run.context = {**run.context, "_loop_iteration": iteration}

        return StepResult(
            success=True,
            output={"iterations": iteration, "last_result": last_result.output if last_result else None},
        )
```

---

## 5. Pipeline Scheduler — Фоновый процесс

```python
# backend/services/orchestrator/pipeline_scheduler.py

class PipelineScheduler:
    """Фоновый процесс: подбирает QUEUED pipeline runs и запускает executor.
    
    Аналог _task_dispatcher_loop, но для pipeline-ов.
    Работает как singleton — один на инстанс бэкенда.
    Использует SELECT ... FOR UPDATE SKIP LOCKED для масштабирования на N инстансов.
    """

    def __init__(
        self,
        session_maker: async_sessionmaker,
        executor: PipelineExecutor,
        max_concurrent: int = 50,
    ):
        self._session_maker = session_maker
        self._executor = executor
        self._max_concurrent = max_concurrent
        self._active_runs: dict[UUID, asyncio.Task] = {}

    async def run_forever(self) -> None:
        """Основной цикл планировщика."""
        logger.info("pipeline_scheduler.started", max_concurrent=self._max_concurrent)
        
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.error("pipeline_scheduler.error", error=str(e), exc_info=True)
            await asyncio.sleep(2)  # Интервал проверки

    async def _tick(self) -> None:
        """Одна итерация: подобрать QUEUED runs, запустить executor."""
        # Очистить завершённые задачи
        done = [rid for rid, task in self._active_runs.items() if task.done()]
        for rid in done:
            task = self._active_runs.pop(rid)
            if task.exception():
                logger.error("pipeline_run.crashed", run_id=str(rid), error=str(task.exception()))

        # Сколько слотов свободно
        free_slots = self._max_concurrent - len(self._active_runs)
        if free_slots <= 0:
            return

        async with self._session_maker() as db:
            # SELECT ... FOR UPDATE SKIP LOCKED — для горизонтального масштабирования
            runs = (await db.execute(
                select(PipelineRun)
                .where(PipelineRun.status == PipelineRunStatus.QUEUED)
                .order_by(PipelineRun.created_at.asc())
                .limit(free_slots)
                .with_for_update(skip_locked=True)
            )).scalars().all()

            for run in runs:
                run.status = PipelineRunStatus.RUNNING
                task = asyncio.create_task(
                    self._executor.execute(run.id),
                    name=f"pipeline_run_{run.id}",
                )
                self._active_runs[run.id] = task

            await db.commit()

    async def cancel_run(self, run_id: UUID) -> None:
        """Отменить pipeline run."""
        task = self._active_runs.get(run_id)
        if task:
            task.cancel()
            self._active_runs.pop(run_id, None)
        
        async with self._session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run and run.status in (PipelineRunStatus.RUNNING, PipelineRunStatus.QUEUED, PipelineRunStatus.WAITING):
                run.status = PipelineRunStatus.CANCELLED
                run.finished_at = datetime.now(timezone.utc)
                await db.commit()

    async def pause_run(self, run_id: UUID) -> None:
        """Поставить pipeline run на паузу.
        
        executor проверяет status перед каждым шагом.
        """
        async with self._session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run and run.status == PipelineRunStatus.RUNNING:
                run.status = PipelineRunStatus.PAUSED
                await db.commit()

    async def resume_run(self, run_id: UUID) -> None:
        """Возобновить pipeline run с точки паузы."""
        async with self._session_maker() as db:
            run = await db.get(PipelineRun, run_id)
            if run and run.status == PipelineRunStatus.PAUSED:
                run.status = PipelineRunStatus.QUEUED  # Scheduler подберёт на следующем tick
                await db.commit()
```

---

## 6. REST API

### 6.1 Pipelines (шаблоны)

```
POST   /api/v1/pipelines                      — Создать pipeline
GET    /api/v1/pipelines                      — Список pipeline-ов
GET    /api/v1/pipelines/{id}                 — Детали pipeline
PATCH  /api/v1/pipelines/{id}                 — Обновить pipeline
DELETE /api/v1/pipelines/{id}                 — Удалить (soft) pipeline
POST   /api/v1/pipelines/{id}/validate        — Валидировать граф (проверка связности, циклов)
POST   /api/v1/pipelines/{id}/duplicate        — Дублировать pipeline
```

### 6.2 Pipeline Runs (запуски)

```
POST   /api/v1/pipelines/{id}/run              — Запустить на одном устройстве
POST   /api/v1/pipelines/{id}/batch            — Массовый запуск на N устройств
GET    /api/v1/pipeline-runs                   — Список запусков (фильтры)
GET    /api/v1/pipeline-runs/{id}              — Детали запуска + step_logs
POST   /api/v1/pipeline-runs/{id}/pause        — Пауза
POST   /api/v1/pipeline-runs/{id}/resume       — Возобновление
POST   /api/v1/pipeline-runs/{id}/cancel       — Отмена
GET    /api/v1/pipeline-runs/{id}/context      — Текущий контекст (переменные)
```

---

## 7. Интеграция с существующими компонентами

### 7.1 Связь с TaskService

```
PipelineExecutor                     TaskService
      │                                   │
      │  ExecuteScriptHandler             │
      ├───create_task(script, device)────►│
      │                                   ├──► Redis Queue
      │                                   │       │
      │                                   │  TaskDispatcher
      │                                   │       │
      │   poll task.status                │       ▼
      ◄───────────────────────────────────┤  Agent (WS)
      │   task.status == COMPLETED        │
      │   → next step                     │
```

### 7.2 Связь с EventReactor (SPLIT-3)

EventReactor из SPLIT-3 получает события от агента. Для pipeline-ов добавляется дополнительная логика:

```python
# Расширение EventReactor
class EventReactor:
    async def handle(self, event: DeviceEvent, db: AsyncSession) -> None:
        # ... существующие handler-ы ...
        
        # НОВОЕ: Пробудить pipeline run, если он ждёт это событие
        await self._wake_pipeline_run(event, db)

    async def _wake_pipeline_run(self, event: DeviceEvent, db: AsyncSession) -> None:
        """Опубликовать событие в Redis для WaitForEventHandler."""
        import json
        channel = f"device:{event.device_id}:events"
        await self._redis.publish(channel, json.dumps({
            "event_type": event.event_type,
            "severity": event.severity.value,
            "message": event.message,
            "payload": event.payload,
            "task_id": str(event.task_id) if event.task_id else None,
            "account_id": str(event.account_id) if event.account_id else None,
        }))
```

### 7.3 Связь с n8n

```
Pipeline (wait_for_event)                n8n Workflow
      │                                        │
      │ [Event: task_completed]                 │
      ├─────(webhook)──────────────────────────►│
      │                                        │ [IF ban → rotate]
      │                                        │ [Generate new nick]
      │    {nickname: "ProGamer42"}             │
      ◄────────────────────────────────────────┤
      │                                        │
      │ set_variable → ctx.nickname             │
      │ execute_script(login_with_nick)         │
```

---

## 8. Пример: Pipeline "Black Russia — Полный цикл"

```json
{
    "name": "Black Russia — Полный цикл фарма",
    "global_timeout_ms": 86400000,
    "input_schema": {
        "type": "object",
        "properties": {
            "game_id": {"type": "string", "default": "blackrussia"}
        }
    },
    "steps": [
        {
            "id": "assign_account",
            "name": "Назначить аккаунт",
            "type": "action",
            "params": {"action": "assign_account", "game_id": "{{ctx.game_id}}", "strategy": "round_robin"},
            "on_success": "launch_game",
            "on_failure": "no_accounts_alert",
            "timeout_ms": 10000
        },
        {
            "id": "launch_game",
            "name": "Запустить игру и залогиниться",
            "type": "execute_script",
            "params": {"script_id": "770bf806-...", "wait": true},
            "on_success": "check_login",
            "on_failure": "retry_login",
            "retry": 2,
            "retry_delay_ms": 10000,
            "timeout_ms": 300000
        },
        {
            "id": "check_login",
            "name": "Проверить успешность входа",
            "type": "condition",
            "params": {
                "check": "variable_equals",
                "key": "last_task_result.success",
                "value": "true"
            },
            "on_success": "start_farm",
            "on_failure": "rotate_account"
        },
        {
            "id": "start_farm",
            "name": "Запустить скрипт фарма",
            "type": "execute_script",
            "params": {"script_id": "abc123-...", "wait": true},
            "on_success": "farm_completed",
            "on_failure": "handle_farm_error",
            "timeout_ms": 3600000
        },
        {
            "id": "handle_farm_error",
            "name": "Ожидание события при ошибке фарма",
            "type": "wait_for_event",
            "params": {
                "events": {
                    "account.banned": "rotate_account",
                    "game.crashed": "launch_game",
                    "account.captcha": "captcha_alert"
                },
                "timeout_ms": 30000,
                "on_timeout": "launch_game"
            },
            "on_success": null,
            "on_failure": "pipeline_failed"
        },
        {
            "id": "rotate_account",
            "name": "Ротация аккаунта",
            "type": "action",
            "params": {"action": "rotate_account", "ban_current": true},
            "on_success": "launch_game",
            "on_failure": "no_accounts_alert"
        },
        {
            "id": "retry_login",
            "name": "Повтор входа через 30 секунд",
            "type": "delay",
            "params": {"ms": 30000},
            "on_success": "launch_game"
        },
        {
            "id": "farm_completed",
            "name": "Фарм завершён: освободить аккаунт",
            "type": "action",
            "params": {"action": "release_account", "cooldown_minutes": 30},
            "on_success": "assign_account"
        },
        {
            "id": "no_accounts_alert",
            "name": "Пул исчерпан — уведомление",
            "type": "action",
            "params": {"action": "notify", "level": "critical", "title": "Нет свободных аккаунтов"},
            "on_success": null
        },
        {
            "id": "captcha_alert",
            "name": "Капча — пауза pipeline",
            "type": "action",
            "params": {"action": "notify", "level": "warning", "title": "Капча — требуется ручное решение"},
            "on_success": null
        }
    ]
}
```

---

## 9. Безопасность

| Аспект | Решение |
|--------|---------|
| **Injection в expression** | Whitelist для safe_eval: запрет import/exec/eval/__builtins__ |
| **SSRF в http_request/n8n** | Блокировка localhost, 127.0.0.1, link-local, metadata endpoints |
| **SQL injection в db_query** | Action `db_query` — только параметризованные запросы, whitelist таблиц |
| **Escaping паролей в context** | Пароли аккаунтов шифруются AES-256-GCM, дешифруются только в момент передачи в DAG |
| **RLS** | pipeline_runs.org_id — все запросы фильтруются по организации |
| **Бесконечные циклы** | max_iterations=100, global_timeout_ms, каждый loop шаг имеет лимит |

---

## 10. Отказоустойчивость

| Сценарий | Механизм |
|----------|----------|
| **Рестарт бэкенда** | PipelineRun.current_step_id + status=RUNNING → Scheduler подберёт и продолжит |
| **Потеря WebSocket агента** | execute_script polling → задача в Redis queue, agent reconnect → pickup |
| **Сбой Redis** | Pipeline переходит в PAUSED, при восстановлении → QUEUED |
| **Сбой PostgreSQL** | Pipeline Executor обёрнут в try/catch → retry через Scheduler |
| **Агент offline** | execute_script задача остаётся в QUEUED, dispatch при reconnect |
| **N процессов бэкенда** | FOR UPDATE SKIP LOCKED — pipeline run обрабатывается ровно одним процессом |

---

## 11. Таблица изменений

| Компонент | Файл | Описание |
|-----------|------|----------|
| Backend | `models/pipeline.py` | NEW: Pipeline, PipelineRun, PipelineBatch |
| Backend | `schemas/pipeline.py` | NEW: PipelineStepSchema, PipelineCreate, PipelineRunResponse |
| Backend | `services/orchestrator/__init__.py` | NEW: Пакет оркестратора |
| Backend | `services/orchestrator/pipeline_executor.py` | NEW: PipelineExecutor + StepResult |
| Backend | `services/orchestrator/step_handlers.py` | NEW: Все StepHandler реализации |
| Backend | `services/orchestrator/pipeline_scheduler.py` | NEW: PipelineScheduler (фоновый loop) |
| Backend | `api/v1/pipelines/router.py` | NEW: REST API pipeline CRUD + runs |
| Backend | `services/event_reactor.py` | + _wake_pipeline_run (Redis publish) |
| Backend | `alembic/versions/` | Миграция: pipelines, pipeline_runs, pipeline_batches |
| Frontend | `app/pipelines/` | NEW: Pipeline Builder UI |
| Frontend | `components/pipelines/` | NEW: PipelineGraph, StepEditor, RunTimeline |

---

## 12. Критерии готовности

- [ ] Таблицы pipelines, pipeline_runs, pipeline_batches созданы с RLS и индексами
- [ ] PipelineExecutor проходит все StepTypes: execute_script, condition, action, wait_for_event, delay, n8n_workflow, loop
- [ ] ActionHandler: assign_account, rotate_account, release_account, http_request, set_variable, notify
- [ ] WaitForEventHandler корректно подписывается на Redis PubSub и просыпается при событиях
- [ ] Template resolution: {{ctx.xxx}} подставляется во все параметры рекурсивно
- [ ] PipelineScheduler: FOR UPDATE SKIP LOCKED, max_concurrent, cleanup done tasks
- [ ] Pause/Resume/Cancel pipeline run через API
- [ ] Отказоустойчивость: рестарт бэкенда не теряет pipeline runs
- [ ] safe_eval: whitelist, запрет опасных конструкций
- [ ] SSRF защита в http_request и n8n_workflow
- [ ] REST API: CRUD pipelines + runs с фильтрами
- [ ] Интеграционный тест: полный цикл assign → login → farm → ban → rotate → retry
- [ ] Нагрузочный тест: 100 concurrent pipeline runs
