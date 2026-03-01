# SPLIT-1 — Device CRUD API + Валидация

**ТЗ-родитель:** TZ-02-Device-Registry  
**Ветка:** `stage/2-device-registry`  
**Задача:** `SPHERE-011`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-02 SPLIT-2, SPLIT-3, SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-10 работает с mock device API; при merge подключить реальные endpoints

> [!NOTE]
> **MERGE-9: При merge `stage/2-device-registry` + `stage/10-frontend`:**
>
> 1. Заменить mock `useDevices()` на реальный `/api/v1/devices` endpoint
> 2. Проверить пагинацию: backend `PagedResponse` ↔ frontend `useQuery` params
> 3. Типы: запустить `npm run gen:types` для обновления OpenAPI типов

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-2` — НЕ в `sphere-platform`.
> Ветка `stage/2-device-registry` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**1. Открой в IDE папку:**

```
C:\Users\dimas\Documents\sphere-stage-2
```

*(не `sphere-platform`!)*

**2. Верификация — убедись что ты в правильном месте:**

```bash
git branch --show-current   # ОБЯЗАН показать: stage/2-device-registry
pwd                          # ОБЯЗАНА содержать: sphere-stage-2
```

**3. Если папка ещё не создана** — сообщи DevOps, пусть выполнит из `sphere-platform/`:

```bash
git worktree add ../sphere-stage-2 stage/2-device-registry
# Или: make worktree-setup  (создаёт все сразу)
```

| Команда | Результат |
|---|---|
| `git add` + `git commit` + `git push origin stage/2-device-registry` | ✅ Разрешено |
| `git checkout <любая-ветка>` | ❌ ЗАПРЕЩЕНО — сломает изоляцию |
| `git merge` / `git rebase` | ❌ ЗАПРЕЩЕНО — только через PR |
| `git push --force` | ❌ Ruleset: non_fast_forward |
| PR `stage/2-device-registry` → `develop` | ✅ После 1 review + CI |

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `backend/api/v1/devices/` | `backend/main.py` 🔴 |
| `backend/api/v1/groups/` | `backend/core/` 🔴 |
| `backend/api/v1/bulk/` | `backend/models/` (только TZ-00 создаёт!) 🔴 |
| `backend/api/v1/discovery/` | `backend/core/config.py` 🔴 |
| `backend/services/device_*`, `backend/services/group_*` | `backend/database/` 🔴 |
| `backend/services/bulk_*`, `backend/services/discovery_*` | `backend/api/v1/auth/` (TZ-01!) 🔴 |
| `backend/services/device_status_cache.py` | `docker-compose*.yml` 🔴 |
| `backend/schemas/devices*`, `backend/schemas/bulk*`, `backend/schemas/discovery*` | Файлы других этапов 🔴 |
| `backend/tasks/sync_device_status.py`, `pc_agent/modules/adb_discovery.py` | |
| `tests/test_devices*`, `tests/test_groups*` | |

---

## Цель Сплита

Полный CRUD для устройств, валидация входных данных через Pydantic 2.0, защита от injection через whitelist паттернов.

---

## Шаг 1 — Schemas (Pydantic)

```python
# backend/schemas/devices.py
import re
from pydantic import BaseModel, field_validator, Field

DEVICE_ID_PATTERN = re.compile(r'^[a-zA-Z0-9:_-]{1,100}$')

class CreateDeviceRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100, description="ld:0, sphere_abc123")
    name: str | None = Field(None, max_length=255)
    type: Literal["ldplayer", "physical", "remote"]
    ip_address: str | None = None
    adb_port: int | None = Field(None, ge=1, le=65535)
    android_version: str | None = Field(None, max_length=20)
    device_model: str | None = Field(None, max_length=100)
    workstation_id: uuid.UUID | None = None
    group_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    
    @field_validator("id")
    @classmethod
    def validate_device_id(cls, v: str) -> str:
        if not DEVICE_ID_PATTERN.match(v):
            raise ValueError("Device ID must contain only letters, digits, ':', '_', '-'")
        return v
    
    @field_validator("ip_address")
    @classmethod
    def validate_ip(cls, v: str | None) -> str | None:
        if v is None:
            return None
        # Допустимы только IP адреса
        import ipaddress
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("Invalid IP address")
        return v

