# ТЗ ЧАСТЬ 2: СЦЕНАРИИ НАГРУЗКИ

> **Sphere Platform — Synthetic Fleet Load Test**
> **Версия:** 1.0 | **Дата:** 2026-03-04
> **Зависимость:** [01-ARCHITECTURE.md](01-ARCHITECTURE.md)

---

## 1. ОБЗОР СЦЕНАРИЕВ

Тест состоит из **6 независимых сценариев**, которые комбинируются в итоговый
**Mixed Workload** — точная копия поведения реального флота.

| # | Сценарий | Приоритет | Покрытие |
|---|----------|----------|----------|
| S1 | Device Registration | P0 | REST API, DB, API keys |
| S2 | WebSocket Lifecycle | P0 | WS connect, auth, heartbeat, status, reconnect |
| S3 | Task Execution | P0 | Task queue, dispatcher, DAG results |
| S4 | VPN Enrollment | P1 | VPN API, WireGuard enrollment, status polling |
| S5 | Video Streaming | P1 | Binary WS frames, backpressure, NAL units |
| S6 | Mixed Workload | P0 | **ВСЁ одновременно** — главный сценарий |

---

## 2. СЦЕНАРИЙ S1: МАССОВАЯ РЕГИСТРАЦИЯ УСТРОЙСТВ

### 2.1 Описание

Симуляция одновременной регистрации N устройств через REST API.
В реальности: новая партия эмуляторов впервые подключается к серверу.

### 2.2 HTTP-протокол (точная копия реального агента)

```
Шаг 1: Регистрация устройства
─────────────────────────────
POST /api/v1/devices/register
Headers:
  Content-Type: application/json
  X-API-Key: sphr_load_00001
  X-Request-ID: <uuid>
Body:
{
  "device_id": "a1b2c3d4-...",
  "serial": "LOAD-00001",
  "model": "G576D",
  "os_version": "Android 13",
  "agent_version": "2.1.0",
  "capabilities": ["screen_capture", "root", "vpn", "streaming"],
  "fingerprint": {
    "build_id": "TQ3A.230805.001",
    "hardware": "qcom",
    "product": "phx110",
    "ldplayer_instance_id": "load-00001"
  }
}

Response 201:
{
  "id": "a1b2c3d4-...",
  "org_id": "05b0843a-...",
  "name": "auto-load-00001",
  "status": "registered",
  "created_at": "2026-03-04T..."
}

Response 409 (duplicate):
{
  "detail": "Device with this serial already exists"
}
```

```
Шаг 2: Проверка статуса (после WebSocket)
──────────────────────────────────────────
GET /api/v1/devices/me
Headers:
  X-API-Key: sphr_load_00001

Response 200:
{
  "id": "a1b2c3d4-...",
  "status": "online",
  "last_seen": "2026-03-04T...",
  "pending_commands": []
}
```

### 2.3 Тайминги

| Параметр | Значение |
|----------|---------|
| Ramp-rate регистрации | 100 устройств/сек (линейно) |
| Пауза между повторами (409) | 5 сек |
| Макс. число попыток | 3 |
| Таймаут запроса | 10 сек |

### 2.4 Что замеряем

- **registration_latency** — время ответа POST /devices/register (p50/p95/p99)
- **registration_success_rate** — % успешных 201
- **registration_duplicate_rate** — % 409 (должен быть 0 при первом запуске)
- **registration_error_rate** — % 5xx ошибок
- **db_connections_used** — пул соединений во время массовой регистрации

---

## 3. СЦЕНАРИЙ S2: ЖИЗНЕННЫЙ ЦИКЛ WEBSOCKET

### 3.1 Описание

Полный жизненный цикл WebSocket-соединения: подключение → аутентификация →
heartbeat → обновление статуса → получение команд → reconnect.

### 3.2 WebSocket-протокол (точная копия реального агента)

