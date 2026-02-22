# SPLIT-2 — VPN Pool Manager (Назначение и управление пулом)

**ТЗ-родитель:** TZ-06-VPN-AmneziaWG  
**Ветка:** `stage/6-vpn`  
**Задача:** `SPHERE-032`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-06 SPLIT-3, SPLIT-4
**Интеграция при merge:** TZ-07 Android Agent работает с mock VPN config; при merge подключить реальный Pool Manager

---

## Цель Сплита

Управление пулом IP адресов и peer записей. Атомарное назначение/отзыв. Circuit breaker для WireGuard Router API.

---

## Шаг 1 — IP Pool Allocator

```python
# backend/services/vpn/ip_pool.py
import ipaddress

class IPPoolAllocator:
    """
    Управляет пулом IP адресов для VPN (e.g. 10.100.0.0/16 = 65534 устройств).
    Хранит свободные IP в Redis Sorted Set для быстрой выдачи.
    """
    
    POOL_KEY = "vpn:ip_pool:{org_id}"
    
    def __init__(self, redis, subnet: str = "10.100.0.0/16"):
        self.redis = redis
        self.network = ipaddress.ip_network(subnet, strict=False)
    
    async def initialize_pool(self, org_id: str, count: int = 1000):
        """Предзаполнить пул N адресами из подсети."""
        pool_key = self.POOL_KEY.format(org_id=org_id)
        
        # Начать с .1 (минус сетевой .0 и broadcast)
        ips = [str(host) for host in list(self.network.hosts())[:count]]
        
        # Использовать ZADD с score=0 для FIFO через ZPOPMIN
        async with self.redis.pipeline() as pipe:
            for i, ip in enumerate(ips):
                pipe.zadd(pool_key, {ip: i})
            await pipe.execute()
    
    async def allocate_ip(self, org_id: str) -> str | None:
        """Атомарно взять следующий свободный IP."""
        pool_key = self.POOL_KEY.format(org_id=org_id)
        
        # ZPOPMIN: атомарно взять IP с наименьшим score
        result = await self.redis.zpopmin(pool_key, 1)
        if not result:
            return None
        
        return result[0][0].decode() if isinstance(result[0][0], bytes) else result[0][0]
    
    async def release_ip(self, org_id: str, ip: str):
        """Вернуть IP в пул."""
        pool_key = self.POOL_KEY.format(org_id=org_id)
        # Добавить с текущим timestamp для FIFO
        await self.redis.zadd(pool_key, {ip: time.time()})
    
    async def pool_size(self, org_id: str) -> int:
        return await self.redis.zcard(self.POOL_KEY.format(org_id=org_id))
```

---

## Шаг 2 — VPN Pool Service (с Circuit Breaker)

