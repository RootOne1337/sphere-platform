# Developer Guide

> **Sphere Platform v4.0** — Local Development Setup & Coding Standards

---

## Table of Contents

1. [Local Setup](#1-local-setup)
2. [Project Structure in Depth](#2-project-structure-in-depth)
3. [Backend Development](#3-backend-development)
4. [Frontend Development](#4-frontend-development)
5. [Testing](#5-testing)
6. [Code Quality](#6-code-quality)
7. [Migrations](#7-migrations)
8. [Conventional Commits](#8-conventional-commits)
9. [Branch Strategy](#9-branch-strategy)
10. [Pre-commit Hooks](#10-pre-commit-hooks)
11. [Debugging Tips](#11-debugging-tips)

---

## 1. Local Setup

### Clone and configure

```bash
git clone https://github.com/your-org/sphere-platform.git
cd sphere-platform

# Create Python virtualenv (for scripts, tests, local tools)
python -m venv .venv
source .venv/bin/activate            # Linux/macOS
.venv\Scripts\Activate.ps1           # Windows PowerShell

pip install -r backend/requirements.txt
pip install -r requirements-dev.txt  # if exists

# Generate secrets
python scripts/generate_secrets.py
```

### Start the stack

```bash
# Windows (PowerShell)
$compose = "C:\Program Files\Docker\Docker\resources\cli-plugins\docker-compose.exe"
& $compose -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.override.yml up -d --build

# Linux/macOS
docker compose -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.override.yml up -d --build
```

### Run migrations and bootstrap

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/create_admin.py
```

### Verify

```bash
curl http://localhost/api/v1/health
# {"status":"ok","checks":{"database":{"status":"ok"},"redis":{"status":"ok"}}}
```

---

## 2. Project Structure in Depth

### Backend modules

```
backend/
├── api/
│   └── v1/                  # API version 1 routers
│       ├── auth/
│       │   ├── router.py    # Route definitions
│       │   └── service.py   # Business logic
│       ├── devices/
│       │   ├── router.py
│       │   └── service.py
│       └── ...
├── core/
│   ├── config.py            # pydantic-settings Settings class
│   ├── constants.py         # App-wide constants
│   ├── cors.py              # CORS middleware config
│   ├── dependencies.py      # FastAPI Depends() — auth, DB session, etc.
│   ├── exceptions.py        # Custom exception classes
│   ├── rbac.py              # Role enum + PERMISSIONS matrix
│   └── security.py          # JWT encode/decode, bcrypt helpers
├── database/
│   ├── engine.py            # AsyncEngine factory
│   └── redis_client.py      # Redis connection pool
├── middleware/
│   ├── audit.py             # Auto-audit-log middleware
│   ├── logging_context.py   # Request context for structlog
│   ├── metrics.py           # Prometheus request metrics
│   ├── request_id.py        # X-Request-ID injection
│   └── tenant_middleware.py # Sets app.current_org_id in PG session
├── models/                  # SQLAlchemy ORM models (one file per table)
├── schemas/                 # Pydantic v2 request/response schemas
├── services/                # Business logic (called from routers)
├── tasks/                   # Celery async task functions
├── websocket/
│   ├── connection_manager.py
│   └── pubsub_router.py
└── main.py                  # FastAPI app factory + lifespan
```

### Adding a new API endpoint

1. Create `backend/api/v1/<feature>/router.py`:

```python
from fastapi import APIRouter, Depends
from backend.core.dependencies import require_permission, get_db
from backend.models.mymodel import MyModel
from backend.schemas.mymodel import MyModelCreate, MyModelResponse
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/my-feature", tags=["my-feature"])

@router.get("/", response_model=list[MyModelResponse])
async def list_items(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(require_permission("myfeature:read")),
):
    # query only current org's data — RLS enforces, but filter explicitly too
    result = await db.execute(
        select(MyModel).where(MyModel.org_id == current_user.org_id)
    )
    return result.scalars().all()
```

2. Register in `backend/main.py`:

```python
from backend.api.v1.my_feature.router import router as myfeature_router
app.include_router(myfeature_router, prefix="/api/v1")
```

3. Add permission to `backend/core/rbac.py`.

4. Write tests in `tests/my_feature/`.

---

## 3. Backend Development

### Running locally (outside Docker)

```bash
cd backend
uvicorn main:app --reload --port 8000
```

Requires a running PostgreSQL and Redis. Point `POSTGRES_URL` and `REDIS_URL` at
localhost (exposed in dev docker-compose).

### Environment for local run

```bash
export POSTGRES_URL="postgresql+asyncpg://sphere:password@localhost:5432/sphereplatform"
export REDIS_URL="redis://:password@localhost:6379/0"
export JWT_SECRET_KEY="dev-secret-key-min-64-chars-xxxxxxxxxxxxxxxxxxxxxxxxxx"
```

### Common patterns

**Paginated list response:**
```python
from backend.schemas.pagination import PaginationResponse

@router.get("/", response_model=PaginationResponse[DeviceResponse])
async def list_devices(page: int = 1, per_page: int = 50, ...):
    offset = (page - 1) * per_page
    total = await db.scalar(select(func.count()).select_from(Device)...)
    items = (await db.execute(
        select(Device).offset(offset).limit(per_page)...
    )).scalars().all()
    return PaginationResponse(items=items, total=total, page=page, per_page=per_page)
```

**Async service call:**
```python
class DeviceService:
    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    async def get_status(self, device_id: UUID) -> DeviceStatus:
        cached = await self.redis.get(f"device:status:{device_id}")
        if cached:
            return DeviceStatus.model_validate_json(cached)
        # fallback to DB...
```

---

## 4. Frontend Development

### Running locally

```bash
cd frontend
npm install
cp .env.example .env.local    # set NEXT_PUBLIC_API_URL=http://localhost/api/v1
npm run dev                   # starts on :3000 with hot reload
```

### Adding a new page

1. Create `frontend/app/(dashboard)/my-page/page.tsx`
2. Add nav item in `frontend/app/(dashboard)/layout.tsx`
3. Create data hook in `frontend/hooks/useMyFeature.ts`:

```typescript
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";

export function useMyFeature() {
  return useQuery({
    queryKey: ["my-feature"],
    queryFn: async () => {
      const { data } = await api.get("/my-feature");
      return data;
    },
  });
}
```

### Auth-protected API calls

Use the `api` axios instance from `frontend/lib/api.ts` — it automatically
attaches the access token and handles 401 refresh.

```typescript
import api from "@/lib/api";

const { data } = await api.get("/devices?page=1&per_page=50");
```

### TypeScript types

Generate types from the OpenAPI spec:
```bash
npm run gen:types
# Reads from http://localhost/api/v1/openapi.json
# Writes to src/api/types.ts
```

---

## 5. Testing

### Backend tests

```bash
cd sphere-platform

# Run all tests
pytest

# Run specific module
pytest tests/auth/ -v

# Run with coverage
pytest --cov=backend --cov-report=html

# Run fast (skip slow integration tests)
pytest -m "not slow"
```

### Test structure

```
tests/
├── conftest.py            # Shared fixtures (test DB, HTTP client, auth tokens)
├── auth/
│   ├── test_login.py
│   ├── test_refresh.py
│   └── test_mfa.py
├── devices/
│   ├── test_crud.py
│   └── test_bulk.py
├── vpn/
│   └── test_vpn_api.py
└── test_ws/
    └── test_connection_manager.py
```

### Writing a test

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_create_device(client: AsyncClient, auth_headers: dict):
    response = await client.post(
        "/api/v1/devices",
        json={"name": "Test Device", "serial": "test-001"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Test Device"
    assert data["serial"] == "test-001"
```

### Frontend tests

```bash
cd frontend
npm test          # Jest
npm run type-check  # TypeScript strict check
npm run lint        # ESLint
```

---

## 6. Code Quality

### Linting and formatting

```bash
# Python
ruff check backend/ tests/          # lint
ruff format backend/ tests/         # format
mypy backend/ --strict              # type check
bandit -r backend/                  # security lint

# TypeScript
cd frontend && npm run lint
```

### Style guide

**Python:**
- Ruff rules: `E`, `F`, `I`, `N`, `S` (bandit rules via ruff extension)
- Max line length: 100 characters
- All public functions must have type annotations
- Use `async def` for all I/O operations — no blocking calls in async context

**TypeScript:**
- Strict mode: `"strict": true` in tsconfig
- Prefer `const` over `let`, avoid `var`
- React components: function components only (no class components)
- Hooks: prefix with `use`, one hook per feature

### Pre-commit (auto-run on git commit)

```bash
pre-commit install    # install hooks
pre-commit run --all-files  # run manually
```

Hooks configured in `.pre-commit-config.yaml`:
- `ruff` — Python linting + formatting
- `mypy` — type checking
- `detect-secrets` — secret scanning
- `commitlint` — commit message format
- `prettier` — TypeScript/JSON formatting

---

## 7. Migrations

### Create a new migration

```bash
# Auto-generate from model changes
docker compose exec backend alembic revision --autogenerate -m "add_device_model_field"

# Or create empty migration for manual SQL
docker compose exec backend alembic revision -m "alter_table_x"
```

### Migration file template

```python
# alembic/versions/XXXX_description.py
"""Add field to devices

Revision ID: xxxx
Revises: yyyy
"""
from alembic import op
import sqlalchemy as sa

def upgrade() -> None:
    op.add_column("devices", sa.Column("new_field", sa.String(100), nullable=True))

def downgrade() -> None:
    op.drop_column("devices", "new_field")
```

### Rules for migrations

- **Always** implement `downgrade()`
- **Never** delete columns in the same migration that removes their usage from code
  (two-phase deploy required)
- **Test** both `upgrade` and `downgrade` on a dev database before committing
- **Never** modify existing migration files — always create a new one

---

## 8. Conventional Commits

All commits must follow [Conventional Commits v1.0](https://www.conventionalcommits.org/).

```
<type>(<scope>): <short description>

[optional body]

[optional footer: issue references]
```

**Types:**

| Type | Description |
|------|-------------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `chore` | Build, tooling, CI, deps |
| `refactor` | Code restructure (no behavior change) |
| `test` | Add or fix tests |
| `perf` | Performance improvement |
| `security` | Security fix |

**Scopes:** `auth`, `devices`, `vpn`, `scripts`, `ws`, `frontend`, `android`, `pc-agent`, `infra`, `ci`

**Examples:**
```
feat(devices): add bulk tag assignment endpoint
fix(vpn): use require_permission instead of require_role on /peers
docs(api): add bulk actions reference to API docs
chore(ci): add pip-audit to security scan workflow
security(auth): rate-limit /auth/login to 10 req/min per IP
```

---

## 9. Branch Strategy

```
main           ─── stable production releases (tags: v4.0.0)
  └── develop  ─── integration branch (all features merged here)
        └── feat/SPHERE-123-short-description   ← feature
        └── fix/SPHERE-456-short-description    ← bug fix
        └── chore/update-deps                   ← chores
        └── security/patch-jwt-vuln             ← security fixes
```

### Naming rules

```
feat/SPHERE-<id>-<kebab-case-description>
fix/SPHERE-<id>-<kebab-case-description>
chore/<kebab-case-description>
security/<kebab-case-description>
docs/<kebab-case-description>
release/v<major>.<minor>.<patch>
```

### PR rules

- **Target:** always `develop` (never `main` directly)
- **Squash merge:** preferred for feat/fix branches
- **Merge commit:** used for release branches into main
- **Required reviews:** 1 (staging), 2 (production releases)
- **Required checks:** CI backend, CI Android, lint, type-check

---

## 10. Pre-commit Hooks

```bash
# Install
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg  # for commitlint
```

On every `git commit`, hooks run automatically:
1. `ruff` — lint + format Python
2. `mypy` — type check changed Python files
3. `detect-secrets` — scan for leaked secrets
4. `commitlint` — validate commit message format
5. `prettier` — format TypeScript/JSON/CSS
6. `eslint` — lint TypeScript

To bypass in emergencies (document why in PR):
```bash
git commit --no-verify -m "emergency: hotfix XYZ"
```

---

## 11. Debugging Tips

### Inspect running backend

```bash
# Enter the backend container
docker compose exec backend bash

# Check Python environment
python -c "from backend.core.config import settings; print(settings.ENVIRONMENT)"

# Test DB connection
python -c "
import asyncio
from backend.database.engine import get_engine
from sqlalchemy import text
async def test():
    async with get_engine().connect() as conn:
        result = await conn.execute(text('SELECT 1'))
        print('DB OK:', result.scalar())
asyncio.run(test())
"
```

### Inspect WebSocket connections

```bash
# List active WS connections in Redis
docker compose exec redis redis-cli PUBSUB CHANNELS "device:*"

# Check pending messages
docker compose exec redis redis-cli LLEN celery
```

### Watch real-time logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f backend | grep -E "ERROR|WARNING|device"

# With timestamps
docker compose logs -f --timestamps backend
```

### Reset to clean state (dev only)

```bash
# Destroy all volumes and start fresh
docker compose down -v
docker compose -f docker-compose.yml -f docker-compose.full.yml up -d --build
docker compose exec backend alembic upgrade head
docker compose exec backend python scripts/create_admin.py
```
