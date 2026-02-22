# SPLIT-4 — Secrets Management, .env структура, Security Baseline

**ТЗ-родитель:** TZ-00-Constitution  
**Ветка:** `stage/0-constitution`  
**Задача:** `SPHERE-004`  
**Исполнитель:** DevOps + Security  
**Оценка:** 0.5 рабочего дня  
**Блокирует:** TZ-00 SPLIT-5 (внутри этапа)
**Обеспечивает:** Управление секретами для всех потоков (JWT, Redis, VPN)

---

## Цель Сплита

Настроить безопасное управление секретами через .env файлы, Pydantic Settings, rotate-ready структуру. После выполнения — никакой секрет не попадёт в Git, у каждого окружения свои значения.

---

## Шаг 1 — .env.example (template)

```dotenv
# =============================================================================
# Sphere Platform — Environment Variables Template
# Скопируй в .env.local и заполни значения
# НИКОГДА не коммить .env.local или .env
# =============================================================================

# ── Database ──────────────────────────────────────────────────────────────────
POSTGRES_USER=sphere
POSTGRES_PASSWORD=CHANGE_ME_strong_password_32chars
POSTGRES_URL=postgresql+asyncpg://sphere:CHANGE_ME@localhost:5432/sphereplatform

# ── Redis ─────────────────────────────────────────────────────────────────────
REDIS_PASSWORD=CHANGE_ME_redis_password_32chars
REDIS_URL=redis://:CHANGE_ME@localhost:6379/0

# ── Auth / JWT ────────────────────────────────────────────────────────────────
# Генерация: python -c "import secrets; print(secrets.token_hex(32))"
JWT_SECRET_KEY=CHANGE_ME_jwt_secret_64chars_minimum
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=30
JWT_REFRESH_TOKEN_EXPIRE_DAYS=7

# ── VPN / WireGuard Router ────────────────────────────────────────────────────
WG_ROUTER_URL=http://2.56.122.229:8000
WG_ROUTER_API_KEY=CHANGE_ME_wg_api_key

# AmneziaWG обфускация (НЕ менять если уже есть активные туннели)
AWG_JC=4
AWG_JMIN=40
AWG_JMAX=70
AWG_S1=51
AWG_S2=45
AWG_H1=2545529037
AWG_H2=1767770215
AWG_H3=2031675751
AWG_H4=3699611814

# ── Server ────────────────────────────────────────────────────────────────────
VPN_SERVER_HOSTNAME=adb.leetpc.com
SERVER_HOSTNAME=adb.leetpc.com

# ── n8n ───────────────────────────────────────────────────────────────────────
N8N_ENCRYPTION_KEY=CHANGE_ME_n8n_key_32chars

# ── App Settings ──────────────────────────────────────────────────────────────
DEBUG=false
LOG_LEVEL=INFO
ENVIRONMENT=development   # development | staging | production

# ── SphereAgent OTA ───────────────────────────────────────────────────────────
# SHA-256 отпечаток сертификата подписи APK (hex)
APK_SIGNING_CERT_SHA256=CHANGE_ME_sha256_of_signing_cert
```

---

## Шаг 2 — Pydantic Settings

```python
# backend/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
import secrets

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )
    
    # Database
    POSTGRES_URL: str
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30
    
    # Redis
    REDIS_URL: str
    REDIS_PASSWORD: str
    
    # Auth
    JWT_SECRET_KEY: str = Field(min_length=32)
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # VPN
    WG_ROUTER_URL: str
    WG_ROUTER_API_KEY: str
    AWG_JC: int = 4
    AWG_JMIN: int = 40
    AWG_JMAX: int = 70
    AWG_S1: int = 51
    AWG_S2: int = 45
    AWG_H1: int
    AWG_H2: int
    AWG_H3: int
    AWG_H4: int
    
    # Server
    VPN_SERVER_HOSTNAME: str = "adb.leetpc.com"
    
    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"
    
    # OTA
    APK_SIGNING_CERT_SHA256: str = ""
    
    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        if v.startswith("CHANGE_ME") or len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be set to a secure random value")
        return v
    
    @field_validator("POSTGRES_PASSWORD", mode="before")
    @classmethod
    def validate_pg_password(cls, v: str) -> str:
        if v.startswith("CHANGE_ME"):
            raise ValueError("POSTGRES_PASSWORD must be changed from template value")
        return v

    @field_validator("REDIS_PASSWORD", mode="before")
    @classmethod
    def validate_redis_password(cls, v: str) -> str:
        # FIX: валидация REDIS_PASSWORD отсутствовала — можно было запустить production с CHANGE_ME паролем
        if v.startswith("CHANGE_ME") or len(v) < 16:
            raise ValueError("REDIS_PASSWORD must be changed from template value and be at least 16 chars")
        return v

settings = Settings()
```

---

## Шаг 3 — Генерация секретов

```python
# scripts/generate_secrets.py
"""
Запустить один раз: python scripts/generate_secrets.py
Показывает значения для .env.local
"""
import secrets
import struct

def generate():
    print("# Скопируй в .env.local:\n")
    print(f"POSTGRES_PASSWORD={secrets.token_urlsafe(32)}")
    print(f"REDIS_PASSWORD={secrets.token_urlsafe(32)}")
    print(f"JWT_SECRET_KEY={secrets.token_hex(32)}")
    print(f"N8N_ENCRYPTION_KEY={secrets.token_urlsafe(24)}")
    
    # AWG magic headers — случайные 32-bit числа
    for i in range(1, 5):
        val = struct.unpack("I", secrets.token_bytes(4))[0]
        print(f"AWG_H{i}={val}")

if __name__ == "__main__":
    generate()
```

---

## Шаг 4 — Secrets в GitHub Actions

```yaml
# Для CI/CD добавить в GitHub Secrets (Settings → Secrets):
# POSTGRES_PASSWORD
# REDIS_PASSWORD  
# JWT_SECRET_KEY
# WG_ROUTER_API_KEY
# APK_SIGNING_CERT_SHA256

# В workflow используется так:
env:
  POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
  JWT_SECRET_KEY: ${{ secrets.JWT_SECRET_KEY }}
```

---

## Шаг 5 — detect-secrets baseline

```bash
# Инициализировать baseline для detect-secrets
detect-secrets scan > .secrets.baseline

# Проверить что baseline не содержит реальных секретов
detect-secrets audit .secrets.baseline
```

---

## Критерии готовности

- [ ] `python scripts/generate_secrets.py` генерирует уникальные значения
- [ ] Попытка запустить backend с `CHANGE_ME` значениями → ValueError при старте
- [ ] pre-commit reject коммита с `.env.local` в индексе
- [ ] `.secrets.baseline` создан и добавлен в репо
- [ ] `detect-secrets scan` → 0 новых секретов