```python
# backend/services/vpn/pool_service.py
import httpx
from circuitbreaker import circuit

class VPNPoolService:
    
    def __init__(
        self,
        db: AsyncSession,
        ip_pool: IPPoolAllocator,
        config_builder: AWGConfigBuilder,
        key_cipher: Fernet,
        wg_router_url: str,
    ):
        self.db = db
        self.ip_pool = ip_pool
        self.config_builder = config_builder
        self.key_cipher = key_cipher
        self.wg_router_url = wg_router_url
        # FIX: единый httpx.AsyncClient вместо aiohttp.ClientSession() per call —
        # избегаем TCP pool thrash (каждый new ClientSession = новый TCP handshake)
        self._http = httpx.AsyncClient(
            base_url=wg_router_url,
            timeout=httpx.Timeout(10.0),
            headers={"Content-Type": "application/json"},
        )
    
    async def assign_vpn(
        self,
        device_id: str,
        org_id: uuid.UUID,
        split_tunnel: bool = True,
    ) -> VPNAssignment:
        """
        Назначить VPN peer устройству.
        1. Взять свободный IP
        2. Сгенерировать keypair + obfuscation
        3. Добавить peer на WireGuard сервер
        4. Сохранить в БД
        """
        # Проверить, нет ли уже активного VPN
        existing = await self._get_existing_peer(device_id, org_id)
        if existing:
            return await self._peer_to_assignment(existing)
        
        # Выделить IP (атомарно из Redis)
        assigned_ip = await self.ip_pool.allocate_ip(str(org_id))
        if not assigned_ip:
            raise HTTPException(503, "VPN pool exhausted")
        
        try:
            # Генерировать ключи
            private_key, public_key = self.config_builder.generate_keypair()
            obfuscation = AWGObfuscationParams.generate_random()
            psk = self.config_builder.generate_psk() if self.config_builder.server_psk_enabled else None
            
            # Добавить peer на WG сервер
            await self._add_peer_to_server(public_key, assigned_ip, psk)
            
            # Сохранить в БД (private key зашифрован)
            # ⚠️ ВАЖНО: использовать VPNPeerStatus.ASSIGNED, не строку "assigned" — SAEnum!
            from backend.models.vpn_peer import VPNPeerStatus
            peer = VPNPeer(
                org_id=org_id,
                device_id=device_id,
                assigned_ip=assigned_ip,
                public_key=public_key,
                private_key_encrypted=self.key_cipher.encrypt(private_key.encode()),
                psk_encrypted=self.key_cipher.encrypt(psk.encode()) if psk else None,
                obfuscation_params=obfuscation.model_dump(),
                status=VPNPeerStatus.ASSIGNED,
            )
            self.db.add(peer)
            
            # Сгенерировать конфиг для отправки агенту
            config_text = self.config_builder.build_client_config(
                private_key, assigned_ip, obfuscation, psk, split_tunnel
            )
            
            return VPNAssignment(
                peer_id=peer.id,
                device_id=device_id,
                assigned_ip=assigned_ip,
                config=config_text,
                qr_code=self.config_builder.to_qr_code(config_text),
            )
        except Exception as e:
            # Вернуть IP в пул при ошибке
            await self.ip_pool.release_ip(str(org_id), assigned_ip)
            raise
    
    @circuit(failure_threshold=5, recovery_timeout=30)
    async def _add_peer_to_server(self, public_key: str, ip: str, psk: str | None):
        """
        Добавить peer на WireGuard/AmneziaWG сервер через его API.
        Circuit breaker: 5 ошибок → 30s cooldown.
        """
        # FIX: used shared self._http (httpx.AsyncClient) — no per-call TCP handshake
        payload = {
            "public_key": public_key,
            "allowed_ip": f"{ip}/32",
            "psk": psk,
        }
        resp = await self._http.post("/peers", json=payload)
        if resp.status_code != 201:
            raise RuntimeError(f"WG Router error {resp.status_code}: {resp.text}")
    
    async def revoke_vpn(self, device_id: str, org_id: uuid.UUID):
        """Отозвать VPN peer устройства."""
        peer = await self._get_existing_peer(device_id, org_id)
        if not peer:
            return
        
        # Удалить peer с WG сервера
        await self._remove_peer_from_server(peer.public_key)
        
        # Вернуть IP в пул
        await self.ip_pool.release_ip(str(org_id), peer.assigned_ip)
        
        # Обновить статус
        # ⚠️ ВАЖНО: использовать VPNPeerStatus.FREE, не строку "free" — SAEnum!
        from backend.models.vpn_peer import VPNPeerStatus
        peer.status = VPNPeerStatus.FREE
        peer.device_id = None
        peer.vpn_active = False
```

---

## Критерии готовности

- [ ] `allocate_ip()` атомарна — два запроса не получат один IP
- [ ] IP возвращается в пул при любой ошибке (try/except + release)
- [ ] Circuit breaker: 5 WG API ошибок → 30s cooldown с логированием
- [ ] Private key хранится зашифрованным Fernet (не plaintext)
- [ ] Revoke: IP возвращён в пул, peer удалён с WG сервера
- [ ] Pool size < 10 → `low_pool` Prometheus alert (см. TZ-11)
