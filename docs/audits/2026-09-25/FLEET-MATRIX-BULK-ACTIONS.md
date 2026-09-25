# Fleet Matrix: operational audit and fixes

- **Date:** 2026-09-25
- **Scope:** Devices / Fleet Matrix page, bulk-action API contracts, and stream grid controls.
- **Baseline:** `a19a08b` on `codex/enterprise-audit-20260905`.
- **Disposition:** Source fixes and regression checks are complete for the findings below. This is not a sign-off for remote Android streaming or a 32-device live pilot.

## Executive result

The Devices page had several independent defects that looked like one broken delete control: reboot could report success without delivering a command, VPN revoke used an unsupported action, destructive operations hid failures and discarded selection, and the stream grid had controls that did not control the mounted streams or video canvas. A 390 px browser check also showed that the virtualized table could compress its first column until the device name was effectively unreadable.

The affected controls now use explicit API contracts, per-device outcomes, visible failure states, bounded bulk requests, and regression coverage. The production build serves `/devices`; a browser smoke test against the built app exercised login/refresh with fixtures, table selection, VPN and delete confirmation/cancel/partial-failure/retry, stream grid start/stop, canvas fit, and a narrow viewport. It used mocked APIs and no real device or tunnel.

## Findings, evidence, and disposition

### FLEET-001 — reboot could report success without a command reaching Android

**Severity:** P2 — operational correctness.
**Root cause:** the previous `_reboot_device` implementation only wrote `cmd:reboot:{device_id}` to Redis with a 30-second TTL. Repository search found no reader for that key, so a successful Redis write was not evidence of Android delivery. The bulk endpoint then returned the operation as successful.

**Evidence / reproduction:** at the baseline commit, submit `POST /api/v1/devices/bulk/action` with `action: reboot` for an owned device while the command publisher is unavailable. The old path only wrote the Redis key and had no receiver/acknowledgement. The regression test now asserts that an unavailable transport and an agent rejection produce `success: false`, and that the old Redis key is not written.

**Fix:** dispatch `REBOOT` over the live Android command publisher with a unique command ID, a 15-second command TTL, and a 10-second acknowledgement deadline. Offline transport, timeout, rejection, or an invalid receipt is a per-device failure. `received` / `running` means accepted by the agent; the UI does not claim that reboot has finished.

**Affected files:** `backend/services/bulk_service.py`, `tests/bulk/test_bulk.py`, `frontend/app/(dashboard)/devices/page.tsx`.

**Regression:** `test_bulk_reboot_succeeds_for_owned`, `test_bulk_reboot_fails_explicitly_when_live_transport_is_unavailable`, and `test_bulk_reboot_reports_agent_rejection_without_claiming_success`.

**Residual risk:** this verifies command dispatch and receipt handling through the publisher contract. It does not prove that a real Android agent rebooted a remote emulator; that needs a live pilot with agent-side command evidence.

### FLEET-002 — VPN revoke button called an unsupported bulk action

**Severity:** P2 — visible fleet operation was unusable.
**Root cause:** the UI sent `vpn_revoke` to the generic device bulk-action route, whose request enum does not contain that operation. FastAPI rejected the request before any peer was revoked. The VPN router also used role checks that differed from the declared permission matrix.

**Evidence / reproduction:** select a device and invoke **Отозвать VPN** at the baseline. The generic action schema rejects the unknown action with HTTP 422. Tests now exercise the dedicated endpoint, role permissions, duplicate IDs, and partial provider failure.

**Fix:** added `POST /api/v1/vpn/revoke/bulk`, requires `vpn:mass_operation`, validates 1–500 unique UUIDs, scopes each revoke to the current organization, processes the shared SQLAlchemy session sequentially, and returns one outcome per device. Provider exception details are not returned to the browser. The frontend sends this contract and preserves selection for failed devices.

**Affected files:** `backend/api/v1/vpn/router.py`, `backend/schemas/vpn/peer.py`, `frontend/lib/hooks/useVpn.ts`, `frontend/app/(dashboard)/devices/page.tsx`, `tests/vpn/test_vpn_api.py`, `docs/openapi.json`, `docs/api-endpoints.md`.

**Regression:** `TestVPNBulkRevokeEndpoint` covers success/partial failure, no provider-detail leak, owner/admin permission, manager denial, and duplicate-ID rejection.

**Residual risk:** this request processes peers sequentially to protect the service's single database session. The schema permits 500 IDs, so high-latency providers can make a large request slow. Use staged batches and inspect provider reconciliation before mass revoke. Durable background-job execution is a separate follow-up, not implemented here.

