# ТЗ ЧАСТЬ 3: МЕТРИКИ, KPI И КРИТЕРИИ PASS/FAIL

> **Sphere Platform — Synthetic Fleet Load Test**
> **Версия:** 1.0 | **Дата:** 2026-03-04
> **Зависимости:** [01-ARCHITECTURE.md](01-ARCHITECTURE.md), [02-SCENARIOS.md](02-SCENARIOS.md)

---

## 1. КЛАССИФИКАЦИЯ МЕТРИК

### 1.1 Уровни метрик

```
 ┌──────────────────────────────────────────────────────┐
 │                  L1: БИЗНЕС-МЕТРИКИ                  │
 │  Fleet Availability, Task Success Rate, SLA Compliance│
 ├──────────────────────────────────────────────────────┤
 │                  L2: СЕРВИСНЫЕ МЕТРИКИ               │
 │  API Latency, WS Throughput, Error Rates             │
 ├──────────────────────────────────────────────────────┤
 │                  L3: ИНФРАСТРУКТУРНЫЕ МЕТРИКИ        │
 │  CPU, RAM, Disk I/O, Network, DB Pool, Redis Memory  │
 ├──────────────────────────────────────────────────────┤
 │                  L4: МЕТРИКИ ТЕСТОВОГО ФРЕЙМВОРКА    │
 │  Agent coroutine count, Event loop lag, GC pressure  │
 └──────────────────────────────────────────────────────┘
```

---

## 2. L1: БИЗНЕС-МЕТРИКИ (6 штук)

### 2.1 Fleet Availability (FA)

**Формула:**

$$FA = \frac{N_{online}}{N_{total}} \times 100\%$$

Где:
- $N_{online}$ — количество агентов в состоянии ONLINE
- $N_{total}$ — общее количество запущенных агентов (без DEAD)

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $FA \geq 98\%$ | Всё ОК |
| **WARN** | $95\% \leq FA < 98\%$ | Расследовать причину |
| **FAIL** | $FA < 95\%$ | **Тест провален** |

**Интервал замера:** каждые 10 секунд

---

### 2.2 Task Success Rate (TSR)

**Формула:**

$$TSR = \frac{N_{completed}}{N_{completed} + N_{failed} + N_{timeout}} \times 100\%$$

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $TSR \geq 78\%$ | Норма (ожидаемый 80% ± 2%) |
| **WARN** | $70\% \leq TSR < 78\%$ | Деградация |
| **FAIL** | $TSR < 70\%$ | **Тест провален** (серверный bottleneck) |

Примечание: ожидаемый TSR = 80% (конфигурация; 15% fail + 5% timeout — это
**виртуальный агент** симулирует ошибки, не сервер). Если TSR < 78%, значит
сервер не успевает доставить/обработать задачи.

---

### 2.3 VPN Enrollment Rate (VER)

**Формула:**

$$VER = \frac{N_{enrolled}}{N_{attempted}} \times 100\%$$

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $VER \geq 99\%$ | ОК |
| **FAIL** | $VER < 99\%$ | IP pool exhausted или сервер не справляется |

---

### 2.4 Mean Time To Connect (MTTC)

**Формула:**

$$MTTC = \frac{1}{N} \sum_{i=1}^{N} (t_{auth\_ack}^i - t_{ws\_open}^i)$$

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $MTTC \leq 2000ms$ | ОК |
| **WARN** | $2000ms < MTTC \leq 5000ms$ | Замедление |
| **FAIL** | $MTTC > 5000ms$ | **Тест провален** |

---

### 2.5 Fleet Event Delivery Latency (FEDL)

Задержка от события на агенте до отображения во Frontend WebSocket.

**Формула:**

$$FEDL = t_{frontend\_received} - t_{agent\_event}$$

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $FEDL_{p95} \leq 3000ms$ | Real-time приемлемо |
| **WARN** | $3000ms < FEDL_{p95} \leq 10000ms$ | Заметная задержка |
| **FAIL** | $FEDL_{p95} > 10000ms$ | Dashboard не real-time |

---

### 2.6 SLA Composite Score (SCS)

Наивзвешенная оценка всех L1 метрик:

$$SCS = 0.30 \times FA_{norm} + 0.25 \times TSR_{norm} + 0.15 \times VER_{norm} + 0.15 \times MTTC_{norm} + 0.15 \times FEDL_{norm}$$

