# PC Agent

Operator/developer guide checked against the audit branch on **9 September 2026**.
The audit is ongoing. A successful Python build or server-side regression does not
prove LDPlayer/ADB execution, Windows service recovery or capacity for 10–64 emulators.
See the [audit report](audits/2026-09-05/AUDIT-REPORT.md) for evidence and remaining work.

## Source and startup

The entry point is [agent/main.py](../pc-agent/agent/main.py); the root
[main.py](../pc-agent/main.py) is a launcher shim. The implementation is flat:

| File | Current responsibility |
| --- | --- |
| [config.py](../pc-agent/agent/config.py) | Pydantic settings, `.env`, `SPHERE_` prefix |
| [client.py](../pc-agent/agent/client.py) | WebSocket first-message key auth, reconnect, outgoing queue |
| [dispatcher.py](../pc-agent/agent/dispatcher.py) | Command routing and result messages |
| [ldplayer.py](../pc-agent/agent/ldplayer.py) | `ldconsole.exe` instance operations |
| [adb_bridge.py](../pc-agent/agent/adb_bridge.py) | Local TCP ADB ports, shell/install/push/pull |
| [topology.py](../pc-agent/agent/topology.py) | Workstation/instance registration payload |
| [telemetry.py](../pc-agent/agent/telemetry.py) | Host CPU/memory/disk/network collection |
| [models.py](../pc-agent/agent/models.py) | Registration and telemetry payloads |

From `pc-agent/`, use an isolated Python environment and install
[requirements.txt](../pc-agent/requirements.txt):

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m agent.main
```

The audit uses Python 3.12 for the combined backend/PC tests. The existing Dockerfile
starts from Python 3.11; it has not established a working LDPlayer installation on
Linux. Default executable paths target Windows LDPlayer. OS/device support must be
validated for the actual host rather than inferred from Python portability.

## Configuration and identity

Settings read **`.env` in the working directory**, with the **`SPHERE_` prefix**.
The old guide's `.env.local`, `SPHERE_WS_URL`, `SPHERE_API_KEY`, unprefixed
`WORKSTATION_ID` and `/ws/workstation/...` examples did not match this implementation.

| Variable | Default / meaning |
| --- | --- |
| `SPHERE_SERVER_URL` | `ws://localhost:8000`; base WS origin, without the endpoint path |
| `SPHERE_AGENT_TOKEN` | `changeme`; replace with a real agent API key |
| `SPHERE_WORKSTATION_ID` | `workstation-01`; replace with the existing workstation UUID |
| `SPHERE_LDPLAYER_PATH` | `C:\LDPlayer\LDPlayer9` |
| `SPHERE_LDCONSOLE` | `C:\LDPlayer\LDPlayer9\ldconsole.exe` |
| `SPHERE_ADB_PATH` | `C:\LDPlayer\LDPlayer9\adb.exe` |
| `SPHERE_RECONNECT_INITIAL_DELAY` | 1 second |
| `SPHERE_RECONNECT_MAX_DELAY` | 30 seconds |
| `SPHERE_RECONNECT_BACKOFF_FACTOR` | 2 |
| `SPHERE_TELEMETRY_INTERVAL` | 30 seconds |

Example `.env` with placeholders:

```dotenv
SPHERE_SERVER_URL=wss://management.example
SPHERE_AGENT_TOKEN=<agent-api-key>
SPHERE_WORKSTATION_ID=<existing-workstation-uuid>
SPHERE_LDCONSOLE=C:\LDPlayer\LDPlayer9\ldconsole.exe
SPHERE_ADB_PATH=C:\LDPlayer\LDPlayer9\adb.exe
SPHERE_TELEMETRY_INTERVAL=30
```

Create an agent-type key with `device:register` through the authorized
`POST /api/v1/auth/api-keys` flow. A user access JWT is not this endpoint's PC
credential. The workstation must already exist in the key's organization.
The current [HTTP catalog](api-endpoints.md) has no `POST /workstations` route;
the old guide's curl example was unsupported. A reviewed workstation/instance
provisioning flow remains necessary; the WebSocket registration handler updates
existing rows and does not create missing workstations or instances.

The client appends `/ws/agent/<workstation-uuid>` to the base URL, then sends:

```json
{"type":"auth","token":"<agent-api-key>","workstation_id":"<existing-workstation-uuid>"}
```

The server uses the path identity and the authenticated key organization. AUD-63
reuses the shared API-key tenant resolver, lock and active/expiry checks. The
separate registration Session binds that organization before accessing workstation
and instance rows. Runtime needs the API-key function grants in the
[credential runbook](security/device-credential-bootstrap.md). A key can address
workstations in its own organization; this is not workstation hardware attestation.
Open connections do not automatically close when their key is later revoked.

## Runtime messages and commands

`workstation_register` updates hostname, OS/agent version, heartbeat, online flag
and matching existing instance metadata/serials. SQL commits before the topology
cache write (`topology:workstation:<id>`, one-hour TTL). Redis failure can leave the
cache stale while SQL has committed. `workstation_telemetry` caches the payload for
120 seconds and publishes an organization event; it is not a durable event journal.

