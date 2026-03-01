# SPLIT-3 — Self-Healing VPN (Авторемонт туннеля)

**ТЗ-родитель:** TZ-06-VPN-AmneziaWG  
**Ветка:** `stage/6-vpn`  
**Задача:** `SPHERE-033`  
**Исполнитель:** Backend + Android  
**Оценка:** 1 день  
**Блокирует:** TZ-06 SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-11 Monitoring работает с mock VPN метриками; при merge подключить alerts

---

## Цель Сплита

Автоматическое восстановление VPN туннеля при обрыве. Heartbeat проверка handshake времени. Алерт и авторепуш конфига при зависшем туннеле.

---

## Шаг 1 — WG Handshake Checker

```python
# backend/services/vpn/health_monitor.py
import httpx
class VPNHealthMonitor:
    """
    Периодически проверяет состояние VPN туннелей через WG Router API.
    Период: каждые 60 секунд.
    """
    
    STALE_HANDSHAKE_THRESHOLD = 180   # секунд (3 минуты)
    
    def __init__(
        self,
        db: AsyncSession,
        pool_service: VPNPoolService,
        publisher: EventPublisher,
        wg_router_url: str,
    ):
        self.db = db
        self.pool_service = pool_service
        self.publisher = publisher
        self.wg_router_url = wg_router_url
        # FIX: единый httpx.AsyncClient вместо aiohttp.ClientSession() per call
        self._http = httpx.AsyncClient(
            base_url=wg_router_url,
            timeout=httpx.Timeout(5.0),
        )
    
    async def check_all_peers(self, org_id: uuid.UUID):
        """Проверить все активные peers организации."""
        peers = await self._get_active_peers(org_id)
        if not peers:
            return
        
        # Получить handshake времена с WG сервера
        handshake_data = await self._get_handshake_times()
        # ⚠️ ВАЖНО: использовать timezone-aware datetime, не datetime.utcnow()
        from datetime import timezone
        now = datetime.now(timezone.utc)
        
        for peer in peers:
            last_handshake = handshake_data.get(peer.public_key)
            
            if last_handshake is None:
                # Peer не виден WG серверу вообще
                await self._handle_missing_peer(peer, org_id)
                continue
            
            since_handshake = (now - last_handshake).total_seconds()
            
            # Обновить last_handshake в БД
            peer.last_handshake_at = last_handshake
            peer.vpn_active = since_handshake < self.STALE_HANDSHAKE_THRESHOLD
            
            if since_handshake > self.STALE_HANDSHAKE_THRESHOLD:
                # FIX 6.4: БЫЛО — сразу trigger_reconnect для всех
                # → Ночью генерировались ложные vpn_reconnect для 100+ выключенных эмуляторов
                # СТАЛО — проверяем что устройство ОНЛАЙН перед reconnect
                if not await self.status_cache.is_online(str(peer.device_id)):
                    continue  # Выключенный эмулятор — не дёргать
                logger.warning(
                    "VPN stale handshake",
                    device_id=peer.device_id,
                    since_handshake_s=since_handshake,
                )
                await self._trigger_reconnect(peer, org_id)
        
        await self.db.commit()
    
    async def _get_handshake_times(self) -> dict[str, datetime]:
        """Получить все handshake времена с WG Router API."""
        # FIX: used shared self._http (httpx.AsyncClient) — no per-call TCP handshake
        resp = await self._http.get("/peers/handshakes")
        data = resp.json()
        # {public_key: unix_timestamp}
        # ⚠️ ВАЖНО: datetime.fromtimestamp(v, tz=...) вместо utcfromtimestamp() — timezone-aware
        from datetime import timezone
        return {
            k: datetime.fromtimestamp(v, tz=timezone.utc)
            for k, v in data.items()
            if v > 0
                }
    
    async def _trigger_reconnect(self, peer: VPNPeer, org_id: uuid.UUID):
        """
        Отправить команду агенту переподключить VPN.
        Если агент не отвечает — создать алерт.
        """
        if not peer.device_id:
            return
        
        # Получить актуальный конфиг
        decrypted_private = self.pool_service.key_cipher.decrypt(
            peer.private_key_encrypted
        ).decode()
        obfuscation = AWGObfuscationParams.model_validate(peer.obfuscation_params)
        config = self.pool_service.config_builder.build_client_config(
            private_key=decrypted_private,
            assigned_ip=peer.assigned_ip,
            obfuscation=obfuscation,
        )
        
        # Отправить через WebSocket
        sent = await self.publisher.send_command_to_device(peer.device_id, {
            "type": "vpn_reconnect",
            "config": config,
            "reason": "stale_handshake",
        })
        
        if not sent:
            # Агент оффлайн — эвент в fleet
            await self.publisher.emit(FleetEvent(
                event_type=EventType.VPN_FAILED,
                device_id=peer.device_id,
                org_id=str(org_id),
                payload={
                    "reason": "agent_offline",
                    "peer_id": str(peer.id),
                }
            ))
    
    async def _handle_missing_peer(self, peer: VPNPeer, org_id: uuid.UUID):
        """Peer не существует на WG сервере — переустановить."""
        try:
            await self.pool_service._add_peer_to_server(
                peer.public_key, peer.assigned_ip, None
            )
            logger.info("Re-added missing peer", device_id=peer.device_id)
        except Exception as e:
            logger.error(f"Failed to re-add peer: {e}", device_id=peer.device_id)
```

