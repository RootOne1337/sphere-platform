# SPLIT-4 — Bulk Actions (Массовые операции с устройствами)

**ТЗ-родитель:** TZ-02-Device-Registry  
**Ветка:** `stage/2-device-registry`  
**Задача:** `SPHERE-014`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-02 SPLIT-5
**Интеграция при merge:** TZ-10 Frontend работает с mock bulk API

---

## Цель Сплита

Атомарные массовые операции: reboot, connect ADB, disconnect, assign group — с отчётом success/fail на каждое устройство.

---

## Шаг 1 — Bulk Action Schema

```python
# backend/schemas/bulk.py
class BulkActionType(str, Enum):
    REBOOT = "reboot"
    CONNECT_ADB = "connect_adb"
    DISCONNECT_ADB = "disconnect_adb"
    SET_GROUP = "set_group"
    SET_TAGS = "set_tags"
    SEND_COMMAND = "send_command"

class BulkActionRequest(BaseModel):
    action: BulkActionType
    device_ids: list[str] = Field(min_length=1, max_length=500)
    params: dict = Field(default_factory=dict)
    
    @model_validator(mode="after")
    def validate_params(self) -> "BulkActionRequest":
        if self.action == BulkActionType.SET_GROUP:
            if "group_id" not in self.params:
                raise ValueError("params.group_id required for set_group action")
        if self.action == BulkActionType.SEND_COMMAND:
            if "command_type" not in self.params:
                raise ValueError("params.command_type required")
        return self

class BulkActionItemResult(BaseModel):
    device_id: str
    success: bool
    error: str | None = None

class BulkActionResponse(BaseModel):
    total: int
    succeeded: int
    failed: int
    results: list[BulkActionItemResult]
```

---

## Шаг 2 — BulkActionService

```python
# backend/services/bulk_service.py
class BulkActionService:
    ACTIONS: dict[str, Callable] = {}
    
    async def execute(
        self,
        request: BulkActionRequest,
        org_id: uuid.UUID,
    ) -> BulkActionResponse:
        # Проверить что все устройства принадлежат org
        owned = await self.device_svc.filter_owned(request.device_ids, org_id)
        not_owned = set(request.device_ids) - set(owned)
        
        results: list[BulkActionItemResult] = []
        
        # Запускаем параллельно с ограничением concurrency
        semaphore = asyncio.Semaphore(50)  # max 50 параллельных операций
        
        async def execute_one(device_id: str) -> BulkActionItemResult:
            if device_id in not_owned:
                return BulkActionItemResult(
                    device_id=device_id, success=False, error="Device not found"
                )
            async with semaphore:
                try:
                    await self._dispatch(request.action, device_id, request.params, org_id)
                    return BulkActionItemResult(device_id=device_id, success=True)
                except Exception as e:
                    logger.warning(f"Bulk action failed for {device_id}: {e}")
                    return BulkActionItemResult(
                        device_id=device_id, success=False, error=str(e)[:200]
                    )
        
        tasks = [execute_one(did) for did in request.device_ids]
        results = await asyncio.gather(*tasks)
        
        succeeded = sum(1 for r in results if r.success)
        return BulkActionResponse(
            total=len(results),
            succeeded=succeeded,
            failed=len(results) - succeeded,
            results=results,
        )
    
    async def _dispatch(self, action: BulkActionType, device_id: str, params: dict, org_id: uuid.UUID):
        match action:
            case BulkActionType.REBOOT:
                await self._reboot_device(device_id, org_id)
            case BulkActionType.CONNECT_ADB:
                await self._connect_adb(device_id, org_id)
            case BulkActionType.DISCONNECT_ADB:
                await self._disconnect_adb(device_id, org_id)
            case BulkActionType.SET_GROUP:
                await self.group_svc.move_single(device_id, params["group_id"], org_id)
            case BulkActionType.SET_TAGS:
                await self.group_svc.set_device_tags(device_id, params.get("tags", []), org_id)
            case BulkActionType.SEND_COMMAND:
                await self._send_command(device_id, params, org_id)
    
    async def _reboot_device(self, device_id: str, org_id: uuid.UUID):
        device = await self.device_svc.get(device_id, org_id)
        if device.type == "ldplayer":
            await self.pc_agent_svc.send_command(
                str(device.workstation_id),
                {"type": "ldplayer_restart", "instance": str(device.id)}
            )
        else:
            # Physical device через ADB
            await self.adb_svc.execute_command(device_id, "reboot")
```

---

## Шаг 3 — Router

```python
# backend/api/v1/bulk.py
router = APIRouter(prefix="/devices/bulk", tags=["devices", "bulk"])

@router.post("/action", response_model=BulkActionResponse)
async def bulk_action(
    body: BulkActionRequest,
    current_user: User = require_permission("device:write"),
    svc: BulkActionService = Depends(get_bulk_service),
):
    """
    Массовая операция над устройствами.
    Max 500 устройств за раз.
    Возвращает результат для каждого устройства.
    """
    return await svc.execute(body, current_user.org_id)

@router.delete("", status_code=200, response_model=BulkDeleteResponse)
async def bulk_delete(
    body: BulkDeleteRequest,  # {device_ids: list[str]}
    current_user: User = require_permission("device:delete"),  # Требует org_admin или выше
    svc: DeviceService = Depends(get_device_service),
):
    """Массовое удаление устройств (soft delete — ставит deleted_at)."""
    deleted = await svc.bulk_soft_delete(body.device_ids, current_user.org_id)
    return {"deleted": deleted}
```

---

## Критерии готовности

- [ ] 500 устройств: bulk reboot завершается за < 10 секунд (asyncio.gather с semaphore=50)
- [ ] Устройства не из своей org → `success=False, error="Device not found"` (не 403)
- [ ] Один failed device не отменяет остальные
- [ ] Bulk delete требует роли `org_admin` или выше
- [ ] Результаты: succeeded + failed счётчики + per-device детали
