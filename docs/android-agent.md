# Android Agent

> **Sphere Platform v4.6** — Android Agent (APK) Developer & Operator Guide

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Build Instructions](#3-build-instructions)
4. [Configuration](#4-configuration)
5. [Deployment to Devices](#5-deployment-to-devices)
6. [OTA Updates](#6-ota-updates)
7. [Command Reference](#7-command-reference)
8. [VPN Integration](#8-vpn-integration)
9. [H.264 Streaming](#9-h264-streaming)
10. [Troubleshooting](#10-troubleshooting)
11. [Security Notes](#11-security-notes)
12. [v4.3–4.6 Enhancements](#12-v43-46-enhancements)

---

## 1. Overview

The Android Agent is a native Kotlin application that runs as a **persistent foreground service** on managed Android devices. It connects to the Sphere Platform backend over a secure WebSocket, executes commands, streams H.264 video, and manages AmneziaWG VPN tunnels.

**Minimum Android version:** API 26 (Android 8.0)
**Target SDK:** API 35 (Android 15) *(compileSdk 35, обновлено в v4.3)*

---

## 2. Architecture

```
SphereApp (@HiltAndroidApp)
  │  WorkManager initialization
  │
  └── SphereAgentService (Foreground Service)
        │  Persistent notification, crash recovery via WorkManager
        │
        ├── SphereWebSocketClient
        │     WebSocket connection to wss://<host>/ws/device/<id>
        │     Reconnect: exponential backoff (1s, 2s, 4s … 120s)
        │     Auth: JWT in query param ?token=<access_token>
        │     wsLock: ReentrantLock для потокобезопасной отправки (v4.6)
        │     Reconnect debounce 5с (v4.6)
        │
        ├── CommandHandler
        │     Receives typed command objects from WS
        │     Dispatches to handlers:
        │       adb_exec → LocalAdbExecutor
        │       screenshot → ScreenshotCapture
        │       stream_start → StreamingModule
        │       stream_stop → StreamingModule
        │       vpn_connect → SphereVpnManager
        │       vpn_disconnect → SphereVpnManager
        │       reboot → SystemCommands
        │       app_install → PackageInstaller
        │
        ├── StreamingModule (Hilt @Singleton)
        │     MediaProjection.createVirtualDisplay()
        │     MediaCodec (video/avc) encoder
        │     NAL unit relay → SphereWebSocketClientLive → WS binary
        │     isEncoding guard перед callback (v4.6)
        │
        ├── ConfigWatchdog (v4.3)
        │     Периодический опрос config из GitHub Raw
        │     5 мин (онлайн) / 60с (оффлайн)
        │     При смене server_url → атомарный reconnect
        │
        ├── ServiceWatchdog (v4.3)
        │     AlarmManager keepalive каждые 5 мин
        │     Тройная защита: BootReceiver + START_STICKY + AlarmManager
        │
        ├── AutoEnrollmentWorker (v4.5)
        │     Фоновая авторегистрация через WorkManager
        │
        ├── SphereVpnManager
        │     wg-quick connect/disconnect
        │     Config written to context.filesDir/vpn/sphere0.conf
        │     ConnectivityManager tunnel state verification
        │     Exponential backoff reconnect on tunnel loss
        │
        └── KillSwitchManager
              iptables SPHERE_KILLSWITCH chain
              enable(vpnServerEndpoint) / disable()
```

### Dependency Injection (Hilt)

All major components are provided via Hilt modules:
- `NetworkModule` — OkHttp client, WebSocket client
- `StreamingModule` — MediaCodec pipeline, live WS adapter
- `VpnModule` — SphereVpnManager, KillSwitchManager
- `CommandModule` — CommandHandler, command executors

---

## 3. Build Instructions

### Prerequisites

- Android Studio Hedgehog 2023.1.1+
- JDK 17
- Android SDK API 34
- Gradle 8.3+

### Build

```bash
cd android

# Debug build
./gradlew assembleDebug

# Release build (requires signing config)
./gradlew assembleRelease

# Output location:
# app/build/outputs/apk/debug/app-debug.apk
# app/build/outputs/apk/release/app-release.apk
```

### Signing for release

1. Generate keystore:
```bash
keytool -genkeypair \
  -alias sphere-agent \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000 \
  -keystore sphere-agent.jks
```

2. Configure in `android/app/build.gradle.kts`:
```kotlin
android {
    signingConfigs {
        create("release") {
            storeFile = file(System.getenv("SIGNING_KEYSTORE_PATH") ?: "sphere-agent.jks")
            storePassword = System.getenv("SIGNING_STORE_PASSWORD") ?: ""
            keyAlias = System.getenv("SIGNING_KEY_ALIAS") ?: "sphere-agent"
            keyPassword = System.getenv("SIGNING_KEY_PASSWORD") ?: ""
        }
    }
    buildTypes {
        release {
            signingConfig = signingConfigs.getByName("release")
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
}
```

3. Build signed APK:
```bash
SIGNING_KEYSTORE_PATH=/path/to/sphere-agent.jks \
SIGNING_STORE_PASSWORD=secret \
SIGNING_KEY_ALIAS=sphere-agent \
SIGNING_KEY_PASSWORD=secret \
./gradlew assembleRelease
```

### CI Build (GitHub Actions)

See `.github/workflows/ci-android.yml`. Secrets stored as GitHub Secrets:
- `SIGNING_KEYSTORE` (base64-encoded .jks)
- `SIGNING_STORE_PASSWORD`
- `SIGNING_KEY_ALIAS`
- `SIGNING_KEY_PASSWORD`

---

## 4. Configuration

The agent is configured via the backend — **no manual config file on the device**.

At first launch, the agent registers itself with the backend using a **provisioning code**
(scanned as a QR code or entered manually).

### Build-time configuration (`android/app/src/main/res/values/config.xml`)

```xml
<resources>
    <string name="sphere_backend_url">wss://yourdomain.com</string>
    <string name="sphere_api_url">https://yourdomain.com/api/v1</string>
</resources>
```

Change these before building for each environment.

### Runtime configuration (delivered via WebSocket)

After connection and authentication, the backend sends initial configuration:

```json
{
  "type": "config.update",
  "data": {
    "heartbeat_interval_ms": 30000,
    "stream_bitrate": 2000000,
    "stream_fps": 30,
    "vpn_config": "<optional: if VPN peer assigned>"
  }
}
```

---

## 5. Deployment to Devices

### Via ADB (USB)

```bash
# Single device
adb install -r app/build/outputs/apk/debug/app-debug.apk

# Multiple devices (USB hub)
adb devices | grep "device$" | awk '{print $1}' | \
  xargs -I{} adb -s {} install -r app-debug.apk
```

### Via Platform Web UI

1. Upload APK to MinIO storage via `POST /api/v1/updates/upload`
2. Use **Scripts** → create a DAG script with `app_install` action
3. Execute against target device group

### Via OTA Update System

See [OTA Updates](#6-ota-updates) below.

### Required Permissions (granted at install or first run)

| Permission | Required For |
|-----------|-------------|
| `FOREGROUND_SERVICE` | Persistent agent service |
| `MEDIA_PROJECTION` | Screen capture for streaming |
| `INTERNET` | WebSocket connection |
| `ACCESS_NETWORK_STATE` | Connectivity checks |
| `RECEIVE_BOOT_COMPLETED` | Auto-start on reboot |
| `REQUEST_INSTALL_PACKAGES` | OTA APK installation |
| `ROOT` or `SHELL` | ADB command execution (emulators/rooted devices) |

---

## 6. OTA Updates

The update mechanism allows rolling APK updates across the fleet.

### Update flow

```
1. POST /api/v1/updates/upload   ← upload new APK to S3/MinIO
2. POST /api/v1/updates/deploy   ← target device or group
      { "version": "4.1.0", "device_ids": [...] }
3. Backend sends "ota.update" WS command to each device
4. Android agent:
   a. Downloads APK from signed URL
   b. Verifies SHA-256 checksum
   c. Verifies APK certificate fingerprint against APK_SIGNING_CERT_SHA256
   d. Triggers PackageInstaller session
```

### Certificate pinning

The agent pins the APK signing certificate. Updates will only be installed
if the signing cert SHA-256 matches `APK_SIGNING_CERT_SHA256` in backend config.

```bash
# Get your cert fingerprint
keytool -printcert -jarfile app-release.apk | grep "SHA256:"
```

---

## 7. Command Reference

All commands are JSON messages sent over the WebSocket connection.

### adb_exec

```json
{
  "type": "command.execute",
  "correlation_id": "req-uuid",
  "data": {
    "cmd": "adb_exec",
    "args": { "command": "adb shell input tap 540 960" }
  }
}
```

**Response:**
```json
{
  "type": "command.result",
  "correlation_id": "req-uuid",
  "data": { "exit_code": 0, "stdout": "", "stderr": "" }
}
```

---

### screenshot

```json
{
  "type": "command.execute",
  "correlation_id": "req-uuid",
  "data": { "cmd": "screenshot" }
}
```

**Response:**
```json
{
  "type": "command.result",
  "correlation_id": "req-uuid",
  "data": {
    "exit_code": 0,
    "screenshot_url": "https://storage.yourdomain.com/screenshots/uuid.png"
  }
}
```

---

### stream_start

```json
{
  "type": "command.execute",
  "data": {
    "cmd": "stream_start",
    "args": { "bitrate": 2000000, "fps": 30 }
  }
}
```

H.264 NAL units are then sent as binary WebSocket messages.

---

### stream_stop

```json
{ "type": "command.execute", "data": { "cmd": "stream_stop" } }
```

---

### vpn_connect

```json
{
  "type": "command.execute",
  "data": {
    "cmd": "vpn_connect",
    "args": { "config_b64": "<base64 wg config>" }
  }
}
```

---

### vpn_disconnect

```json
{ "type": "command.execute", "data": { "cmd": "vpn_disconnect" } }
```

---

### reboot

```json
{ "type": "command.execute", "data": { "cmd": "reboot" } }
```

Reboots the device. Agent reconnects automatically after reboot via `RECEIVE_BOOT_COMPLETED`.

---

## 8. VPN Integration

### SphereVpnManager

Manages the `sphere0` WireGuard interface via `wg-quick`.

**State machine:**
```
DISCONNECTED → CONNECTING → CONNECTED → RECONNECTING → CONNECTED
                                     ↘ FAILED
```

**Config storage:**
- Config written to `context.filesDir/vpn/sphere0.conf` (app-private)
- File permissions: `0600` (owner readable only)
- Config is deleted on `vpn_disconnect` command

### Kill Switch

The kill switch is **automatically enabled** when VPN connect starts and
**disabled only on clean disconnect**. If the device reboots mid-connection,
the kill switch chain is absent (iptables reset by kernel restart), so traffic
flows normally until the VPN is re-established at boot.

For maximum security, configure `kill_switch_on_boot: true` in the backend
device policy to immediately re-enable the kill switch on agent startup if
a VPN peer is assigned.

### Reconnect behavior

| Attempt | Delay |
|---------|-------|
| 1 | 1s |
| 2 | 2s |
| 3 | 4s |
| 4 | 8s |
| 5 | 16s |
| 6+ | 120s (max) |

After 10 failed attempts: `vpn.error` event sent to backend, kill switch maintained.

---

## 9. H.264 Streaming

### Codec Configuration

```kotlin
MediaFormat.createVideoFormat("video/avc", width, height).apply {
    setInteger(KEY_BIT_RATE, bitrate)         // default: 2 Mbps
    setInteger(KEY_FRAME_RATE, fps)            // default: 30
    setInteger(KEY_I_FRAME_INTERVAL, 1)        // keyframe every 1s
    setInteger(KEY_COLOR_FORMAT, COLOR_FormatSurface)
    setInteger(KEY_PROFILE, AVCProfileBaseline)
    setInteger(KEY_LEVEL, AVCLevel31)
}
```

### NAL Unit Framing

Each encoded frame is prefixed with a 4-byte big-endian length before sending:

```
[4 bytes: length][NAL unit data]
```

This allows the receiver (WebCodecs decoder) to reconstruct frame boundaries
from the stream.

### Frame Drop Policy

Under backpressure (WebSocket send buffer > threshold), non-keyframe frames
are dropped:
- All keyframes (SPS/PPS/IDR) are always sent
- Non-IDR frames may be dropped when backlogged
- Quality gracefully degrades rather than increasing latency

---

## 10. Troubleshooting

### Agent not connecting

1. Check `wss://yourdomain.com` is reachable from the device
2. Verify JWT token is valid: `curl https://yourdomain.com/api/v1/health`
3. Check logcat:
```bash
adb logcat -s SphereWebSocketClient SphereAgentService
```

### Streaming not working

1. Verify `MEDIA_PROJECTION` permission granted
2. Check if stream session is active in backend:
```bash
curl -H "Authorization: Bearer <token>" \
     https://yourdomain.com/api/v1/streaming/sessions
```
3. Check for H.264 hardware encoder availability:
```bash
adb shell "dumpsys media.codec | grep -i h264"
```

### VPN not connecting

1. Check `wg-quick` binary available:
```bash
adb shell which wg-quick
```
2. Verify peer config delivered:
```bash
adb logcat -s SphereVpnManager
```
3. Check kill switch state:
```bash
adb shell iptables -L SPHERE_KILLSWITCH
```

---

## 11. Security Notes

- The agent WebSocket uses TLS always — no plaintext WS connections
- JWTs for devices are scoped with `role=device` — no admin API access
- ADB command execution is restricted to the user-space shell (no root required for most commands)
- Config files containing VPN private keys are stored in app-private storage
  with `0600` permissions — not accessible to other apps without root
- OTA updates require certificate fingerprint match — prevents untrusted APK installation
- **wsLock (v4.6):** ReentrantLock защищает от race condition при отправке WS-сообщений из разных потоков
- **MediaCodec guard (v4.6):** `isEncoding` флаг предотвращает callback на disposed encoder

---

## 12. v4.3–4.6 Enhancements

### v4.3 — Watchdog механизмы (100% uptime)

#### ConfigWatchdog (удалённая конфигурация)
- `@Singleton` компонент, периодический опрос `CONFIG_URL` (напр. GitHub Raw)
- Интервал: 5 мин (онлайн) / 60с (оффлайн), минимум 30с
- При смене `server_url`: атомарное обновление `AuthTokenStore` + `forceReconnectNow()`
- `forceCheck()` — вызывается CircuitBreaker при 10+ ошибках WS

#### ServiceWatchdog (AlarmManager keepalive)
- BroadcastReceiver + AlarmManager (ELAPSED_REALTIME_WAKEUP)
- Перезапуск `SphereAgentService` каждые 5 мин
- `enrolled` флаг в SharedPreferences — запуск только после enrollment
- Покрывает aggressive battery optimization (Xiaomi, Huawei, Samsung)

#### Жизненный цикл (6 точек входа)
1. `SphereAgentService.onCreate()` — ConfigWatchdog coroutine + ServiceWatchdog alarm
2. `BootReceiver.onReceive()` — enrollment check + watchdog scheduling
3. `SphereApp.onCreate()` — watchdog scheduling при старте Application
4. `SetupActivity.launchAgent()` — markEnrolled + schedule при enrollment
5. `AndroidManifest.xml` — ServiceWatchdog receiver registration
6. `ForegroundServiceStartNotAllowedException` (Android 12+) — try-catch в BootReceiver

### v4.4 — Dynamic server URL
- `AppModule.kt`: DI использует `ConfigWatchdog` вместо `BuildConfig.SERVER_URL`
- Пересборка APK не требуется при смене сервера

### v4.5 — AutoEnrollmentWorker + деплой-скрипты
- `AutoEnrollmentWorker.kt` — фоновая авторегистрация через WorkManager
- `android/scripts/` — деплой-скрипты:
  - `deploy-farm.sh` — развёртывание на ферму через ADB
  - `deploy-ldplayer.bat` — LDPlayer эмуляторы (Windows)
  - `deploy-waydroid.sh` — Waydroid контейнеры
  - `install-init-script.sh` — инициализация при загрузке
  - `install-system-app.sh` — установка как системное приложение

### v4.6 — Android Hardening

| Проблема | Решение | Файл |
|----------|---------|------|
| WS race condition при отправке из нескольких потоков | `wsLock` (ReentrantLock) | SphereWebSocketClient.kt |
| CPU usage скачки при телеметрии | CPU delta debounce (<3% игнорируется) | TelemetryCollector.kt |
| Reconnect storm | Debounce 5с | SphereWebSocketClient.kt |
| MediaCodec callback на disposed encoder | Guard `isEncoding` | StreamingModule.kt |
| ForegroundServiceStartNotAllowedException | try-catch в BootReceiver | BootReceiver.kt |

**Тесты**: 272 теста в 16 файлах (JUnit, MockK, Turbine, Robolectric).
