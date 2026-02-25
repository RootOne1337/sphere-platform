# ADR-003 — Use Redis Pub/Sub for WebSocket Fan-out

**Status:** Accepted  
**Date:** 2024-02-15  
**Deciders:** Backend Team Lead  

---

## Context

The backend manages WebSocket connections from:

1. **Android devices** — thousands of persistent device connections
2. **Frontend clients** — web UI sessions watching device status in real-time

When a device sends a status update, or when the backend broadcasts a command,
the message must reach all subscribed frontend clients regardless of which
backend instance handles their WebSocket connection.

As we scale beyond a single backend instance, we cannot use in-process shared
memory for connection management.

---

## Decision Drivers

- **Horizontal scalability**: multiple backend instances must share device state
- **Low latency**: device status changes must propagate to UI within 100ms
- **Backpressure safety**: slow consumers must not block fast producers
- **Existing infrastructure**: Redis is already deployed for session caching

---

## Considered Options

### Option A — In-process shared connection registry

All WebSocket connections managed in a single Python `dict` in the backend process.

**Pros:**
- Zero additional infrastructure
- Minimal latency (direct function call)

**Cons:**
- **Not scalable beyond a single process** — sticky sessions would be required
  in nginx, adding operational complexity and creating a SPOF
- OOM risk: thousands of active coroutines held in memory

### Option B — Redis Pub/Sub

Each backend instance subscribes to Redis channels for relevant events.
Incoming device messages are published to Redis; all backend instances
receive the message and forward it to their local subscribers.

Channel naming:
```
ws:device:{device_id}       — per-device updates (subscribed by device's UI watchers)
ws:org:{org_id}             — organization-wide broadcast
ws:broadcast                — platform-wide broadcast
```

**Pros:**
- Scales horizontally — any number of backend instances
- Well-understood pattern, low operational complexity
- Redis already deployed — no new infrastructure
- Sub-millisecond pub/sub latency in local network

**Cons:**
- Additional Redis round-trip adds ~1–2ms latency vs. in-process
- Redis becomes a message bus SPOF (mitigated by Redis Sentinel/Cluster in production)
- No message persistence — messages delivered at most once (acceptable for status updates)

### Option C — Kafka / RabbitMQ message broker

Dedicated message broker with persistence, consumer groups, and replay.

**Pros:**
- Message persistence and replay
- Better fan-out guarantees at very high scale
- Consumer group mechanics for competing consumers

**Cons:**
- Significant additional operational complexity (Kafka Zookeeper, or RabbitMQ cluster)
- Overkill for our use case — device status updates are ephemeral, no replay needed
- Increases deployment footprint and cost

### Option D — Server-Sent Events (SSE) for frontend only

Use WebSocket for devices, SSE for the frontend.

**Pros:**
- SSE is simpler for server→browser push
- HTTP/2 multiplexing

**Cons:**
- Still requires cross-instance fan-out for SSE — same problem remains
- Adds a second push protocol to maintain
- Browser SSE connections hit per-domain connection limits (6 per domain in HTTP/1.1)

---

## Decision

**Chosen: Option B — Redis Pub/Sub**

Redis is already available, the pattern is well understood, and sub-millisecond
latency is sufficient for device status propagation. The at-most-once delivery
guarantee is acceptable because:

- Device status events are idempotent (latest value wins)
- Heartbeat reconnection recovers from any individual missed event
- Frontend polls on reconnect, so no status is permanently lost

---

## Consequences

### Positive

- Backend scales horizontally behind a load balancer without sticky sessions
- Device connections can be load-balanced round-robin across instances
- WebSocket connection manager code is stateless w.r.t. other backend instances
- Redis channels are also used for Celery task result callbacks, sharing infra

### Negative / Trade-offs

- Redis is now a critical real-time dependency (not just caching)
- If Redis restarts, all in-flight WebSocket messages are lost (not persisted)
- The backend must handle Redis connection loss gracefully (reconnect with backoff)
- Channel namespace must be carefully managed to avoid cross-tenant data leakage
  (enforced by `ws:{org_id}:` prefix in channel names and verified in subscription logic)

### Backpressure

Slow frontend clients are detected via `asyncio.wait_for` timeouts on WebSocket
send operations. If a client cannot drain its send buffer within 5 seconds, the
connection is dropped with code 1008 (Policy Violation). This prevents slow
consumer backpressure from blocking the Redis subscriber coroutine.

---

## Links

- [backend/websocket/manager.py](../../backend/websocket/manager.py)
- [docs/architecture.md — WebSocket Architecture](../architecture.md#websocket-architecture)
- [TZ-03-WebSocket-Layer/SPLIT-2-Redis-PubSub.md](../../TZ-03-WebSocket-Layer/SPLIT-2-Redis-PubSub.md)
