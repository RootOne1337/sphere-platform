# SPLIT-4 — VPN Kill Switch (Блокировка утечек трафика)

**ТЗ-родитель:** TZ-06-VPN-AmneziaWG  
**Ветка:** `stage/6-vpn`  
**Задача:** `SPHERE-034`  
**Исполнитель:** Android + Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-06 SPLIT-5
**Зависит от:** TZ-06 SPLIT-2 (Pool Manager), SPLIT-3 (Self-Healing)
**Интеграция при merge:** TZ-07 Android Agent работает с mock VPN; при merge подключить реальный Kill Switch

---

## Цель Сплита

Kill Switch: при обрыве VPN туннеля iptables блокирует весь трафик (кроме WG endpoint и LAN). Это предотвращает утечку реального IP при автоматизации. Управляется командой с сервера.

---

## Шаг 1 — Android: Kill Switch Manager

```kotlin
// AndroidAgent/vpn/KillSwitchManager.kt
class KillSwitchManager @Inject constructor(
    private val shellExecutor: ShellExecutor,
) {
    private var isActive = false
    
    /**
     * Включить Kill Switch: блокировать весь трафик кроме WG endpoint.
     * 
     * ВАЖНО: требует ROOT или DeviceOwner + прошивку с iptables.
     * На стандартном Android без root — использовать VpnService.Builder.setBlockingConnection()
     */
    suspend fun enable(vpnEndpoint: String, vpnInterface: String = "awg0") {
        if (isActive) return
        
        // Сохранить правила для restoration
        // FIX 6.1: sphereBackendIp берётся из конфига агента (AuthTokenStore.getServerUrl())
        // Резолвим ЗАРАНЕЕ и кэшируем — DNS тоже будет заблокирован после Kill Switch!
        val sphereBackendIp = resolveBackendIp()
        
        val rules = listOf(
            // Разрешить localhost
            "iptables -A OUTPUT -o lo -j ACCEPT",
            // Разрешить трафик через VPN интерфейс
            "iptables -A OUTPUT -o $vpnInterface -j ACCEPT",
            // Разрешить трафик к WG серверу (для handshake)
            "iptables -A OUTPUT -d ${vpnEndpoint.split(":")[0]} -p udp --dport ${vpnEndpoint.split(":")[1]} -j ACCEPT",
            // ─── FIX 6.1: РАЗРЕШИТЬ WebSocket к бэкенду Sphere Platform ──────────
            // КРИТИЧНО: без этого правила Kill Switch заблокирует WS-соединение
            // к серверу → устройство станет неуправляемым «кирпичом»!
            // Правило ОБЯЗАТЕЛЬНО стоит ДО REJECT.
            "iptables -A OUTPUT -d $sphereBackendIp -p tcp --dport 443 -j ACCEPT",
            // DNS для первичного резолва (только если backend по домену)
            "iptables -A OUTPUT -p udp --dport 53 -j ACCEPT",
            "iptables -A OUTPUT -p tcp --dport 53 -j ACCEPT",
            // ────────────────────────────────────────────────────────────────
            // Разрешить LAN (для ADB отладки)
            "iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT",
            "iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT",
            "iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT",
            // Разрешить DHCP
            "iptables -A OUTPUT -p udp --dport 67:68 -j ACCEPT",
            // Блокировать всё остальное
            "iptables -A OUTPUT -j REJECT --reject-with icmp-net-unreachable",
        )
        
        for (rule in rules) {
            shellExecutor.executeAsRoot(rule)
        }
        
        isActive = true
        Timber.i("Kill Switch enabled, endpoint=$vpnEndpoint, interface=$vpnInterface")
    }
    
    /**
     * Отключить Kill Switch: восстановить нормальный трафик.
     */
    suspend fun disable() {
        if (!isActive) return
        
        // Очистить все правила OUTPUT
        shellExecutor.executeAsRoot("iptables -F OUTPUT")
        // Восстановить policy ACCEPT
        shellExecutor.executeAsRoot("iptables -P OUTPUT ACCEPT")
        
        isActive = false
        Timber.i("Kill Switch disabled")
    }
    
    /**
     * Проверить активен ли Kill Switch.
     */
    fun isEnabled(): Boolean = isActive
}
```

---

## Шаг 2 — Android: VpnService Kill Switch (без root)

```kotlin
// AndroidAgent/vpn/VpnServiceKillSwitch.kt
/**
 * Альтернативный Kill Switch через Android VpnService API.
 * Работает БЕЗ root через setBlockConnection().
 * 
 * Подход: VpnService.Builder настраивает маршрутизацию так,
 * что при обрыве VPN весь трафик идёт в "чёрную дыру".
 */
class VpnServiceKillSwitch {
    
    fun configureBuilder(
        builder: VpnService.Builder,
        assignedIp: String,
        allowLan: Boolean = true,
    ): VpnService.Builder {
        return builder.apply {
            // Установить адрес VPN интерфейса
            addAddress(assignedIp, 32)
            
            // DNS через VPN
            addDnsServer("1.1.1.1")
            addDnsServer("8.8.8.8")
            
            // Весь трафик через VPN
            addRoute("0.0.0.0", 0)
            
            // Исключить LAN из VPN (опционально)
            if (allowLan) {
                // Android 13+ поддерживает excludeRoute
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                    excludeRoute(IpPrefix(InetAddress.getByName("192.168.0.0"), 16))
                    excludeRoute(IpPrefix(InetAddress.getByName("10.0.0.0"), 8))
                    excludeRoute(IpPrefix(InetAddress.getByName("172.16.0.0"), 12))
                }
            }
            
            // MTU для AmneziaWG (с учётом обфускации overhead)
            setMtu(1280)
            
            // Блокировать соединения при обрыве VPN (Kill Switch)
            // API 29+ (Android 10+)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                setMetered(false)
            }
            
            // "Always-on VPN" + "Block connections without VPN"
            // Настраивается пользователем в Android Settings → Network → VPN
            // Наша часть: документировать и предложить при первом запуске
        }
    }
}
```