The dispatcher accepts `type`, `command_id` and `payload`, for example:

```json
{"type":"ping","command_id":"<command-uuid>","payload":{}}
```

| Types | Required payload fields |
| --- | --- |
| `ping`, `ld_list`, `adb_devices`, `adb_sync` | None |
| `ld_launch`, `ld_quit`, `ld_reboot` | `index` |
| `ld_create` | `name` |
| `ld_install_apk` | `index`, `apk_path` |
| `ld_run_app` | `index`, `package_name` |
| `ld_exec` | `index`, `command` |
| `adb_shell` | `port`, `command` |
| `adb_install` | `port`, `apk_path` |
| `adb_push` | `port`, `local`, `remote` |
| `adb_pull` | `port`, `remote`, `local` |

ADB operations here target `127.0.0.1:<port>`; they do not implement the former
guide's generic `adb_exec`/serial envelope or automatic single-device selection.
The bridge computes default instance ports as `5554 + index * 2`; verify the actual
emulator configuration. The separate [ADBDiscovery module](../pc-agent/modules/adb_discovery.py)
is not routed by the current dispatcher. End-to-end discovery and OS execution
remain under audit; the command list is an implementation inventory,
not proof of successful remote execution. Unknown command types currently return
`None`, so a success-shaped reply is not evidence that an action ran.

Success and error replies now include the `command_result` discriminator (AUD-64):

```json
{"type":"command_result","command_id":"<command-uuid>","status":"completed","result":{"pong":true}}
```

An execution exception uses `status: failed` and an `error` string. The backend
publishes the payload to `sphere:agent:result:<workstation-id>:<command-id>`.
During a rolling client upgrade it also accepts the older untyped terminal reply
with a nonempty string command ID. Explicit telemetry and intermediate statuses
are not results. Redis PubSub publication is not a durable receipt or execution ACK;
there is no guarantee of recovery if the subscriber, connection or Redis is unavailable.

## Recovery, operations and verification

The main process starts the WS client, telemetry, a 15-second ADB sync loop and one
initial topology task. That task waits one second; it is not a verified per-reconnect
registration mechanism. The client marks itself connected after writing the auth
frame; server auth is not yet confirmed. Its outgoing queue is bounded at 1000
messages, drops sends while disconnected or full, and is not a durable result outbox.

AUD-65 makes either sender or receiver termination close the session and collect
both transport tasks. Failed/cancelled auth writes clear connection state. Reconnect
delays and the five-minute circuit cooldown after ten failures respond to stop;
expired delays do not retain shielded waiter tasks. Clean peer closes also wait
before reconnecting. The failed send is not automatically replayed: its physical
outcome may be unknown. Dispatch tasks can outlive a session and still need bounded
concurrency, shutdown and subprocess recovery design. Real process/network delivery
and stop during an incomplete connect handshake remain unverified.

[install.bat](../pc-agent/install.bat) configures an NSSM service named
`SpherePCAgent`, working directory `pc-agent/`, parameters `-m agent.main`, daily log
rotation and automatic restart. It also starts the service. Review the chosen Python,
working directory, credentials and executable paths before using it; the audit did
not install/start an operating-system service. Container/Windows/Linux service
behavior and access to local emulator executables remain separate validation work.

AUD-63 retains [six failures before](audits/2026-09-05/evidence/pc-tenant-before.txt)
and [45 related passing cases after](audits/2026-09-05/evidence/pc-tenant-after.txt).
Twelve new PostgreSQL/Redis cases use actual non-owner credentials. The real endpoint,
receive-loop dispatch and registration handler execute with explicit socket/manager
transport doubles. They cover connect/reconnect plus registration, invalid keys,
foreign workstations, two SQL key-lock waiters during revoke, committed instance
updates, SQL abort/retry, Redis failure and pooled context cleanup. They do not test
normal ASGI disconnect frames, real PC network recovery, command execution, LDPlayer
processes or CPU/RAM capacity. No claim of minimal CPU consumption or support for
10–64 emulators follows from these tests.

AUD-64 retains [four failures before](audits/2026-09-05/evidence/pc-result-protocol-before.txt)
and [24 related passing cases after](audits/2026-09-05/evidence/pc-result-protocol-after.txt).
Ten new cases link the actual dispatcher and backend handler to a real isolated
Redis subscriber, covering success, execution error, legacy clients and controls.
The transport is an in-process adapter; LDPlayer/ADB are doubles. This verifies
result formatting/routing without claiming durable delivery or physical execution.

AUD-65 retains [six failures before](audits/2026-09-05/evidence/pc-client-recovery-before.txt)
and [91 PC cases passing after](audits/2026-09-05/evidence/pc-client-recovery-after.txt).
Nine new lifecycle cases run the actual client with controlled in-process sockets:
sender failure/reconnect, auth failure/cancellation, circuit stop, repeated backoff,
clean-close pacing, receive termination and concurrent producer ordering. No real
WebSocket listener, DNS lookup, TLS handshake or emulator is involved.