Где $X_{norm} = \min(1.0, \frac{X_{actual}}{X_{target}})$

| Порог | Значение | Действие |
|-------|---------|----------|
| **PASS** | $SCS \geq 0.95$ | Enterprise SLA выполнен |
| **WARN** | $0.85 \leq SCS < 0.95$ | Условно |
| **FAIL** | $SCS < 0.85$ | **SLA нарушен** |

---

## 3. L2: СЕРВИСНЫЕ МЕТРИКИ (15 штук)

### 3.1 WebSocket Connection Metrics

| Метрика | Единица | p50 target | p95 target | p99 target | FAIL |
|---------|---------|-----------|-----------|-----------|------|
| `ws_connect_duration` | ms | 200 | 2 000 | 5 000 | p99 > 10 000 |
| `ws_auth_duration` | ms | 50 | 200 | 500 | p99 > 2 000 |
| `ws_heartbeat_rtt` | ms | 20 | 100 | 500 | p99 > 2 000 |
| `ws_message_latency` | ms | 10 | 50 | 200 | p99 > 1 000 |
| `ws_connection_error_rate` | % | — | — | — | > 2% |
| `ws_active_connections` | count | — | — | — | < 95% от target |

### 3.2 REST API Metrics

| Метрика | Единица | p50 target | p95 target | p99 target | FAIL |
|---------|---------|-----------|-----------|-----------|------|
| `api_device_register_duration` | ms | 100 | 1 000 | 3 000 | p95 > 3 000 |
| `api_vpn_enroll_duration` | ms | 200 | 2 000 | 5 000 | p95 > 5 000 |
| `api_vpn_status_duration` | ms | 50 | 200 | 500 | p95 > 1 000 |
| `api_task_create_duration` | ms | 100 | 500 | 2 000 | p95 > 5 000 |
| `api_error_rate_5xx` | % | — | — | — | > 1% |

### 3.3 Task Pipeline Metrics

| Метрика | Единица | Target | FAIL |
|---------|---------|--------|------|
| `task_dispatch_latency` | ms | p95 < 5 000 | p95 > 10 000 |
| `task_queue_depth` | count | < 1 000 | > 5 000 (backpressure) |
| `task_throughput` | tasks/sec | ≥ 20 | < 10 |
| `task_timeout_server_rate` | % | < 1% | > 5% (сервер не дождался ответа) |

---

## 4. L3: ИНФРАСТРУКТУРНЫЕ МЕТРИКИ (12 штук)

### 4.1 Серверные ресурсы

| Метрика | Источник | Target | WARN | FAIL |
|---------|---------|--------|------|------|
| `server_cpu_percent` | `psutil` / Prometheus | < 70% | 70–85% | > 85% |
| `server_memory_used_mb` | `psutil` | < 3 072 MB | 3–4 GB | > 4 GB |
| `server_memory_percent` | `psutil` | < 75% | 75–90% | > 90% |
| `server_open_fds` | `/proc/self/fd` | < 50 000 | 50–60K | > 60 000 |
| `server_network_rx_mbps` | `psutil` | < 800 Mbps | 800–950 | > 950 |
| `server_network_tx_mbps` | `psutil` | < 200 Mbps | 200–400 | > 400 |

### 4.2 PostgreSQL

| Метрика | Источник | Target | WARN | FAIL |
|---------|---------|--------|------|------|
| `pg_active_connections` | `pg_stat_activity` | < 100 | 100–180 | > 180 (из 200) |
| `pg_pool_utilization` | Backend pool stats | < 70% | 70–90% | > 90% |
| `pg_query_duration_p95` | `pg_stat_statements` | < 100ms | 100–500ms | > 500ms |
| `pg_deadlock_count` | `pg_stat_database` | 0 | 1–5 | > 5 |
| `pg_tup_inserted_per_sec` | `pg_stat_database` | < 1 000 | 1K–5K | > 5 000 |
| `pg_cache_hit_ratio` | `pg_stat_database` | > 99% | 95–99% | < 95% |

### 4.3 Redis

| Метрика | Источник | Target | WARN | FAIL |
|---------|---------|--------|------|------|
| `redis_used_memory_mb` | `INFO memory` | < 1 024 MB | 1–1.5 GB | > 1.5 GB |
| `redis_connected_clients` | `INFO clients` | < 200 | 200–280 | > 280 (из 300) |
| `redis_ops_per_sec` | `INFO stats` | < 50 000 | 50K–100K | > 100 000 |
| `redis_keyspace_misses_rate` | `INFO stats` | < 5% | 5–15% | > 15% |
| `redis_pubsub_channels` | `INFO` | < 20 000 | 20K–30K | > 30 000 |
| `redis_evicted_keys` | `INFO stats` | 0 | 1–100 | > 100 |

