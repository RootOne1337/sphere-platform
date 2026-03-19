# Configuration Reference

> **Sphere Platform v4.7** — All environment variables

---

All configuration is loaded from `.env.local` at startup via `pydantic-settings`.
Copy `.env.example` as a starting point and fill in your values.

```bash
cp .env.example .env.local
python scripts/generate_secrets.py   # auto-fills all secret fields
```

> **Security:** Never commit `.env.local` or `.env` to version control.
> Use `detect-secrets` baseline and pre-commit hooks to prevent accidental leaks.

---

## Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `POSTGRES_USER` | ✓ | `sphere` | PostgreSQL username |
| `POSTGRES_PASSWORD` | ✓ | — | PostgreSQL password (32+ chars) |
| `POSTGRES_URL` | ✓ | — | Full asyncpg connection URL |
| `DB_POOL_SIZE` | | `20` | SQLAlchemy connection pool size |
| `DB_MAX_OVERFLOW` | | `10` | Max overflow connections above pool_size |
| `DB_POOL_TIMEOUT` | | `30` | Seconds to wait for a connection from pool |

**Example:**
```bash
POSTGRES_USER=sphere
POSTGRES_PASSWORD=super_secure_password_here
POSTGRES_URL=postgresql+asyncpg://sphere:super_secure_password_here@postgres:5432/sphereplatform
```

---

## Redis

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_PASSWORD` | ✓ | — | Redis AUTH password (32+ chars) |
| `REDIS_URL` | ✓ | — | Redis connection URL with password |

**Example:**
```bash
REDIS_PASSWORD=another_secure_password_32chars
REDIS_URL=redis://:another_secure_password_32chars@redis:6379/0
```

---

## Authentication / JWT

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET_KEY` | ✓ | — | HMAC-SHA256 signing secret (64+ chars) |
| `JWT_ALGORITHM` | | `HS256` | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | | `30` | Access token TTL in minutes |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | | `7` | Refresh token TTL in days |

**Generate a strong key:**
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## VPN / AmneziaWG

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `WG_ROUTER_URL` | ✓ | — | WireGuard router service URL |
| `WG_ROUTER_API_KEY` | ✓ | — | API key for WG router |
| `WG_SERVER_PUBLIC_KEY` | ✓ | — | Server WireGuard public key (base64) |
| `WG_SERVER_ENDPOINT` | ✓ | `vpn.example.com:51820` | Server endpoint for clients |
| `WG_PSK_ENABLED` | | `true` | Enable pre-shared keys per peer |
| `VPN_KEY_ENCRYPTION_KEY` | ✓ | — | Fernet key for peer config encryption |
| `VPN_POOL_SUBNET` | | `10.100.0.0/16` | CIDR block for peer IP allocation |
| `VPN_SERVER_HOSTNAME` | | — | Hostname used in VPN QR code generation |

**AmneziaWG obfuscation parameters (change only if you have active tunnels):**

| Variable | Default | Description |
|----------|---------|-------------|
| `AWG_JC` | `4` | Junk packet count |
| `AWG_JMIN` | `40` | Junk packet min size |
| `AWG_JMAX` | `70` | Junk packet max size |
| `AWG_S1` | `51` | Init packet junk size |
| `AWG_S2` | `45` | Response packet junk size |
| `AWG_H1` | `2545529037` | Magic header 1 |
| `AWG_H2` | `1767770215` | Magic header 2 |
| `AWG_H3` | `2031675751` | Magic header 3 |
| `AWG_H4` | `3699611814` | Magic header 4 |