```
Фаза 1: TCP + WebSocket Handshake
──────────────────────────────────
GET /ws/android/{token} HTTP/1.1
Upgrade: websocket
Connection: Upgrade
Sec-WebSocket-Version: 13


Фаза 2: First-message аутентификация
──────────────────────────────────────
Client → Server (JSON text frame):
{
  "type": "auth",
  "token": "sphr_load_00001",        // API key (не JWT!)
  "device_id": "a1b2c3d4-...",
  "agent_version": "2.1.0",
  "protocol_version": 2
}

Server → Client (JSON text frame):
{
  "type": "auth_ack",
  "session_id": "sess_abc123def456",
  "server_time": "2026-03-04T12:00:00Z",
  "heartbeat_interval": 30,
  "config": {
    "status_interval": 10,
    "max_concurrent_tasks": 1
  }
}


Фаза 3: Heartbeat (каждые 30 секунд)
─────────────────────────────────────
Client → Server (JSON text frame):
{
  "type": "ping",
  "timestamp": 1709553600000
}

Server → Client (JSON text frame):
{
  "type": "pong",
  "timestamp": 1709553600000,
  "server_time": 1709553600050
}


Фаза 4: Обновление статуса устройства (каждые 10 секунд)
─────────────────────────────────────────────────────────
Client → Server (JSON text frame):
{
  "type": "device_status",
  "status": "online",
  "battery_level": 87,
  "battery_charging": true,
  "memory_total_mb": 4096,
  "memory_used_mb": 2134,
  "cpu_usage_percent": 23.5,
  "screen_on": true,
  "screen_width": 1080,
  "screen_height": 2340,
  "wifi_ssid": "LoadTestNet",
  "wifi_rssi": -45,
  "vpn_active": true,
  "vpn_ip": "10.100.0.42",
  "uptime_seconds": 86400,
  "storage_free_mb": 12800,
  "running_app": "com.example.target",
  "agent_pid": 12345,
  "timestamp": 1709553600000
}

Server → Client (JSON text frame):
{
  "type": "status_ack",
  "timestamp": 1709553600050
}


Фаза 5: Получение команды от сервера
────────────────────────────────────
Server → Client (JSON text frame):
{
  "type": "command",
  "command_id": "cmd_xyz789",
  "command_type": "execute_dag",
  "payload": {
    "task_id": "task_abc123",
    "script_id": "script_def456",
    "dag": { ... },
    "timeout_seconds": 300
  },
  "ttl": 60,
  "created_at": "2026-03-04T12:05:00Z"
}

Client → Server (JSON text frame):  // ACK немедленно
{
  "type": "command_ack",
  "command_id": "cmd_xyz789",
  "timestamp": 1709553900050
}


Фаза 6: Reconnect (при разрыве)
────────────────────────────────
Детекция: WebSocket close frame / network timeout (90s без pong)

Backoff: attempt 1 → 1s, 2 → 2s, 3 → 4s, ... cap → 30s
Jitter: ±20% к каждой задержке (anti-stampede)

При reconnect: полный цикл Фаза 1 → Фаза 2 → продолжение
```

### 3.3 Тайминги для виртуального агента

| Параметр | Значение |
|----------|---------|
| Heartbeat interval | 30 ± 2 сек (джиттер) |
| Status interval | 10 ± 1 сек |
| Watchdog timeout (нет pong) | 90 сек → reconnect |
| Reconnect backoff base | 1 сек |
| Reconnect backoff max | 30 сек |
| Reconnect jitter | ±20% |
| Max reconnect retries | 10 (потом агент → DEAD) |

### 3.4 Генерация реалистичных данных

