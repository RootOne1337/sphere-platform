# App VPN — проверка серверной модели при замене management-сессии

Вызов `AppVpnObservation.freshness()` в `.venv-audit` с синтетическим VPN-статусом `RECONCILIATION_REQUIRED`. Дата приёма и дата нативной выборки равны времени чтения, устройство online. Функция вызывается сначала с ID сессии, к которой привязан отчёт, затем с новым ID. PostgreSQL, Redis, Android и сеть для этой проверки не использовались.

```python
from datetime import datetime, timezone

from backend.schemas.vpn.runtime import AppVpnObservation, AppVpnSnapshot

now = datetime.now(timezone.utc)
observation = AppVpnObservation(
    snapshot=AppVpnSnapshot(
        phase="RECONCILIATION_REQUIRED",
        sampledAtEpochMs=int(now.timestamp() * 1000),
        providerPid=42,
    ),
    received_at=now,
    ws_session_id="first-session",
)
assert observation.freshness("first-session", True, now) == "fresh"
assert observation.freshness("replacement-session", True, now) == "unknown"
```

```text
same_ws_session=fresh
replacement_ws_session=unknown
```
