# backend/core/config.py
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    POSTGRES_URL: str = "postgresql+asyncpg://sphere:sphere@localhost:5432/sphereplatform"
    DB_POOL_SIZE: int = 20
    DB_MAX_OVERFLOW: int = 10
    DB_POOL_TIMEOUT: int = 30

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_PASSWORD: str = ""

    # Auth
    JWT_SECRET_KEY: str = Field(...)  # Required — no default; set via env/secrets
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # VPN
    WG_ROUTER_URL: str = "http://localhost:8001"
    WG_ROUTER_API_KEY: str = ""
    AWG_JC: int = 4
    AWG_JMIN: int = 40
    AWG_JMAX: int = 70
    AWG_S1: int = 51
    AWG_S2: int = 45
    AWG_H1: int = 2545529037
    AWG_H2: int = 1767770215
    AWG_H3: int = 2031675751
    AWG_H4: int = 3699611814

    # Server
    VPN_SERVER_HOSTNAME: str = "adb.leetpc.com"

    # VPN (TZ-06 SPLIT-1: AWG Config Builder)
    WG_SERVER_PUBLIC_KEY: str = ""                        # Public key WG сервера
    WG_SERVER_ENDPOINT: str = "vpn.example.com:51820"    # WG endpoint для клиентов
    WG_PSK_ENABLED: bool = True                           # Pre-Shared Key
    VPN_KEY_ENCRYPTION_KEY: str = ""                      # Fernet key (Fernet.generate_key())
    VPN_POOL_SUBNET: str = "10.100.0.0/16"                # Подсеть для пула IP

    # App
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"

    # OTA
    APK_SIGNING_CERT_SHA256: str = ""

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def validate_jwt_secret(cls, v: str) -> str:
        insecure_patterns = ("change_me", "changeme", "default", "example", "secret", "password")
        if len(v) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters")
        if any(v.lower().startswith(pat) for pat in insecure_patterns):
            raise ValueError("JWT_SECRET_KEY must be set to a secure random value — do not use default/example values")
        return v

    @field_validator("REDIS_PASSWORD", mode="before")
    @classmethod
    def validate_redis_password(cls, v: str) -> str:
        if v and v.startswith("CHANGE_ME"):
            raise ValueError("REDIS_PASSWORD must be changed from template value")
        return v


settings = Settings()
