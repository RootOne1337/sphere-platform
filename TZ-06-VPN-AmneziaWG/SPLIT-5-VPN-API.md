# SPLIT-5 — VPN REST API (Endpoints для управления VPN)

**ТЗ-родитель:** TZ-06-VPN-AmneziaWG  
**Ветка:** `stage/6-vpn`  
**Задача:** `SPHERE-035`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Зависит от:** TZ-06 SPLIT-1 (Config), SPLIT-2 (Pool), SPLIT-3 (Self-Healing), SPLIT-4 (Kill Switch)
**Интеграция при merge:** TZ-10 Frontend `VPN Management` страница использует эти endpoints

> [!NOTE]
> **MERGE-12: При merge `stage/6-vpn` + `stage/10-frontend`:**
>
> 1. TZ-10 SPLIT-4 VPN-UI → заменить mock VPN API на реальные endpoints из `backend/api/v1/vpn/`
> 2. Проверить WebSocket events для VPN status → подключить к `sphere:org:events:{org_id}` канал

---

## Цель Сплита

REST API для VPN: назначение/отзыв peer, массовая ротация IP, статус пула, Kill Switch управление. Все endpoints защищены RBAC (`org_admin`+).

---

## Шаг 1 — Pydantic Schemas

```python
# backend/schemas/vpn.py
from pydantic import BaseModel, Field
from datetime import datetime

class VPNAssignRequest(BaseModel):
    device_id: str
    split_tunnel: bool = True    # True = весь трафик через VPN

class VPNAssignResponse(BaseModel):
    peer_id: str
    device_id: str
    assigned_ip: str
    config: str                  # AmneziaWG .conf
    qr_code: str                 # Base64 PNG QR-код
    
class VPNPeerResponse(BaseModel):
    id: str
    device_id: str | None
    assigned_ip: str
    status: str                  # free | assigned | error
    vpn_active: bool
    last_handshake_at: datetime | None
    created_at: datetime

class VPNPoolStats(BaseModel):
    total_ips: int
    allocated: int
    free: int
    active_tunnels: int          # vpn_active=True
    stale_handshakes: int        # handshake > 3 мин

class VPNBulkRotateRequest(BaseModel):
    device_ids: list[str] = Field(default=[], description="Пустой = все устройства org")
    reason: str = "scheduled_rotation"

class VPNBulkRotateResponse(BaseModel):
    total: int
    success: int
    failed: int
    details: list[dict]          # [{device_id, old_ip, new_ip, error}]

class KillSwitchRequest(BaseModel):
    device_ids: list[str]
    action: str = "enable"       # enable | disable
    method: str = "vpnservice"   # vpnservice | iptables
```

---

## Шаг 2 — VPN Router