```python
# Статус устройства генерируется реалистично
def generate_device_status(agent: VirtualAgent) -> dict:
    """Генерация реалистичного статуса виртуального агента."""
    elapsed = time.time() - agent.start_time
    return {
        "type": "device_status",
        "status": "online" if agent.connected else "reconnecting",
        "battery_level": max(15, 100 - int(elapsed / 60)),  # Разряжается 1% в минуту
        "battery_charging": random.random() < 0.3,          # 30% шанс на зарядке
        "memory_total_mb": agent.identity.memory_mb,
        "memory_used_mb": random.randint(
            agent.identity.memory_mb // 3,
            agent.identity.memory_mb * 2 // 3
        ),
        "cpu_usage_percent": round(
            random.gauss(30, 15),  # Нормальное распределение ~30% ± 15%
            1
        ),
        "screen_on": True,
        "screen_width": agent.identity.screen_w,
        "screen_height": agent.identity.screen_h,
        "wifi_rssi": random.randint(-70, -30),
        "vpn_active": agent.vpn_enrolled,
        "vpn_ip": agent.vpn_ip or "",
        "uptime_seconds": int(elapsed),
        "storage_free_mb": random.randint(8000, 24000),
        "running_app": "com.example.target" if agent.executing_task else "",
        "timestamp": int(time.time() * 1000)
    }
```

### 3.5 Нагрузочный профиль WebSocket

При **10 000 агентов online** на сервер приходит:

| Тип сообщения | Частота per agent | Total msg/sec | Total bytes/sec |
|---------------|------------------|---------------|-----------------|
| ping | 1 / 30s | 333 msg/s | ~20 KB/s |
| device_status | 1 / 10s | 1 000 msg/s | ~500 KB/s |
| command_ack | ~0.01/s (по задачам) | ~100 msg/s | ~10 KB/s |
| task_result | ~0.003/s | ~30 msg/s | ~30 KB/s |
| **ИТОГО входящий** | — | **~1 463 msg/s** | **~560 KB/s** |

Исходящий от сервера:

| Тип сообщения | Частота per agent | Total msg/sec | Total bytes/sec |
|---------------|------------------|---------------|-----------------|
| pong | 1 / 30s | 333 msg/s | ~13 KB/s |
| status_ack | 1 / 10s | 1 000 msg/s | ~30 KB/s |
| command | ~0.01/s | ~100 msg/s | ~50 KB/s |
| **ИТОГО исходящий** | — | **~1 433 msg/s** | **~93 KB/s** |

---

## 4. СЦЕНАРИЙ S3: ВЫПОЛНЕНИЕ ЗАДАЧ (TASK EXECUTION)

### 4.1 Описание

Сервер отправляет команду `execute_dag`, агент «выполняет» скрипт и
возвращает результат. Виртуальный агент симулирует задержку выполнения.

### 4.2 Полный flow

```
1. Сервер → Агент: command (execute_dag)
   ↓
2. Агент → Сервер: command_ack (мгновенно)
   ↓
3. Агент → Сервер: task_progress (периодически)
   {
     "type": "task_progress",
     "task_id": "task_abc123",
     "progress": 0.35,         // 35%
     "current_node": "tap_button",
     "elapsed_ms": 4200,
     "timestamp": 1709553900000
   }
   ↓
4. Агент ожидает 2–30 секунд (симуляция DAG execution)
   ↓
5. Агент → Сервер: task_result
   {
     "type": "task_result",
     "task_id": "task_abc123",
     "command_id": "cmd_xyz789",
     "status": "completed",      // | "failed" | "timeout"
     "result": {
       "nodes_executed": 5,
       "total_nodes": 5,
       "duration_ms": 12450,
       "variables": {
         "cycle_count": "3",
         "last_action": "tap_ok"
       },
       "screenshots": 0,          // виртуальный агент не шлёт скриншоты
       "errors": []
     },
     "logs": [
       {"ts": "...", "node": "start", "action": "set_variable", "ok": true},
       {"ts": "...", "node": "tap_btn", "action": "tap", "ok": true},
       {"ts": "...", "node": "wait_2s", "action": "wait", "ok": true},
       {"ts": "...", "node": "check", "action": "condition", "ok": true},
       {"ts": "...", "node": "done", "action": "set_variable", "ok": true}
     ],
     "timestamp": 1709553912450
   }
```

### 4.3 Распределение результатов задач

```python
# Вероятности результатов (конфигурируемо)
TASK_OUTCOMES = {
    "completed": 0.80,    # 80% — успех
    "failed": 0.15,       # 15% — ошибка (node not found, app crash)
    "timeout": 0.05       # 5% — timeout (зависание)
}

# Время выполнения (нормальное распределение)
TASK_DURATION_DISTRIBUTION = {
    "completed": (8000, 3000),    # μ=8s, σ=3s → 80% в [5s, 11s]
    "failed": (4000, 2000),       # Быстрее (ошибка на раннем ноде)
    "timeout": (300000, 0)        # Всегда 300s (ровно timeout)
}
```

