# SPLIT-2 — Device Groups & Tags

**ТЗ-родитель:** TZ-02-Device-Registry  
**Ветка:** `stage/2-device-registry`  
**Задача:** `SPHERE-012`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-02 SPLIT-3, SPLIT-4
**Интеграция при merge:** TZ-10 Frontend работает с mock groups API

---

## Цель Сплита

Группировка устройств по логическим группам (ферма, регион, проект). Теги для label-based фильтрации.

---

## Шаг 1 — Device Group Model

```python
# backend/models/device_group.py
class DeviceGroup(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "device_groups"
    __table_args__ = (
        UniqueConstraint("org_id", "name", name="uq_device_group_name"),
    )
    
    # FIX-2.2: Убран "schema": "sphere" — в TZ-00 схема sphere не создавалась,
    # все таблицы в public.
    org_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organizations.id"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(String(7))   # #RRGGBB
    parent_group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_groups.id", ondelete="SET NULL")
    )
    
    # Отношения
    devices: Mapped[list["Device"]] = relationship(back_populates="group")
    parent: Mapped["DeviceGroup | None"] = relationship(
        remote_side="DeviceGroup.id", back_populates="children"
    )
    children: Mapped[list["DeviceGroup"]] = relationship(back_populates="parent")
```

---

## Шаг 2 — Tags (PostgreSQL Array)

```python
# В Device модели добавить
from sqlalchemy.dialects.postgresql import ARRAY

class Device(UUIDMixin, TimestampMixin, Base):
    # ... existing fields ...
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(50)),
        server_default="{}",
        default=list,
    )
    group_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("device_groups.id", ondelete="SET NULL"),
        index=True,
    )
```

```sql
-- Миграция: индекс для поиска по тегам
CREATE INDEX idx_devices_tags ON devices USING GIN (tags);
```

---

## Шаг 3 — Group Service

```python
# backend/services/group_service.py
class GroupService:
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def get_group_stats(self, org_id: uuid.UUID) -> list[dict]:
        """Статистика по группам: кол-во устройств, онлайн/оффлайн."""
        stmt = (
            select(
                DeviceGroup.id,
                DeviceGroup.name,
                DeviceGroup.color,
                func.count(Device.id).label("total"),
                func.sum(case((Device.status == "online", 1), else_=0)).label("online"),
            )
            .outerjoin(Device, Device.group_id == DeviceGroup.id)
            .where(DeviceGroup.org_id == org_id)
            .group_by(DeviceGroup.id)
        )
        rows = (await self.db.execute(stmt)).all()
        return [{"id": r.id, "name": r.name, "color": r.color, "total": r.total, "online": r.online} for r in rows]
    
    async def move_devices_to_group(
        self,
        device_ids: list[str],
        group_id: uuid.UUID | None,
        org_id: uuid.UUID,
    ) -> int:
        """Переместить несколько устройств в группу (или убрать из группы)."""
        stmt = (
            update(Device)
            .where(Device.id.in_(device_ids), Device.org_id == org_id)
            .values(group_id=group_id)
        )
        result = await self.db.execute(stmt)
        return result.rowcount
    
    async def set_device_tags(self, device_id: str, tags: list[str], org_id: uuid.UUID):
        """Заменить теги устройства (идемпотентно)."""
        if len(tags) > 20:
            raise HTTPException(400, "Maximum 20 tags per device")
        # Нормализуем теги
        clean_tags = [re.sub(r'[^\w-]', '', t.lower().strip())[:50] for t in tags if t.strip()]
        
        stmt = (
            update(Device)
            .where(Device.id == device_id, Device.org_id == org_id)
            .values(tags=clean_tags)
            .returning(Device.id)
        )
        result = (await self.db.execute(stmt)).scalar_one_or_none()
        if not result:
            raise HTTPException(404, f"Device '{device_id}' not found")
    
    async def list_all_tags(self, org_id: uuid.UUID) -> list[str]:
        """Все уникальные теги в организации (для автодополнения)."""
        stmt = select(func.unnest(Device.tags)).where(Device.org_id == org_id).distinct()
        rows = (await self.db.execute(stmt)).scalars().all()
        return sorted(rows)
```

---

## Шаг 4 — Groups Router

```python
# backend/api/v1/groups.py
router = APIRouter(prefix="/groups", tags=["groups"])

@router.get("", response_model=list[GroupResponse])
async def list_groups(
    current_user: User = require_permission("device:read"),
    svc: GroupService = Depends(get_group_service),
):
    return await svc.get_group_stats(current_user.org_id)

@router.post("", response_model=GroupResponse, status_code=201)
async def create_group(body: CreateGroupRequest, ...): ...

@router.put("/{group_id}", response_model=GroupResponse)
async def update_group(group_id: uuid.UUID, body: UpdateGroupRequest, ...): ...

@router.delete("/{group_id}", status_code=204)
async def delete_group(group_id: uuid.UUID, ...): ...

@router.post("/{group_id}/devices/move", status_code=204)
async def move_devices(
    group_id: uuid.UUID,
    body: MoveDevicesRequest,  # {device_ids: list[str]}
    current_user: User = require_permission("device:write"),
    svc: GroupService = Depends(get_group_service),
):
    moved = await svc.move_devices_to_group(body.device_ids, group_id, current_user.org_id)
    return {"moved": moved}

# Tags
@router.get("/tags", response_model=list[str])
async def list_tags(current_user: User = require_permission("device:read"), ...):
    return await svc.list_all_tags(current_user.org_id)

@router.put("/devices/{device_id}/tags", status_code=204)
async def set_device_tags(
    device_id: str,
    body: SetTagsRequest,  # {tags: list[str]}
    ...
):
    await svc.set_device_tags(device_id, body.tags, current_user.org_id)
```

---

## Критерии готовности

- [ ] Создание/редактирование/удаление групп с цветом и иерархией
- [ ] Массовое перемещение устройств в группу
- [ ] GIN-индекс по тегам — поиск по тегу < 10ms на 10k устройств
- [ ] Теги нормализуются (lowercase, никаких спецсимволов)
- [ ] GET /groups возвращает счётчики online/total для каждой группы
- [ ] Автодополнение тегов /groups/tags
