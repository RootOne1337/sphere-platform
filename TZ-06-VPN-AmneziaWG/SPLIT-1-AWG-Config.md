# SPLIT-1 — AWG Config Builder (Генерация ключей и конфигурация)

**ТЗ-родитель:** TZ-06-VPN-AmneziaWG  
**Ветка:** `stage/6-vpn`  
**Задача:** `SPHERE-031`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-06 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-07 Android Agent работает с mock VPN config; при merge подключить реальный AWG Builder

> [!NOTE]
> **MERGE-11: При merge `stage/6-vpn` + `stage/7-android`:**
>
> 1. Android `VpnConfigManager` → заменить mock WG config на реальный `PoolManager.generate_config(device_id)`
> 2. Kill Switch `iptables` правила → получать `vpn_server_ip` из реального config (не hardcoded)
> 3. Self-Healing → проверять handshake через реальный WG Router API

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-6` — НЕ в `sphere-platform`.
> Ветка `stage/6-vpn` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-6
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/6-vpn
pwd                          # ОБЯЗАН содержать: sphere-stage-6
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-6 stage/6-vpn
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/6-vpn` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/6-vpn` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `backend/services/vpn/` | `backend/main.py` 🔴 |
| `backend/schemas/vpn/` | `backend/core/` 🔴 |
| `backend/api/v1/vpn/` | `backend/database/` 🔴 |
| `backend/models/vpn_peer.py` (расширение) | `backend/websocket/` (TZ-03) 🔴 |
| `tests/test_vpn*` | `frontend/` (TZ-10) 🔴 |

---

## Цель Сплита

Создать AWG (AmneziaWG) конфигуратор: генерация WireGuard keypair, Pre-Shared Key, параметры обфускации AmneziaWG, сборка клиентского `.conf` файла, генерация QR-кода для Android агента.

---

## Шаг 1 — Зависимости

```
# В backend/requirements.txt уже должны быть (TZ-00 SPLIT-2 MED-2):
httpx>=0.27.0
circuitbreaker>=2.0.0
qrcode>=7.4
cryptography>=42.0.0    # Fernet для шифрования private key
```

---

## Шаг 2 — AWG Obfuscation Parameters

```python
# backend/services/vpn/awg_config.py
import secrets
import subprocess
import qrcode
import io
import base64
from pydantic import BaseModel

class AWGObfuscationParams(BaseModel):
    """
    Параметры обфускации AmneziaWG — рандомизируются для каждого peer.
    Документация: https://docs.amnezia.org/documentation/amnezia-wg/
    """
    jc: int     # Junk packet Count (1-128)
    jmin: int   # Junk packet Min size (0-1280)
    jmax: int   # Junk packet Max size (jmin-1280)
    s1: int     # Init packet magic Header (1-2048)
    s2: int     # Response packet magic Header (1-2048)
    h1: int     # Init Handshake header (1-2147483647)
    h2: int     # Response Handshake header (1-2147483647)
    h3: int     # Under load Handshake header (1-2147483647)
    h4: int     # Cookie reply Handshake header (1-2147483647)

    @classmethod
    def generate_random(cls) -> "AWGObfuscationParams":
        """Генерировать случайные параметры обфускации."""
        jmin = secrets.randbelow(200)
        return cls(
            jc=secrets.randbelow(128) + 1,
            jmin=jmin,
            jmax=jmin + secrets.randbelow(1000) + 1,
            s1=secrets.randbelow(2048) + 1,
            s2=secrets.randbelow(2048) + 1,
            h1=secrets.randbelow(2147483647) + 1,
            h2=secrets.randbelow(2147483647) + 1,
            h3=secrets.randbelow(2147483647) + 1,
            h4=secrets.randbelow(2147483647) + 1,
        )