### 4.4 Batch Task Dispatch (серверная сторона)

Для теста нужна отдельная горутина, которая создаёт задачи:

```
Task Generator:
  Каждые 60 секунд:
    POST /api/v1/batches
    {
      "script_id": "load_test_dag",
      "device_ids": [первые 100 ONLINE не-busy агентов],
      "wave_count": 10,
      "devices_per_wave": 10,
      "delay_between_waves_ms": 5000,
      "priority": 5
    }

  Результат: 100 задач за 50 секунд (10 волн × 10)
  При 10K агентов: 100 batches = 10 000 задач за ~8.3 мин
```

### 4.5 Нагрузка на Task Queue

| Метрика | Значение |
|---------|---------|
| Task create rate | ~20 tasks/sec (batch) |
| Task dequeue rate | ~20 tasks/sec (dispatcher Lua ZPOPMIN) |
| Task running concurrently | ≤ 10 000 (1 per device) |
| Task result rate | ~30 results/sec (staggered completion) |
| Redis ZSet size peak | ~10 000 entries |
| PostgreSQL task INSERTs | ~20/sec |
| PostgreSQL task UPDATEs | ~30/sec (status transitions) |

---

## 5. СЦЕНАРИЙ S4: VPN ENROLLMENT

### 5.1 Описание

Каждый агент при подключении включает VPN: enrollment → получение
WireGuard конфига → проверка статуса.

### 5.2 REST-протокол

```
Шаг 1: Enrollment
─────────────────
POST /api/v1/vpn/enroll
Headers:
  Authorization: Bearer <jwt_token>
  Content-Type: application/json
Body:
{
  "device_id": "a1b2c3d4-...",
  "public_key": "base64_wg_pubkey_32_bytes..."
}

Response 201:
{
  "peer_id": "peer_xyz",
  "allocated_ip": "10.100.0.42",
  "server_endpoint": "vpn.sphere.example.com:51820",
  "server_public_key": "base64_server_pubkey...",
  "dns": ["10.100.0.1"],
  "allowed_ips": "0.0.0.0/0",
  "keepalive": 25,
  "amnezia_jc": 4,
  "amnezia_jmin": 50,
  "amnezia_jmax": 1000
}


Шаг 2: Статус-check (каждые 60 секунд)
───────────────────────────────────────
GET /api/v1/vpn/status?device_id=a1b2c3d4-...
Headers:
  Authorization: Bearer <jwt_token>

Response 200:
{
  "device_id": "a1b2c3d4-...",
  "vpn_active": true,
  "allocated_ip": "10.100.0.42",
  "last_handshake": "2026-03-04T12:05:00Z",
  "transfer_rx_bytes": 1234567,
  "transfer_tx_bytes": 7654321,
  "connected_since": "2026-03-04T12:01:00Z"
}
```

### 5.3 Генерация WireGuard ключей

```python
# Каждый виртуальный агент генерирует уникальную пару ключей
import base64
import os

def generate_wg_keypair() -> tuple[str, str]:
    """Генерация WireGuard keypair (Curve25519)."""
    private_key = os.urandom(32)
    # Применяем clamp (RFC 7748)
    private_bytes = bytearray(private_key)
    private_bytes[0] &= 248
    private_bytes[31] &= 127
    private_bytes[31] |= 64
    private_b64 = base64.b64encode(bytes(private_bytes)).decode()
    # Публичный ключ — заглушка (сервер его просто сохраняет)
    public_b64 = base64.b64encode(os.urandom(32)).decode()
    return private_b64, public_b64
```

### 5.4 Нагрузка VPN

| Метрика | Значение |
|---------|---------|
| Enrollment rate (ramp-up) | 100-200 per sec |
| Status check rate (steady) | ~167 per sec (10K / 60s) |
| VPN peers in DB | 10 000 |
| IP allocation range | 10.100.0.0/16 (65K адресов) |
| Redis VPN hash size | ~10K entries |