class DeviceResponse(BaseModel):
    id: str
    name: str | None
    type: str
    status: str
    ip_address: str | None
    adb_port: int | None
    android_version: str | None
    device_model: str | None
    workstation_id: uuid.UUID | None
    group_id: uuid.UUID | None
    tags: list[str]
    last_seen_at: datetime | None
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)
```

---

## Шаг 2 — Device Service

```python
# backend/services/device_service.py
class DeviceService:
    def __init__(self, db: AsyncSession, cache: CacheService):
        self.db = db
        self.cache = cache
    
    async def create_device(self, org_id: uuid.UUID, data: CreateDeviceRequest) -> Device:
        # Проверить что ID не занят
        existing = await self.db.get(Device, data.id)
        if existing:
            raise HTTPException(409, f"Device with ID '{data.id}' already exists")
        
        device = Device(org_id=org_id, **data.model_dump())
        self.db.add(device)
        return device
    
    async def list_devices(
        self,
        org_id: uuid.UUID,
        status: str | None = None,
        group_id: uuid.UUID | None = None,
        type_filter: str | None = None,
        search: str | None = None,
        page: int = 1,
        per_page: int = 50,
    ) -> tuple[list[Device], int]:
        stmt = select(Device).where(Device.org_id == org_id)
        count_stmt = select(func.count()).select_from(Device).where(Device.org_id == org_id)
        
        if status:
            stmt = stmt.where(Device.status == status)
            count_stmt = count_stmt.where(Device.status == status)
        if group_id:
            stmt = stmt.where(Device.group_id == group_id)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(or_(Device.id.ilike(like), Device.name.ilike(like)))
        
        total = (await self.db.execute(count_stmt)).scalar_one()
        devices = (await self.db.execute(
            stmt.order_by(Device.created_at.desc())
               .offset((page-1)*per_page).limit(per_page)
        )).scalars().all()
        
        return devices, total
    
    async def get_device_with_live_status(self, device_id: str, org_id: uuid.UUID) -> dict:
        """Объединяет DB данные с live статусом из Redis."""
        device = await self._get_device(device_id, org_id)
        live_status = await self.cache.get_device_status(device_id)
        
        return {
            **DeviceResponse.model_validate(device).model_dump(),
            "live": live_status,  # None если агент оффлайн
        }
    
    async def connect_adb(self, device_id: str, org_id: uuid.UUID):
        """Инициировать ADB подключение через PC Agent."""
        device = await self._get_device(device_id, org_id)
        if not device.workstation_id:
            raise HTTPException(400, "Device has no workstation assigned")
        
        # MED-9: sphere_agent_service был undefined reference.
        # Команда отправляется через PubSubPublisher (TZ-03), инжектируемый через DI.
        # DeviceService.__init__ принимает publisher: PubSubPublisher как зависимость.
        command_payload = {"type": "adb_connect", "device_id": device_id}
        await self.publisher.send_command_to_device(
            device_id=str(device.workstation_id),
            command=command_payload,
        )
        device.status = "connecting"
```

---

## Шаг 3 — Router

```python
# backend/api/v1/devices.py
router = APIRouter(prefix="/devices", tags=["devices"])

@router.get("", response_model=PaginatedResponse[DeviceResponse])
async def list_devices(
    status: str | None = None,
    group_id: uuid.UUID | None = None,
    search: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, le=200),
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
):
    devices, total = await svc.list_devices(
        current_user.org_id, status, group_id, search=search, page=page, per_page=per_page
    )
    return {"items": devices, "total": total, "page": page, "per_page": per_page}

@router.post("", response_model=DeviceResponse, status_code=201)
async def create_device(
    body: CreateDeviceRequest,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
):
    device = await svc.create_device(current_user.org_id, body)
    return device

@router.get("/{device_id}/status")
async def get_device_status(
    device_id: str,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
):
    return await svc.get_device_with_live_status(device_id, current_user.org_id)

@router.post("/{device_id}/connect", status_code=204)
async def connect_device(
    device_id: str,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
):
    await svc.connect_adb(device_id, current_user.org_id)

@router.get("/{device_id}/screenshot")
async def take_screenshot(
    device_id: str,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
):
    return await svc.request_screenshot(device_id, current_user.org_id)
```

---

## Критерии готовности

- [ ] GET /devices возвращает пагинированный список с фильтрацией
- [ ] Device ID с символами `; && |` → 422 Validation Error
- [ ] GET /devices/{id}/status возвращает DB данные + live Redis статус
- [ ] Устройства другой организации → 404
- [ ] ADB connect → команда ушла на PC Agent
- [ ] 100 устройств в тесте: list занимает < 50ms
