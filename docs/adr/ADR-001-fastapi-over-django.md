# ADR-001 — Use FastAPI over Django for the Backend

**Status:** Accepted  
**Date:** 2024-01-15  
**Deciders:** Backend Team Lead, CTO  

---

## Context

Sphere Platform requires a Python backend that can:

1. Handle thousands of concurrent WebSocket connections (one per Android device)
2. Execute long-running background tasks (script execution, VPN management)
3. Provide a REST API consumed by a Next.js frontend
4. Integrate with PostgreSQL (async), Redis (async), and Celery
5. Be maintainable by a small team with strong Python skills

The team evaluated three mature Python web frameworks.

---

## Decision Drivers

- **Concurrency**: devices maintain persistent WebSocket connections → async I/O is mandatory
- **Developer experience**: clean code, fast iteration, type safety
- **Performance**: minimal latency under heavy connection load
- **Ecosystem**: good async ORM support (SQLAlchemy 2.0 async), Pydantic v2
- **OpenAPI**: auto-generated API docs and client types for the frontend

---

## Considered Options

### Option A — Django + Django Channels

Django is the most mature Python web framework with batteries included (ORM,
admin, auth, migrations). Django Channels adds async/WebSocket support.

**Pros:**
- Large ecosystem, extensive community
- Built-in admin panel
- Battle-tested auth system

**Cons:**
- Channels uses ASGI but the core Django ORM is synchronous — async queries
  require `sync_to_async()` wrappers everywhere
- Django admin not useful for our use case (custom React frontend)
- Heavier memory footprint
- More boilerplate for simple REST endpoints

### Option B — FastAPI + SQLAlchemy 2.0 async

FastAPI is a modern async-first Python framework built on Starlette + Pydantic.
SQLAlchemy 2.0 provides first-class `asyncio` support.

**Pros:**
- Native `async/await` throughout — no sync/async impedance mismatch
- Pydantic v2 for request/response validation with zero extra integration code
- Auto-generated OpenAPI docs (`/docs`, `/redoc`)
- WebSocket support built-in via Starlette
- FastAPI's dependency injection made auth, DB sessions, and RBAC clean
- ~5–10× less boilerplate than Django for a REST + WS API

**Cons:**
- No built-in admin panel
- No built-in migrations (use Alembic separately — which we need anyway for SQLAlchemy)
- Smaller ecosystem than Django

### Option C — aiohttp (raw async)

Pure async Python HTTP library, no framework opinions.

**Pros:**
- Maximum flexibility
- Very low overhead

**Cons:**
- No dependency injection, minimal structure
- Every cross-cutting concern (auth, validation, docs) must be implemented from scratch
- Team productivity would be significantly lower

---

## Decision

**Chosen: Option B — FastAPI + SQLAlchemy 2.0 async**

FastAPI's async-native design, Pydantic integration, and automatic OpenAPI
generation align directly with our requirements. The lack of a built-in admin
is not an issue since the frontend is a custom React app.

SQLAlchemy 2.0's asyncio support, combined with `asyncpg` driver, provides the
performance needed for device-heavy workloads.

Alembic for migrations and Celery for background tasks are standard additions
that integrate seamlessly.

---

## Consequences

### Positive

- All database queries run natively async (no `sync_to_async` overhead)
- Pydantic v2 schemas double as API docs and TypeScript type generation source
- Dependency injection (`Depends()`) keeps route handlers thin and testable
- WebSocket handler code is idiomatic and straightforward
- `httpx.AsyncClient` in tests provides a realistic async test client

### Negative / Trade-offs

- No auto-generated admin panel — requires custom UI for operational data views
- The team needed to learn Alembic's autogenerate quirks (enum handling, RLS directives)
- Celery is a separate process/service, adding operational complexity

---

## Links

- [FastAPI documentation](https://fastapi.tiangolo.com/)
- [SQLAlchemy 2.0 asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [backend/main.py](../../backend/main.py)
- [backend/core/config.py](../../backend/core/config.py)