### 4.4 Nginx

| Метрика | Источник | Target | WARN | FAIL |
|---------|---------|--------|------|------|
| `nginx_active_connections` | `stub_status` | < 12 000 | 12K–15K | > 15 000 |
| `nginx_waiting_connections` | `stub_status` | < 5 000 | 5K–8K | > 8 000 |
| `nginx_requests_per_sec` | `stub_status` | — | — | — (мониторинг) |
| `nginx_5xx_rate` | access log | < 0.5% | 0.5–2% | > 2% |

---

## 5. L4: МЕТРИКИ ТЕСТОВОГО ФРЕЙМВОРКА

| Метрика | Target | Описание |
|---------|--------|----------|
| `loadtest_active_agents` | == target step | Все агенты запущены |
| `loadtest_event_loop_lag_ms` | < 100ms | asyncio loop не захлёбывается |
| `loadtest_gc_collections` | < 10/min | GC не давит на CPU |
| `loadtest_memory_used_mb` | < 15 000 MB | Не более 1.5 MB на агента |
| `loadtest_coroutine_count` | ~= 3 × N_agents | 3 корутины на агента (heartbeat + status + main) |
| `loadtest_messages_sent_per_sec` | ~= expected | Темп отправки соответствует расчёту |
| `loadtest_errors_per_sec` | < 10 | Ошибки в самом тесте (не в SUT) |

---

## 6. СВОДНАЯ ТАБЛИЦА PASS/FAIL КРИТЕРИЕВ

### 6.1 Scalability Test (32 → 10 000)

| Ступень | Агенты | FA ≥ | TSR ≥ | MTTC ≤ | API p95 ≤ | CPU ≤ | RAM ≤ |
|---------|--------|------|-------|--------|----------|-------|-------|
| Step 1 | 32 | 100% | 80% | 500ms | 200ms | 20% | 512MB |
| Step 2 | 64 | 100% | 80% | 500ms | 200ms | 20% | 512MB |
| Step 3 | 128 | 100% | 80% | 500ms | 300ms | 25% | 600MB |
| Step 4 | 256 | 100% | 80% | 700ms | 400ms | 30% | 700MB |
| Step 5 | 512 | 99% | 79% | 1000ms | 500ms | 35% | 900MB |
| Step 6 | 1 024 | 99% | 79% | 1200ms | 700ms | 45% | 1.2GB |
| Step 7 | 2 048 | 98% | 78% | 1500ms | 1000ms | 55% | 1.8GB |
| Step 8 | 4 096 | 98% | 78% | 2000ms | 1500ms | 65% | 2.5GB |
| Step 9 | 8 192 | 97% | 78% | 2500ms | 2000ms | 75% | 3.5GB |
| Step 10 | 10 000 | 97% | 78% | 3000ms | 2500ms | 85% | 4.0GB |

**Правило:** если ЛЮБАЯ метрика на текущей ступени в FAIL — ступень считается
**не пройденной**, тест продолжается, но в отчёте фиксируется точка деградации.

### 6.2 Spike Test (+2 000 за 10 секунд)

| Метрика | Target |
|---------|--------|
| FA во время spike | ≥ 92% |
| FA через 60 секунд после spike | ≥ 97% |
| Reconnect success rate | ≥ 95% |
| API 5xx rate во время spike | < 5% |
| API 5xx через 60 секунд | < 1% |

### 6.3 Soak Test (5K × 4 часа)

| Метрика | Target | Описание |
|---------|--------|----------|
| FA min за 4 часа | ≥ 97% | Не проседает со временем |
| FA std deviation | < 2% | Стабильна |
| Memory growth per hour | < 100 MB | Нет утечки памяти |
| Redis memory growth per hour | < 50 MB | Нет утечки ключей |
| DB connection leaks | 0 | Pool стабилен |
| Task success rate drift | < 3% | Не деградирует со временем |
| 99th latency drift per hour | < 20% | Не растёт со временем |

---

## 7. ФОРМУЛЫ РАСЧЁТА ПЕРЦЕНТИЛЕЙ

### 7.1 HdrHistogram (алгоритм)

