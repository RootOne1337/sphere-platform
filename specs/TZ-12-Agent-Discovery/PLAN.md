# TZ-12: Agent Discovery, AutoConnect & Device Management

> **Статус:** ПЛАН (без кода)  
> **Версия:** 1.0  
> **Автор:** Sphere Platform Team  
> **Дата:** 2025-07-18  

---

## Оглавление

1. [Аудит текущей архитектуры](#1-аудит-текущей-архитектуры)
2. [Discovery & Auto-Provisioning](#2-discovery--auto-provisioning)
3. [Dynamic Server URL & AutoReconnect](#3-dynamic-server-url--autoreconnect)
4. [AutoStart на загрузке эмулятора/устройства](#4-autostart-на-загрузке-эмулятораустройства)
5. [Уникальная идентификация клонов LDPlayer](#5-уникальная-идентификация-клонов-ldplayer)
6. [Device Management: группы, локации, игры](#6-device-management-группы-локации-игры)
7. [Масштабирование на 1000+ устройств](#7-масштабирование-на-1000-устройств)
8. [API-контракты (новые и изменённые эндпоинты)](#8-api-контракты)
9. [Миграции БД](#9-миграции-бд)
10. [Roadmap и приоритеты](#10-roadmap-и-приоритеты)

---

## 1. Аудит текущей архитектуры

### 1.1. Что уже работает

| Компонент | Файл | Статус |
|-----------|-------|--------|
| **ZeroTouchProvisioner** | `android/.../provisioning/ZeroTouchProvisioner.kt` | ✅ Цепочка: MDM → file → BuildConfig |
| **AuthTokenStore** | `android/.../store/AuthTokenStore.kt` | ✅ EncryptedSharedPreferences, server_url + JWT |
| **BootReceiver** | `android/.../BootReceiver.kt` | ✅ BOOT_COMPLETED + QUICKBOOT_POWERON |
| **SphereAgentService** | `android/.../service/SphereAgentService.kt` | ✅ Foreground START_STICKY |
| **SphereWebSocketClient** | `android/.../ws/SphereWebSocketClient.kt` | ✅ Exponential backoff 1→30s, circuit breaker (10 fails → 5min) |
| **NetworkChangeHandler** | `android/.../network/NetworkChangeHandler.kt` | ✅ forceReconnectNow() при смене сети |
| **DeviceInfoProvider** | `android/.../providers/DeviceInfoProvider.kt` | ⚠️ ANDROID_ID → проблема с клонами |
| **PC-Agent WS** | `pc-agent/agent/client.py` | ✅ Аналогичный backoff + circuit breaker |
| **TopologyReporter** | `pc-agent/agent/topology.py` | ✅ workstation_register с инстансами |
| **Device model** | `backend/models/device.py` | ✅ CRUD, tags[], groups M2M |
| **DeviceGroup model** | `backend/models/device_group.py` | ✅ Иерархия, цвет, filter_criteria |
| **LDPlayerInstance** | `backend/models/ldplayer_instance.py` | ✅ workstation_id + instance_index |
| **Workstation** | `backend/models/workstation.py` | ✅ hostname, os_version, agent_version |
| **ConnectionManager** | `backend/websocket/connection_manager.py` | ⚠️ In-process dict (не шардирован) |
| **HeartbeatManager** | `backend/websocket/heartbeat.py` | ✅ 30s ping, 15s timeout |
| **Device API** | `backend/api/v1/devices/router.py` | ✅ CRUD + fleet status + /me |

### 1.2. Выявленные проблемы

| # | Проблема | Влияние | Приоритет |
|---|----------|---------|-----------|
| P1 | **ANDROID_ID одинаковый у клонов LDPlayer** — значение `9774d56d682e549c` (дефолт эмулятора) или идентичное на всех клонах одного мастер-инстанса | Все клоны получают один device_id → конфликт подключений, eviction | 🔴 Critical |
| P2 | **Server URL зашит при enrollment навсегда** — `AuthTokenStore.saveServerUrl()` вызывается один раз, нет механизма обновления | При смене домена/IP сервера все агенты "потеряются" | 🔴 Critical |
| P3 | **Нет авторегистрации устройств** — при первом подключении агент должен быть заранее создан в БД | Ручное создание 1000 устройств невозможно | 🟡 High |
| P4 | **Нет location/region в модели** — `Device` не хранит геолокацию | Невозможно отличить устройства из разных офисов/дата-центров | 🟡 High |
| P5 | **DeviceGroup не привязана к играм** — нет `game_id` или task-профиля | Невозможно сказать "эта группа фармит Game X" | 🟡 High |
| P6 | **ConnectionManager — in-process dict** — при горизонтальном масштабировании бэкенда теряются подключения | Ограничение до ~500 WS на один процесс | 🟡 High |
| P7 | **Нет OTA-механизма обновления конфига** — агент не перечитывает config при reconnect | Любые изменения требуют ручного вмешательства (adb push) | 🟠 Medium |

### 1.3. Текущий enrollment flow (as-is)

```
┌─────────────┐          ┌──────────────────┐          ┌────────────┐
│  LDPlayer    │          │  Android Agent   │          │  Backend   │
│  (эмулятор)  │          │  (APK)           │          │  (FastAPI) │
└──────┬───────┘          └────────┬─────────┘          └─────┬──────┘
       │                          │                           │
       │  1. Boot → BootReceiver  │                           │
       │─────────────────────────>│                           │
       │                          │ 2. SetupActivity.onCreate │
       │                          │    authStore.getToken()?  │
       │                          │    └── null → show form   │
       │                          │                           │
       │                          │ 3. ZeroTouchProvisioner   │
       │                          │    .discoverConfig()      │
       │                          │    ├── MDM?  → null       │
       │                          │    ├── /sdcard/config? ──>│ 4. GET /api/v1/devices/me
       │                          │    │                      │    X-API-Key: sphr_...
       │                          │    │                      │    → 200 OK
       │                          │    └── saveServerUrl()    │
       │                          │        saveApiKey()       │
       │                          │        saveDeviceId()     │
       │                          │                           │
       │                          │ 5. SphereAgentService     │
       │                          │    .start() → WS connect  │
       │                          │─────── WS ───────────────>│ 6. authenticate_ws_token()
       │                          │    first-message: JWT     │
       │                          │<──── WS established ──────│
```

**Ключевой момент:** Device ID генерируется `DeviceInfoProvider.getDeviceId()` на стороне агента:
1. Сохранённый в EncryptedSharedPreferences → используем его
2. `ANDROID_ID` → `"android-{ANDROID_ID}"` (если не дефолтный `9774d56d682e549c`)
3. `UUID.randomUUID()` → `"android-{uuid}"` (fallback)

**Проблема клонов:** При клонировании LDPlayer-инстанса копируется весь `/data/data/` включая EncryptedSharedPreferences → клон получает **ТОЧНО ТОТ ЖЕ** device_id, server_url и API key что и мастер.

---

## 2. Discovery & Auto-Provisioning

### 2.1. Проблема

Сейчас `ZeroTouchProvisioner` ищет конфиг в 5 источниках, но:
- Файл `/sdcard/sphere-agent-config.json` надо пушить вручную через `adb push`
- BuildConfig baked-in → требует пересборки APK при смене сервера
- MDM — избыточен для эмулятора
- **Нет механизма централизованного обновления config** для 1000 агентов разом

### 2.2. Решение: Config Distribution Service

Добавляем **новый источник в цепочку ZeroTouchProvisioner** — HTTP endpoint для получения актуального конфига.

#### 2.2.1. Цепочка приоритетов (новая)

```
1. EncryptedSharedPreferences (уже enrolled → используем сохранённое)
2. Android Enterprise Managed Config (MDM/EMM)  ← оставляем
3. /sdcard/sphere-agent-config.json              ← оставляем
4. <appExternalFiles>/sphere-agent-config.json   ← оставляем
5. <appInternalFiles>/sphere-agent-config.json   ← оставляем
6. ★ НОВОЕ: HTTP Config Endpoint (GitHub Raw / собственный CDN)
7. BuildConfig baked-in defaults                 ← fallback
```

#### 2.2.2. Config Endpoint — два варианта

**Вариант A: GitHub Raw (простой, бесплатный)**

```
GET https://raw.githubusercontent.com/{org}/{repo}/main/agent-config.json
```

Конфиг хранится в отдельном приватном GitHub-репозитории (например `sphere-agent-config`):

```json
{
  "version": 3,
  "environments": {
    "production": {
      "server_url": "wss://api.sphere.example.com",
      "api_key_enrollment": "sphr_enroll_...",
      "config_poll_interval_hours": 24
    },
    "staging": {
      "server_url": "wss://staging-api.sphere.example.com",
      "api_key_enrollment": "sphr_stg_enroll_...",
      "config_poll_interval_hours": 1
    }
  },
  "default_environment": "production"
}
```

**Плюсы:** Бесплатно, версионируется Git, просто обновлять через push.  
**Минусы:** GitHub Rate Limit (60 req/hour без токена), приватный репо требует PAT в APK.

**Вариант B: Backend Config Endpoint (рекомендуемый)**

Добавляем эндпоинт прямо на бэкенде:

```
GET /api/v1/config/agent
Headers: X-Agent-Fingerprint: {fingerprint}
Response:
{
  "server_url": "wss://api.sphere.example.com",
  "ws_path": "/ws/android",
  "enrollment_key": "sphr_enroll_...",
  "config_version": 3,
  "poll_interval_seconds": 86400,
  "features": {
    "telemetry_enabled": true,
    "streaming_enabled": true,
    "ota_enabled": true
  }
}
```

**Плюсы:**  
- Полный контроль, нет rate limit  
- Можно отдавать разный конфиг разным агентам (по fingerprint/org)  
- HTTPS с certificate pinning  

**Минусы:**  
- Курица и яйцо: агент должен знать URL бэкенда, чтобы получить URL бэкенда  
- Решение: **bootstrap URL baked в BuildConfig**, а конфиг-эндпоинт может вернуть redirect на актуальный сервер  

#### 2.2.3. Рекомендуемый подход: Hybrid (B + файл)

```
1. Первый запуск:
   └── ZeroTouchProvisioner:
       ├── sphere-agent-config.json (adb push при массовом деплое)
       └── BuildConfig.DEFAULT_CONFIG_URL → GET /api/v1/config/agent
           └── Получаем актуальный server_url + enrollment key

2. Последующие запуски:
   └── AuthTokenStore уже содержит server_url и token
       └── Периодический poll конфига (1 раз/сутки):
           GET {server_url}/api/v1/config/agent
           └── Если server_url изменился → обновляем AuthTokenStore
               → forceReconnectNow() на новый адрес
```

#### 2.2.4. Config File для массового деплоя (LDPlayer)

PC-Agent при создании/клонировании эмулятора автоматически пушит конфиг:

```
pc-agent → ldconsole clone --name "Farm-042"
         → adb push sphere-agent-config.json /sdcard/sphere-agent-config.json
         → ldconsole launch --name "Farm-042"
         → APK (уже установлен в мастер-образе) → BootReceiver → ZeroTouchProvisioner
           → читает /sdcard/sphere-agent-config.json → enrollment
```

**sphere-agent-config.json** для PC-Agent генерирует автоматически:

```json
{
  "server_url": "http://10.0.2.2:8000",
  "api_key": "sphr_farm_api_key_from_backend",
  "device_id": null,
  "workstation_id": "ws-PC-FARM-01",
  "instance_index": 42,
  "location": "msk-office-1"
}
```

`device_id: null` — **критически важно!** Агент должен сгенерировать уникальный ID сам (см. секцию 5).

#### 2.2.5. Auto-enrollment flow (to-be)

```
┌──────────┐     ┌─────────────┐     ┌────────────┐     ┌──────────┐
│ PC-Agent │     │ LDPlayer    │     │ Android    │     │ Backend  │
│          │     │ (клон)      │     │ Agent APK  │     │          │
└────┬─────┘     └──────┬──────┘     └─────┬──────┘     └────┬─────┘
     │                  │                  │                  │
     │ 1. clone + push  │                  │                  │
     │  config.json     │                  │                  │
     │─────────────────>│                  │                  │
     │                  │ 2. boot          │                  │
     │                  │─────────────────>│                  │
     │                  │                  │ 3. detect clone  │
     │                  │                  │    (см. сек.5)   │
     │                  │                  │ 4. wipe old      │
     │                  │                  │    device_id     │
     │                  │                  │ 5. generate new  │
     │                  │                  │    unique ID     │
     │                  │                  │                  │
     │                  │                  │ 6. POST /api/v1/ │
     │                  │                  │    devices/      │
     │                  │                  │    register      │
     │                  │                  │──────────────────>│
     │                  │                  │                  │ 7. Create Device
     │                  │                  │                  │    in DB + assign
     │                  │                  │                  │    to workstation
     │                  │                  │<─────── 201 ─────│
     │                  │                  │ {device_id, jwt} │
     │                  │                  │                  │
     │                  │                  │ 8. WS connect    │
     │                  │                  │──── WS ─────────>│
```

#### 2.2.6. Новый endpoint: POST /api/v1/devices/register

```
POST /api/v1/devices/register
Headers:
  X-API-Key: sphr_enroll_...          (enrollment API key с правом device:register)
  X-Fingerprint: sha256:abc123...     (уникальный отпечаток устройства)

Body:
{
  "name": "auto",                    // или null → бэкенд назначит "Device-{index}"
  "fingerprint": "sha256:abc123...", // отпечаток (подробности в секции 5)
  "workstation_id": "ws-PC-FARM-01", // опционально — привязка к воркстанции
  "instance_index": 42,              // опционально — LDPlayer index
  "android_version": "9",
  "model": "LDPlayer samsung SM-G988N",
  "location": "msk-office-1",        // опционально — локация
  "meta": {
    "ldplayer_name": "Farm-042",
    "clone_source": "master-image-v3"
  }
}

Response 201:
{
  "device_id": "550e8400-e29b-41d4-a716-446655440000",
  "name": "Farm-042",
  "access_token": "eyJhbG...",
  "refresh_token": "...",
  "expires_in": 900,
  "server_url": "wss://api.sphere.example.com"
}

Response 409 (fingerprint уже зарегистрирован):
{
  "device_id": "550e8400-...",  ← возвращаем существующий
  "access_token": "eyJhbG...", ← новый токен
  ...
}
```

**Идемпотентность:** Если агент с таким `fingerprint` уже зарегистрирован — возвращаем его `device_id` + новые токены (409 → по сути re-enroll). Это покрывает сценарий factory reset / переустановки APK.

---

## 3. Dynamic Server URL & AutoReconnect

### 3.1. Проблема

Текущий `SphereWebSocketClient.connectOnce()`:
```kotlin
val serverUrl = authStore.getServerUrl()  // один раз сохранён при enrollment
val wsUrl = "${serverUrl.trimEnd('/')}/ws/android/$deviceId"
```

Если сервер переехал на новый домен — все агенты теряются навсегда.

### 3.2. Решение: Config Refresh перед каждым reconnect cycle

#### 3.2.1. Логика в SphereWebSocketClient

```
reconnectLoop():
  while (not stopped):
    1. ★ refreshServerUrlIfNeeded()
       ├── if (lastConfigCheck + pollInterval < now):
       │     GET {configUrl}/api/v1/config/agent
       │     if (response.server_url != authStore.getServerUrl()):
       │       authStore.saveServerUrl(response.server_url)
       │       log("Server URL updated: old → new")
       │   lastConfigCheck = now
       └── else: skip (не чаще раза в N часов)
    
    2. connectOnce() ← использует обновлённый server_url
    3. если разорвано → backoff → goto 1
```

#### 3.2.2. Config URL — откуда брать?

**Bootstrap chain:**
1. `BuildConfig.CONFIG_URL` — baked при сборке APK (например `https://config.sphere.example.com`)
2. `sphere-agent-config.json` → поле `config_url`
3. Текущий `authStore.getServerUrl()` + `/api/v1/config/agent` (самый актуальный)

**Важно:** `CONFIG_URL` — это **стабильный, редко меняющийся URL** (отдельный от основного API). Можно использовать:
- DNS CNAME на CDN (CloudFlare/AWS)
- Отдельный lightweight сервис за load balancer
- Даже GitHub Pages с static JSON

#### 3.2.3. Server-side push обновления URL (опционально)

Когда агент **уже подключён** по WS, сервер может отправить команду смены URL:

```json
{
  "type": "config_update",
  "payload": {
    "server_url": "wss://new-api.sphere.example.com",
    "effective_at": "2025-01-15T00:00:00Z",
    "reason": "Migration to new datacenter"
  }
}
```

Агент сохраняет новый URL и при следующем reconnect подключается к нему.

### 3.3. Reconnect flow (to-be)

```
┌────────────────────────────────────────────────────────────────┐
│               SphereWebSocketClient.reconnectLoop()             │
├────────────────────────────────────────────────────────────────┤
│                                                                │
│  ┌──────────────────┐                                         │
│  │ refreshConfig()  │ ← 1 раз/сутки или при каждом reconnect  │
│  │ GET config/agent │    после 3+ неудачных попыток            │
│  └────────┬─────────┘                                         │
│           │ server_url changed?                                │
│           ├── yes → authStore.saveServerUrl(new)               │
│           │         consecutiveFailures = 0                    │
│           └── no  → continue                                  │
│                                                                │
│  ┌──────────────────┐                                         │
│  │ getFreshToken()  │ ← proactive refresh если <5 мин до exp  │
│  └────────┬─────────┘                                         │
│           │                                                    │
│  ┌──────────────────┐                                         │
│  │ connectOnce()    │ ← WS к текущему server_url              │
│  └────────┬─────────┘                                         │
│           │ success?                                           │
│           ├── yes → ∞ message loop (ping/pong, commands)      │
│           │         consecutiveFailures = 0                    │
│           └── no  → backoff 1s→2s→4s→...→30s                 │
│                     consecutiveFailures++                      │
│                     if ≥ 3 → force refreshConfig() next iter  │
│                     if ≥ 10 → circuit breaker 5 мин           │
│                                                                │
└────────────────────────────────────────────────────────────────┘
```

### 3.4. Триггеры для refresh config

| Триггер | Когда |
|---------|-------|
| **Периодический** | Раз в 24 часа (настраивается сервером через `poll_interval_seconds`) |
| **После 3+ неудачных reconnect** | Возможно сервер переехал |
| **NetworkChangeHandler** | Сеть восстановилась → refresh + reconnect |
| **Server-side push** | Получена команда `config_update` по WS |
| **Ручной** | Через UI SetupActivity или adb shell am broadcast |

---

## 4. AutoStart на загрузке эмулятора/устройства

### 4.1. Текущее состояние (уже работает)

```kotlin
// BootReceiver.kt
override fun onReceive(context: Context, intent: Intent) {
    if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
        intent.action == "android.intent.action.QUICKBOOT_POWERON"
    ) {
        SphereAgentService.start(context)  // ← foreground service
    }
}
```

```kotlin
// SphereAgentService.kt
override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
    return START_STICKY  // ← перезапуск после kill
}
```

✅ `BOOT_COMPLETED` + `QUICKBOOT_POWERON` — работает.  
✅ `START_STICKY` — Android перезапустит сервис.  
✅ Foreground service с notification — выше приоритет, меньше шансов на kill.

### 4.2. Проблемы и улучшения

#### P4.1: LDPlayer QUICKBOOT vs Cold Boot

LDPlayer поддерживает два режима загрузки:
- **Cold boot** → `BOOT_COMPLETED` срабатывает ✅
- **Quick boot (snapshot)** → `QUICKBOOT_POWERON` срабатывает ✅
- **Resume from save state** → **НИ ОДИН intent НЕ срабатывает** ⚠️

**Решение:** Добавить `AlarmManager` + `JobScheduler` как safety net:

```
onCreate(SetupActivity / SphereAgentService):
  1. schedulePeriodicHealthCheck()
     ├── WorkManager.enqueueUniquePeriodicWork(
     │     "sphere-health", 15 мин, ExistingPeriodicWorkPolicy.KEEP)
     └── HealthCheckWorker:
           if (!SphereAgentService.isRunning):
             SphereAgentService.start(context)
```

#### P4.2: Doze Mode / App Standby

На Android 6+ (и LDPlayer с Android 9/12):
- **Doze mode** отключает network → WS разрывается
- Battery optimization может убить service

**Текущая защита:**
- `requestIgnoreBatteryOptimization()` в SetupActivity ✅
- Foreground service notification ✅

**Дополнительно:**
- Добавить `FOREGROUND_SERVICE_DATA_SYNC` permission ← уже есть в Manifest ✅
- WakeLock для критических операций (DAG execution) — **НЕ рекомендуется** для простого подключения, расходует батарею

#### P4.3: Автозапуск после OTA / обновления APK

При обновлении APK через OTA (уже есть `OtaUpdateService`):
- `ACTION_MY_PACKAGE_REPLACED` → нужен ещё один BroadcastReceiver
- Гарантирует что после обновления агент запустится без ребута

```
Новый receiver: PackageUpdateReceiver
  action: android.intent.action.MY_PACKAGE_REPLACED
  → SphereAgentService.start(context)
```

#### P4.4: PC-Agent: автостарт клона

PC-Agent должен гарантировать что агент внутри эмулятора запускается:

```
PC-Agent → ldconsole launch --name "Farm-042"
         → wait for boot (poll "adb shell getprop sys.boot_completed")
         → adb shell am start -n com.sphereplatform.agent/.ui.SetupActivity
            (на случай если BootReceiver не сработал)
```

Это **страховочный механизм** — в 99% случаев BootReceiver сработает сам.

### 4.3. Полная цепочка автозапуска (to-be)

```
LDPlayer Boot
  │
  ├── BOOT_COMPLETED → BootReceiver → SphereAgentService.start()
  │                                    └── WS connect loop
  │
  ├── QUICKBOOT_POWERON → BootReceiver → (то же самое)
  │
  ├── Resume from snapshot → ❌ No intent
  │   └── WorkManager HealthCheckWorker (каждые 15 мин)
  │       └── if service not running → start()
  │
  ├── APK Update → PackageUpdateReceiver → start()
  │
  └── PC-Agent safety net:
      └── adb shell "am startservice com.sphereplatform.agent/.service.SphereAgentService"
```

---

## 5. Уникальная идентификация клонов LDPlayer

### 5.1. Проблема (детально)

При клонировании LDPlayer (`ldconsole copy --name "Clone" --from 0`):

1. **Копируется весь /data/** → `EncryptedSharedPreferences` с device_id, server_url, tokens
2. **ANDROID_ID** (`Settings.Secure`) = `9774d56d682e549c` (дефолт) или клонированный вместе с /data/
3. **Build.SERIAL** = `unknown` на всех эмуляторах
4. **Build.FINGERPRINT** = одинаковый (один и тот же образ Android)
5. **MAC-адрес** = виртуальный, может быть одинаковым
6. **IMEI** = недоступен (эмулятор без SIM)

**Итог:** Текущий `DeviceInfoProvider` не может отличить клон от оригинала. Все клоны подключаются с одним device_id → сервер evict-ит предыдущее подключение (код 4001) → агенты бесконечно выбивают друг друга.

### 5.2. Решение: Composite Fingerprint + Clone Detection

#### 5.2.1. Генерация уникального Sphere Device ID

**Принцип:** Ни один аппаратный идентификатор не уникален у клонов. Поэтому используем **комбинацию доступных сигналов + гарантированно уникальный компонент**.

```
Sphere Fingerprint = SHA-256(
  ANDROID_ID                    // может совпадать у клонов
  + "|" + instance_index        // из config.json, уникален в пределах workstation
  + "|" + workstation_id        // из config.json, уникален глобально
  + "|" + installation_uuid     // генерируется при ПЕРВОМ запуске APK, NEVER cloned
  + "|" + boot_id               // /proc/sys/kernel/random/boot_id — уникален после каждого boot
)
```

**installation_uuid** — ключевой элемент:
- Генерируется `UUID.randomUUID()` при первом запуске
- Сохраняется в **Internal Storage** (НЕ SharedPreferences) файл `/data/data/{pkg}/files/.sphere_installation_id`
- При клонировании LDPlayer копируется → **НО мы его детектим и пересоздаём** (см. 5.2.2)

#### 5.2.2. Clone Detection Algorithm

При каждом запуске агент проверяет, не является ли он клоном:

```
fun detectAndHandleClone():
  1. savedFingerprint = readFile(".sphere_fingerprint")
  2. currentBootId = readFile("/proc/sys/kernel/random/boot_id")
  3. savedBootId = prefs.getString("last_boot_id")
  4. savedInstanceIndex = prefs.getInt("instance_index")
  5. currentInstanceIndex = readFromConfigJson("instance_index")
                            OR readSystemProp("sphere.instance.index")
  
  // Сигнал клона #1: instance_index изменился
  if (savedInstanceIndex != -1 && currentInstanceIndex != savedInstanceIndex):
    log("🔄 Clone detected: instance_index changed $saved → $current")
    return CLONE_DETECTED
  
  // Сигнал клона #2: наличие маркер-файла от PC-Agent
  if (fileExists("/sdcard/.sphere_clone_marker")):
    log("🔄 Clone detected: marker file present")
    deleteFile("/sdcard/.sphere_clone_marker")
    return CLONE_DETECTED
  
  // Сигнал клона #3: boot_id совпадает с мастером (snapshot clone)
  // (невозможен после реального reboot, но возможен при clone + immediate start)
  // Это edge case — покрывается маркер-файлом от PC-Agent
  
  return NOT_CLONE

fun onCloneDetected():
  1. Удаляем старый device_id, tokens, fingerprint
     authStore.clearTokens()
     authStore.clearDeviceId()
     deleteFile(".sphere_installation_id")
     deleteFile(".sphere_fingerprint")
  
  2. Генерируем новый installation_uuid
     newUUID = UUID.randomUUID()
     writeFile(".sphere_installation_id", newUUID)
  
  3. Сохраняем текущий instance_index
     prefs.putInt("instance_index", currentInstanceIndex)
  
  4. Перезапускаем enrollment:
     → ZeroTouchProvisioner.discoverConfig()
     → POST /api/v1/devices/register (новый fingerprint)
     → Получаем новый device_id + tokens
```

#### 5.2.3. PC-Agent: подготовка клона

При клонировании PC-Agent обязан:

```python
async def prepare_clone(self, source_index: int, target_index: int, target_name: str):
    # 1. Клонируем эмулятор
    await self._run_ldconsole("copy", "--name", target_name, "--from", str(source_index))
    
    # 2. Генерируем конфиг с уникальным instance_index
    config = {
        "server_url": self.config.server_url,
        "api_key": self.config.enrollment_api_key,
        "device_id": None,  # агент сгенерирует сам
        "workstation_id": self.config.workstation_id,
        "instance_index": target_index,
        "location": self.config.location
    }
    
    # 3. Пушим конфиг + clone marker
    write_json("/tmp/sphere-agent-config.json", config)
    await self._adb_push(target_index, "/tmp/sphere-agent-config.json", "/sdcard/sphere-agent-config.json")
    await self._adb_push(target_index, "/dev/null", "/sdcard/.sphere_clone_marker")
    
    # 4. Запускаем клон
    await self._run_ldconsole("launch", "--name", target_name)
```

#### 5.2.4. Instance Index: откуда берётся надёжно

| Источник | Надёжность | Описание |
|----------|-----------|----------|
| `sphere-agent-config.json` → `instance_index` | ★★★ | PC-Agent генерирует при клонировании |
| `adb shell getprop sphere.instance.index` | ★★ | PC-Agent устанавливает через `adb shell setprop` |
| ADB serial port mapping | ★★ | `emulator-5554` → index 0, `-5556` → 1 и т.д. |
| LDPlayer shared folder | ★ | Можно записать index в shared folder |

**Рекомендация:** `sphere-agent-config.json` как primary + `setprop` как backup.

#### 5.2.5. Финальная формула Device ID

```
Sphere Device ID = "sphere-{workstation_id}-{instance_index}-{short_uuid}"
                 = "sphere-ws-PC-FARM-01-042-a1b2c3d4"
```

**Свойства:**
- Человекочитаемый (видно workstation + index в имени)
- Глобально уникальный (UUID суффикс)
- Стабильный после enrollment (сохранён в AuthTokenStore)
- При clone detection — генерируется новый

---

## 6. Device Management: группы, локации, игры

### 6.1. Текущая модель (as-is)

```sql
-- devices
id, org_id, name, serial, android_version, model, tags[], is_active,
last_status, meta{}, notes

-- device_groups
id, org_id, name, description, color, parent_group_id, filter_criteria{}

-- device_group_members (M2M)
device_id, group_id

-- ldplayer_instances
id, org_id, workstation_id, device_id, instance_index, android_serial, status, meta{}

-- workstations
id, org_id, name, hostname, os_version, agent_version, is_online, last_heartbeat_at, meta{}
```

### 6.2. Новые поля и таблицы

#### 6.2.1. Расширение Device

```sql
ALTER TABLE devices ADD COLUMN location_id UUID REFERENCES locations(id);
ALTER TABLE devices ADD COLUMN device_type VARCHAR(50) DEFAULT 'ldplayer';
-- device_type: 'ldplayer' | 'physical' | 'remote' | 'genymotion' | 'nox'
ALTER TABLE devices ADD COLUMN fingerprint VARCHAR(128) UNIQUE;
ALTER TABLE devices ADD COLUMN last_seen_at TIMESTAMPTZ;
ALTER TABLE devices ADD COLUMN assigned_game_id UUID REFERENCES games(id);
ALTER TABLE devices ADD COLUMN sort_order INTEGER DEFAULT 0;
```

#### 6.2.2. Новая таблица: locations

```sql
CREATE TABLE locations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      UUID NOT NULL REFERENCES organizations(id),
    name        VARCHAR(255) NOT NULL,         -- "Офис Москва", "DC Frankfurt"
    code        VARCHAR(50) NOT NULL,          -- "msk-office-1", "fra-dc-2"
    timezone    VARCHAR(50) DEFAULT 'UTC',     -- "Europe/Moscow"
    country     VARCHAR(2),                    -- ISO 3166-1 alpha-2: "RU", "DE"
    city        VARCHAR(100),
    description TEXT,
    meta        JSONB DEFAULT '{}',
    is_active   BOOLEAN DEFAULT true,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now(),
    UNIQUE(org_id, code)
);
```

**Примеры:**
| name | code | timezone | country |
|------|------|----------|---------|
| Офис Москва | msk-office-1 | Europe/Moscow | RU |
| DC Frankfurt | fra-dc-2 | Europe/Berlin | DE |
| Home Lab | home-lab | Europe/Moscow | RU |

#### 6.2.3. Новая таблица: games

```sql
CREATE TABLE games (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id       UUID NOT NULL REFERENCES organizations(id),
    name         VARCHAR(255) NOT NULL,         -- "Clash of Clans"
    package_name VARCHAR(255),                  -- "com.supercell.clashofclans"
    icon_url     VARCHAR(500),
    description  TEXT,
    meta         JSONB DEFAULT '{}',            -- версия, настройки фарма
    is_active    BOOLEAN DEFAULT true,
    created_at   TIMESTAMPTZ DEFAULT now(),
    updated_at   TIMESTAMPTZ DEFAULT now(),
    UNIQUE(org_id, package_name)
);
```

#### 6.2.4. Расширение DeviceGroup

```sql
ALTER TABLE device_groups ADD COLUMN location_id UUID REFERENCES locations(id);
ALTER TABLE device_groups ADD COLUMN game_id UUID REFERENCES games(id);
ALTER TABLE device_groups ADD COLUMN auto_assign_rule JSONB DEFAULT '{}';
-- auto_assign_rule: {"location": "msk-office-1", "device_type": "ldplayer"}
-- устройства, подходящие под правило, автоматически добавляются в группу
ALTER TABLE device_groups ADD COLUMN max_devices INTEGER;
-- лимит устройств в группе (для балансировки нагрузки)
ALTER TABLE device_groups ADD COLUMN sort_order INTEGER DEFAULT 0;
```

### 6.3. Операции Device Management

#### 6.3.1. Переименование

```
PUT /api/v1/devices/{device_id}
Body: { "name": "Farm-Moscow-042" }
```

**Правила именования (автоматическое при регистрации):**
```
{location_code}-{device_type_short}-{index:03d}
Примеры:
  msk-ld-001   (LDPlayer #1 в Москве)
  fra-ph-005   (Physical phone #5 в Франкфурте)
  home-ld-042  (LDPlayer #42 дома)
```

Пользователь может переименовать в любое имя через frontend.

#### 6.3.2. Назначение в группу

```
POST /api/v1/groups/{group_id}/devices
Body: { "device_ids": ["uuid1", "uuid2", ...] }
```

```
DELETE /api/v1/groups/{group_id}/devices
Body: { "device_ids": ["uuid1"] }
```

Устройство может быть в нескольких группах (M2M). Примеры:
- "Moscow Farm" (по локации)
- "Clash of Clans Farm" (по игре)
- "VIP Accounts" (по важности)

#### 6.3.3. Назначение локации

```
PUT /api/v1/devices/{device_id}
Body: { "location_id": "uuid-of-msk-office-1" }
```

Или bulk:
```
POST /api/v1/devices/bulk/update
Body: {
  "device_ids": ["uuid1", "uuid2", ...],
  "update": { "location_id": "uuid-of-msk-office-1" }
}
```

#### 6.3.4. Назначение игры

```
PUT /api/v1/devices/{device_id}
Body: { "assigned_game_id": "uuid-of-clash" }
```

Или через группу (группа = "фармит определённую игру"):
```
PUT /api/v1/groups/{group_id}
Body: { "game_id": "uuid-of-clash" }
```

Все устройства в группе наследуют игру группы.

#### 6.3.5. Удаление устройства

```
DELETE /api/v1/devices/{device_id}
```

**Каскад:**
1. Разрываем WS-подключение (если онлайн) → send close(4010, "device_deleted")
2. Удаляем из всех групп (CASCADE в device_group_members)
3. Удаляем статус из Redis
4. Удаляем LDPlayerInstance привязку
5. Soft-delete: `is_active = false` (для audit trail) или hard-delete (по настройке)

#### 6.3.6. Сортировка

Фронтенд поддерживает сортировку по:
- `name` (A-Z, Z-A)
- `status` (online first, offline first)
- `location` (группировка по локациям)
- `last_seen_at` (самые активные / самые неактивные)
- `sort_order` (ручной drag-n-drop порядок)
- `created_at` (новые / старые)
- `assigned_game` (группировка по играм)

```
GET /api/v1/devices?sort=location,name&order=asc
GET /api/v1/devices?sort=last_seen_at&order=desc
GET /api/v1/devices?sort=sort_order&order=asc
```

#### 6.3.7. Фильтрация

```
GET /api/v1/devices?status=online&location=msk-office-1&game=clash-of-clans&group=uuid
GET /api/v1/devices?tags=vip,premium&type=ldplayer
GET /api/v1/devices?search=Farm-042
```

### 6.4. Auto-assign правила для групп

DeviceGroup может иметь `auto_assign_rule`:

```json
{
  "location_code": "msk-office-1",
  "device_type": "ldplayer",
  "tags_any": ["farm", "production"],
  "workstation_id": "ws-PC-FARM-01"
}
```

При регистрации нового устройства бэкенд проверяет все группы с `auto_assign_rule` и автоматически добавляет устройство в подходящие. Это решает проблему ручного назначения 1000 устройств.

### 6.5. Иерархия: Location → Workstation → Device

```
Location: "Офис Москва" (msk-office-1)
├── Workstation: "PC-FARM-01" (hostname: DESKTOP-ABC123)
│   ├── LDPlayer Instance 0 → Device: msk-ld-001 (online, Clash of Clans)
│   ├── LDPlayer Instance 1 → Device: msk-ld-002 (busy, executing DAG)
│   ├── LDPlayer Instance 2 → Device: msk-ld-003 (offline)
│   └── ...30 instances
├── Workstation: "PC-FARM-02"
│   ├── LDPlayer Instance 0 → Device: msk-ld-031
│   └── ...
└── Physical Phone: msk-ph-001 (Samsung Galaxy S21, online)

Location: "DC Frankfurt" (fra-dc-2)
├── Workstation: "SERVER-FRA-01"
│   └── ...50 LDPlayer instances
└── ...
```

---

## 7. Масштабирование на 1000+ устройств

### 7.1. Текущие ограничения

| Компонент | Ограничение | Ожидаемое на 1000 устройств |
|-----------|-------------|----------------------------|
| **ConnectionManager** | In-process dict | 1 процесс = все подключения = OOM / CPU bottleneck |
| **HeartbeatManager** | asyncio.Task per device | 1000 тасков → OK если нет утечек |
| **Redis Pub/Sub** | Один subscriber | OK, Redis держит 100k+ msg/s |
| **PostgreSQL** | Синхронные запросы при подключении | N+1 при проверке org_id |
| **WS message throughput** | json.dumps per message | OK до ~5000 msg/s на Python |
| **Frontend** | Рендеринг списка 1000 устройств | Нужна виртуализация |

### 7.2. Горизонтальное масштабирование бэкенда

#### 7.2.1. Архитектура: Multiple WS Workers

```
                    ┌──────────────┐
                    │   Traefik    │  sticky session по device_id cookie
                    │   (LB)      │
                    └──────┬───────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
        ┌─────┴─────┐ ┌───┴──────┐ ┌───┴──────┐
        │ WS Worker │ │ WS Worker│ │ WS Worker│
        │    #1     │ │    #2    │ │    #3    │
        │ 350 conn  │ │ 350 conn │ │ 300 conn │
        └─────┬─────┘ └────┬─────┘ └────┬─────┘
              │             │            │
              └─────────────┼────────────┘
                            │
                    ┌───────┴────────┐
                    │  Redis Pub/Sub │  межпроцессная маршрутизация
                    │  + Stream      │
                    └───────┬────────┘
                            │
                    ┌───────┴────────┐
                    │  PostgreSQL    │
                    └────────────────┘
```

#### 7.2.2. PubSubRouter как межпроцессный мост

Текущий `PubSubRouter` уже подписывается на Redis каналы. Расширяем:

```
Отправка команды устройству (device_id = "abc-123"):
  1. API получает команду
  2. Публикует в Redis: PUBLISH cmd:abc-123 {command_json}
  3. Все WS Workers подписаны на cmd:*
  4. Worker, у которого есть connection "abc-123", доставляет по WS
  5. Остальные workers игнорируют (нет в _connections)
```

Это **уже реализовано** в `PubSubRouter`. Горизонтальное масштабирование = запуск N процессов.

#### 7.2.3. Device Registry: Redis Set вместо in-process dict

Для fast lookup "на каком worker-е устройство?":

```redis
# При подключении устройства:
HSET device_registry:{device_id} worker_id "worker-1" connected_at "2025-01-15T..."
EXPIRE device_registry:{device_id} 120  # TTL = 2 × heartbeat interval

# При отключении:
DEL device_registry:{device_id}

# Lookup:
HGET device_registry:{device_id} worker_id → "worker-1"
```

#### 7.2.4. Connection Limits per Worker

| Метрика | Рекомендация |
|---------|-------------|
| WS connections per process | 500-1000 (зависит от RAM, ~1MB per connection) |
| Heartbeat tasks | = connections (30s interval, минимальная нагрузка) |
| Redis subscribers per worker | 1 (multiplexed) |
| DB connection pool per worker | 10-20 (asyncpg) |

Для 1000 устройств: **2-3 WS worker процесса** через Gunicorn/Uvicorn.

### 7.3. PC-Agent масштабирование

Один PC (32GB RAM) → ~30 LDPlayer инстансов.  
1000 устройств = **~34 PC** (с запасом 30 на каждый).

```
34 PC × 30 LDPlayer = 1020 Android-агентов
34 PC × 1 PC-Agent  = 34 PC-Agent WS connections
                       ──────────
                       1054 WS total
```

PC-Agent → backend по WS:
- Topology: `workstation_register` (1 раз при подключении + при изменениях)
- Telemetry: каждые 30с (CPU, RAM, disk, running instances)
- Commands: launch/stop/clone instances, forward ADB commands

### 7.4. Frontend: виртуализация и пагинация

- **Виртуальный список** (react-window / @tanstack/virtual) для 1000+ строк
- **Server-side пагинация** — уже реализована (`page`, `per_page`)
- **Группировка** в UI по location/group/game — expandable tree view
- **Real-time статус** через WS events от бэка (device_online, device_offline)

### 7.5. Мониторинг масштабирования

Новые метрики (Prometheus):

```
# Количество WS подключений по типу
sphere_ws_connections_total{agent_type="android|pc", worker_id="..."}

# Heartbeat latency
sphere_heartbeat_latency_seconds{device_id="..."}

# Очередь команд
sphere_command_queue_size{device_id="..."}

# Device registration rate
sphere_device_registrations_total{location="...", device_type="..."}

# Fleet health
sphere_fleet_online_ratio{org_id="...", location="..."}
```

---

## 8. API-контракты

### 8.1. Новые эндпоинты

| Метод | Path | Описание |
|-------|------|----------|
| `POST` | `/api/v1/devices/register` | Авторегистрация устройства (enrollment) |
| `GET` | `/api/v1/config/agent` | Получение актуального конфига (server_url, features) |
| `GET` | `/api/v1/locations` | Список локаций |
| `POST` | `/api/v1/locations` | Создать локацию |
| `PUT` | `/api/v1/locations/{id}` | Обновить локацию |
| `DELETE` | `/api/v1/locations/{id}` | Удалить локацию |
| `GET` | `/api/v1/games` | Список игр |
| `POST` | `/api/v1/games` | Создать игру |
| `PUT` | `/api/v1/games/{id}` | Обновить игру |
| `DELETE` | `/api/v1/games/{id}` | Удалить игру |
| `POST` | `/api/v1/devices/bulk/update` | Bulk обновление устройств |
| `POST` | `/api/v1/devices/bulk/delete` | Bulk удаление устройств |
| `POST` | `/api/v1/devices/bulk/assign-group` | Bulk назначение в группу |
| `POST` | `/api/v1/devices/bulk/assign-location` | Bulk назначение локации |

### 8.2. Изменённые эндпоинты

| Метод | Path | Изменения |
|-------|------|-----------|
| `GET` | `/api/v1/devices` | + query params: `location`, `game`, `sort`, `order` |
| `PUT` | `/api/v1/devices/{id}` | + поля: `location_id`, `assigned_game_id`, `sort_order` |
| `POST` | `/api/v1/devices` | + поля: `fingerprint`, `location_id`, `assigned_game_id` |
| `PUT` | `/api/v1/groups/{id}` | + поля: `location_id`, `game_id`, `auto_assign_rule`, `max_devices`, `sort_order` |

### 8.3. WS-сообщения (новые)

| Type | Direction | Описание |
|------|-----------|----------|
| `config_update` | server → agent | Обновление server_url и/или features |
| `device_registered` | server → frontend WS | Новое устройство зарегистрировалось |
| `device_relocated` | server → frontend WS | Устройство сменило локацию |
| `fleet_topology` | server → frontend WS | Полная топология (locations → workstations → devices) |

---

## 9. Миграции БД

### 9.1. Порядок миграций

```
001_create_locations.py
  - CREATE TABLE locations(...)
  - INSERT default location "Default" для каждой org

002_create_games.py
  - CREATE TABLE games(...)

003_alter_devices_add_location_game.py
  - ALTER TABLE devices ADD location_id, device_type, fingerprint, last_seen_at,
    assigned_game_id, sort_order
  - CREATE UNIQUE INDEX idx_devices_fingerprint ON devices(fingerprint) WHERE fingerprint IS NOT NULL
  - UPDATE devices SET location_id = (SELECT id FROM locations WHERE code = 'default' AND org_id = devices.org_id)

004_alter_device_groups_add_location_game.py
  - ALTER TABLE device_groups ADD location_id, game_id, auto_assign_rule, max_devices, sort_order

005_add_rls_locations_games.py
  - RLS policies для locations и games (по org_id)
```

### 9.2. Обратная совместимость

- Все новые поля `NULLABLE` с defaults → старый код продолжит работать
- `location_id` = NULL означает "не назначена" → фронт показывает "Unknown Location"
- `assigned_game_id` = NULL → "No game assigned"
- Миграция `003` назначает `device_type = 'ldplayer'` для существующих устройств

---

## 10. Roadmap и приоритеты

### Фаза 1: Clone Identification + Auto-Registration (🔴 Critical)

**Цель:** Агенты-клоны получают уникальные ID, регистрируются автоматически.

| Задача | Компонент | Оценка сложности |
|--------|-----------|-----------------|
| Clone detection algorithm | Android Agent | Medium |
| Composite fingerprint generation | Android Agent | Medium |
| `POST /api/v1/devices/register` endpoint | Backend | Medium |
| PC-Agent: push config + clone marker | PC-Agent | Low |
| Тесты: clone detection, registration | Tests | Medium |

### Фаза 2: Dynamic Server URL (🔴 Critical)

**Цель:** Агент всегда знает актуальный адрес сервера.

| Задача | Компонент | Оценка сложности |
|--------|-----------|-----------------|
| `GET /api/v1/config/agent` endpoint | Backend | Low |
| Config refresh в reconnect loop | Android Agent | Medium |
| Config refresh в PC-Agent | PC-Agent | Low |
| `config_update` WS command handler | Android Agent | Low |
| Тесты: config refresh, server migration | Tests | Medium |

### Фаза 3: Locations & Games (🟡 High)

**Цель:** Устройства организованы по локациям и играм.

| Задача | Компонент | Оценка сложности |
|--------|-----------|-----------------|
| Миграции: locations, games, alter devices | Backend DB | Medium |
| CRUD endpoints: locations, games | Backend API | Medium |
| Расширение device CRUD (новые поля) | Backend API | Low |
| Auto-assign rules для групп | Backend Service | Medium |
| Frontend: location tree, game badges | Frontend | High |
| Тесты: CRUD, auto-assign | Tests | Medium |

### Фаза 4: AutoStart Hardening (🟠 Medium)

**Цель:** 100% гарантия автозапуска при любом сценарии.

| Задача | Компонент | Оценка сложности |
|--------|-----------|-----------------|
| WorkManager HealthCheckWorker | Android Agent | Low |
| PackageUpdateReceiver | Android Agent | Low |
| PC-Agent safety net (adb start) | PC-Agent | Low |
| Тесты: autostart scenarios | Tests | Low |

### Фаза 5: Scaling to 1000+ (🟡 High)

**Цель:** Горизонтальное масштабирование на 1000+ WS.

| Задача | Компонент | Оценка сложности |
|--------|-----------|-----------------|
| Redis Device Registry (HSET/EXPIRE) | Backend | Medium |
| Multi-worker config (Gunicorn) | Infrastructure | Low |
| Frontend virtual list | Frontend | Medium |
| Fleet topology WS events | Backend + Frontend | Medium |
| Prometheus metrics | Monitoring | Low |
| Нагрузочные тесты (1000 fake agents) | Tests | High |

---

## Приложение A: Глоссарий

| Термин | Описание |
|--------|----------|
| **Enrollment** | Первичная регистрация агента на сервере (получение device_id + tokens) |
| **ZeroTouch** | Автоматический enrollment без ручного ввода данных |
| **Clone Detection** | Алгоритм определения что APK запущен в клонированном эмуляторе |
| **Fingerprint** | Уникальный хэш устройства (SHA-256 от набора параметров) |
| **Circuit Breaker** | Паттерн прерывания повторных попыток при каскадных ошибках |
| **Config Endpoint** | HTTP endpoint для получения актуальной конфигурации агента |
| **Fleet** | Весь парк устройств организации |
| **Topology** | Иерархия Location → Workstation → LDPlayer Instance → Device |

## Приложение B: Зависимости между фазами

```
Фаза 1 (Clone ID) ──┐
                     ├──→ Фаза 3 (Locations & Games) → Фаза 5 (Scaling)
Фаза 2 (Dynamic URL)┘                                       ↑
                                                             │
Фаза 4 (AutoStart) ─────────────────────────────────────────┘
```

Фазы 1 и 2 — независимы, можно вести параллельно.  
Фаза 3 зависит от 1 (автоматическая регистрация с привязкой к локации).  
Фаза 4 — независима.  
Фаза 5 — финальная, требует все предыдущие.
