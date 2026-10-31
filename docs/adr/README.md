# Architecture Decision Records

This directory contains Architecture Decision Records (ADRs) for Sphere Platform.

An ADR documents an architecturally significant decision: the context that led to it,
the options considered, the decision made, and the consequences.
The dates and status labels below are metadata from the records, not independent
proof of a current deployment, measured capacity, the recorded date/deciders,
or a revalidated decision. The records preserve historical reasoning and planned
designs; annotations link to present source and operational contracts where the
implementation differs. Check those sources before relying on an old ADR.

## Index

| # | Title | Status | Date |
|---|-------|--------|------|
| [ADR-001](ADR-001-fastapi-over-django.md) | Use FastAPI over Django for the backend | Accepted | 2024-01-15 |
| [ADR-002](ADR-002-amneziawg-vpn.md) | Use AmneziaWG for device VPN tunnels | Accepted | 2024-02-01 |
| [ADR-003](ADR-003-redis-pubsub-websocket.md) | Use Redis Pub/Sub for WebSocket fan-out | Accepted | 2024-02-15 |
| [ADR-004](ADR-004-dag-script-engine.md) | DAG-based automation script engine | Accepted | 2024-03-10 |
| [ADR-005](ADR-005-hilt-android-di.md) | Use Hilt for Android agent dependency injection | Accepted | 2024-03-20 |

## ADR Status Values

| Status | Meaning |
|--------|---------|
| **Proposed** | Under discussion, not yet decided |
| **Accepted** | Decision recorded as accepted at that time; implementation and present applicability need independent verification |
| **Deprecated** | No longer recommended; no replacement is necessarily identified |
| **Superseded by ADR-NNN** | Replaced by the specified newer decision |

## ADR Template

```markdown
# ADR-NNN — <Short Title>

**Status:** Proposed | Accepted | Deprecated  
**Date:** YYYY-MM-DD  
**Deciders:** [list of people involved]

## Context

What situation or problem led to this decision?

## Decision Drivers

- Requirement 1
- Requirement 2

## Considered Options

1. Option A
2. Option B
3. Option C

## Decision

Chosen option: **Option X**, because [reasoning].

## Consequences

### Positive
- ...

### Negative / Trade-offs
- ...

## Links

- [Related ADR](ADR-NNN.md)
```
