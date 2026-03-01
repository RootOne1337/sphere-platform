# SPLIT-5 — Network Discovery (Автообнаружение устройств)

**ТЗ-родитель:** TZ-02-Device-Registry  
**Ветка:** `stage/2-device-registry`  
**Задача:** `SPHERE-015`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** ничего (опциональная фича)

---

## Цель Сплита

Сканирование подсети для обнаружения ADB-устройств, автоматическая регистрация в реестре.

---

## Шаг 1 — Discovery Request Schema

```python
# backend/schemas/discovery.py
class DiscoverRequest(BaseModel):
    subnet: str = Field(description="e.g. '192.168.1.0/24' or '10.0.0.0/16'")
    port_range: list[int] = Field(default=[5554, 5584], min_length=2, max_length=2)  # LOW-4: list вместо tuple — JSON-сериализуемо, Field-валидация длины
    timeout_ms: int = Field(default=500, ge=100, le=5000)
    workstation_id: uuid.UUID
    auto_register: bool = True
    group_id: uuid.UUID | None = None
    
    @field_validator("subnet")
    @classmethod
    def validate_subnet(cls, v: str) -> str:
        import ipaddress
        try:
            net = ipaddress.ip_network(v, strict=False)
            # Безопасность: не разрешаем слишком большие подсети
            if net.num_addresses > 65536:
                raise ValueError("Subnet too large. Max /16 (65536 hosts)")
        except ValueError as e:
            raise ValueError(str(e))
        return str(net)

class DiscoveredDevice(BaseModel):
    ip: str
    port: int
    serial: str
    model: str | None
    android_version: str | None
    already_registered: bool
    registered_id: str | None = None

class DiscoverResponse(BaseModel):
    scanned: int
    found: int
    registered: int
    devices: list[DiscoveredDevice]
    duration_ms: float
```

---

## Шаг 2 — ADB Discovery via PC Agent

```python
# backend/services/discovery_service.py
class DiscoveryService:
    def __init__(self, pc_agent_svc, device_svc, db: AsyncSession):
        self.pc_agent_svc = pc_agent_svc
        self.device_svc = device_svc
        self.db = db
    
    async def discover_subnet(
        self,
        request: DiscoverRequest,
        org_id: uuid.UUID,
    ) -> DiscoverResponse:
        start = time.monotonic()
        
        # Отправить команду PC Agent для сканирования
        response = await self.pc_agent_svc.send_command_wait(
            workstation_id=str(request.workstation_id),
            command={
                "type": "discover_adb",
                "subnet": request.subnet,
                "port_range": list(request.port_range),
                "timeout_ms": request.timeout_ms,
            },
            timeout=60.0,  # Сканирование /24 занимает ~30сек
        )
        
        raw_devices: list[dict] = response.get("devices", [])
        found_devices = [self._parse_device(d) for d in raw_devices]
        
        # Проверить уже существующие
        existing_ids = await self._get_existing_device_ids(
            [f"{d.ip}:{d.port}" for d in found_devices], org_id
        )
        
        registered_count = 0
        result = []
        for dev in found_devices:
            serial = f"{dev['ip']}:{dev['port']}"
            already = serial in existing_ids
            
            reg_id: str | None = existing_ids.get(serial)
            if not already and request.auto_register:
                new_device = await self.device_svc.create_device(org_id, CreateDeviceRequest(
                    id=f"adb_{serial.replace(':', '_').replace('.', '_')}",
                    type="physical",
                    ip_address=dev["ip"],
                    adb_port=dev["port"],
                    android_version=dev.get("android_version"),
                    device_model=dev.get("model"),
                    workstation_id=request.workstation_id,
                    group_id=request.group_id,
                ))
                reg_id = str(new_device.id)
                registered_count += 1
            
            result.append(DiscoveredDevice(
                ip=dev["ip"],
                port=dev["port"],
                serial=serial,
                model=dev.get("model"),
                android_version=dev.get("android_version"),
                already_registered=already,
                registered_id=reg_id,
            ))
        
        return DiscoverResponse(
            scanned=self._count_hosts(request.subnet) * len(range(*request.port_range)),
            found=len(result),
            registered=registered_count,
            devices=result,
            duration_ms=(time.monotonic() - start) * 1000,
        )
```

---

## Шаг 3 — PC Agent ADB Scanner (Python)

```python
# pc_agent/modules/adb_discovery.py
import asyncio
import subprocess

class ADBDiscovery:
    async def scan_subnet(self, subnet: str, port_range: tuple[int, int], timeout_ms: int) -> list[dict]:
        import ipaddress
        
        network = ipaddress.ip_network(subnet, strict=False)
        hosts = list(network.hosts())
        ports = list(range(port_range[0], port_range[1] + 1))
        
        semaphore = asyncio.Semaphore(256)
        tasks = []
        for host in hosts:
            for port in ports:
                tasks.append(self._try_connect(str(host), port, timeout_ms, semaphore))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        found = [r for r in results if isinstance(r, dict)]
        return found
    
    async def _try_connect(self, ip: str, port: int, timeout_ms: int, sem: asyncio.Semaphore) -> dict | None:
        async with sem:
            try:
                # TCP connect
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(ip, port),
                    timeout=timeout_ms / 1000
                )
                writer.close()
                
                # ADB connect для получения device info
                proc = await asyncio.create_subprocess_exec(
                    "adb", "connect", f"{ip}:{port}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5.0)
                
                if b"connected" in stdout or b"already" in stdout:
                    info = await self._get_device_info(ip, port)
                    return {"ip": ip, "port": port, **info}
            except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                pass
            return None
    
    async def _get_device_info(self, ip: str, port: int) -> dict:
        target = f"{ip}:{port}"
        async def prop(name: str) -> str | None:
            proc = await asyncio.create_subprocess_exec(
                "adb", "-s", target, "shell", "getprop", name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=3.0)
            return out.decode().strip() or None
        
        return {
            "model": await prop("ro.product.model"),
            "android_version": await prop("ro.build.version.release"),
        }
```

---

## Шаг 4 — Router

```python
# backend/api/v1/discovery.py
router = APIRouter(prefix="/discovery", tags=["discovery"])

@router.post("/scan", response_model=DiscoverResponse)
async def scan_subnet(
    body: DiscoverRequest,
    current_user: User = require_permission("device:write"),
    svc: DiscoveryService = Depends(get_discovery_service),
):
    """
    Сканировать подсеть через PC Agent для обнаружения ADB-устройств.
    Timeout: до 60 секунд.
    """
    return await svc.discover_subnet(body, current_user.org_id)
```

---

## Критерии готовности

- [ ] Сканирование /24 (256 хостов × 2 порта) ≤ 15 секунд
- [ ] Subnet > /16 отклоняется с 422
- [ ] Найденные устройства авторегистрируются c корректным ID
- [ ] Уже зарегистрированные устройства: `already_registered=true`, не дублируются
- [ ] Отчёт: scanned/found/registered/duration_ms per scan