**Generate Fernet key:**
```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

---

## Application

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DEBUG` | | `false` | Enable debug mode (NEVER true in production) |
| `LOG_LEVEL` | | `INFO` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ENVIRONMENT` | | `development` | `development`, `staging`, `production` |
| `SERVER_HOSTNAME` | | — | Public hostname (used in CORS and redirects) |
| `DEV_SKIP_AUTH` | | `""` (отключено) | `true` для отключения JWT-проверки в dev-режиме (**NEVER** в production) |

---

## n8n Integration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `N8N_ENCRYPTION_KEY` | ✓ | — | n8n credential encryption key (32+ chars) |

---

## MinIO (S3-compatible storage)

Used for storing screenshots and script output artifacts.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `MINIO_ROOT_USER` | | `spheredev` | MinIO admin username |
| `MINIO_ROOT_PASSWORD` | ✓ | — | MinIO admin password (16+ chars) |

---

## Android Agent OTA

| Variable | Required | Description |
|----------|----------|-------------|
| `APK_SIGNING_CERT_SHA256` | ✓ for OTA | SHA-256 hex fingerprint of APK signing certificate |

**Get certificate fingerprint:**
```bash
keytool -printcert -file app.cer | grep "SHA256:"
# Or from keystore:
keytool -list -v -keystore mykeystore.jks | grep "SHA256:"
```

---

## Frontend (Next.js)

These are set in `frontend/.env.local`:

| Variable | Description |
|----------|-------------|
| `NEXT_PUBLIC_API_URL` | Backend API base URL (e.g. `http://localhost/api/v1`) |
| `NEXT_PUBLIC_WS_URL` | WebSocket base URL (e.g. `ws://localhost/ws`) |

---

## Docker Compose Variables

Consumed directly by `docker-compose.yml`:

| Variable | Description |
|----------|-------------|
| `POSTGRES_USER` | PostgreSQL user for container init |
| `POSTGRES_PASSWORD` | PostgreSQL password for container init |
| `REDIS_PASSWORD` | Redis AUTH password for container command |

---

## Orchestration & Event System (v4.7)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ORCHESTRATION_LOOP_INTERVAL` | | `10` | Seconds between orchestration loop ticks |
| `TASK_HEARTBEAT_TIMEOUT` | | `120` | Seconds before a task is considered stale |
| `TASK_HEARTBEAT_CHECK_INTERVAL` | | `30` | Watchdog check interval in seconds |
| `EVENT_REACTOR_ENABLED` | | `true` | Enable/disable the event reactor |
| `EVENT_REACTOR_MAX_BATCH` | | `100` | Max events processed per reactor tick |
| `NICK_GENERATOR_LOCALE` | | `en` | Locale for random nickname generation |

---

## Environment Matrix

| Variable | Development | Staging | Production |
|----------|-------------|---------|------------|
| `DEBUG` | `true` | `false` | `false` |
| `LOG_LEVEL` | `DEBUG` | `DEBUG` | `INFO` |
| `ENVIRONMENT` | `development` | `staging` | `production` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | `60` | `30` |
| `DB_POOL_SIZE` | `5` | `10` | `30` |

---

## Secret Rotation

When rotating secrets:

1. **JWT_SECRET_KEY** — All active sessions will be invalidated. Users must log in again.
2. **VPN_KEY_ENCRYPTION_KEY** — Existing encrypted peer configs cannot be decrypted.
   Re-provision all VPN peers after rotation.
3. **POSTGRES_PASSWORD** — Update in `.env.local` and restart all services.
4. **REDIS_PASSWORD** — Update in `.env.local` and restart all services.

**Rotation procedure:**
```bash
# Generate new secret
NEW_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")

# Update .env.local
sed -i "s/^JWT_SECRET_KEY=.*/JWT_SECRET_KEY=${NEW_SECRET}/" .env.local

# Rolling restart
docker compose restart backend
```

---

## Validation

The `Settings` class (`backend/core/config.py`) validates all values at startup.
Required fields with no default will cause a `ValidationError` with a clear message.

```bash
# Test configuration is valid before deploying
docker compose run --rm backend python -c "
from backend.core.config import Settings
s = Settings()
print('Config OK:', s.ENVIRONMENT)
"
```