---

## 6. СЦЕНАРИЙ S5: VIDEO STREAMING

### 6.1 Описание

5–10% агентов одновременно стримят H.264 видео через WebSocket binary frames.
Это самый тяжёлый сценарий по bandwidth.

### 6.2 Binary WebSocket Protocol

```
Video Frame (binary WebSocket message):
┌──────────────┬──────────────┬─────────────────┐
│ NAL Header   │ NAL Type     │ NAL Payload     │
│ (4 bytes     │ (1 byte      │ (variable)      │
│ start code)  │ & 0x1F)      │                 │
│ 00 00 00 01  │ 67 (SPS)     │ ...             │
│ 00 00 00 01  │ 68 (PPS)     │ ...             │
│ 00 00 00 01  │ 65 (IDR)     │ I-frame payload │
│ 00 00 00 01  │ 41 (NON_IDR) │ P-frame payload │
└──────────────┴──────────────┴─────────────────┘

Порядок отправки:
  1. SPS (1 раз при старте + каждый IDR)
  2. PPS (1 раз при старте + каждый IDR)
  3. IDR frame (I-frame, каждые 2s при 15fps)
  4. NON_IDR frames (P-frames, 14 из каждых 15)
```

### 6.3 Предзаписанный H.264 поток

Вместо реального кодирования используется **предзаписанный файл**:

```
fixtures/sample_video.h264:
  Разрешение: 720 × 1280
  FPS: 15
  Bitrate: ~1.5 Mbps
  GOPSize: 30 (1 IDR каждые 2 секунды)
  Длительность: 10 секунд (зацикливается)
  Кодек: H.264 Baseline Profile Level 3.1
  Размер: ~1.8 MB
```

### 6.4 Симуляция отправки

```python
class VideoStreamer:
    """Симулятор H.264 видео-стриминга для виртуального агента."""

    def __init__(self, h264_file: Path, fps: int = 15):
        self.nal_units = self._parse_nal_units(h264_file)
        self.fps = fps
        self.frame_interval = 1.0 / fps

    async def stream(self, ws: WebSocket):
        """Бесконечный цикл отправки NAL units."""
        idx = 0
        while True:
            nal = self.nal_units[idx % len(self.nal_units)]
            await ws.send(nal.data)  # binary frame

            # Метрики
            self.frames_sent += 1
            self.bytes_sent += len(nal.data)

            idx += 1
            await asyncio.sleep(self.frame_interval)

    @staticmethod
    def _parse_nal_units(path: Path) -> list[NALUnit]:
        """Парсинг NAL units из H.264 Annex B файла."""
        data = path.read_bytes()
        units = []
        # Ищем стартовые коды 00 00 00 01
        starts = []
        for i in range(len(data) - 3):
            if data[i:i+4] == b'\x00\x00\x00\x01':
                starts.append(i)
        for i, start in enumerate(starts):
            end = starts[i+1] if i+1 < len(starts) else len(data)
            nal_data = data[start:end]
            nal_type = nal_data[4] & 0x1F
            units.append(NALUnit(data=nal_data, nal_type=nal_type))
        return units
```

### 6.5 Нагрузка Video Streaming

При **500 агентов** стримящих видео (5% от 10K):

| Метрика | Значение |
|---------|---------|
| Total video streams | 500 |
| FPS per stream | 15 |
| Total frames/sec | 7 500 |
| Avg frame size | ~6.7 KB (1.5 Mbps / 15 fps / 8) |
| **Total bandwidth** | **~93.75 MB/s (750 Mbps!)** |
| Binary WS messages/sec | 7 500 |
| WebSocket buffer pressure | ВЫСОКАЯ |

**ВАЖНО:** 750 Mbps — это предельная нагрузка на сеть. В реальности:
- Backpressure на сервере дропает P-frames
- Если нет viewer для агента — сервер не запрашивает видео
- Реальная нагрузка ~ 10-50 стримов одновременно ≈ 15-75 Mbps