Для точных перцентилей используем **HdrHistogram** вместо digest-алгоритмов:

```python
from hdrh.histogram import HdrHistogram

class LatencyHistogram:
    """Высокоточная гистограмма задержек."""

    def __init__(
        self,
        lowest_discernible_value: int = 1,     # 1 мс
        highest_trackable_value: int = 60_000,  # 60 сек
        significant_figures: int = 3             # 3 значащие цифры
    ):
        self.hist = HdrHistogram(
            lowest_discernible_value,
            highest_trackable_value,
            significant_figures
        )

    def record(self, value_ms: float) -> None:
        """Записать значение задержки."""
        self.hist.record_value(int(value_ms))

    def percentile(self, p: float) -> float:
        """Получить перцентиль (p=50.0, 95.0, 99.0, 99.9)."""
        return self.hist.get_value_at_percentile(p)

    def summary(self) -> dict:
        """Полная сводка."""
        return {
            "count": self.hist.total_count,
            "min": self.hist.min_value,
            "max": self.hist.max_value,
            "mean": self.hist.get_mean_value(),
            "stddev": self.hist.get_stddev(),
            "p50": self.percentile(50.0),
            "p75": self.percentile(75.0),
            "p90": self.percentile(90.0),
            "p95": self.percentile(95.0),
            "p99": self.percentile(99.0),
            "p999": self.percentile(99.9),
        }
```

### 7.2 Throughput (скользящее среднее)

$$Throughput_{window} = \frac{N_{messages}}{T_{window}}$$

Окно: 10 секунд, скользящее с шагом 1 секунда.

### 7.3 Error Rate

$$ErrorRate = \frac{N_{errors}}{N_{total}} \times 100\%$$

Где $N_{errors}$ = 5xx ответы + WS disconnect без graceful close + timeout.

### 7.4 Деградация (Degradation Coefficient)

Коэффициент деградации при масштабировании:

$$DC_{step} = \frac{Latency_{p95}^{step}}{Latency_{p95}^{baseline}} \times \frac{N_{agents}^{baseline}}{N_{agents}^{step}}$$

При **идеальном масштабировании** $DC = 1.0$.

| DC | Оценка |
|----|--------|
| $DC \leq 1.2$ | Отличное масштабирование |
| $1.2 < DC \leq 2.0$ | Приемлемое |
| $2.0 < DC \leq 5.0$ | Плохое (bottleneck) |
| $DC > 5.0$ | Критический bottleneck |

---

## 8. ФОРМАТ ОТЧЁТА

### 8.1 JSON отчёт (машиночитаемый)

```json
{
  "meta": {
    "test_name": "Sphere Fleet Scalability Test",
    "test_version": "1.0.0",
    "started_at": "2026-03-04T12:00:00Z",
    "finished_at": "2026-03-04T12:48:00Z",
    "duration_seconds": 2880,
    "target_url": "http://10.0.2.2:8000",
    "git_commit": "abc123",
    "result": "PASS"
  },
  "steps": [
    {
      "name": "step_32",
      "target_agents": 32,
      "actual_agents_peak": 32,
      "duration_seconds": 150,
      "result": "PASS",
      "metrics": {
        "fleet_availability": {
          "mean": 100.0,
          "min": 100.0,
          "max": 100.0
        },
        "ws_connect_duration": {
          "p50": 120,
          "p95": 250,
          "p99": 400,
          "count": 32
        },
        "api_latency": {
          "p50": 45,
          "p95": 120,
          "p99": 200,
          "count": 384
        },
        "task_success_rate": 81.2,
        "server_cpu_percent": {
          "mean": 8.5,
          "max": 15.0
        },
        "server_memory_mb": {
          "mean": 420,
          "max": 450
        },
        "degradation_coefficient": 1.0
      }
    }
  ],
  "summary": {
    "max_agents_passed": 10000,
    "first_degradation_step": "step_4096",
    "bottleneck_identified": "PostgreSQL pool exhaustion at 4096 agents",
    "sla_composite_score": 0.96,
    "total_messages_sent": 4850000,
    "total_messages_received": 4750000,
    "total_errors": 2340,
    "total_reconnects": 156,
    "peak_throughput_msg_per_sec": 12500
  },
  "thresholds_evaluation": [
    {
      "metric": "ws_connect_p95_ms",
      "threshold": 2000,
      "actual": 1850,
      "result": "PASS"
    }
  ],
  "recommendations": [
    "Увеличить DB_POOL_SIZE до 30 для стабильной работы на 10K",
    "Redis maxmemory: увеличить до 2GB (текущий пик 1.2GB)",
    "Рассмотреть horizontal scaling backend при > 5K агентов"
  ]
}
```

