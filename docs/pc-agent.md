# PC Agent

> **Sphere Platform v4.0** — PC Agent Operator & Developer Guide

---

## Table of Contents

1. [Overview](#1-overview)
2. [Architecture](#2-architecture)
3. [Installation](#3-installation)
4. [Configuration](#4-configuration)
5. [ADB Bridge](#5-adb-bridge)
6. [Device Discovery](#6-device-discovery)
7. [LDPlayer Integration](#7-ldplayer-integration)
8. [Telemetry](#8-telemetry)
9. [Running as a Service](#9-running-as-a-service)
10. [Command Reference](#10-command-reference)
11. [Troubleshooting](#11-troubleshooting)

---

## 1. Overview

The PC Agent is a Python `asyncio` daemon that runs on a **Windows or Linux host** where
Android devices (real or emulated) are connected via USB or ADB over TCP. It bridges
the Sphere Platform backend to locally connected devices through a WebSocket connection.

**Primary functions:**
- ADB command relay: backend sends commands → PC Agent executes via `adb` → returns result
- Device discovery: scans USB/TCP for connected Android devices
- LDPlayer emulator lifecycle management (Windows only)
- Host telemetry: CPU, RAM, disk metrics reported to backend

---

## 2. Architecture

```
pc-agent/
├── main.py              ← launcher shim (entry point)
└── agent/
    ├── main.py          ← asyncio app entry
    ├── ws/
    │   └── client.py    ← WebSocket client, JWT auth, reconnect
    ├── adb/
    │   ├── bridge.py    ← adb CLI wrapper (asyncio.subprocess)
    │   └── executor.py  ← command execution with timeout
    ├── modules/
    │   ├── discovery.py ← USB/TCP device enumeration
    │   └── commands.py  ← command dispatch table
    ├── ldplayer/
    │   ├── manager.py   ← LDPlayer lifecycle (start/stop/list instances)
    │   └── config.py    ← LDPlayer path + registry detection
    ├── core/
    │   ├── config.py    ← pydantic-settings Settings
    │   └── constants.py
    └── telemetry/
        └── collector.py ← psutil metrics collection + reporting
```

### Event loop architecture

```
main() coroutine
  ├── ws_client.run()          ← persistent WS connection
  ├── telemetry_loop()         ← every 30s reports host metrics
  └── heartbeat_loop()         ← every 10s sends ping

ws_client.run():
  ├── await connect_with_backoff()
  ├── async for msg in ws:
  │     command = parse_command(msg)
  │     result = await dispatch(command)
  │     await ws.send_json(result)
  └── on disconnect: reconnect with backoff
```

---

## 3. Installation

### Windows

**Prerequisites:**
- Python 3.11+
- Android Platform Tools (adb) in PATH
- (Optional) LDPlayer 9.x installed

```powershell
# Clone or extract the agent
cd C:\sphere-pc-agent

# Create virtualenv
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Configure
copy .env.example .env.local
notepad .env.local
```

### Linux

```bash
# Install Python 3.11+
sudo apt-get install python3.11 python3.11-venv android-tools-adb

# Create virtualenv
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure
cp .env.example .env.local
nano .env.local
```

### Required Python packages

```
websockets>=12.0
aiohttp>=3.9
pydantic>=2.0
pydantic-settings>=2.0
psutil>=5.9
structlog>=24.0
aiofiles>=23.0
tenacity>=8.0        # reconnect with exponential backoff
```

---

## 4. Configuration

Configuration is loaded from `pc-agent/.env.local`:

| Variable | Required | Description |
|----------|----------|-------------|
| `SPHERE_WS_URL` | ✓ | Backend WebSocket URL: `wss://yourdomain.com/ws/workstation/<id>` |
| `SPHERE_API_URL` | ✓ | Backend API URL: `https://yourdomain.com/api/v1` |
| `SPHERE_API_KEY` | ✓ | API key from `POST /api-keys` (role: `device_manager`) |
| `WORKSTATION_ID` | ✓ | UUID registered via `POST /workstations` |
| `ADB_PATH` | | Path to adb binary (default: `adb` from PATH) |
| `ADB_CONNECT_TIMEOUT` | | Seconds before ADB command timeout (default: `10`) |
| `LDPLAYER_PATH` | | Path to LDPlayer installation (Windows) |
| `TELEMETRY_INTERVAL` | | Seconds between telemetry reports (default: `30`) |
| `LOG_LEVEL` | | `DEBUG`, `INFO`, `WARNING` (default: `INFO`) |
| `RECONNECT_MAX_DELAY` | | Max reconnect delay in seconds (default: `120`) |

**Example `.env.local`:**
```bash
SPHERE_WS_URL=wss://yourdomain.com/ws/workstation/550e8400-e29b-41d4-a716-446655440000
SPHERE_API_URL=https://yourdomain.com/api/v1
SPHERE_API_KEY=sk_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WORKSTATION_ID=550e8400-e29b-41d4-a716-446655440000
ADB_PATH=C:\Platform-Tools\adb.exe
LDPLAYER_PATH=C:\LDPlayer\LDPlayer9
LOG_LEVEL=INFO
```

### Registering the workstation

Before first run, register the workstation in the platform:

```bash
# Via API
curl -X POST https://yourdomain.com/api/v1/workstations \
  -H "Authorization: Bearer <admin_token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Windows PC-01", "hostname": "pc-01.lan", "location": "Office"}'

# Note the returned UUID → set as WORKSTATION_ID
```

---

## 5. ADB Bridge

The ADB bridge wraps the `adb` CLI tool using `asyncio.subprocess`.

### Command execution

```python
# Internal (agent/adb/bridge.py)
result = await bridge.execute("adb -s emulator-5554 shell input tap 540 960")
# Returns: AdbResult(exit_code=0, stdout="", stderr="", duration_ms=89)
```

### Supported ADB operations

| Operation | Command pattern |
|-----------|----------------|
| Shell command | `adb shell <cmd>` |
| Install APK | `adb install -r <path>` |
| Push file | `adb push <local> <remote>` |
| Pull file | `adb pull <remote> <local>` |
| Reboot | `adb reboot` |
| Screenshot | `adb exec-out screencap -p` |
| Port forward | `adb forward tcp:<local> tcp:<remote>` |

### Multi-device targeting

When multiple devices are connected, commands must specify a serial:

```json
{
  "cmd": "adb_exec",
  "args": {
    "serial": "emulator-5554",
    "command": "adb shell getprop ro.product.model"
  }
}
```

If `serial` is omitted and only one device is connected, it is used automatically.

---

## 6. Device Discovery

Discovery scans for connected Android devices and returns them to the backend.

### Trigger discovery

Backend sends command or discovery is triggered via `POST /discovery/scan`:

```json
{
  "type": "command.execute",
  "data": { "cmd": "discover_adb" }
}
```

### Discovery algorithm

```python
# agent/modules/discovery.py
async def discover_devices():
    # 1. Run: adb devices -l
    stdout = await adb.execute("adb devices -l")

    # 2. Parse output
    devices = parse_adb_devices(stdout)
    # Each device: { serial, state, model, transport_id }

    # 3. For each connected device, get extra properties
    for device in devices:
        props = await get_device_props(device.serial)
        device.update(props)

    return devices
```

### Discovery response format

```json
{
  "devices": [
    {
      "serial": "emulator-5554",
      "state": "device",
      "model": "sdk_gphone64_x86_64",
      "android_version": "13",
      "api_level": "33",
      "product": "sdk_gphone64_x86_64",
      "transport": "usb"
    },
    {
      "serial": "192.168.11.101:5555",
      "state": "device",
      "model": "Pixel_6",
      "android_version": "14",
      "api_level": "34",
      "transport": "tcp"
    }
  ]
}
```

---

## 7. LDPlayer Integration

LDPlayer is an Android emulator for Windows. The PC Agent can manage LDPlayer
instances via the `ldconsole.exe` CLI.

### Commands

| Backend command | LDPlayer operation |
|----------------|--------------------|
| `ldplayer.list` | `ldconsole list` |
| `ldplayer.start` | `ldconsole launch --index <n>` |
| `ldplayer.stop` | `ldconsole quit --index <n>` |
| `ldplayer.reboot` | `ldconsole reboot --index <n>` |
| `ldplayer.create` | `ldconsole add --name <name>` |
| `ldplayer.delete` | `ldconsole remove --index <n>` |

### List instances

```json
{
  "cmd": "ldplayer.list"
}
```

**Response:**
```json
{
  "instances": [
    { "index": 0, "name": "LDPlayer-0", "top_level_adb": "emulator-5554", "running": true },
    { "index": 1, "name": "LDPlayer-1", "top_level_adb": "emulator-5556", "running": false }
  ]
}
```

### Auto-detection of LDPlayer path

On Windows, the agent auto-detects LDPlayer from the registry:
```
HKEY_LOCAL_MACHINE\SOFTWARE\leidian\ldplayer9\InstallDir
```

Override with `LDPLAYER_PATH` env variable if needed.

---

## 8. Telemetry

The agent reports host metrics every `TELEMETRY_INTERVAL` seconds (default: 30).

### Metrics reported

```json
{
  "type": "telemetry.report",
  "data": {
    "workstation_id": "uuid",
    "timestamp": "2026-02-23T10:00:00Z",
    "cpu_percent": 23.4,
    "ram_total_mb": 32768,
    "ram_used_mb": 12800,
    "ram_percent": 39.1,
    "disk_total_gb": 500,
    "disk_used_gb": 180,
    "disk_percent": 36.0,
    "connected_devices": 4,
    "adb_server_running": true
  }
}
```

Metrics are stored in the backend and exposed via Prometheus for Grafana dashboards.

---

## 9. Running as a Service

### Windows — Task Scheduler

```powershell
# Create scheduled task (run at startup, hidden)
$action = New-ScheduledTaskAction `
  -Execute "C:\sphere-pc-agent\.venv\Scripts\python.exe" `
  -Argument "C:\sphere-pc-agent\pc-agent\main.py" `
  -WorkingDirectory "C:\sphere-pc-agent\pc-agent"

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
  -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
  -RestartCount 10 `
  -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask `
  -TaskName "SphereAgent" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -RunLevel Highest `
  -Force
```

### Windows — NSSM (Non-Sucking Service Manager)

```powershell
# Download nssm from https://nssm.cc/
nssm install SphereAgent "C:\sphere-pc-agent\.venv\Scripts\python.exe"
nssm set SphereAgent Arguments "C:\sphere-pc-agent\pc-agent\main.py"
nssm set SphereAgent AppDirectory "C:\sphere-pc-agent\pc-agent"
nssm set SphereAgent Start SERVICE_AUTO_START
nssm set SphereAgent AppStdout "C:\sphere-pc-agent\logs\stdout.log"
nssm set SphereAgent AppStderr "C:\sphere-pc-agent\logs\stderr.log"
nssm start SphereAgent
```

### Linux — systemd

```ini
# /etc/systemd/system/sphere-agent.service
[Unit]
Description=Sphere PC Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=sphere-agent
WorkingDirectory=/opt/sphere-pc-agent/pc-agent
ExecStart=/opt/sphere-pc-agent/.venv/bin/python main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable sphere-agent
sudo systemctl start sphere-agent
sudo journalctl -u sphere-agent -f   # follow logs
```

---

## 10. Command Reference

### Full command list

| Command | Args | Description |
|---------|------|-------------|
| `discover_adb` | — | Enumerate connected ADB devices |
| `adb_exec` | `serial`, `command` | Execute ADB command |
| `adb_connect` | `host`, `port` | Connect via ADB TCP |
| `adb_disconnect` | `serial` | Disconnect ADB device |
| `screenshot` | `serial` | Capture device screenshot |
| `ldplayer.list` | — | List LDPlayer instances |
| `ldplayer.start` | `index` | Start LDPlayer instance |
| `ldplayer.stop` | `index` | Stop LDPlayer instance |
| `ldplayer.reboot` | `index` | Reboot LDPlayer instance |
| `telemetry.report` | — | Request immediate telemetry report |
| `agent.status` | — | Agent status (version, uptime, connections) |
| `agent.restart` | — | Graceful restart of the agent process |

---

## 11. Troubleshooting

### Agent can't connect to backend

```bash
# Test WebSocket endpoint
python -c "
import asyncio, websockets

async def test():
    uri = 'wss://yourdomain.com/ws/workstation/uuid?token=...'
    async with websockets.connect(uri) as ws:
        print('Connected:', await ws.recv())

asyncio.run(test())
"
```

### ADB not found

```bash
# Check ADB in PATH
adb version

# Windows: add Platform Tools to PATH
$env:PATH += ";C:\platform-tools"

# Verify adb server is running
adb start-server
adb devices
```

### No devices found after discovery

```bash
# Check USB debugging enabled on device
adb devices
# Should show: serial    device (not "unauthorized")

# If "unauthorized": check device screen for RSA key prompt

# For LDPlayer: ensure adb port is accessible
adb connect localhost:5554
```

### High CPU usage

The agent is asyncio-based and uses minimal CPU. If usage is high:
```bash
# Check Python process
wmic process where "name='python.exe'" get ProcessId,CommandLine,WorkingSetSize

# Increase telemetry interval
TELEMETRY_INTERVAL=60  # in .env.local
```

### Logs

```bash
# Windows (if using NSSM)
Get-Content C:\sphere-pc-agent\logs\stdout.log -Wait -Tail 50

# Linux (systemd)
journalctl -u sphere-agent -f --since "1 hour ago"
```