Для теста: стримят **ТОЛЬКО если есть виртуальный viewer** (настраиваемо).

---

## 7. СЦЕНАРИЙ S6: MIXED WORKLOAD (ОСНОВНОЙ)

### 7.1 Описание

Комбинация ВСЕХ сценариев одновременно — точная копия поведения реального флота.

### 7.2 Временная шкала одного виртуального агента

```
t=0.000s  │ Agent created
t=0.100s  │ POST /api/v1/devices/register → 201
t=0.500s  │ WebSocket connect → /ws/android/{token}
t=0.600s  │ WS: auth message → auth_ack
t=0.700s  │ POST /api/v1/vpn/enroll → 201 (WireGuard peer)
t=1.000s  │ WS: first device_status update
          │
          │ ┌─ ONLINE LOOP ────────────────────────────────────┐
t=10.00s  │ │ WS: device_status (battery=98, cpu=25%)         │
t=20.00s  │ │ WS: device_status (battery=97, cpu=31%)         │
t=30.00s  │ │ WS: ping → pong (heartbeat)                     │
t=30.50s  │ │ WS: device_status (battery=96, cpu=22%)         │
          │ │                                                   │
t=47.00s  │ │ Server → command(execute_dag) → ack              │
t=47.10s  │ │ WS: task_progress(0.20)                          │
t=52.00s  │ │ WS: task_progress(0.60)                          │
t=55.00s  │ │ WS: task_result(completed, duration=8000ms)      │
          │ │                                                   │
t=60.00s  │ │ WS: ping → pong                                  │
t=60.50s  │ │ GET /api/v1/vpn/status → 200 (vpn_active=true)  │
t=70.00s  │ │ WS: device_status (battery=93, cpu=18%)         │
          │ │ ...продолжается по кругу...                       │
          │ └──────────────────────────────────────────────────┘
          │
          │ [5% шанс] → видео-стриминг параллельно (H.264)
          │ [0.1%/мин] → случайный disconnect → reconnect
```

### 7.3 Распределение нагрузки по типам агентов

| Тип агента | % от флота | Поведение |
|-----------|-----------|-----------|
| **Idle** | 30% | Online, heartbeat + status, НЕ выполняет задачи |
| **Worker** | 55% | Online, heartbeat + status, ВЫПОЛНЯЕТ задачи (1 за раз) |
| **Streamer** | 5% | Worker + H.264 видео стриминг |
| **Flaky** | 8% | Worker, но часто disconnected (reconnect каждые 3-5 мин) |
| **Dead** | 2% | Зарегистрированы, но offline (симуляция сломанных эмуляторов) |

### 7.4 Суммарный профиль нагрузки (10 000 агентов)

| Метрика | Значение/сек |
|---------|-------------|
| **WebSocket соединений (steady)** | 9 800 (10K - 200 dead) |
| **Heartbeat ping/pong** | 327 msg/s |
| **Device status updates** | 980 msg/s |
| **Task commands (server→agent)** | 20-100 msg/s |
| **Task acks (agent→server)** | 20-100 msg/s |
| **Task progress** | 40-200 msg/s |
| **Task results** | 20-100 msg/s |
| **VPN status checks (REST)** | 163 req/s |
| **Video frames (binary WS)** | 7 500 frames/s (500×15fps) |
| **Random reconnects** | ~1.6/s (980 × 0.001/min ÷ 60) |
| --- | --- |
| **ИТОГО WS messages** | **~10 000 msg/s** |
| **ИТОГО REST requests** | **~300 req/s** |
| **ИТОГО WS binary** | **~7 500 frames/s** |
| **ИТОГО bandwidth (inbound)** | **~100 MB/s** |

---

## 8. СЦЕНАРИЙ RECONNECT STORM

### 8.1 Описание

Симуляция массового disconnect/reconnect — имитация сетевого сбоя или
рестарта сервера.

### 8.2 Фазы

