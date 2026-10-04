# backend/api/v1/devices/router.py
# ВЛАДЕЛЕЦ: TZ-02 SPLIT-1. Device CRUD router.
# Авто-дискавери: main.py подключает все backend/api/v1/*/router.py автоматически.
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi import status as http_status
from pydantic import BaseModel, Field
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import require_permission
from backend.database.engine import get_db
from backend.database.redis_client import get_redis_binary
from backend.models.user import User
from backend.schemas.device_register import (
    DeviceRegisterRequest,
    DeviceRegisterResponse,
)
from backend.schemas.device_status import (
    BulkStatusRequest,
    FleetStatusResponse,
    FleetSummaryResponse,
)
from backend.schemas.devices import (
    CreateDeviceRequest,
    DeviceListResponse,
    DeviceResponse,
    DeviceStatusCounts,
    DeviceStatusResponse,
    UpdateDeviceRequest,
)
from backend.schemas.stream_diagnostics import StreamDiagnosticsResponse
from backend.schemas.ui_hierarchy import UiHierarchyResponse
from backend.services.api_key_service import APIKeyService
from backend.services.cache_service import CacheService
from backend.services.device_registration_service import DeviceRegistrationService
from backend.services.device_service import DeviceService
from backend.services.device_status_cache import DeviceStatusCache

router = APIRouter(prefix="/devices", tags=["devices"])
logger = logging.getLogger(__name__)


def get_device_service(db: AsyncSession = Depends(get_db)) -> DeviceService:
    """
    DI-фабрика для DeviceService.
    FastAPI дедуплицирует Depends(get_db) — в одном запросе все зависимости
    получат одну и ту же сессию, что позволяет роутеру вызвать db.commit().
    """
    return DeviceService(db, CacheService())


async def get_status_cache(
    redis=Depends(get_redis_binary),
) -> DeviceStatusCache:
    return DeviceStatusCache(redis)


# ── List ──────────────────────────────────────────────────────────────────────


