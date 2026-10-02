# VPN control: targets, receipts and recovery

Updated: 2026-10-03. Scope: the existing `/vpn` page and REST control contracts.
This work does not introduce a VPN provider, install Amnezia, or change the
Android connection/tunnel configuration. The Android + server architecture stays
the same; no Windows agent or host ADB is required by these controls.

## What a result actually proves

| Operation / result | Evidence | What it does not prove |
| --- | --- | --- |
| Assign: valid response | A router peer assignment was returned for the selected device | The APK installed this configuration or completed a handshake |
| Rotate: `configured` | Provider revoke and replacement assignment returned successfully | Android applied the new configuration or regained network access |
| Rotate: `rejected` | No assigned peer was found; the route did not call revoke/assign | That a different request has not changed the device |
| Rotate: `unknown` | A provider/lifecycle call did not return a confirmed result | Absence of side effects; do not blindly repeat |
| Kill switch: `submitted` | A compatible sender accepted the envelope | Android received, applied or completed the command |
| Kill switch: `not_sent` | The compatible sender explicitly returned false | General Android connectivity or the outcome of older requests |
| Kill switch: `unsupported` | No compatible legacy kill switch sender is wired | A working kill switch on the device |
| Kill switch: `unknown` | The sender raised while handling that target | That the target was unaffected |
| Reboot: `acknowledged` | The existing bulk route accepted an agent progress/completion receipt | A successful new boot and reconnect; inspect the next heartbeat |

The VPN rotate and kill switch responses contain `execution_confirmed: false`.
This field is intentionally fixed to false. It is not a placeholder for an
invented Android acknowledgement. `success` remains a compatibility counter:
router configuration for rotation, sender acceptance for kill switch.

## Explicit selection and permission boundary

- Rotate and kill switch accept 1–500 unique UUID device IDs.
- Empty lists, duplicates and unknown request fields are rejected with 422.
- Kill switch requires an explicit `action: enable|disable`; there is no implicit
  enable default. `method` accepts `vpnservice|iptables` only.
- Legacy `{enabled: false}` is rejected instead of silently becoming enable.
  The existing frontend hook translates its boolean to the correct action.
- The entire selection must contain active devices owned by the caller's
  organization before any provider/command call. A foreign, missing or inactive
  target produces a generic 404 for the whole request; no earlier targets run.
- `vpn:mass_operation` is required for rotation/kill switch. Assignment requires
  `vpn:write`. Reboot continues to use `device:write` and the existing Android
  live command channel.
- Frontend mutation controls are gated by these roles; VPN cache keys include
  actor, organization, role and session generation.

This replaces the old empty-list rotation of every assigned peer. Integrations
must list their intended targets explicitly. These request validation changes
are deliberate compatibility changes, documented in the generated OpenAPI.

The router initializes the encryption cipher/provider lifecycle lazily, after
request validation and route ownership preflight. Missing provider credentials
must not turn an invalid empty rotation request into a misleading provider 503.
This ordering was found during installed API acceptance (N06), not inferred
from the mock-provider regression suite.

## Why kill switch currently reports unsupported

The route's `EventPublisher` is still a no-op. The Android dispatcher supports
`VPN_CONNECT`, `VPN_DISCONNECT`, and `VPN_RECONNECT`; this route sends a separate
legacy `vpn_killswitch` envelope. Replacing the no-op with a generic pub/sub
publisher would not establish protocol compatibility or execution receipts.

`KillSwitchService.supported` therefore requires an explicit
`supports_killswitch = True` capability from a compatible publisher. The installed
no-op publisher has that capability set to false. Owned requests receive one
`unsupported` outcome per target, and no envelope is sent. There is no claim
that this control is production ready. Actual Android VPN integration remains
separate work, consistent with the user's instruction to defer it.

## Rotation is a two-stage provider operation

1. Verify owned active targets.
2. Read an assigned peer for each target; do not turn a missing peer into an
   implicit assignment.
3. Revoke through the existing durable lifecycle service.
4. Assign a replacement through that service.
5. Return one result for every explicit target.

On an exception, the route retains the observed `old_ip` and reports whether
revoke returned successfully (`revoke_confirmed`). That boolean is not proof
that the failed subsequent assignment had no side effects. Existing
`PROVISIONING`/`REVOKING` durable reservations still require reconciliation;
private provider errors are not echoed to the web.

Targets run sequentially, and an unknown result does not silently replay.
Another target may still complete. This is not an atomic cross-device operation,
nor an exactly-once rotation API. The preflight snapshot is not a per-peer
revision fence; concurrent admin requests remain subject to the existing
durable lifecycle checks.

## Web confirmation and recovery

The main VPN page opens a confirmation with the full device list and the effect
on connectivity, streams and tasks. It re-reads the catalog before dispatch,
guards against duplicate clicks, prevents closing a pending operation, and
ignores late callbacks after a session change/unmount.

Receipt parsing checks exact device membership, uniqueness, counters, action,
and the stage/outcome fields. A malformed or incomplete successful HTTP response
is treated as unknown, not success. Results remain visible in the dialog and on
the page after closing it. Assignment also retains its receipt and does not
equate a router assignment with Android configuration delivery.

Only explicit `not_sent` kill switch targets can be prepared for a retry, with
a new impact confirmation and catalog reload. Submitted, unsupported, unknown
and router rotation outcomes are not included in that retry selection. There is
no automatic mutation retry. Authentication/ownership/schema rejections are
distinguished from network/server failures whose effects cannot be established.

Unknown targets are blocked from new controls for the lifetime of this mounted
page and actor scope. This is **not** a durable operation journal: a full reload
or a separate browser does not retain this client guard. Reconcile the persisted
peer/device state before beginning a new operation elsewhere. The current page
does not offer a button claiming that a heartbeat proves a VPN transition.

## Acceptance boundaries

Regression tests use disposable PostgreSQL/Redis, synthetic tenants, fake
provider replies and a sender explicitly marked compatible for protocol tests.
They never switch networking, rotate VPNs or reboot the connected fleet.
These tests prove request/response behavior and recovery controls; they do not
prove a live Android kill switch or VPN migration.

The legacy `_tabs` components are not mounted by the main VPN page and are not
accepted as the new workflow. The original F32 finding remains partial until
the complete browser/keyboard/mobile acceptance and the remaining lifecycle
work are reviewed. See [remediation ledger](../audits/2026-10-01/WEB-AUDIT-REMEDIATION.md),
[current state](CURRENT-STATE.md), [readiness](READINESS.md), and
[API reference](../api-reference.md).