### 8.2 HTML отчёт (человекочитаемый)

Генерируется из Jinja2-шаблона и содержит:

1. **Заголовок** — название теста, дата, результат (PASS/WARN/FAIL бейдж)
2. **Executive Summary** — ключевые цифры одним экраном
3. **Графики ступеней** — latency/throughput/error rate на каждой ступени
4. **Тепловая карта** — матрица метрик × ступеней (зелёный/жёлтый/красный)
5. **Timeline** — временная ось с ключевыми событиями
6. **Bottleneck Analysis** — автоматический анализ узких мест
7. **Рекомендации** — автоматически сгенерированные советы
8. **Raw Data** — ссылка на JSON-отчёт

### 8.3 Grafana Dashboard (real-time)

Панели:

| # | Панель | Тип | Описание |
|---|--------|-----|----------|
| 1 | Active Agents | Gauge + Graph | Текущее кол-во агентов vs target |
| 2 | Fleet Availability | Stat + Sparkline | % онлайн (красный если < 95%) |
| 3 | WS Connect Latency | Histogram | p50/p95/p99 |
| 4 | API Latency | Histogram | p50/p95/p99 по endpoint |
| 5 | Throughput | Graph | msg/sec inbound + outbound |
| 6 | Error Rate | Graph | % ошибок (5xx + WS errors) |
| 7 | Task Pipeline | Stacked Bar | Queued / Running / Completed / Failed |
| 8 | Server CPU | Graph | % по ядрам |
| 9 | Server Memory | Graph | Used / Available (MB) |
| 10 | PostgreSQL | Graph | Connections / Query latency |
| 11 | Redis | Graph | Memory / Ops/sec / Clients |
| 12 | Nginx | Graph | Active connections / 5xx rate |

---

## 9. АВТОМАТИЗАЦИЯ ЗАПУСКА

### 9.1 CLI интерфейс

```bash
# Быстрый smoke-test (32→512, 5 минут)
python -m tests.load --scenario quick --target http://localhost:8000

# Полный scalability test (32→10K, ~48 минут)
python -m tests.load --scenario scalability --target http://localhost:8000

# Soak test (5K × 4 часа)
python -m tests.load --scenario soak --target http://localhost:8000

# Spike test
python -m tests.load --scenario spike --target http://localhost:8000

# С кастомным конфигом
python -m tests.load --config config/custom.yml

# С push в Prometheus gateway
python -m tests.load --scenario scalability --push-metrics http://pushgateway:9091

# Только отчёт из существующего прогона
python -m tests.load report --input results/2026-03-04_12-00-00.json --format html
```

### 9.2 pytest-интеграция

```python
# test_load_scalability.py
import pytest

@pytest.mark.loadtest
@pytest.mark.timeout(3600)  # 1 час макс
class TestFleetScalability:
    """Ступенчатый нагрузочный тест флота 32→10K."""

    def test_step_32(self, load_orchestrator):
        """Baseline — 32 агента."""
        result = load_orchestrator.run_step("step_32")
        assert result.fleet_availability >= 100.0
        assert result.ws_connect_p95 <= 500

    def test_step_1024(self, load_orchestrator):
        """Тысячник."""
        result = load_orchestrator.run_step("step_1024")
        assert result.fleet_availability >= 99.0
        assert result.ws_connect_p95 <= 1200
        assert result.api_error_rate_5xx <= 0.01

    def test_step_10000(self, load_orchestrator):
        """Полный флот — 10K агентов."""
        result = load_orchestrator.run_step("step_10000")
        assert result.fleet_availability >= 97.0
        assert result.ws_connect_p95 <= 3000
        assert result.task_success_rate >= 78.0
        assert result.server_cpu_percent <= 85.0
        assert result.server_memory_mb <= 4096

    def test_spike_recovery(self, load_orchestrator):
        """Spike +2K и восстановление."""
        result = load_orchestrator.run_step("spike_12000")
        assert result.fleet_availability >= 92.0
        # Ждём recovery
        recovery = load_orchestrator.run_step("recovery_10000")
        assert recovery.fleet_availability >= 97.0
```