@router.get(
    "/me",
    response_model=DeviceResponse | None,
    summary="Информация об устройстве по X-API-Key (для агента)",
    tags=["devices"],
)
async def get_device_me(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceResponse | None:
    """
    Аутентификация по X-API-Key. Возвращает устройство или 404 если не найдено.
    Используется агентом при zero-touch enrollment для верификации ключа.
    """
    from fastapi import HTTPException

    if not x_api_key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED, detail="X-API-Key required"
        )
    from backend.services.api_key_service import APIKeyService

    api_key_svc = APIKeyService(db)
    key = await api_key_svc.authenticate(x_api_key)
    if not key:
        raise HTTPException(status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    # Key is valid — try to find the device by X-Device-Id header
    if x_device_id:
        try:
            device_uuid = uuid.UUID(x_device_id)
            device = await svc.get_device(device_uuid, key.org_id)
            if device:
                return DeviceResponse.model_validate(device)
        except (ValueError, Exception):
            pass
    return None


@router.get(
    "",
    response_model=DeviceListResponse,
    summary="Список устройств с пагинацией и фильтрацией",
    description=(
        "Возвращает одну страницу данных и live status counts для всей отфильтрованной области. "
        "Для точных live counts backend читает presence всех ID области одним Redis MGET; "
        "размер ответа ограничен per_page, но работа подсчёта пока O(N)."
    ),
)
async def list_devices(
    status: str | None = Query(None, description="Legacy DB last_status filter; use live_status for current reachability."),
    group_id: uuid.UUID | None = Query(None, description="Filter by an organization-owned group UUID."),
    location_id: uuid.UUID | None = Query(None, description="Filter by an organization-owned location UUID."),
    type_filter: str | None = Query(None, alias="type", description="Device type stored at enrollment, such as ldplayer, physical, or remote."),
    search: str | None = Query(None, description="Case-insensitive name, serial, or model search; exact full UUID is also supported."),
    live_status: Literal["online", "busy", "connecting", "offline", "attention"] | None = Query(
        None,
        description="Current Redis presence filter. online includes busy; attention includes error, maintenance, and unknown.",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=5000),
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> DeviceListResponse:
    # Read the small inventory projection once, then use one Redis MGET for both
    # exact live-status counts and page selection. The response body remains bounded
    # by per_page instead of serializing every device for the Fleet Matrix.
    candidates = await svc.list_device_status_candidates(
        org_id=current_user.org_id,
        status=status,
        group_id=group_id,
        location_id=location_id,
        type_filter=type_filter,
        search=search,
    )
    candidate_ids = [device_id for device_id, _ in candidates]
    live_statuses = {}
    presence_available = False
    if status_cache.redis is not None:
        try:
            live_statuses = await status_cache.bulk_get_status([str(device_id) for device_id in candidate_ids])
            presence_available = True
        except (RedisError, OSError, TimeoutError) as exc:
            # An initialized Redis client does not prove the live-presence read
            # succeeded. Keep the inventory available and surface status as unknown.
            logger.warning(
                "Device presence lookup failed (%s); returning unknown live state",
                type(exc).__name__,
            )
    as_of = datetime.now(timezone.utc)

    effective_statuses: dict[uuid.UUID, str] = {}
    status_counts = {"online": 0, "busy": 0, "connecting": 0, "offline": 0, "issues": 0}
    for device_id, db_status in candidates:
        live = live_statuses.get(str(device_id))
        effective: str
        if live:
            effective = live.status
        elif not presence_available:
            # Without Redis we cannot infer liveness from a stale DB snapshot.
            effective = "unknown"
        elif db_status in {"error", "maintenance"}:
            effective = db_status
        else:
            # Redis is reachable and the TTL-backed presence key is absent.
            effective = "offline"
        if effective not in {"online", "busy", "connecting", "offline", "error", "maintenance"}:
            effective = "unknown"
        effective_statuses[device_id] = effective
        if effective in {"online", "busy"}:
            status_counts["online"] += 1
        if effective == "busy":
            status_counts["busy"] += 1
        elif effective == "connecting":
            status_counts[effective] += 1
        elif effective == "offline":
            status_counts["offline"] += 1
        elif effective in {"error", "maintenance", "unknown"}:
            status_counts["issues"] += 1

    scope_total = len(candidate_ids)
    matching_ids = candidate_ids
    if live_status == "online":
        matching_ids = [did for did in candidate_ids if effective_statuses[did] in {"online", "busy"}]
    elif live_status == "attention":
        matching_ids = [did for did in candidate_ids if effective_statuses[did] in {"error", "maintenance", "unknown"}]
    elif live_status:
        matching_ids = [did for did in candidate_ids if effective_statuses[did] == live_status]

    total = len(matching_ids)
    page_ids = matching_ids[(page - 1) * per_page : page * per_page]
    devices = await svc.get_devices_by_ids(page_ids, current_user.org_id)
    # Enrich only the returned page; aggregate candidates were read through one MGET.
    for device in devices:
        device.status = effective_statuses.get(device.id, "unknown")
        live = live_statuses.get(str(device.id))
        if live:
            device.status = live.status
            device.battery_level = live.battery
            device.cpu_usage = live.cpu_usage
            device.ram_usage_mb = live.ram_usage_mb
            device.screen_on = live.screen_on
            device.adb_connected = live.adb_connected
            device.vpn_active = live.vpn_active
            device.last_heartbeat = live.last_heartbeat
            device.connected_since = live.connected_since
            device.agent_version = live.agent_version
            device.agent_version_code = live.agent_version_code
    pages = (total + per_page - 1) // per_page if total > 0 else 0
    return DeviceListResponse(
        items=devices,
        total=total,
        page=page,
        per_page=per_page,
        pages=pages,
        scope_total=scope_total,
        status_counts=DeviceStatusCounts(**status_counts),
        presence_available=presence_available,
        as_of=as_of,
    )


# ── Fleet status (bulk MGET) ──────────────────────────────────────────────────
# NOTE: These routes MUST appear before /{device_id} routes so FastAPI
# doesn't try to coerce "status" into a UUID.


@router.post(
    "/status/bulk",
    response_model=FleetStatusResponse,
    summary="Live статус для batch устройств (MGET — одна RTT до Redis)",
)
async def get_bulk_status(
    body: BulkStatusRequest,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> FleetStatusResponse:
    """Bulk live status для Dashboard. Возвращает только устройства этой org."""
    owned = await svc.filter_owned(body.device_ids, current_user.org_id)
    summary = await status_cache.get_fleet_summary(owned)
    return FleetStatusResponse(**summary)


@router.get(
    "/status/fleet",
    response_model=FleetSummaryResponse,
    summary="Сводный статус всего fleet организации",
)
async def get_fleet_status(
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> FleetSummaryResponse:
    """Total/online/busy/connecting/offline aggregation for Fleet Dashboard."""
    all_ids = await svc.get_all_device_ids(current_user.org_id)
    summary = await status_cache.get_fleet_summary(all_ids)
    return FleetSummaryResponse(
        total=summary["total"],
        online=summary["online"],
        busy=summary["busy"],
        connecting=summary["connecting"],
        offline=summary["offline"],
    )


@router.post("/refresh", response_model=DeviceRegisterResponse)
async def refresh_device(
    refresh_token: str | None = Cookie(default=None),
    refresh_request_id: uuid.UUID | None = Header(
        default=None, alias="X-Refresh-Request-Id",
        description="Persist before sending; reuse with the same refresh token to recover a lost response.",
    ),
    db: AsyncSession = Depends(get_db),
) -> DeviceRegisterResponse:
    if not refresh_token or len(refresh_token) > 512:
        raise HTTPException(status_code=401, detail="Device refresh token required")
    return await DeviceRegistrationService(db).refresh_device_token(refresh_token, refresh_request_id)


# ── Auto-register (TZ-12 Agent Discovery) ────────────────────────────────────


@router.post(
    "/register",
    response_model=DeviceRegisterResponse,
    status_code=201,
    summary="Автоматическая регистрация устройства (для агентов)",
    description=(
        "Автоматическая регистрация нового устройства. "
        "Аутентификация по enrollment API-ключу (X-API-Key с правом device:register). "
        "Идемпотентна по fingerprint и instance_binding. "
        "Копии APK с разными привязками VM получают отдельные устройства."
    ),
)
async def register_device(
    body: DeviceRegisterRequest,
    x_api_key: str = Header(alias="X-API-Key"),
    db: AsyncSession = Depends(get_db),
) -> DeviceRegisterResponse:
    """
    Автоматическая регистрация устройства при первом подключении.

    Требования к API-ключу:
    - Право 'device:register' в permissions
    - Активный, не истёкший

    Идемпотентность:
    - Повторный вызов с тем же fingerprint и instance_binding возвращает то же устройство.
    - Первый bound-клиент сохраняет старую карточку; остальные клоны получают новые.
    """
    from fastapi import HTTPException

    # Аутентификация API-ключа
    api_key_svc = APIKeyService(db)
    key = await api_key_svc.authenticate(x_api_key)
    if not key:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный или истёкший API-ключ",
        )

    # Проверка права device:register
    if "device:register" not in (key.permissions or []):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="API-ключ не имеет права device:register",
        )

    # Регистрация
    reg_svc = DeviceRegistrationService(db)
    result = await reg_svc.register_device(org_id=key.org_id, data=body)
    await db.commit()
    return result


# ── Create ────────────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=DeviceResponse,
    status_code=201,
    summary="Создать устройство",
)
async def create_device(
    body: CreateDeviceRequest,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    result = await svc.create_device(current_user.org_id, body)
    await db.commit()
    return result


# ── Get one ───────────────────────────────────────────────────────────────────


@router.get(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Получить устройство по ID",
)
async def get_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> DeviceResponse:
    device = await svc.get_device(device_id, current_user.org_id)
    live = await status_cache.get_status(str(device_id))
    if live:
        device.status = live.status
        device.battery_level = live.battery
        device.cpu_usage = live.cpu_usage
        device.ram_usage_mb = live.ram_usage_mb
        device.screen_on = live.screen_on
        device.adb_connected = live.adb_connected
        device.vpn_active = live.vpn_active
        device.last_heartbeat = live.last_heartbeat
        device.connected_since = live.connected_since
        device.agent_version = live.agent_version
        device.agent_version_code = live.agent_version_code
    return device


# ── Update ────────────────────────────────────────────────────────────────────


@router.put(
    "/{device_id}",
    response_model=DeviceResponse,
    summary="Обновить устройство",
)
async def update_device(
    device_id: uuid.UUID,
    body: UpdateDeviceRequest,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
) -> DeviceResponse:
    result = await svc.update_device(device_id, current_user.org_id, body)
    await db.commit()
    return result


# ── Delete ────────────────────────────────────────────────────────────────────


@router.delete(
    "/{device_id}",
    status_code=204,
    response_model=None,
    summary="Убрать устройство из активного каталога, сохранив историю",
)
async def delete_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:delete"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.delete_device(device_id, current_user.org_id)
    await db.commit()


# ── Status (live Redis) ───────────────────────────────────────────────────────


@router.get(
    "/{device_id}/status",
    response_model=DeviceStatusResponse,
    summary="DB данные + live Redis статус устройства",
)
async def get_device_status(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> DeviceStatusResponse:
    return await svc.get_device_with_live_status(device_id, current_user.org_id)


@router.get(
    "/{device_id}/stream-diagnostics",
    response_model=StreamDiagnosticsResponse,
    summary="Последний подтверждённый heartbeat-отчёт о стадиях Android-стрима",
)
async def get_device_stream_diagnostics(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
    status_cache: DeviceStatusCache = Depends(get_status_cache),
) -> StreamDiagnosticsResponse:
    """Return bounded Android stage counters with explicit freshness semantics."""
    # Verify tenant ownership before looking up any device-keyed live telemetry.
    await svc.get_device(device_id, current_user.org_id)
    device_key = str(device_id)
    live = await status_cache.get_status(device_key)
    snapshot = await status_cache.get_stream_diagnostics(device_key)
    now = datetime.now(timezone.utc)

    def age_seconds(observed_at: datetime | None) -> float | None:
        if observed_at is None:
            return None
        if observed_at.tzinfo is None:
            observed_at = observed_at.replace(tzinfo=timezone.utc)
        return max(0.0, (now - observed_at).total_seconds())

    heartbeat_age = age_seconds(live.last_heartbeat if live else None)
    snapshot_age = age_seconds(snapshot.observed_at if snapshot else None)
    heartbeat_fresh = (
        live is not None
        and live.status in ("online", "busy")
        and heartbeat_age is not None
        and heartbeat_age <= 75
    )
    state: Literal["active_report", "not_streaming", "stale", "unavailable"]
    if not heartbeat_fresh:
        state = "stale" if snapshot is not None else "unavailable"
    elif snapshot is None:
        state = "not_streaming"
    elif snapshot_age is None or snapshot_age > 75:
        state = "stale"
    else:
        # The agent only reports its local capture stages. This does not prove
        # the backend received a picture NAL or that a viewer rendered it.
        state = "active_report"

    return StreamDiagnosticsResponse(
        device_id=device_key,
        state=state,
        agent_status=live.status if live else None,
        last_heartbeat=live.last_heartbeat if live else None,
        age_seconds=snapshot_age,
        diagnostics=snapshot,
    )


# ── ADB Connect ───────────────────────────────────────────────────────────────


@router.post(
    "/{device_id}/connect",
    status_code=204,
    response_model=None,
    summary="Инициировать ADB подключение через PC Agent (TZ-03 stub)",
)
async def connect_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    db: AsyncSession = Depends(get_db),
):
    await svc.connect_adb(device_id, current_user.org_id)
    await db.commit()


# ── Screenshot ────────────────────────────────────────────────────────────────


@router.get(
    "/{device_id}/screenshot",
    summary="Запросить скриншот устройства (TZ-03 stub)",
)
async def take_screenshot(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:read"),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    return await svc.request_screenshot(device_id, current_user.org_id)


# ── Shell (TTY over HTTP) ─────────────────────────────────────────────────────


async def _request_interactive_command(
    device_id: uuid.UUID, user: User, svc: DeviceService,
    kind: str, payload: dict, timeout: float, *, accept_progress: bool = False,
) -> dict:
    import time

    from backend.websocket.pubsub_router import get_pubsub_publisher

    # Authorize against SQL before publishing to any worker's device channel.
    await svc.get_device(device_id, user.org_id)
    publisher = get_pubsub_publisher()
    if publisher is None:
        raise HTTPException(503, "Device command transport is unavailable")
    result = await publisher.send_command_wait_result(str(device_id), {
        "type": kind,
        # Bare UUIDs identify durable SQL tasks in the result handler. These
        # live-only RPC receipts must remain distinct even after waiter timeout.
        "command_id": f"interactive_{uuid.uuid4()}",
        "payload": payload,
        "signed_at": int(time.time()),
        "ttl_seconds": max(15, int(timeout)),
    }, timeout=timeout, live_only=True, accept_progress=accept_progress)
    allowed = {"completed", "failed"} | ({"received", "running"} if accept_progress else set())
    if result.get("status") not in allowed:
        raise HTTPException(502, "Invalid device command result")
    return result


class ExecuteShellRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4096)


@router.post("/{device_id}/ui-hierarchy", response_model=UiHierarchyResponse,
             summary="Прочитать ограниченный снимок дерева Android UI Automator")
async def request_ui_hierarchy(
    device_id: uuid.UUID,
    response: Response,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    redis=Depends(get_redis_binary),
) -> UiHierarchyResponse:
    from backend.services.ui_hierarchy import InvalidUiHierarchy, display_size, parse_hierarchy

    response.headers["Cache-Control"] = "no-store"

    # This uses the existing root SHELL capability, so it retains its stronger
    # permission even though every command below is a fixed read/cleanup.
    await svc.get_device(device_id, current_user.org_id)
    if redis is None:
        raise HTTPException(503, "UI inspection lock unavailable")
    snapshot_id = uuid.uuid4().hex
    key = f"sphere:ui-inspection:{current_user.org_id}:{device_id}"
    try:
        acquired = await redis.set(key, snapshot_id, nx=True, ex=60)
    except RedisError as exc:
        raise HTTPException(503, "UI inspection lock unavailable") from exc
    if not acquired:
        raise HTTPException(429, "UI inspection already in progress")
    path = f"/data/local/tmp/sphere-ui-{snapshot_id}.xml"
    requested_at = datetime.now(timezone.utc)
    snapshot: UiHierarchyResponse | None = None

    async def shell(command: str) -> str:
        result = await _request_interactive_command(device_id, current_user, svc, "SHELL", {"cmd": command}, 8.0)
        receipt = result.get("result")
        output = receipt.get("output") if isinstance(receipt, dict) else None
        if result.get("status") != "completed" or not isinstance(output, str):
            raise HTTPException(502, "Android UI inspection unavailable: root/UI Automator command failed")
        return output

    try:
        async with asyncio.timeout(40):
            before = display_size(await shell("wm size"))
            await shell(f"uiautomator dump {path}")
            xml = await shell(f"cat {path}")
            after = display_size(await shell("wm size"))
            if before != after:
                raise HTTPException(409, "Android display geometry changed; request a new snapshot")
            width, height, rotation, nodes = parse_hierarchy(xml, after)
        snapshot = UiHierarchyResponse(device_id=str(device_id), snapshot_id=snapshot_id,
                                       requested_at=requested_at, completed_at=datetime.now(timezone.utc),
                                       width=width, height=height, rotation=rotation, nodes=nodes)
        return snapshot
    except InvalidUiHierarchy as exc:
        raise HTTPException(502, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(504, "Android UI snapshot deadline exceeded; no automatic retry") from exc
    finally:
        # Unique UUID-owned path; do not delete any other dump. Cleanup failure
        # is recorded without logging the potentially sensitive node text/XML.
        try:
            await shell(f"rm -f {path}")
            if snapshot is not None:
                snapshot.temporary_file_cleanup_confirmed = True
        except Exception:
            logger.warning("ui_inspection_cleanup_unconfirmed", extra={"device_id": str(device_id), "snapshot_id": snapshot_id})
        try:
            await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
                             1, key, snapshot_id)
        except RedisError:
            logger.warning("ui_inspection_lock_release_unconfirmed", extra={"device_id": str(device_id)})


@router.post("/{device_id}/screenshot/native", response_class=Response,
             responses={200: {"content": {"image/png": {}}}},
             summary="Получить исходный PNG экрана через APK, без видеоперекодирования")
async def request_native_screenshot(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:write"),
    svc: DeviceService = Depends(get_device_service),
    redis=Depends(get_redis_binary),
) -> Response:
    import structlog

    from backend.services.native_screenshot import CaptureTrace, InvalidScreenshot, capture_png
    from backend.services.ui_hierarchy import InvalidUiHierarchy

    await svc.get_device(device_id, current_user.org_id)
    if redis is None:
        raise HTTPException(503, "Screenshot lock unavailable")
    snapshot_id = uuid.uuid4().hex
    key = f"sphere:native-screenshot:{current_user.org_id}:{device_id}"
    try:
        acquired = await redis.set(key, snapshot_id, nx=True, ex=120)
    except RedisError as exc:
        raise HTTPException(503, "Screenshot lock unavailable") from exc
    if not acquired:
        raise HTTPException(429, "Screenshot capture already in progress")

    async def shell(command: str) -> str:
        result = await _request_interactive_command(device_id, current_user, svc, "SHELL", {"cmd": command}, 8.0)
        receipt = result.get("result")
        output = receipt.get("output") if isinstance(receipt, dict) else None
        if result.get("status") != "completed" or not isinstance(output, str):
            raise HTTPException(502, "Original screenshot unavailable: Android root command failed")
        return output

    requested_at = datetime.now(timezone.utc)
    trace = CaptureTrace()
    response_status = 500

    def trace_headers() -> dict[str, str]:
        headers = {"X-Screenshot-Id": snapshot_id, "X-Screenshot-Elapsed-Ms": str(trace.elapsed_ms),
                   "X-Screenshot-Cleanup-Confirmed": str(trace.cleanup_confirmed).lower(),
                   "Cache-Control": "no-store"}
        if trace.failure_phase is not None:
            headers["X-Screenshot-Failed-Phase"] = trace.failure_phase
        return headers

    try:
        screenshot = await capture_png(shell, snapshot_id, trace=trace)
        response_status = 200
        return Response(screenshot.data, media_type="image/png", headers={
            **trace_headers(),
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'attachment; filename="sphere-{device_id}-{snapshot_id}.png"',
            "X-Screenshot-Device-Id": str(device_id), "X-Screenshot-Id": snapshot_id,
            "X-Screenshot-SHA256": screenshot.sha256,
            "X-Screenshot-Android-SHA256": screenshot.sha256,
            "X-Screenshot-Width": str(screenshot.width), "X-Screenshot-Height": str(screenshot.height),
            "X-Screenshot-Requested-At": requested_at.isoformat(),
            "X-Screenshot-Completed-At": datetime.now(timezone.utc).isoformat(),
            "X-Screenshot-Cleanup-Confirmed": str(screenshot.cleanup_confirmed).lower(),
        })
    except (InvalidScreenshot, InvalidUiHierarchy) as exc:
        response_status = 502
        raise HTTPException(502, str(exc), headers=trace_headers()) from exc
    except TimeoutError as exc:
        response_status = 504
        raise HTTPException(504, "Original screenshot deadline exceeded; no automatic retry", headers=trace_headers()) from exc
    except HTTPException as exc:
        response_status = exc.status_code
        raise HTTPException(exc.status_code, exc.detail, headers={**(exc.headers or {}), **trace_headers()}) from exc
    except asyncio.CancelledError:
        response_status = 499
        raise
    finally:
        structlog.get_logger(__name__).info("native_screenshot.finished",
            device_id=str(device_id), snapshot_id=snapshot_id, http_status=response_status,
            elapsed_ms=trace.elapsed_ms, phase=trace.phase, failed_phase=trace.failure_phase,
            failed_rpc_index=trace.failure_rpc_index, rpc_count=trace.rpc_count,
            completed_rpcs=trace.completed_rpcs, phase_elapsed_ms=trace.phase_elapsed_ms,
            cleanup_confirmed=trace.cleanup_confirmed, cleanup_failed=trace.cleanup_failed)
        try:
            await redis.eval("if redis.call('get',KEYS[1]) == ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
                             1, key, snapshot_id)
        except RedisError:
            logger.warning("native_screenshot_lock_release_unconfirmed", extra={"device_id": str(device_id)})


@router.post(
    "/{device_id}/shell",
    summary="Выполнить команду shell на устройстве",
)
async def execute_shell(
    device_id: uuid.UUID,
    body: ExecuteShellRequest,
    current_user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    result = await _request_interactive_command(
        device_id, current_user, svc, "SHELL", {"cmd": body.command}, 30.0,
    )
    if result.get("status") == "failed":
        return {"error": result.get("error", "Unknown error")}
    return {"output": result.get("result", {}).get("output", "")}


# ── Logcat Viewer ─────────────────────────────────────────────────────────────


class RequestLogcatRequest(BaseModel):
    lines: int = Field(500, ge=1, le=10000)
    mode: str = "sphere"


@router.post(
    "/{device_id}/logcat",
    summary="Запросить logcat устройства",
)
async def request_logcat(
    device_id: uuid.UUID,
    body: RequestLogcatRequest,
    current_user: User = require_permission("device:read"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    # SphereApp always persists its own logs, including release builds where
    # Timber.DebugTree/logcat output is disabled. A fixed logcat tag allowlist
    # misses both those logs and the class tags emitted by debug builds.
    sphere_logs = body.mode == "sphere"
    command_type = "REQUEST_LOGS" if sphere_logs else "UPLOAD_LOGCAT"
    # The APK reads this byte tail before returning it over its command WS.
    # Sending 64 KiB for a one-line request can time out on a degraded WAN.
    byte_budget = min(64 * 1024, max(4 * 1024, body.lines * 256))
    payload: dict[str, Any] = (
        {"max_bytes": byte_budget} if sphere_logs else {"lines": body.lines, "mode": body.mode}
    )
    result = await _request_interactive_command(
        device_id, current_user, svc, command_type, payload, 15.0,
    )
    if result.get("status") == "failed":
        return {"error": result.get("error", "Unknown error")}
    content = result.get("result", {}).get("logs" if sphere_logs else "logcat", "")
    if sphere_logs:
        content = "\n".join(content.splitlines()[-body.lines:])
    return {"logcat": content}


# ── Reboot ────────────────────────────────────────────────────────────────────


@router.post(
    "/{device_id}/reboot",
    summary="Перезагрузить устройство через агент",
)
async def reboot_device(
    device_id: uuid.UUID,
    current_user: User = require_permission("device:write"),
    db: AsyncSession = Depends(get_db),
    svc: DeviceService = Depends(get_device_service),
) -> dict:
    try:
        result = await _request_interactive_command(
            device_id, current_user, svc, "REBOOT", {}, 10.0, accept_progress=True,
        )
    except HTTPException as exc:
        if exc.status_code == 504:
            raise HTTPException(504, "Reboot outcome unknown: device did not acknowledge") from exc
        raise
    if result.get("status") == "failed":
        return {"error": result.get("error", "Reboot failed")}
    return {"status": "reboot_initiated", "device_id": str(device_id)}
