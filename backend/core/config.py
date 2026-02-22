# backend/core/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


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
    JWT_SECRET_KEY: str = Field(default="changeme_jwt_secret_key_at_least_32_chars")
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
            raise ValueError("JWT_SECRET_KEY must be set to a secure random value of at least 32 chars")
        return v

    @field_validator("REDIS_PASSWORD", mode="before")
    @classmethod
    def validate_redis_password(cls, v: str) -> str:
        if v and v.startswith("CHANGE_ME"):
            raise ValueError("REDIS_PASSWORD must be changed from template value")
        return v


settings = Settings()
