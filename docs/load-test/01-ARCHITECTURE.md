# ТЗ ЧАСТЬ 1: АРХИТЕКТУРА СИНТЕТИЧЕСКОГО НАГРУЗОЧНОГО ТЕСТА

> **Sphere Platform — Synthetic Fleet Load Test**
> **Версия:** 1.0 | **Дата:** 2026-03-04
> **Тип:** Синтетический нагрузочный тест (Synthetic Load / Stress Test)
> **Терминология:** Synthetic Load Test = имитация реальных агентов без физических устройств

---

## 1. ЦЕЛЬ И ОБОСНОВАНИЕ

### 1.1 Что тестируем

Серверную инфраструктуру Sphere Platform под нагрузкой **10 000 одновременных
виртуальных эмуляторов**, каждый из которых:

- Подключён к серверу через **WebSocket** (`/ws/android/{token}`)
- Выполняет **DAG-скрипт** (получает задачи, отправляет результаты)
- Включает **VPN** (WireGuard enrollment + iptables kill-switch)
- Отправляет **heartbeat** и **device_status** каждые 10–30 секунд
- Опционально стримит **H.264 видео** (5–10% агентов)

### 1.2 Что это называется

| Термин | Значение |
|--------|---------|
| **Synthetic Load Test** | Имитация реальной нагрузки программными «виртуальными агентами» |
| **Stress Test** | Поиск точки отказа при монотонном наращивании нагрузки |
| **Soak Test** (Endurance) | Длительный прогон (2–4 часа) на стабильной нагрузке |
| **Spike Test** | Резкий всплеск +1000 агентов за 10 секунд |
| **Scalability Test** | Замер деградации при шагах 32→64→…→10 000 |

Наш тест объединяет **все пять типов** в одном сценарии.

### 1.3 Зачем

1. **Валидация масштабируемости** — можем ли мы реально обслужить 10K устройств?
2. **Поиск bottleneck** — DB pool, Redis memory, WebSocket connections, nginx limits
3. **Определение SLA** — p50/p95/p99 latency, error rate, throughput
4. **Capacity planning** — сколько серверов нужно на 50K / 100K устройств
5. **Regression baseline** — метрики для CI pipeline (alert если деградация > 10%)

---

## 2. АРХИТЕКТУРА СИСТЕМЫ ПОД НАГРУЗКОЙ

### 2.1 Текущая архитектура Sphere Platform

```
┌──────────────────────────────────────────────────────────────────────┐
│                     SPHERE PLATFORM — компоненты                     │
│                                                                      │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────────────┐  │
│  │  Nginx   │──▶│ FastAPI  │──▶│PostgreSQL│   │     Redis        │  │
│  │ (proxy)  │   │ (4 wkrs) │   │(max=200) │   │ (512MB, 50 conn)│  │
│  │ ws:100/IP│   │ pool=10  │   │          │   │                  │  │
│  └──────────┘   └──────────┘   └──────────┘   └──────────────────┘  │
│       │              │                                │              │
│       │         ┌────┴─────┐                          │              │
│       │         │ WS mgr   │◀────── Redis PubSub ─────┘              │
│       │         │ (in-mem) │                                         │
│       │         └──────────┘                                         │
│       │              │                                               │
│  ┌────┴────┐    ┌────┴─────┐   ┌──────────┐   ┌──────────────────┐  │
│  │Frontend │    │Task Disp │   │Scheduler │   │Pipeline Executor │  │
│  │Next.js  │    │(0.1s loop│   │(30s loop)│   │(2s loop, max=10) │  │
│  │port 3002│    │Lua deq.) │   │          │   │                  │  │
│  └─────────┘    └──────────┘   └──────────┘   └──────────────────┘  │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐│
│  │               Prometheus + Grafana (monitoring)                   ││
│  └──────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────┘
                              ▲
                              │ WebSocket + REST
                              │
                    ┌─────────┴──────────┐
                    │  10,000 Android     │
                    │  Emulator Agents    │
                    │  (LDPlayer / AVD)   │
                    └────────────────────┘
```

