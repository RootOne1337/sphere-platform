from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentConfig(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="SPHERE_", extra="ignore")

    server_url: str = "ws://localhost:8000"  # wss://api.sphere.local
    agent_token: str = "changeme"            # токен агента (не пользовательский JWT)
    workstation_id: str = "workstation-01"  # уникальный ID хоста

    ldplayer_path: str = r"C:\LDPlayer\LDPlayer9"
    ldconsole: str = r"C:\LDPlayer\LDPlayer9\ldconsole.exe"
    adb_path: str = r"C:\LDPlayer\LDPlayer9\adb.exe"

    reconnect_initial_delay: float = 1.0
    reconnect_max_delay: float = 30.0
    reconnect_backoff_factor: float = 2.0

    telemetry_interval: int = 30  # секунды


config = AgentConfig()