```python
# backend/api/v1/vpn/router.py
from fastapi import APIRouter, Depends, HTTPException, Query
from backend.core.dependencies import get_current_user, get_tenant_db, require_role
from backend.services.vpn.pool_service import VPNPoolService
from backend.services.vpn.killswitch_service import KillSwitchService
from backend.services.vpn.ip_pool import IPPoolAllocator
from backend.schemas.vpn import *

router = APIRouter(prefix="/vpn", tags=["vpn"])


@router.post("/assign", response_model=VPNAssignResponse)
async def assign_vpn(
    req: VPNAssignRequest,
    db = Depends(get_tenant_db),
    current_user = Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(),
):
    """Назначить VPN peer устройству."""
    try:
        assignment = await pool_service.assign_vpn(
            device_id=req.device_id,
            org_id=current_user.org_id,
            split_tunnel=req.split_tunnel,
        )
        await db.commit()
        return assignment
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"VPN assignment failed: {e}")


@router.delete("/revoke/{device_id}", status_code=204)
async def revoke_vpn(
    device_id: str,
    db = Depends(get_tenant_db),
    current_user = Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(),
):
    """Отозвать VPN peer устройства."""
    await pool_service.revoke_vpn(device_id, current_user.org_id)
    await db.commit()


@router.get("/peers", response_model=list[VPNPeerResponse])
async def list_peers(
    status: str | None = Query(None, description="free|assigned|error"),
    device_id: str | None = None,
    db = Depends(get_tenant_db),
    current_user = Depends(require_role("device_manager")),
):
    """Список VPN peers организации."""
    query = select(VPNPeer).where(VPNPeer.org_id == current_user.org_id)
    
    if status:
        query = query.where(VPNPeer.status == VPNPeerStatus(status))
    if device_id:
        query = query.where(VPNPeer.device_id == device_id)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/pool/stats", response_model=VPNPoolStats)
async def pool_stats(
    db = Depends(get_tenant_db),
    current_user = Depends(require_role("device_manager")),
    ip_pool: IPPoolAllocator = Depends(),
):
    """Статистика VPN пула IP адресов."""
    from datetime import datetime, timezone, timedelta
    
    org_id = str(current_user.org_id)
    total = await ip_pool.pool_size(org_id)
    
    # Подсчёт из БД
    allocated = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == current_user.org_id,
            VPNPeer.status == VPNPeerStatus.ASSIGNED,
        )
    )
    active = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == current_user.org_id,
            VPNPeer.vpn_active == True,
        )
    )
    stale_threshold = datetime.now(timezone.utc) - timedelta(seconds=180)
    stale = await db.scalar(
        select(func.count(VPNPeer.id)).where(
            VPNPeer.org_id == current_user.org_id,
            VPNPeer.status == VPNPeerStatus.ASSIGNED,
            VPNPeer.last_handshake_at < stale_threshold,
        )
    )
    
    return VPNPoolStats(
        total_ips=total + allocated,
        allocated=allocated or 0,
        free=total,
        active_tunnels=active or 0,
        stale_handshakes=stale or 0,
    )


@router.post("/rotate", response_model=VPNBulkRotateResponse)
async def bulk_rotate(
    req: VPNBulkRotateRequest,
    db = Depends(get_tenant_db),
    current_user = Depends(require_role("org_admin")),
    pool_service: VPNPoolService = Depends(),
):
    """
    Массовая ротация IP: отозвать + назначить заново.
    Используется для периодической смены IP-адресов.
    """
    if not req.device_ids:
        # Ротация всех assigned peers
        result = await db.execute(
            select(VPNPeer.device_id).where(
                VPNPeer.org_id == current_user.org_id,
                VPNPeer.status == VPNPeerStatus.ASSIGNED,
                VPNPeer.device_id.isnot(None),
            )
        )
        req.device_ids = [r[0] for r in result.all()]
    
    details = []
    success = 0
    failed = 0
    
    for device_id in req.device_ids:
        try:
            # Получить текущий IP
            peer = await db.scalar(
                select(VPNPeer).where(
                    VPNPeer.device_id == device_id,
                    VPNPeer.org_id == current_user.org_id,
                    VPNPeer.status == VPNPeerStatus.ASSIGNED,
                )
            )
            old_ip = peer.assigned_ip if peer else None
            
            # Отозвать текущий
            await pool_service.revoke_vpn(device_id, current_user.org_id)
            
            # Назначить новый
            assignment = await pool_service.assign_vpn(
                device_id, current_user.org_id, split_tunnel=True
            )
            
            details.append({
                "device_id": device_id,
                "old_ip": old_ip,
                "new_ip": assignment.assigned_ip,
                "error": None,
            })
            success += 1
        except Exception as e:
            details.append({
                "device_id": device_id,
                "old_ip": None,
                "new_ip": None,
                "error": str(e),
            })
            failed += 1
    
    await db.commit()
    
    return VPNBulkRotateResponse(
        total=len(req.device_ids),
        success=success,
        failed=failed,
        details=details,
    )


@router.post("/killswitch")
async def manage_killswitch(
    req: KillSwitchRequest,
    current_user = Depends(require_role("org_admin")),
    killswitch_svc: KillSwitchService = Depends(),
):
    """Включить/выключить Kill Switch на устройствах."""
    if req.action == "enable":
        results = await killswitch_svc.bulk_enable(
            req.device_ids,
            vpn_endpoint="determined_from_config",
        )
    else:
        results = {}
        for device_id in req.device_ids:
            results[device_id] = await killswitch_svc.disable_killswitch(device_id)
    
    return {
        "action": req.action,
        "results": results,
        "total": len(req.device_ids),
        "success": sum(1 for v in results.values() if v),
    }
```

---

## Стратегия тестирования

### Fixture-зависимости

- `Device(id=uuid.UUID("a1b2c3d4-0000-0000-0000-000000005555"), org_id=TEST_ORG, status="online")`
- `VPNPeer(org_id=TEST_ORG, status=VPNPeerStatus.FREE, assigned_ip="10.100.0.1")`
- `User(org_id=TEST_ORG, role="org_admin")`

### Mock-зависимости

- `VPNPoolService.assign_vpn` → return mock `VPNAssignment`
- `IPPoolAllocator.pool_size` → return `1000`
- `PubSubPublisher.send_command_to_device` → `return True`

### Пример теста

```python
async def test_assign_vpn(client, db_session, mock_pool_service):
    resp = await client.post("/api/v1/vpn/assign", json={
        "device_id": "a1b2c3d4-0000-0000-0000-000000005555",
        "split_tunnel": True,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "assigned_ip" in data
    assert "qr_code" in data

async def test_pool_stats(client, db_session):
    resp = await client.get("/api/v1/vpn/pool/stats")
    assert resp.status_code == 200
    assert "total_ips" in resp.json()
```

---

## Критерии готовности

- [ ] `POST /vpn/assign` → назначает VPN, возвращает конфиг + QR
- [ ] `DELETE /vpn/revoke/{device_id}` → отзывает peer, IP возвращён в пул
- [ ] `GET /vpn/peers` → список peers с фильтрацией по статусу
- [ ] `GET /vpn/pool/stats` → статистика пула (total, allocated, free, active, stale)
- [ ] `POST /vpn/rotate` → массовая ротация IP
- [ ] `POST /vpn/killswitch` → включение/отключение Kill Switch
- [ ] Все endpoints защищены RBAC (`org_admin`+)
- [ ] Peers другой org → 404 (RLS изоляция)