### 2.2 Архитектура нагрузочного теста

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     LOAD TEST INFRASTRUCTURE                            │
│                                                                         │
│  ┌───────────────────────────────────────┐                              │
│  │          Load Test Orchestrator       │                              │
│  │  (Python / asyncio / управление)      │                              │
│  │                                        │                              │
│  │  ● Конфиг сценариев (YAML)            │                              │
│  │  ● Фазы: ramp-up → steady → spike     │                              │
│  │  ● Сбор метрик (InfluxDB)             │                              │
│  │  ● Генерация отчёта (HTML + JSON)     │                              │
│  └────────────────┬──────────────────────┘                              │
│                   │                                                      │
│    ┌──────────────┼──────────────┐                                       │
│    ▼              ▼              ▼                                        │
│  ┌──────┐   ┌──────┐      ┌──────┐                                      │
│  │Pool 1│   │Pool 2│ ...  │Pool N│   N = ceil(10000/2000)               │
│  │2000  │   │2000  │      │2000  │   5 пулов по 2000 виртуальных агентов│
│  │agents│   │agents│      │agents│                                      │
│  └───┬──┘   └───┬──┘      └───┬──┘                                      │
│      │          │              │                                         │
│      ▼          ▼              ▼                                         │
│  ┌──────────────────────────────────────┐                               │
│  │       Virtual Agent (coroutine)       │  × 10 000                    │
│  │                                        │                              │
│  │  1. WebSocket connect + auth           │                              │
│  │  2. Heartbeat loop (30s)               │                              │
│  │  3. Device status updates (10s)        │                              │
│  │  4. Task execution simulation          │                              │
│  │  5. VPN enrollment + status            │                              │
│  │  6. Video frame simulation (5-10%)     │                              │
│  │  7. Command response handling          │                              │
│  └──────────────────────────────────────┘                               │
│                                                                         │
│  ┌──────────────────────────────────────┐                               │
│  │         Metrics Collector             │                               │
│  │  ● Latency histogram (connect, msg)   │                              │
│  │  ● Throughput counter (msg/sec)        │                              │
│  │  ● Error rate (connect fail, timeout)  │                              │
│  │  ● Resource usage (CPU, RAM, FD)       │                              │
│  └──────────────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────────────┘
                              │
                              │ WebSocket + REST API
                              ▼
                    ┌────────────────────┐
                    │  Sphere Platform   │
                    │  (Target Under     │
                    │   Test — TUT)      │
                    └────────────────────┘
```

---

## 3. ВИРТУАЛЬНЫЙ АГЕНТ — ДИЗАЙН

### 3.1 Что эмулирует виртуальный агент

Каждый Virtual Agent — это **одна asyncio-корутина**, которая в точности
воспроизводит поведение реального Android-агента:

| Действие | Реальный агент | Виртуальный агент |
|----------|---------------|-------------------|
| WebSocket connect | OkHttp + first-message auth | `websockets` lib + JSON auth |
| Heartbeat | каждые 30s `{"type":"ping"}` | каждые 30s `{"type":"ping"}` |
| Device status | каждые 10s, battery/memory/screen | каждые 10s, рандомные но реалистичные значения |
| Task execution | DagRunner + LuaEngine + UiAutomator | Задержка 2–30s + случайный результат (80% OK / 15% fail / 5% timeout) |
| VPN | POST /vpn/enroll → wg-quick → iptables | POST /vpn/enroll → GET /vpn/status (без реального WireGuard) |
| Video stream | MediaProjection + H.264 encoder | Предзаписанный H.264 NAL-поток из файла (5–10% агентов) |
| Command response | Выполнение команды + отправка результата | JSON ответ с задержкой 100–500ms |
| Reconnect | Expo backoff 1s→30s | Expo backoff 1s→30s |

### 3.2 Идентичность виртуального агента

Каждый агент при создании получает **устойчивую идентичность**:

```python
@dataclass
class VirtualAgentIdentity:
    """Устойчивая идентичность виртуального агента."""
    device_id: str          # UUID v4, стабильный между прогонами
    serial: str             # "LOAD-{index:05d}" → "LOAD-00001"
    model: str              # Случайный из пула: "G576D", "HD1910", "ASUS_I003DD"
    android_version: str    # "11" | "12" | "13" | "14"
    agent_version: str      # "2.1.0" (текущая)
    screen_w: int           # 1080
    screen_h: int           # 2340
    org_id: str             # UUID организации (одной на все)
    api_key: str            # "sphr_load_{index}" pre-created API key