### 9.3 CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/load-test.yml
name: Fleet Load Test
on:
  schedule:
    - cron: '0 3 * * 0'  # Каждое воскресенье в 3:00
  workflow_dispatch:
    inputs:
      scenario:
        description: 'Сценарий'
        required: true
        default: 'quick'
        type: choice
        options: [quick, scalability, soak, spike]

jobs:
  load-test:
    runs-on: self-hosted  # Нужен мощный раннер
    timeout-minutes: 300
    steps:
      - uses: actions/checkout@v4
      - name: Настройка Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Установка зависимостей
        run: pip install -e ".[loadtest]"

      - name: Поднятие тестового стенда
        run: docker compose -f docker-compose.yml -f docker-compose.full.yml up -d

      - name: Ожидание готовности
        run: |
          for i in $(seq 1 30); do
            curl -sf http://localhost:8000/api/v1/health/ready && break
            sleep 5
          done

      - name: Запуск нагрузочного теста
        run: python -m tests.load --scenario ${{ inputs.scenario }} --target http://localhost:8000

      - name: Публикация отчёта
        uses: actions/upload-artifact@v4
        with:
          name: load-test-report
          path: tests/load/results/
```

---

## 10. ЗАВИСИМОСТИ (requirements)

```toml
# Дополнение в pyproject.toml [project.optional-dependencies]
[project.optional-dependencies]
loadtest = [
    "websockets>=13.0",
    "aiohttp>=3.10",
    "hdrhistogram>=0.10",
    "pyyaml>=6.0",
    "pydantic>=2.5",
    "jinja2>=3.1",
    "prometheus-client>=0.21",
    "rich>=13.0",
    "psutil>=6.0",
    "asyncpg>=0.30",
    "msgpack>=1.0",
]
```

---

## 11. ИТОГОВАЯ МАТРИЦА ОТВЕТСТВЕННОСТИ

| Компонент | Что тестируем | Метрики | Порог FAIL |
|----------|--------------|---------|-----------|
| **Nginx** | WS proxy, rate limit | active_conn, 5xx | > 15K conn, > 2% 5xx |
| **FastAPI** | REST + WS handlers | latency, throughput | p95 > 3s, > 1% 5xx |
| **PostgreSQL** | Pool, queries, locks | pool_util, query_p95 | > 90% pool, > 500ms query |
| **Redis** | PubSub, cache, queue | memory, ops/sec | > 1.5GB, > 100K ops |
| **Task Dispatcher** | Queue processing | dispatch_latency, depth | p95 > 10s, depth > 5K |
| **Pipeline Executor** | DAG orchestration | concurrent_runs | blocked at 10 |
| **WS ConnectionManager** | In-memory registry | connection_count | < 95% target |
| **VPN Service** | IP allocation | enrollment_rate | < 99% success |
| **Video Bridge** | Frame relay | frame_drops, bandwidth | > 50% frame drops |
| **Frontend Events** | Query invalidation | event_delivery_lag | p95 > 10s |

---

## 12. КОНТРОЛЬНЫЕ ВОПРОСЫ ПЕРЕД ЗАПУСКОМ

- [ ] Тестовый стенд изолирован от production?
- [ ] PostgreSQL max_connections ≥ 400?
- [ ] Redis maxmemory ≥ 2GB?
- [ ] Nginx limit_conn ≥ 10 000?
- [ ] Backend DB_POOL_SIZE ≥ 20?
- [ ] ulimit -n ≥ 65 535 (и на тестовой машине, и на сервере)?
- [ ] Промониторить хватит disk space для логов (min 10 GB)?
- [ ] Grafana dashboard импортирован?
- [ ] Prometheus scrape target добавлен?
- [ ] Тестовые API ключи созданы (10 000 штук)?
- [ ] sample_video.h264 сгенерирован?
- [ ] Бэкап БД перед тестом сделан?
- [ ] Скрипт очистки после теста готов?

---

## НАВИГАЦИЯ ПО ТЗ

| Часть | Файл | Содержание |
|-------|------|-----------|
| 1 | [01-ARCHITECTURE.md](01-ARCHITECTURE.md) | Архитектура теста, bottleneck, checklist подготовки |
| 2 | [02-SCENARIOS.md](02-SCENARIOS.md) | Детальные сценарии, протоколы, тайминги |
| 3 | **03-METRICS-AND-CRITERIA.md** (этот файл) | Метрики, KPI, критерии pass/fail, отчёты |