---

## Шаг 2 — Background Health Task

```python
# backend/tasks/vpn_health.py
HEALTH_LOCK_KEY = "vpn:health_loop:lock"
HEALTH_LOCK_TTL = 90  # секунды — чуть больше интервала 60s

async def vpn_health_loop():
    """
    Фоновая задача: проверять VPN здоровье каждые 60 секунд.
    Запускается при старте приложения через lifespan.
    
    FIX: При горизонтальном масштабировании (2+ backend instances) каждый
    запускал бы health check одновременно. Используем Redis SET NX EX
    (distributed lock) — только один instance запускает проверку за цикл.
    """
    while True:
        try:
            # Distributed lock: SET vpn:health_loop:lock <instance_id> NX EX 90
            lock_value = str(uuid.uuid4())
            acquired = await redis.set(
                HEALTH_LOCK_KEY, lock_value, nx=True, ex=HEALTH_LOCK_TTL
            )
            if not acquired:
                # Другой instance держит блокировку — пропускаем этот цикл
                await asyncio.sleep(60)
                continue
            
            try:
                async with get_db_session() as db:
                    orgs = await get_all_active_orgs(db)
                    for org in orgs:
                        monitor = VPNHealthMonitor(db, ...)
                        await monitor.check_all_peers(org.id)
            finally:
                # Освобождаем lock только если мы его держим (проверка value)
                current = await redis.get(HEALTH_LOCK_KEY)
                if current and current.decode() == lock_value:
                    await redis.delete(HEALTH_LOCK_KEY)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"VPN health check error: {e}")
        
        await asyncio.sleep(60)
```

---

## Шаг 3 — Android: Auto-Reconnect

```kotlin
// AndroidAgent/vpn/VpnReconnectHandler.kt
class VpnReconnectHandler @Inject constructor(
    private val vpnManager: VpnManager,
) {
    suspend fun handleVpnReconnect(command: JsonObject) {
        val config = command["config"]?.jsonPrimitive?.content
            ?: return
        
        Timber.i("VPN reconnect requested: ${command["reason"]?.jsonPrimitive?.content}")
        
        // 1. Остановить текущий туннель
        vpnManager.disconnect()
        delay(1000)
        
        // 2. Применить новый конфиг
        vpnManager.applyConfig(config)
        
        // 3. Подключиться
        val result = vpnManager.connect()
        
        // 4. Отчёт серверу
        wsClient.sendJson(buildJsonObject {
            put("type", "vpn_reconnect_result")
            put("success", result.isSuccess)
            result.exceptionOrNull()?.let { put("error", it.message) }
        })
    }
}
```

---

## Критерии готовности

- [ ] Handshake > 3 минуты → `vpn_reconnect` команда отправлена агенту
- [ ] Peer отсутствует на WG сервере → автоматически переустанавливается
- [ ] Агент оффлайн при stale handshake → `VPN_FAILED` event, не краш
- [ ] Health check каждые 60s, не накапливается (asyncio.sleep не дрейфует)
- [ ] `vpn_active=False` для пропущенных handshake → Prometheus gauge обновляется