```

### 3.3 State Machine виртуального агента

```
                ┌──────────────┐
                │  CREATED     │
                └──────┬───────┘
                       │ register()
                       ▼
                ┌──────────────┐
                │ REGISTERING  │──── fail ────▶ BACKOFF ──▶ REGISTERING
                └──────┬───────┘
                       │ 201 OK
                       ▼
                ┌──────────────┐
                │ CONNECTING   │──── fail ────▶ BACKOFF ──▶ CONNECTING
                └──────┬───────┘
                       │ ws open + auth_ack
                       ▼
                ┌──────────────┐
          ┌─────│   ONLINE     │◀────────────────────────┐
          │     └──────┬───────┘                         │
          │            │ server sends command             │
          │            ▼                                  │
          │     ┌──────────────┐                         │
          │     │  EXECUTING   │── done ──▶ ONLINE       │
          │     └──────┬───────┘                         │
          │            │ ws close / error                 │
          │            ▼                                  │
          │     ┌──────────────┐                         │
          └────▶│ RECONNECTING │── success ──────────────┘
                └──────┬───────┘
                       │ max retries exceeded
                       ▼
                ┌──────────────┐
                │   DEAD       │
                └──────────────┘
```

---

## 4. ТЕХНОЛОГИЧЕСКИЙ СТЕК ТЕСТА

### 4.1 Выбор инструментов

| Компонент | Инструмент | Почему |
|-----------|-----------|--------|
| **Виртуальные агенты** | Python 3.12 + asyncio + `websockets` | Нативная async, 10K корутин в одном процессе |
| **HTTP-запросы** | `aiohttp` (ClientSession с connection pooling) | Быстрее `httpx` для массовых запросов |
| **Оркестрация** | Custom Python orchestrator | Полный контроль над фазами и метриками |
| **Конфигурация** | YAML + Pydantic | Типобезопасные сценарии |
| **Метрики сбор** | `prometheus_client` + push gateway | Единая шина метрик |
| **Визуализация** | Grafana dashboards (импорт JSON) | Real-time мониторинг теста |
| **Отчёт** | HTML + JSON (Jinja2 шаблон) | Автоматический отчёт по завершении |
| **H.264 payload** | Предзаписанный NAL-файл (10 секунд 720p) | Реалистичные binary frames |
| **CI интеграция** | pytest + markers (`@pytest.mark.loadtest`) | Запуск из CI с порогами |

### 4.2 Почему НЕ Locust / k6 / Gatling

| Инструмент | Причина отказа |
|-----------|---------------|
| **Locust** | Нет нативной WebSocket поддержки, monkey-patch ненадёжен для 10K постоянных WS |
| **k6** | WebSocket API слабый (нет binary frames), нет полноценного state machine |
| **Gatling** | JVM overhead, слабая WebSocket поддержка |
| **Artillery** | Нет state machine, нет binary WebSocket |

**Наш кастомный Python-оркестратор** даёт полный контроль над:
- Жизненным циклом каждого агента (state machine)
- Binary WebSocket frames (H.264 NAL units)
- Точными таймингами heartbeat/status
- Реалистичной эмуляцией task execution
- Корректным VPN enrollment flow

### 4.3 Системные требования для запуска теста

| Параметр | Значение | Обоснование |
|----------|---------|-------------|
| **CPU** | 8+ ядер | asyncio event loop + 10K корутин |
| **RAM** | 16+ GB | ~1.5 MB на агента × 10K = 15 GB |
| **File descriptors** | 65 535+ | `ulimit -n 65535` |
| **Network** | 1 Gbps+ | 10K WS + heartbeat + video streams |
| **Python** | 3.12+ | Performance improvements, taskgroups |
| **OS** | Linux (предпочтительно) | epoll > IOCP для 10K сокетов |

---

## 5. СТУПЕНИ НАГРУЗКИ (ШАГИ)

Тест выполняется **ступенчато** с фиксацией метрик на каждой ступени:

```
Агенты
  ▲
  │
10000 ┤ ·····································──────────── steady (15 мин)
  │                                         ╱
 8192 ┤ ·····························───────╱
  │                                ╱
 4096 ┤ ···················───────╱
  │                        ╱
 2048 ┤ ···········───────╱
  │                ╱
 1024 ┤ ·····────╱
  │          ╱
  512 ┤ ···──╱
  │      ╱
  256 ┤ ──╱
  │    ╱
  128 ┤ ╱
   64 ┤╱
   32 ┤        
  ────┼──┬──┬──┬──┬──┬──┬──┬──┬──┬──────────────────▶ Время
       0  2  4  6  8 10 12 14 16 18 ... 33 мин
           (минуты, ramp-up)
