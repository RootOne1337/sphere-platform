# Runbook 02 — VPN incidents and address-pool exhaustion

Reviewed: 2026-09-10. Scope: the VPN implementation in this repository. This is an
operating guide for the current incomplete subsystem, not a deployment sign-off.
The [audit report](../audits/2026-09-05/AUDIT-REPORT.md) records verified defects,
fixes and remaining blockers.

For shared incident fields and Compose selection, see [the runbook index](README.md).

## Current architecture

`VPNPoolService` calls the configured `WG_ROUTER_URL` over HTTP to provision or
remove peers. The backend container is not documented by this implementation as
the host of a `wg0` interface. Inspect interfaces on the actual configured router
using that router's operating procedure.

PostgreSQL `vpn_peers` stores device/organization ownership, address, public key,
encrypted private key/PSK, obfuscation parameters and handshake metadata. Client
configuration is generated in memory. This backend does not write
`/etc/wireguard/peers/<device_id>.conf` files.

PostgreSQL now owns held IPs, including PROVISIONING and REVOKING intents, with a
global unique index. `VPN_POOL_SUBNET` defaults to `10.100.0.0/16`; allocation is
bounded to IPv4 /16 or smaller. The legacy Redis sorted sets `vpn:ip_pool:<org_id>`
are no longer consulted for assignment/release. Their contents are diagnostic
history, not evidence that an address is free. Pool stats use SQL and report
global capacity/free addresses and the caller organization's held addresses.

## Read-only diagnosis

Use the deployment's authenticated ingress, not a presumed public backend port.
`BASE_URL` below is the deployment origin and `TOKEN` belongs to an authorized
operator; keep their actual values out of incident attachments.

```bash
curl --fail-with-body -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/v1/vpn/peers"
curl --fail-with-body -H "Authorization: Bearer $TOKEN" \
  "$BASE_URL/api/v1/vpn/pool/stats"
```

The routes are `/pool/stats` and `/peers`; the previous `/pool-stats` and
`/peers/<device_id>/ip-lease` examples were not implemented endpoints. Assignment
exhaustion currently raises HTTP 503 with `VPN pool exhausted`.

`GET /api/v1/vpn/health` currently returns a static success response. It does not
verify a handshake, router availability or usable connectivity. Compare peer
metadata with the router's actual peer inventory, recent handshakes and a
permitted reachability check from the affected device. Keep the scope restricted
to infrastructure you operate.

Read recent backend logs using the deployment's Compose file selection. Match
peer/device IDs and router response status; avoid collecting generated client
configuration or decrypted keys. On the router, use its own logs and monitoring.
Alert names or dashboard values are not assumed to be implemented by this guide.

With the deployment's Redis authentication configured, inspect the actual set:

```text
ZCARD vpn:ip_pool:<org_id>
ZRANGE vpn:ip_pool:<org_id> 0 20
```

An authorized PostgreSQL operator can diagnose conflicting non-free addresses:

```sql
SELECT tunnel_ip, count(*) AS peer_count
FROM vpn_peers
WHERE tunnel_ip IS NOT NULL AND upper(status::text) <> 'FREE'
GROUP BY tunnel_ip
HAVING count(*) > 1;
```

This query does not modify peers and cannot prove that the provider has no
orphaned peers absent from PostgreSQL. Reconcile both inventories.

## Recovery decisions

For an individual device, verify organization ownership, server endpoint/public
key, matching PSK, matching server/client AWG parameters and actual router state.
A repeated successful assignment now returns the original PSK/configuration;
it is not evidence that the tunnel has established a handshake.

The implemented removal route is `DELETE /api/v1/vpn/revoke/<device_id>`, restricted
to the authorized organization administrator. Removal deliberately disrupts that
device's tunnel; use it only for a confirmed target under the incident's approved
scope. Timeout, 403, 404, 500 and unconfirmed 202 preserve the peer
and address. Only 200/204 are currently accepted as deletion confirmation. A
generic 404 can indicate an incorrect proxy/route and is not authoritative proof
of peer absence. A failed response must not be followed by manually returning the
address to Redis. REVOKING now persists before DELETE and releases SQL ownership
only after deletion confirmation and commit. PROVISIONING persists before POST;
unknown results retain their address. Retry of either pending state returns 409
and does not issue another provider mutation. There is no automatic reconciler.
Public keys are percent-encoded as one URL path component; the actual provider
must support this route contract. Reconcile provider routing before treating any
404 as an already-removed peer.

For pool exhaustion or duplicate addresses, preserve PostgreSQL, Redis and router
inventory for reconciliation. Stop new allocations through the deployment's
controlled maintenance procedure while resolving ownership. Do not delete/refill
the free lists, reclaim an address solely because a device is offline, or expand
CIDR and restart as an automatic repair. The former Redis allocator could reissue
active addresses; the SQL allocator ignores these lists. The old `VPN_IP_POOL_SIZE` and
`VPN_IP_POOL_CIDR` settings described by this runbook do not exist; changing the
real `VPN_POOL_SUBNET` needs a coordinated router/routing and allocation migration.

Kill-switch delivery, reconnection and the provider adapter remain under audit.
Do not assume that a successful API response proves an on-device firewall rule,
that backend has a particular iptables chain, or that reboot clears it. Use the
actual installed agent/router recovery procedure and an already available
management path; verify effective device rules and permissions first.

## After the incident

Record the affected organization/device/peer IDs, time window, observed provider
responses, actual handshake/reachability results and the actions taken. Confirm
that no address was reassigned before its former peer was removed. Preserve
unknown outcomes for reconciliation rather than labelling them successful.

Health polling now authenticates to the router and rejects failed or malformed
snapshots without changing the last known peer state. A missing/zero handshake
marks the peer inactive but does not recreate it: the handshake endpoint is not
an authoritative peer inventory. Reconcile actual router configuration before
any provisioning repair. The reconnect configuration preserves the stored PSK;
the current command publisher is still a stub, so this does not prove delivery.
Background observations commit per organization. Writes skip peers revoked during
the poll and do not replace newer handshake timestamps with delayed observations.

Apply migration `20260906_vpn_intents` only after stopping legacy allocation writers
and reconciling PostgreSQL/router inventory. It refuses conflicting held IPs,
invalid addresses and network prefixes without choosing a winner or deleting rows.
Do not run old writers during rollout; their provider POST still precedes SQL.
Downgrade refuses to discard pending PROVISIONING/REVOKING intents.

Open audit work includes lost-response reconciliation and orphan router peers,
the provider adapter, reserved router addresses, AWG settings, split routes and kill-switch runtime.
The current tests use local PostgreSQL and mocked router transport; they do not
certify a deployed tunnel or physical Android behavior.
The [durable lease design](../audits/2026-09-05/VPN-LEASE-DESIGN.md) records the implemented
transaction boundaries, migration preflight and incomplete recovery contract.