class AWGConfigBuilder:
    """
    Сборщик клиентских конфигураций AmneziaWG.
    Один экземпляр на приложение (DI через FastAPI Depends).
    """

    def __init__(
        self,
        server_public_key: str,
        server_endpoint: str,       # "vpn.example.com:51820"
        dns: str = "1.1.1.1, 8.8.8.8",
        server_psk_enabled: bool = True,
    ):
        self.server_public_key = server_public_key
        self.server_endpoint = server_endpoint
        self.dns = dns
        self.server_psk_enabled = server_psk_enabled

    def generate_keypair(self) -> tuple[str, str]:
        """
        Генерировать WireGuard keypair (private_key, public_key).
        Используем subprocess + wg genkey / wg pubkey — стандартный путь.
        Fallback: nacl если wg binary не доступен.
        """
        try:
            private = subprocess.check_output(
                ["wg", "genkey"], text=True
            ).strip()
            public = subprocess.check_output(
                ["wg", "pubkey"], input=private, text=True
            ).strip()
            return private, public
        except FileNotFoundError:
            # Fallback: X25519 через cryptography
            from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
            privkey = X25519PrivateKey.generate()
            private_bytes = privkey.private_bytes_raw()
            public_bytes = privkey.public_key().public_bytes_raw()
            return (
                base64.b64encode(private_bytes).decode(),
                base64.b64encode(public_bytes).decode(),
            )

    def generate_psk(self) -> str:
        """Генерировать Pre-Shared Key (32 байта base64)."""
        return base64.b64encode(secrets.token_bytes(32)).decode()

    def build_client_config(
        self,
        private_key: str,
        assigned_ip: str,
        obfuscation: AWGObfuscationParams,
        psk: str | None = None,
        split_tunnel: bool = True,
    ) -> str:
        """
        Собрать AmneziaWG клиентский конфиг (формат .conf).

        split_tunnel=True  → AllowedIPs = 0.0.0.0/0 (весь трафик через VPN)
        split_tunnel=False → AllowedIPs = 10.100.0.0/16 (только внутренний трафик)
        """
        allowed_ips = "0.0.0.0/0" if split_tunnel else "10.100.0.0/16"

        config = f"""[Interface]
PrivateKey = {private_key}
Address = {assigned_ip}/32
DNS = {self.dns}
Jc = {obfuscation.jc}
Jmin = {obfuscation.jmin}
Jmax = {obfuscation.jmax}
S1 = {obfuscation.s1}
S2 = {obfuscation.s2}
H1 = {obfuscation.h1}
H2 = {obfuscation.h2}
H3 = {obfuscation.h3}
H4 = {obfuscation.h4}

[Peer]
PublicKey = {self.server_public_key}
AllowedIPs = {allowed_ips}
Endpoint = {self.server_endpoint}
PersistentKeepalive = 25"""

        if psk:
            config += f"\nPresharedKey = {psk}"

        return config.strip()

    def to_qr_code(self, config_text: str) -> str:
        """Конвертировать конфиг в base64 PNG QR-код для Android клиента."""
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data(config_text)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode()
```

---

## Шаг 3 — DI (FastAPI Dependency)

```python
# backend/services/vpn/dependencies.py
from functools import lru_cache
from cryptography.fernet import Fernet
from backend.core.config import settings

@lru_cache(maxsize=1)
def get_awg_config_builder() -> AWGConfigBuilder:
    return AWGConfigBuilder(
        server_public_key=settings.WG_SERVER_PUBLIC_KEY,
        server_endpoint=settings.WG_SERVER_ENDPOINT,
        server_psk_enabled=settings.WG_PSK_ENABLED,
    )

@lru_cache(maxsize=1)
def get_key_cipher() -> Fernet:
    """Fernet для шифрования private key перед хранением в БД."""
    return Fernet(settings.VPN_KEY_ENCRYPTION_KEY.encode())
```

---

## Шаг 4 — Config Settings

```python
# backend/core/config.py — ДОБАВИТЬ (в существующий Settings class):
class Settings(BaseSettings):
    # ... существующие поля ...

    # VPN (TZ-06)
    WG_ROUTER_URL: str = "http://vpn-router:8080"      # API WireGuard Router
    WG_ROUTER_API_KEY: str = ""                          # API key для WG Router
    WG_SERVER_PUBLIC_KEY: str = ""                        # Public key WG сервера
    WG_SERVER_ENDPOINT: str = "vpn.example.com:51820"    # WG endpoint для клиентов
    WG_PSK_ENABLED: bool = True                          # Pre-Shared Key
    VPN_KEY_ENCRYPTION_KEY: str = ""                      # Fernet key (32 байта base64)
    VPN_POOL_SUBNET: str = "10.100.0.0/16"               # Подсеть для пула IP
```

---

## Стратегия тестирования

### Fixture-зависимости (ORM INSERT через модели из TZ-00)

- `Organization(id=TEST_ORG, name="test_org")`
- `VPNPeer(org_id=TEST_ORG, status=VPNPeerStatus.FREE)`

### Mock-зависимости (pytest-mock)

- `subprocess.check_output` → mock keypair генерации
- `qrcode.QRCode` → mock QR генерации

### Пример unit-теста

```python
async def test_generate_keypair_fallback(awg_builder, monkeypatch):
    # Имитируем отсутствие wg binary
    monkeypatch.setattr("subprocess.check_output", side_effect=FileNotFoundError)
    
    private, public = awg_builder.generate_keypair()
    
    assert len(base64.b64decode(private)) == 32
    assert len(base64.b64decode(public)) == 32

async def test_build_client_config(awg_builder):
    obfuscation = AWGObfuscationParams.generate_random()
    config = awg_builder.build_client_config(
        "test_private_key", "10.100.0.1", obfuscation, psk="test_psk"
    )
    
    assert "[Interface]" in config
    assert "PrivateKey = test_private_key" in config
    assert f"Jc = {obfuscation.jc}" in config
    assert "PresharedKey = test_psk" in config
```

---

## Критерии готовности

- [ ] `generate_keypair()` возвращает валидные X25519 ключи (32 байта)
- [ ] `generate_psk()` возвращает 32 байта base64
- [ ] AWG obfuscation параметры рандомизируются для каждого peer
- [ ] Конфиг содержит все AWG-специфичные поля (Jc, Jmin, Jmax, S1, S2, H1-H4)
- [ ] `split_tunnel=True` → AllowedIPs `0.0.0.0/0`; `False` → `10.100.0.0/16`
- [ ] QR-код генерируется корректно (base64 PNG, сканируется клиентом)
- [ ] Private key шифруется Fernet перед хранением в БД
- [ ] Fallback на `cryptography` при отсутствии `wg` binary