```

### 5.1 Фазы теста

| Фаза | Агенты | Длительность | Действия |
|------|--------|-------------|----------|
| **Step 1** | 32 | 2 мин | Baseline: замер всех метрик |
| **Step 2** | 64 | 2 мин | Линейное масштабирование |
| **Step 3** | 128 | 2 мин | Первый рубеж |
| **Step 4** | 256 | 2 мин | Проверка DB pool |
| **Step 5** | 512 | 2 мин | Проверка Redis |
| **Step 6** | 1 024 | 3 мин | Тысячник |
| **Step 7** | 2 048 | 3 мин | Серьёзная нагрузка |
| **Step 8** | 4 096 | 3 мин | Полулимит |
| **Step 9** | 8 192 | 3 мин | Стресс-рубеж |
| **Step 10** | 10 000 | 15 мин | **Full fleet — steady state** |
| **Spike** | +2 000 за 10с | 1 мин | Spike test (12K пик) |
| **Recovery** | 10 000 | 5 мин | Проверка восстановления |
| **Ramp-down** | 10K → 0 | 5 мин | Graceful disconnect |
| **ИТОГО** | — | ~48 мин | Полный цикл |

### 5.2 Soak Test (отдельный запуск)

| Фаза | Агенты | Длительность |
|------|--------|-------------|
| Ramp-up | 0 → 5 000 | 10 мин |
| Steady | 5 000 | **4 часа** |
| Ramp-down | 5 000 → 0 | 5 мин |

---

## 6. СТРУКТУРА ФАЙЛОВ ТЕСТА

```
tests/
└── load/
    ├── README.md                      # Документация запуска
    ├── pyproject.toml                 # Зависимости (websockets, aiohttp, ...)
    ├── conftest.py                    # pytest fixtures (server URL, org setup)
    │
    ├── config/
    │   ├── scenario_scalability.yml   # Ступенчатый тест 32→10K
    │   ├── scenario_soak.yml          # Soak-тест 5K × 4 часа
    │   ├── scenario_spike.yml         # Spike-тест +2K за 10с
    │   └── scenario_quick.yml         # CI quick-check 32→512 (5 мин)
    │
    ├── core/
    │   ├── __init__.py
    │   ├── orchestrator.py            # Главный оркестратор (фазы, метрики)
    │   ├── virtual_agent.py           # VirtualAgent (state machine)
    │   ├── agent_pool.py              # Pool управления N агентами
    │   ├── identity_factory.py        # Генерация идентичностей
    │   ├── metrics_collector.py       # Сбор и агрегация метрик
    │   └── report_generator.py        # HTML/JSON отчёт
    │
    ├── protocols/
    │   ├── __init__.py
    │   ├── ws_client.py               # WebSocket клиент (connect, auth, heartbeat)
    │   ├── rest_client.py             # REST API клиент (register, tasks, vpn)
    │   ├── video_streamer.py          # H.264 NAL frame sender
    │   └── message_factory.py         # Фабрика JSON/binary сообщений
    │
    ├── scenarios/
    │   ├── __init__.py
    │   ├── device_registration.py     # Сценарий: массовая регистрация
    │   ├── task_execution.py          # Сценарий: выполнение скриптов
    │   ├── vpn_enrollment.py          # Сценарий: VPN включение
    │   ├── video_streaming.py         # Сценарий: видео-стриминг
    │   ├── mixed_workload.py          # Сценарий: смешанная нагрузка (основной!)
    │   └── reconnect_storm.py         # Сценарий: массовый reconnect
    │
    ├── fixtures/
    │   ├── sample_video.h264          # 10с предзаписанного H.264 720p
    │   ├── sample_dag.json            # DAG-скрипт для task execution
    │   └── device_models.json         # Пул моделей устройств
    │
    ├── dashboards/
    │   ├── grafana_load_test.json     # Grafana dashboard (импорт)
    │   └── prometheus_rules.yml       # Alert rules для теста
    │
    ├── test_load_scalability.py       # pytest: ступенчатый тест
    ├── test_load_soak.py              # pytest: soak тест
    ├── test_load_spike.py             # pytest: spike тест
    └── test_load_quick.py             # pytest: CI quick smoke