### FLEET-003 — delete confirmation hid errors and cleared the selection too early

**Severity:** P2 — destructive action was hard to diagnose and recover.
**Root cause:** the previous UI used native `confirm()`, fired the mutation without awaiting its result, and cleared row selection immediately. A permission, network, or server error left no useful page-level explanation and removed the context needed to retry. The service method was also named `bulk_soft_delete` although it physically deleted catalog rows.

**Evidence / reproduction:** select one or more rows, confirm delete, and make the endpoint return 403 or a network error. The old handler had no error path and selection was cleared before the response. Regression tests exercise cancel, failure, retained selection, duplicate submission, the 500-item limit, and partial results.

**Fix:** single and bulk removal use an accessible in-app confirmation dialog. A failure remains visible in the dialog and selection is retained; successful removal clears selection only after the API confirms the count. Partial results are reported. The action now retires records from active inventory, revokes device refresh credentials, and preserves task/event history and foreign-key references.

**Affected files:** `frontend/src/features/devices/DeviceBulkDeleteButton.tsx`, `frontend/src/features/devices/DeviceDeleteConfirmationDialog.tsx`, `frontend/app/(dashboard)/devices/page.tsx`, `backend/services/device_service.py`, `backend/api/v1/bulk/router.py`, `tests/bulk/test_bulk.py`.

**Regression:** `DeviceBulkDeleteButton.test.tsx`, `DeviceDeleteConfirmationDialog.test.tsx`, and `TestBulkDelete` including organization isolation and idempotent repeated deletion. A production-browser smoke test verified that cancel sent zero DELETE requests, a 403 left the selection available, and a later 200 cleared it.

**Residual risk:** archived rows are omitted from the default inventory list but remain addressable by ID for history and can be reactivated by an authorized update. This action does not uninstall the Android app or remove its game data. An online device may retain its already-issued short-lived access token until its normal expiry; WebSocket and task admission paths still enforce active-device state.

### FLEET-009 — bulk removal returned HTTP 500 for devices with task history

**Severity:** P1 — observed in the active pilot and blocks fleet cleanup for devices with retained work history.

**Root cause:** both single and bulk removal called `AsyncSession.delete(Device)`. PostgreSQL correctly rejected the parent-row delete when `tasks.device_id` or `pipeline_runs.device_id` still referenced the device. Bulk deletion is one transaction, so one referenced row rolled back the whole selected batch. The usual SQLite test engine did not enforce PostgreSQL foreign keys, which left this path uncovered.

**Evidence / reproduction:** the supplied browser console shows `DELETE /api/v1/devices/bulk` returning HTTP 500. The active pilot backend log records `ForeignKeyViolationError` for `tasks_device_id_fkey` on that same route. A new regression test was first run against the isolated local PostgreSQL test database and failed with the same constraint error when one selected device had a task and a second selected device did not.

**Fix:** removal now marks owned active device rows inactive, sets the stored status offline, clears refresh-token hashes and rotation state, and preserves task, pipeline, event, and account history. The default device inventory query excludes inactive rows. Repeating the request returns zero without deleting history. Single-device removal uses the same retirement path.

**Affected files:** `backend/services/device_service.py`, `backend/api/v1/bulk/router.py`, `backend/api/v1/devices/router.py`, `backend/schemas/bulk.py`, `frontend/src/features/devices/DeviceBulkDeleteButton.tsx`, `tests/production/test_device_bulk_retirement.py`, `tests/bulk/test_bulk.py`, `tests/devices/test_devices.py`.

**Regression:** the isolated PostgreSQL test asserts bulk removal succeeds with linked history, retained task rows, hidden inventory rows, refresh-token rejection, and idempotent replay. The backend unit tests cover single removal, tenant scoping, and repeat requests.

**Residual risk:** the fix must be deployed to the pilot backend before the live button can work. At audit time the active containers still use image tag `e308b1b`, while PR #19 is ahead at `d8c2562`; the public page also served a different Devices chunk than the local build. No live deletion was replayed during this audit.

### FLEET-004 — stopping broadcast did not unmount the streams

**Severity:** P2 — operators could leave multiple live WebSockets and decoders running after pressing stop.
**Root cause:** the grid's **End Broadcast** button only invoked an optional `onClose`. The Devices page did not provide that callback, and local `broadcastActive` remained true, so child `DeviceStream` components stayed mounted.

**Evidence / reproduction:** open the grid, start broadcast, then press the stop control. At baseline there was no local state change on this page. The browser smoke test now confirms that stop changes the UI state and disables the stop control after the stream children are unmounted.

