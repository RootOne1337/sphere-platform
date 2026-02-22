# SPLIT-3 — RBAC: Роли, Permissions, Middleware

**ТЗ-родитель:** TZ-01-Auth-Service  
**Ветка:** `stage/1-auth`  
**Задача:** `SPHERE-008`  
**Исполнитель:** Backend  
**Оценка:** 1 рабочий день  
**Блокирует:** TZ-01 SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-02 и TZ-04 работают с mock RBAC; при merge подключить реальные декораторы авторизации

---

## Цель Сплита

Реализовать Role-Based Access Control с 7 ролями и декораторами для endpoints.

---

## Шаг 1 — Матрица ролей

```python
# backend/core/rbac.py
from enum import Enum

class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    ORG_OWNER = "org_owner"
    ORG_ADMIN = "org_admin"
    DEVICE_MANAGER = "device_manager"
    SCRIPT_RUNNER = "script_runner"
    VIEWER = "viewer"
    API_USER = "api_user"

# Иерархия (включает все нижние роли)
ROLE_HIERARCHY = {
    Role.SUPER_ADMIN:     {Role.SUPER_ADMIN, Role.ORG_OWNER, Role.ORG_ADMIN, Role.DEVICE_MANAGER, Role.SCRIPT_RUNNER, Role.VIEWER},
    Role.ORG_OWNER:       {Role.ORG_OWNER, Role.ORG_ADMIN, Role.DEVICE_MANAGER, Role.SCRIPT_RUNNER, Role.VIEWER},
    Role.ORG_ADMIN:       {Role.ORG_ADMIN, Role.DEVICE_MANAGER, Role.SCRIPT_RUNNER, Role.VIEWER},
    Role.DEVICE_MANAGER:  {Role.DEVICE_MANAGER, Role.SCRIPT_RUNNER, Role.VIEWER},
    Role.SCRIPT_RUNNER:   {Role.SCRIPT_RUNNER, Role.VIEWER},
    Role.VIEWER:          {Role.VIEWER},
    Role.API_USER:        {Role.API_USER},
}

# Что может каждая роль
PERMISSIONS = {
    # Устройства
    "device:read":          [Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "device:write":         [Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "device:delete":        [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "device:bulk_action":   [Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    
    # Скрипты
    "script:read":          [Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "script:write":         [Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "script:execute":       [Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    
    # VPN
    "vpn:read":             [Role.VIEWER, Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "vpn:write":            [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "vpn:mass_operation":   [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    
    # Пользователи
    "user:read":            [Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
    "user:write":           [Role.ORG_OWNER, Role.SUPER_ADMIN],
    
    # Мониторинг
    "monitoring:read":      [Role.VIEWER, Role.SCRIPT_RUNNER, Role.DEVICE_MANAGER, Role.ORG_ADMIN, Role.ORG_OWNER, Role.SUPER_ADMIN],
}

def has_permission(user_role: str, permission: str) -> bool:
    allowed_roles = PERMISSIONS.get(permission, [])
    return Role(user_role) in allowed_roles
```

---

## Шаг 2 — FastAPI Dependencies

```python
# backend/core/dependencies.py

def require_roles(roles: list[str]):
    """Декоратор: требует одну из указанных ролей."""
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Required roles: {roles}. Your role: {current_user.role}"
            )
        return current_user
    return Depends(dependency)

def require_permission(permission: str):
    """Декоратор: требует право на действие."""
    async def dependency(current_user: User = Depends(get_current_user)) -> User:
        if not has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: {permission}"
            )
        return current_user
    return Depends(dependency)

def require_same_org(org_id: uuid.UUID, current_user: User = Depends(get_current_user)):
    """Проверить что ресурс принадлежит организации текущего пользователя."""
    if current_user.role != "super_admin" and current_user.org_id != org_id:
        raise HTTPException(403, "Access to resource from another organization denied")

# Алиас для обратной совместимости (require_role == require_roles)
require_role = require_roles

# Dependency factory для AuditLogService
def get_audit_service(db: AsyncSession = Depends(get_db)) -> "AuditLogService":
    from backend.services.audit_log_service import AuditLogService
    return AuditLogService(db)

# Использование в endpoints:
# @router.delete("/devices/{id}")
# async def delete_device(
#     id: str,
#     current_user: User = require_permission("device:delete"),
# ):
```

---

## Шаг 3 — org_id фильтрация (tenant isolation)

```python
# backend/services/device_service.py
class DeviceService:
    async def list_devices(self, org_id: uuid.UUID, filters: DeviceFilters) -> list[Device]:
        """ВСЕГДА фильтруем по org_id — нельзя видеть чужие устройства."""
        stmt = select(Device).where(
            Device.org_id == org_id,  # ← обязательно!
            Device.status.in_(filters.statuses) if filters.statuses else True,
        )
        return (await self.db.execute(stmt)).scalars().all()
    
    async def get_device(self, device_id: str, org_id: uuid.UUID) -> Device:
        device = await self.db.get(Device, device_id)
        if not device or device.org_id != org_id:
            raise HTTPException(404, "Device not found")  # 404 а не 403 (не раскрывать существование)
        return device
```

---

## Критерии готовности

- [ ] Viewer → GET /devices → 200, POST /devices → 403
- [ ] Device Manager → POST /devices → 200, DELETE /devices → 403
- [ ] Org Admin → DELETE /devices → 200
- [ ] Пользователь из org A не видит устройства org B (404)
- [ ] super_admin видит ресурсы любой организации
- [ ] Матрица прав задокументирована и протестирована