```

---

## 7. КОНФИГУРАЦИЯ СЦЕНАРИЯ (YAML-СХЕМА)

```yaml
# config/scenario_scalability.yml
meta:
  name: "Sphere Fleet Scalability Test"
  version: "1.0.0"
  description: "Ступенчатый нагрузочный тест 32→10K виртуальных агентов"

target:
  base_url: "http://10.0.2.2:8000"
  ws_url: "ws://10.0.2.2:8000/ws/android"
  org_id: "05b0843a-8464-45f6-8d7e-73ffa293a515"
  api_key_prefix: "sphr_load_"

agents:
  serial_prefix: "LOAD"
  models: ["G576D", "HD1910", "ASUS_I003DD", "SM-G998B", "Pixel_7"]
  android_versions: ["11", "12", "13", "14"]
  agent_version: "2.1.0"

steps:
  - name: "step_32"
    target_agents: 32
    ramp_duration_sec: 30
    hold_duration_sec: 120
  - name: "step_64"
    target_agents: 64
    ramp_duration_sec: 30
    hold_duration_sec: 120
  - name: "step_128"
    target_agents: 128
    ramp_duration_sec: 30
    hold_duration_sec: 120
  - name: "step_256"
    target_agents: 256
    ramp_duration_sec: 30
    hold_duration_sec: 120
  - name: "step_512"
    target_agents: 512
    ramp_duration_sec: 30
    hold_duration_sec: 120
  - name: "step_1024"
    target_agents: 1024
    ramp_duration_sec: 60
    hold_duration_sec: 180
  - name: "step_2048"
    target_agents: 2048
    ramp_duration_sec: 60
    hold_duration_sec: 180
  - name: "step_4096"
    target_agents: 4096
    ramp_duration_sec: 60
    hold_duration_sec: 180
  - name: "step_8192"
    target_agents: 8192
    ramp_duration_sec: 60
    hold_duration_sec: 180
  - name: "step_10000"
    target_agents: 10000
    ramp_duration_sec: 120
    hold_duration_sec: 900  # 15 минут steady state
  - name: "spike_12000"
    target_agents: 12000
    ramp_duration_sec: 10   # резкий всплеск!
    hold_duration_sec: 60
  - name: "recovery_10000"
    target_agents: 10000
    ramp_duration_sec: 10
    hold_duration_sec: 300
  - name: "ramp_down"
    target_agents: 0
    ramp_duration_sec: 300
    hold_duration_sec: 0

workload:
  heartbeat_interval_sec: 30
  status_update_interval_sec: 10
  task_execution:
    enabled: true
    concurrent_tasks_per_agent: 1
    task_duration_min_sec: 2
    task_duration_max_sec: 30
    success_rate: 0.80
    failure_rate: 0.15
    timeout_rate: 0.05
  vpn:
    enabled: true
    enrollment_at_connect: true
    status_check_interval_sec: 60
  video_streaming:
    enabled: true
    percent_agents: 5       # 5% агентов стримят видео
    fps: 15
    bitrate_kbps: 1500
    resolution: "720x1280"
  reconnect:
    enabled: true
    random_disconnect_rate: 0.001  # 0.1% вероятность дисконнекта в минуту
    max_retries: 10
    backoff_base_sec: 1
    backoff_max_sec: 30

thresholds:
  ws_connect_p95_ms: 2000      # 95-й перцентиль подключения < 2с
  ws_connect_error_rate: 0.02  # < 2% ошибок подключения
  heartbeat_p99_ms: 500        # 99-й перцентиль heartbeat RTT < 500мс
  task_dispatch_p95_ms: 5000   # 95-й перцентиль отправки задачи < 5с
  api_error_rate: 0.01         # < 1% ошибок API
  device_registration_p95_ms: 3000  # Регистрация < 3с
  memory_usage_max_mb: 4096    # сервер не должен превышать 4 ГБ RAM
  cpu_usage_max_percent: 85    # CPU сервера < 85%