```
t=0     : 10 000 агентов online
t=10s   : KILL 5 000 WebSocket (50% флота) одномоментно
t=10-40s: 5 000 агентов пытаются reconnect с expo backoff + jitter
t=40-90s: Reconnect storm — 5K агентов подключаются за ~80 секунд
t=90s+  : Стабилизация — все 10K online
```

### 8.3 Anti-Stampede Jitter

```python
async def reconnect_with_jitter(agent: VirtualAgent):
    """Reconnect с anti-stampede jitter."""
    attempt = 0
    while attempt < MAX_RETRIES:
        base_delay = min(BACKOFF_BASE * (2 ** attempt), BACKOFF_MAX)
        jitter = base_delay * random.uniform(-0.2, 0.2)  # ±20%
        delay = base_delay + jitter
        await asyncio.sleep(delay)
        try:
            await agent.connect()
            return
        except Exception:
            attempt += 1
    agent.state = AgentState.DEAD
```

### 8.4 Нагрузка при reconnect storm

| Метрика | Значение |
|---------|---------|
| Peak WS connects/sec | ~200 (5K / ~25s effective window) |
| Peak auth messages/sec | ~200 |
| Peak device_status/sec | ~500 (reconnected → first status) |
| Peak Redis writes/sec | ~400 (status cache + session) |
| Peak DB queries/sec | ~200 (device lookup + session create) |

---

## 9. ТЕСТОВЫЙ DAG ДЛЯ TASK EXECUTION

```json
{
  "version": 6,
  "name": "load_test_dag",
  "description": "Тестовый DAG для нагрузочного теста (5 нод)",
  "timeout_seconds": 300,
  "nodes": [
    {
      "id": "start",
      "type": "set_variable",
      "key": "iteration",
      "value": "0",
      "next": "check_iteration"
    },
    {
      "id": "check_iteration",
      "type": "condition",
      "code": "(tonumber(ctx.iteration) or 0) < 3",
      "on_true": "simulate_action",
      "on_false": "done"
    },
    {
      "id": "simulate_action",
      "type": "wait",
      "duration_ms": 2000,
      "next": "increment"
    },
    {
      "id": "increment",
      "type": "increment_variable",
      "key": "iteration",
      "next": "check_iteration"
    },
    {
      "id": "done",
      "type": "set_variable",
      "key": "status",
      "value": "completed",
      "next": null
    }
  ]
}
```

---

## 10. ДАННЫЕ ДЛЯ SEED (ПРЕДЗАПОЛНЕНИЕ)

### 10.1 API ключи

```python
# Генерация 10 000 API ключей перед тестом
for i in range(1, 10001):
    key_raw = f"sphr_load_{i:05d}"
    key_hash = hashlib.sha256(key_raw.encode()).hexdigest()
    # INSERT INTO api_keys (org_id, key_hash, type, name, ...)
    # VALUES (org_id, key_hash, 'agent', f'Load Test Key {i}', ...)
```

### 10.2 Тестовый скрипт

```python
# INSERT INTO scripts (org_id, name, dag, is_archived)
# VALUES (org_id, 'Load Test DAG', dag_json, false)
```

### 10.3 Очистка после теста

```sql
-- Удаление всех тестовых данных
DELETE FROM task_logs WHERE task_id IN (
  SELECT id FROM tasks WHERE device_id IN (
    SELECT id FROM devices WHERE serial LIKE 'LOAD-%'
  )
);
DELETE FROM tasks WHERE device_id IN (
  SELECT id FROM devices WHERE serial LIKE 'LOAD-%'
);
DELETE FROM vpn_peers WHERE name LIKE 'load-%';
DELETE FROM devices WHERE serial LIKE 'LOAD-%';
DELETE FROM api_keys WHERE name LIKE 'Load Test Key%';
DELETE FROM scripts WHERE name = 'Load Test DAG';
```

---

## ПРОДОЛЖЕНИЕ

- **[01-ARCHITECTURE.md](01-ARCHITECTURE.md)** — Архитектура теста, bottleneck, checklist
- **[03-METRICS-AND-CRITERIA.md](03-METRICS-AND-CRITERIA.md)** — Метрики, KPI, критерии pass/fail