**Fix:** stop clears `broadcastActive` and then invokes `onClose` when a parent has supplied one. The current selected-device set is passed to the grid, and only up to the configured grid size is subscribed at once.

**Affected files:** `frontend/src/features/devices/MultiStreamGrid.tsx`, `frontend/app/(dashboard)/devices/page.tsx`, `frontend/__tests__/devices/multi-stream-grid.test.tsx`.

**Residual risk:** the smoke test closed a mocked browser WebSocket and verifies component lifecycle only. It does not establish frame delivery through the public ingress/tunnel.

### FLEET-005 — FIT changed a wrapper instead of the video canvas

**Severity:** P2 — the visible fit control had no effect on decoded frames.
**Root cause:** `object-fit` was set on a `div`, while the decoded picture is painted into a child `<canvas>`.

**Evidence / reproduction:** in the grid, toggle FIT and inspect the canvas computed style; at baseline the control did not change it.
**Fix:** pass `fit` through `MultiStreamGrid` to `DeviceStream` and apply it to the canvas. The browser smoke test verified the canvas switches to `object-fit: cover`.

**Affected files:** `frontend/src/features/devices/MultiStreamGrid.tsx`, `frontend/components/sphere/DeviceStream.tsx`, `frontend/__tests__/stream/diagnostics.test.tsx`.

**Residual risk:** this verifies layout behavior, not H.264 decode quality or real-frame cadence.

### FLEET-006 — selected devices and displayed health did not match reality

**Severity:** P2 — the operator could watch unintended devices and be shown invented status.
**Root cause:** the grid always took the first N devices even when table rows were selected. Offline cells showed a hard-coded `ERR_CONN_REFUSED`, while heartbeat age was shown as a fixed `< 5s` whenever any timestamp existed.

**Evidence / reproduction:** select a later device and start the grid, or supply an old heartbeat. The baseline grid still chose the first device and the fixed labels remained unchanged.
**Fix:** selected IDs now define the stream candidates; the grid visibly reports overflow beyond its configured capacity. Heartbeat age derives from the API timestamp and invalid/missing timestamps are shown as unknown. Removed the fabricated connection error.

**Affected files:** `frontend/src/features/devices/MultiStreamGrid.tsx`, `frontend/__tests__/devices/multi-stream-grid.test.tsx`.

**Regression:** tests cover selected-device precedence, subscription cap, and timestamp/status rendering.

### FLEET-007 — narrow screens clipped the table and compressed device identifiers

**Severity:** P2 — mobile operators could not reliably identify a device or reach its row actions.
**Root cause:** the page fixed itself to the viewport height while its mobile header, KPI cards, and stacked filters consumed most of the space. The table was trapped in the remaining clipped region. Its flex rows also allowed fixed-width columns to shrink below their declared widths.

**Evidence / reproduction:** run the production UI at a 390 px viewport with one real-shaped API fixture. Before the fix, the device-name element measured about 6 px wide and the row was clipped below the header.
**Fix:** allow the mobile page to grow and scroll, give the device section a mobile minimum height, compact the mobile KPIs and place group/location filters side by side, and make table rows/cells non-shrinking so horizontal scrolling happens inside the table. At the same viewport the device name measured 42 px and document width remained exactly 390 px.

**Affected files:** `frontend/app/(dashboard)/devices/page.tsx`, `frontend/src/features/devices/FleetMatrix.tsx`, `frontend/__tests__/devices/fleet-matrix-real-data.test.tsx`.

**Regression:** a structural table test protects non-shrinking cells; the local production-browser smoke test checked 390 px width, no document overflow, and a fully readable device name.

### FLEET-008 — VPN revoke used a browser-native confirmation

**Severity:** P3 — inconsistent and inaccessible operator flow.
**Root cause:** the VPN bulk action used `window.confirm()`, bypassing the app's dialog styling, focus handling, pending state, and inline failure details.

**Evidence / reproduction:** select a device and choose **Отозвать VPN**. The browser-owned modal cannot show Sphere's selected scope or API failure details. The production-browser smoke now verifies that cancel sends zero requests and that a partial server result closes the confirmation while retaining the failed device selection.

**Fix:** replaced the native prompt with an accessible Sphere dialog that states the organization/device scope, disables controls during mutation, displays request-level failures, and preserves failed-device selection after partial results.

**Affected files:** `frontend/app/(dashboard)/devices/page.tsx`, `docs/web-ui-guide.md`.

