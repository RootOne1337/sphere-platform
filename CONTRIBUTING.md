# Contributing to Sphere Platform

Thank you for your interest in contributing! This document explains how to set up
your environment, submit changes, and meet the standards required for merging.

---

## Table of Contents

1. [Code of Conduct](#code-of-conduct)
2. [Getting Started](#getting-started)
3. [Development Workflow](#development-workflow)
4. [Branch Strategy](#branch-strategy)
5. [Commit Convention](#commit-convention)
6. [Pull Request Process](#pull-request-process)
7. [Code Standards](#code-standards)
8. [Testing Requirements](#testing-requirements)
9. [Security Contributions](#security-contributions)
10. [Release Process](#release-process)

---

## Code of Conduct

This project adheres to the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md).
By participating, you agree to uphold a welcoming and respectful environment.

Unacceptable behavior should be reported to **conduct@yourdomain.com**.

---

## Getting Started

### Fork and clone

```bash
# 1. Fork the repo on GitHub
# 2. Clone your fork
git clone https://github.com/YOUR-USERNAME/sphere-platform.git
cd sphere-platform

# 3. Add upstream
git remote add upstream https://github.com/your-org/sphere-platform.git
```

### Local setup

```bash
# Create virtualenv
python -m venv .venv
source .venv/bin/activate   # or .venv\Scripts\Activate.ps1 on Windows

# Install backend deps
pip install -r backend/requirements.txt

# Install pre-commit hooks
pip install pre-commit
pre-commit install
pre-commit install --hook-type commit-msg

# Generate dev secrets
python scripts/generate_secrets.py

# Start services
docker compose -f docker-compose.yml -f docker-compose.full.yml -f docker-compose.override.yml up -d

# Run migrations
docker compose exec backend alembic upgrade head
```

> For full setup details, see [docs/development.md](docs/development.md).

---

## Development Workflow

```bash
# 1. Sync with upstream
git fetch upstream
git checkout develop
git merge upstream/develop

# 2. Create feature branch
git checkout -b feat/SPHERE-123-your-feature-name

# 3. Make changes with passing tests
# ... code ...
pytest tests/my-feature/ -v

# 4. Commit with conventional commit message
git commit -m "feat(devices): add bulk tag removal endpoint"

# 5. Push to your fork
git push origin feat/SPHERE-123-your-feature-name

# 6. Open Pull Request → target branch: develop
```

---

## Branch Strategy

| Branch | Purpose | Merge from | Merge to |
|--------|---------|-----------|----------|
| `main` | Production-stable releases | `develop` (via PR) | — |
| `develop` | Integration branch | feature/fix branches | `main` |
| `feat/SPHERE-XXX-*` | New features | `develop` | `develop` |
| `fix/SPHERE-XXX-*` | Bug fixes | `develop` | `develop` |
| `security/*` | Security patches | `develop` | `develop` |
| `chore/*` | Tooling, deps, CI | `develop` | `develop` |
| `docs/*` | Documentation-only | `develop` | `develop` |
| `release/vX.Y.Z` | Release preparation | `develop` | `main` + `develop` |

### Branch naming rules

```
feat/SPHERE-{ticket}-{kebab-description}
fix/SPHERE-{ticket}-{kebab-description}
security/{kebab-description}
chore/{kebab-description}
docs/{kebab-description}
```

---

## Commit Convention

All commits must follow [Conventional Commits v1.0](https://www.conventionalcommits.org/).

```
<type>(<scope>): <short description>

[optional body: what and why, not how]

[optional footer: SPHERE-XXX or BREAKING CHANGE: description]
```

### Types

| Type | Use for |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation updates |
| `chore` | Build scripts, CI, dependency updates |
| `refactor` | Code reorganization without behavior change |
| `test` | Adding or fixing tests |
| `perf` | Performance improvements |
| `security` | Security vulnerability patches |

### Scopes

`auth` · `devices` · `groups` · `scripts` · `vpn` · `ws` · `streaming` ·
`frontend` · `android` · `pc-agent` · `n8n` · `monitoring` · `infra` · `ci` · `deps`

### Examples

```
feat(vpn): add per-device kill-switch enable/disable API
fix(auth): prevent infinite refresh loop in useInitAuth hook
docs(api): document bulk actions endpoint
security(auth): rate-limit login to 10 req/min per IP
chore(deps): upgrade fastapi from 0.109 to 0.115
test(devices): add integration tests for bulk tag assignment
```

### Breaking changes

```
feat(api)!: rename device status enum values to lowercase

BREAKING CHANGE: StatusEnum values changed from ONLINE/OFFLINE to online/offline.
Clients must update their status comparisons.
```

---

## Pull Request Process

### Before opening a PR

- [ ] All tests pass: `pytest`
- [ ] Linting passes: `ruff check backend/`
- [ ] Type checking passes: `mypy backend/`
- [ ] No secrets committed: `detect-secrets scan --baseline .secrets.baseline`
- [ ] PR description filled in using the PR template
- [ ] Issue linked in the PR description (SPHERE-XXX)

### PR review requirements

| Merge target | Required approvals | Required checks |
|-------------|-------------------|-----------------|
| `develop` | 1 | CI backend, ruff, mypy |
| `main` | 2 (including 1 senior) | CI backend, CI Android, all linters |

### Process

1. Open PR against `develop` (not `main`)
2. Fill in the PR template completely
3. Request review from relevant CODEOWNERS (assigned automatically)
4. Address all review comments
5. Squash-merge after approval (default for feature branches)
6. Delete source branch after merge

### Review turnaround

- First response: within 1 business day
- Full review: within 2 business days
- Security PRs: expedited — same business day

---

## Code Standards

### Python

- **Formatter / linter:** `ruff` (configured in `pyproject.toml`)
- **Type checker:** `mypy --strict`
- **Max line length:** 100 characters
- **Imports:** sorted by `ruff` (isort-compatible)
- **Security linter:** `bandit`

```bash
# Format
ruff format backend/ tests/

# Lint
ruff check backend/ tests/ --fix

# Type check
mypy backend/ --strict
```

### TypeScript / React

- **Formatter:** Prettier (config in `frontend/.prettierrc`)
- **Linter:** ESLint with TypeScript strict rules
- **Target:** ES2022, strict mode enabled
- **Components:** function components + hooks only

```bash
cd frontend
npm run lint
npm run type-check
npx prettier --write .
```

### SQL / Migrations

- Always implement `downgrade()` in every migration
- Never modify existing migration files
- Use descriptive migration names: `add_device_vpn_ip_column`
- Test both `upgrade` and `downgrade` before committing

---

## Testing Requirements

### Coverage expectations

| Component | Minimum coverage |
|-----------|-----------------|
| `backend/core/` | 90% |
| `backend/api/v1/` | 80% |
| `backend/services/` | 75% |

### Test types

**Unit tests:** test a single function/class in isolation with mocked dependencies.
**Integration tests:** test full API endpoint with a real test database.
**Architecture tests:** verify module structure and import boundaries (see `tests/test_pc_agent_arch.py`).

### Writing tests

```python
# tests/my_feature/test_my_feature.py
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_my_endpoint(
    client: AsyncClient,         # from conftest.py
    auth_headers_admin: dict,    # from conftest.py
):
    response = await client.post(
        "/api/v1/my-feature",
        json={"name": "test"},
        headers=auth_headers_admin,
    )
    assert response.status_code == 201
    assert response.json()["name"] == "test"
```

### Test fixtures

Common fixtures available in `tests/conftest.py`:

| Fixture | Type | Description |
|---------|------|-------------|
| `client` | `AsyncClient` | HTTP test client with test DB |
| `db` | `AsyncSession` | Test database session |
| `auth_headers` | `dict` | Bearer token for `org_admin` user |
| `auth_headers_viewer` | `dict` | Bearer token for `viewer` user |
| `auth_headers_super` | `dict` | Bearer token for `super_admin` user |
| `test_device` | `Device` | Pre-created test device |
| `test_org` | `Organization` | Pre-created test organization |

---

## Security Contributions

**Do not open public GitHub Issues for security vulnerabilities.**

Report security issues via:
- Email: **security@yourdomain.com**
- See [SECURITY.md](SECURITY.md) for the full policy

Security patches follow an expedited review process:
- Initial response: within 24 hours
- Fix merged and released: within 7 days for critical severity

---

## Release Process

Releases are managed by the core maintainers.

### Version scheme

The project uses [Semantic Versioning](https://semver.org/):
- `MAJOR.MINOR.PATCH` — e.g., `4.1.0`
- `MAJOR`: breaking API changes
- `MINOR`: backward-compatible new features
- `PATCH`: backward-compatible bug fixes

### Release checklist

1. `git checkout develop && git pull`
2. Update `VERSION` file: `echo "4.1.0" > VERSION`
3. Update `CHANGELOG.md` — move `[Unreleased]` section to `[4.1.0] - 2026-MM-DD`
4. Create release branch: `git checkout -b release/v4.1.0`
5. Run full test suite: `pytest && cd frontend && npm test`
6. Create PR: `release/v4.1.0` → `main`
7. After merge to `main`: tag `git tag -a v4.1.0 -m "Release v4.1.0"`
8. Also merge back into `develop`: `git merge main`
9. Push tag: `git push origin v4.1.0`
10. GitHub Actions creates Docker images and GitHub Release automatically