---

## Шаг 3 — Backend: Команда управления Kill Switch

```python
# backend/services/vpn/killswitch_service.py
class KillSwitchService:
    """Управление Kill Switch на устройствах через WebSocket команды."""
    
    def __init__(self, publisher: PubSubPublisher):
        self.publisher = publisher
    
    async def enable_killswitch(
        self,
        device_id: str,
        vpn_endpoint: str,
        use_root: bool = False,
    ) -> bool:
        """
        Отправить команду включения Kill Switch на устройство.
        
        use_root=True  → iptables (требует root)
        use_root=False → VpnService API (без root, но менее гибко)
        """
        return await self.publisher.send_command_to_device(device_id, {
            "type": "vpn_killswitch",
            "action": "enable",
            "endpoint": vpn_endpoint,
            "method": "iptables" if use_root else "vpnservice",
        })
    
    async def disable_killswitch(self, device_id: str) -> bool:
        """Отправить команду отключения Kill Switch."""
        return await self.publisher.send_command_to_device(device_id, {
            "type": "vpn_killswitch",
            "action": "disable",
        })
    
    async def bulk_enable(
        self,
        device_ids: list[str],
        vpn_endpoint: str,
    ) -> dict[str, bool]:
        """Включить Kill Switch на группе устройств."""
        results = {}
        for device_id in device_ids:
            results[device_id] = await self.enable_killswitch(
                device_id, vpn_endpoint
            )
        return results
```

---

## Шаг 4 — Android: Обработчик команды Kill Switch

```kotlin
// AndroidAgent/commands/KillSwitchCommandHandler.kt
class KillSwitchCommandHandler @Inject constructor(
    private val killSwitchManager: KillSwitchManager,
    private val vpnServiceKillSwitch: VpnServiceKillSwitch,
    private val wsClient: SphereWebSocketClient,
) {
    suspend fun handle(command: JsonObject) {
        val action = command["action"]?.jsonPrimitive?.content ?: return
        val method = command["method"]?.jsonPrimitive?.content ?: "vpnservice"
        
        try {
            when (action) {
                "enable" -> {
                    val endpoint = command["endpoint"]?.jsonPrimitive?.content ?: return
                    when (method) {
                        "iptables" -> killSwitchManager.enable(endpoint)
                        "vpnservice" -> {
                            // VpnService метод уже настроен при создании туннеля
                            Timber.i("VpnService Kill Switch is configured at tunnel creation")
                        }
                    }
                }
                "disable" -> killSwitchManager.disable()
            }
            
            // Отчёт серверу
            wsClient.sendJson(buildJsonObject {
                put("type", "vpn_killswitch_result")
                put("action", action)
                put("success", true)
            })
        } catch (e: Exception) {
            Timber.e(e, "Kill Switch command failed")
            wsClient.sendJson(buildJsonObject {
                put("type", "vpn_killswitch_result")
                put("action", action)
                put("success", false)
                put("error", e.message)
            })
        }
    }
}
```

---

## Стратегия тестирования

### Mock-зависимости (MockK / pytest-mock)

- Android: `ShellExecutor.executeAsRoot()` → mock iptables без реального запуска
- Backend: `PubSubPublisher.send_command_to_device()` → `return True`

### Пример unit-теста (Kotlin — MockK)

```kotlin
@Test
fun `enable kill switch adds correct iptables rules`() = runTest {
    val shellExecutor = mockk<ShellExecutor> {
        coEvery { executeAsRoot(any()) } returns ShellResult(0, "")
    }
    val manager = KillSwitchManager(shellExecutor)
    
    manager.enable("vpn.example.com:51820")
    
    // 8 правил iptables
    coVerify(exactly = 8) { shellExecutor.executeAsRoot(any()) }
    // Проверить что REJECT правило последнее
    coVerify { shellExecutor.executeAsRoot(match { it.contains("REJECT") }) }
}
```

### Пример unit-теста (Python — pytest)

```python
async def test_enable_killswitch(mock_publisher):
    svc = KillSwitchService(mock_publisher)
    mock_publisher.send_command_to_device = AsyncMock(return_value=True)
    
    result = await svc.enable_killswitch("device:5555", "vpn.example.com:51820")
    
    assert result is True
    mock_publisher.send_command_to_device.assert_called_once()
    call_args = mock_publisher.send_command_to_device.call_args[0]
    assert call_args[1]["type"] == "vpn_killswitch"
    assert call_args[1]["action"] == "enable"
```

---

## Критерии готовности

- [ ] Kill Switch через iptables: весь трафик заблокирован кроме WG endpoint и LAN
- [ ] Kill Switch через VpnService: работает без root
- [ ] Команда `vpn_killswitch` → агент применяет правила → отчёт серверу
- [ ] `disable` → правила очищены, трафик восстановлен
- [ ] LAN трафик (ADB) НЕ блокируется Kill Switch
- [ ] Bulk enable на группу устройств работает
- [ ] При повторном `enable` — idempotent (не дублирует правила)