**Regression:** local production-browser smoke covered cancel and one per-device provider failure; frontend type-check, lint, and Jest suites passed.

### API-001 — committed OpenAPI schema was generated with a different dependency set

**Severity:** P3 — contract documentation and CI reproducibility.
**Root cause:** the local Python environment used FastAPI 0.141.1 / Pydantic 2.13.5, while `backend/requirements.txt` and CI pin FastAPI 0.136.3 / Pydantic 2.9.2. OpenAPI output differed even though the local exporter check passed.

**Evidence / reproduction:** GitHub backend run `36149584324` passed its complete unit/real-service test step, then failed `Verify generated HTTP API documentation` with `Stale API documentation: docs/openapi.json`. Re-running the exporter in an isolated environment with the repository's pinned FastAPI, Starlette, Pydantic, and Pydantic Settings versions reproduced the stale-schema result.

**Fix:** regenerated `docs/openapi.json` using the dependency versions declared by the project. The endpoint catalog had no difference.

**Regression:** `python -m scripts.export_api_docs --check` passed in that isolated pinned-version environment. Follow-up GitHub run `36151375451` on head `a20342e` passed the same check together with the full backend suite and Redis acceptance.

**Residual risk:** none remains for this version-mismatch finding; the exact Python 3.12 CI job passed after regeneration.

## Validation evidence

| Check | Result |
| --- | --- |
| Frontend Jest | 38 suites, 295 tests passed |
| Frontend TypeScript | `npm run type-check` passed |
| Changed frontend files lint | No warnings or errors |
| Production build | Exit 0; optimized build completed; 30/30 static pages generated |
| Production-browser smoke | Passed login/refresh fixtures, Fleet Matrix data, VPN cancel/partial failure, delete cancel/403/retry/200, grid stop, FIT canvas style, and 390 px layout |
| Backend targeted tests | 40 passed (`tests/bulk/test_bulk.py`, `tests/vpn/test_vpn_api.py`) |
| Backend Ruff | Passed for all changed backend/test files |
| OpenAPI/catalog verification | Passed with FastAPI 0.136.3 / Starlette 1.3.1 / Pydantic 2.9.2 / Pydantic Settings 2.2.1 in an isolated environment |
| GitHub backend CI (`a20342e`) | Passed: full unit/real-service tests, generated API docs, Redis memory/persistence acceptance, Alembic single-head, Ruff/mypy, RLS, security, and production-image bootstrap |
| GitHub frontend CI (`a20342e`) | Tests, TypeScript, and production build passed |
| GitHub Android CI (`a20342e`) | Debug APK build and unit tests passed; CI artifact is not a published release |
| Whitespace validation | `git diff --check` passed |

The Playwright smoke used a test-only identity, mocked API responses, and no external device traffic. Expected fixture responses include one 401 (signed-out refresh) and one 403 (the deliberate delete-failure case); browser JavaScript raised no exceptions.

## Remaining risks and release gates

1. **Remote stream path remains unverified.** This work does not change APK capture, Cloudflare/alternate tunnel routing, TLS, or remote WebSocket ingress. A real remote frame and server/agent correlation IDs are required before claiming the original remote-stream incident is solved.
2. **VPN large batches can be slow.** Provider calls are sequential on one service session; stage requests and check peer reconciliation. A durable asynchronous bulk-operation resource should precede very large remote revocations.
3. **Repository lint debt remains visible.** The full production build completed with 99 ESLint warning lines across legacy files. The changed frontend files lint clean. Warnings include unused imports, `any`, and hook dependencies; they were not silently fixed as part of this focused Fleet pass.
4. **Next standalone trace warning remains.** Next 15.5.13 reports `ENOENT` while copying the dashboard segment's `page_client-reference-manifest.js` into `.next/standalone`. Build exits successfully and `/devices`, `/login`, `/stream`, and its CSS asset were served in a local runtime smoke after applying the same `.next/static`/`public` copies as the Dockerfile, but the warning needs a CI/container investigation before release.
5. **Tooling warnings remain.** `next lint` is deprecated for Next 16, the installed Browserslist database is stale, and API doc export surfaces an existing FastAPI `regex` deprecation in `game_accounts/router.py`.
6. **No rollout occurred.** Android CI produced a debug APK artifact only; no production APK release or second GitHub repository was published or changed, and no remote backend or emulator was modified in this audit pass.

## Related documentation

- [Fleet operations and observability](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md)
- [Web UI guide](../../web-ui-guide.md)
- [API endpoint catalog](../../api-endpoints.md)
- [Generated OpenAPI schema](../../openapi.json)