```

---

## 8. ОБНАРУЖЕННЫЕ BOTTLENECK (РЕЗУЛЬТАТ АНАЛИЗА)

### 8.1 Критические (Tier 1 — MUST FIX перед тестом)

| # | Компонент | Текущее | Проблема | Рекомендация |
|---|-----------|---------|----------|-------------|
| **B1** | PostgreSQL `max_connections` | 200 | 4 workers × 15 = 60 used; при 10K запросов в секунду — исчерпание | → 400 |
| **B2** | Backend `DB_POOL_SIZE` | 10 per worker | 10 × 4 = 40 active connections ← мало | → 20, overflow → 10 |
| **B3** | Redis `maxmemory` | 512 MB | 10K device status + task queues + video buffers | → 2 GB |
| **B4** | Nginx `limit_conn ws_conn_limit` | 100/IP | 10K WS connections с одного IP → reject | → 10 000 или отключить для теста |
| **B5** | Pipeline Executor `MAX_CONCURRENT_RUNS` | 10 | При 10K устройств 10 одновременных pipeline — узко | → 100 |

### 8.2 Серьёзные (Tier 2 — SHOULD FIX)

| # | Компонент | Текущее | Проблема | Рекомендация |
|---|-----------|---------|----------|-------------|
| **B6** | Redis `max_connections` | 50 + 20 (binary) | 4 workers × subscriptions + commands | → 150 + 50 |
| **B7** | Frontend event invalidation | Каждый event → full query refetch | 10K device_online events = storm | Debounce 2s |
| **B8** | Axios `timeout` | 5 000 ms | Может быть мало при нагрузке | → 15 000 ms |
| **B9** | Task Dispatcher loop | 0.1s poll | 10K × ZPOPMIN → Redis load | Batch dequeue |
| **B10** | ConnectionManager | In-process dict | Не масштабируется между workers | Redis-backed registry |

### 8.3 Умеренные (Tier 3 — NICE TO HAVE)

| # | Компонент | Текущее | Проблема | Рекомендация |
|---|-----------|---------|----------|-------------|
| **B11** | Prometheus labels | path-normalized | 10K devices × 22 endpoints = high cardinality | Sampling |
| **B12** | Audit middleware | PostgreSQL INSERT per request | 10K × 10 req/min = 100K INSERTs/min | Batch INSERT |
| **B13** | VPN IP pool | /16 = 65K адресов | Достаточно, но allocation fragmentation | Monitor |

---

## 9. ПРЕДТЕСТОВАЯ ПОДГОТОВКА (CHECKLIST)

### 9.1 Серверная подготовка

```bash
# PostgreSQL
ALTER SYSTEM SET max_connections = 400;
ALTER SYSTEM SET shared_buffers = '512MB';
ALTER SYSTEM SET work_mem = '16MB';
ALTER SYSTEM SET effective_cache_size = '1GB';
SELECT pg_reload_conf();

# Redis (redis.conf)
maxmemory 2gb
maxclients 300
tcp-keepalive 60

# Nginx
limit_conn ws_conn_limit 10000;
worker_connections 8192;

# Backend (.env)
DB_POOL_SIZE=20
DB_MAX_OVERFLOW=10

# OS (Linux)
ulimit -n 65535
sysctl -w net.core.somaxconn=65535
sysctl -w net.ipv4.tcp_max_syn_backlog=65535
sysctl -w fs.file-max=2097152
```

### 9.2 Создание тестовых данных

1. **Организация** — одна тестовая org с `plan=enterprise`
2. **API ключи** — 10 000 pre-generated API keys (`sphr_load_00001` … `sphr_load_10000`)
3. **Скрипт** — тестовый DAG с 5 нодами (tap → wait → condition → set_var → done)
4. **VPN пул** — /16 subnet (65K адресов) pre-allocated

### 9.3 Изоляция окружения

- Тест запускается на **выделенном** стенде (не prod!)
- Отдельная БД: `sphereplatform_loadtest`
- Отдельный Redis DB: `redis://.../{db_number}`
- Метрики отправляются в отдельный Prometheus instance

---

## ПРОДОЛЖЕНИЕ

Следующие части ТЗ:

- **[02-SCENARIOS.md](02-SCENARIOS.md)** — Детальные сценарии нагрузки (каждый endpoint, every message)
- **[03-METRICS-AND-CRITERIA.md](03-METRICS-AND-CRITERIA.md)** — Метрики, KPI, критерии pass/fail, формулы
