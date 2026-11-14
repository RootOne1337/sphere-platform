# backend/api/v1/n8n/router.py
# TZ-09 SPLIT-5 — n8n integration: webhook CRUD + task creation endpoints
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_, func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased, defer, load_only

import backend.services.webhook_outbox_worker  # noqa: F401 — registers lifecycle hooks
from backend.core.config import settings
from backend.core.dependencies import get_current_user, get_db, require_permission
from backend.models.task import Task
from backend.models.webhook import Webhook
from backend.models.webhook_delivery import WebhookDelivery
from backend.schemas.webhook import (
    DeliveryStatus,
    WebhookCreate,
    WebhookDeliveryDetail,
    WebhookDeliveryList,
    WebhookDeliveryResponse,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdate,
)
from backend.services.n8n_webhook_service import n8n_webhook_service
from backend.services.webhook_outbox import (
    MAX_HISTORY,
    SUBSCRIPTION_EVENTS,
    enforce_active_subscription_limit,
    lock_webhook_tenant,
    may_replay,
    replay_delivery,
    subscription_receiver_allowed,
)

router = APIRouter(prefix="/n8n", tags=["n8n"])


# ── Webhook CRUD ─────────────────────────────────────────────────────────────

@router.post(
    "/webhooks",
    response_model=WebhookResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register n8n webhook",
)
async def create_webhook(
    body: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:write"),
) -> WebhookResponse:
    """
    Register a new webhook endpoint.
    The response includes `secret` only once — store it in n8n as the Webhook Secret.
    """
    webhook, plain_secret = await n8n_webhook_service.create_webhook(
        db=db,
        org_id=current_user.org_id,
        name=body.name,
        url=str(body.url),
        events=body.events,
        tags=body.tags,
        secret=body.secret,
    )
    data = _webhook_response(webhook)
    data.secret = plain_secret  # expose plain secret once on creation
    return data


@router.get(
    "/webhooks",
    response_model=WebhookListResponse,
    summary="List registered webhooks",
)
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:read"),
) -> WebhookListResponse:
    webhooks = await n8n_webhook_service.get_org_webhooks(db, current_user.org_id)
    items = [_webhook_response(w) for w in webhooks]
    return WebhookListResponse(
        items=items, total=len(items), publishing_enabled=settings.WEBHOOK_SUBSCRIPTIONS_ENABLED,
        supported_events=list(SUBSCRIPTION_EVENTS),
    )


@router.get(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Get webhook by ID",
)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:read"),
) -> WebhookResponse:
    webhook = await _get_webhook_or_404(db, webhook_id, current_user.org_id)
    return _webhook_response(webhook)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Update webhook",
)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:write"),
) -> WebhookResponse:
    await lock_webhook_tenant(db, current_user.org_id)
    webhook = await _get_webhook_or_404(db, webhook_id, current_user.org_id)
    if body.name is not None:
        webhook.name = body.name
    if body.events is not None:
        webhook.events = body.events
    if body.tags is not None:
        webhook.tags = body.tags
    if body.is_active is not None:
        if body.is_active and not webhook.is_active:
            await enforce_active_subscription_limit(db, current_user.org_id)
        webhook.is_active = body.is_active
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return _webhook_response(webhook)


@router.delete(
    "/webhooks/{webhook_id}",
    response_model=None,
    summary="Delete webhook",
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:write"),
) -> Response:
    await lock_webhook_tenant(db, current_user.org_id)
    deleted = await n8n_webhook_service.delete_webhook(db, webhook_id, current_user.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _webhook_response(webhook: Webhook) -> WebhookResponse:
    response = WebhookResponse.model_validate(webhook)
    response.receiver_allowed = subscription_receiver_allowed(webhook.url)
    return response


def _delivery_rows():
    return select(WebhookDelivery, Webhook, WebhookDelivery.body.is_not(None)).options(
        defer(WebhookDelivery.body, raiseload=True), defer(WebhookDelivery.signature, raiseload=True),
    ).outerjoin(Webhook, and_(Webhook.id == WebhookDelivery.webhook_id, Webhook.org_id == WebhookDelivery.org_id))


@router.get("/deliveries", response_model=WebhookDeliveryList, summary="List webhook delivery history")
async def list_deliveries(
    response: Response,
    page: int = Query(1, ge=1, le=MAX_HISTORY),
    per_page: int = Query(25, ge=1, le=100),
    delivery_status: DeliveryStatus | None = Query(None, alias="status"),
    webhook_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:read"),
) -> WebhookDeliveryList:
    filters = [WebhookDelivery.org_id == current_user.org_id]
    if delivery_status is not None:
        filters.append(WebhookDelivery.status == delivery_status)
    if webhook_id is not None:
        filters.append(WebhookDelivery.webhook_id == webhook_id)
    counter = select(func.count().label("total")).select_from(WebhookDelivery).where(*filters).subquery()
    summary_columns: list[InstrumentedAttribute[Any]] = [
        WebhookDelivery.id, WebhookDelivery.org_id, WebhookDelivery.webhook_id, WebhookDelivery.subject_id,
        WebhookDelivery.source, WebhookDelivery.event_type, WebhookDelivery.destination, WebhookDelivery.status,
        WebhookDelivery.attempts_count, WebhookDelivery.max_attempts, WebhookDelivery.replay_count,
        WebhookDelivery.next_attempt_at, WebhookDelivery.last_http_status, WebhookDelivery.last_error,
        WebhookDelivery.created_at, WebhookDelivery.updated_at,
    ]
    page_rows = select(
        *summary_columns, WebhookDelivery.body.is_not(None).label("has_body"),
    ).where(*filters).order_by(
        WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc(),
    ).offset((page - 1) * per_page).limit(per_page).subquery()
    delivery_row = aliased(WebhookDelivery, page_rows)
    rows = (await db.execute(select(counter.c.total, delivery_row, Webhook, page_rows.c.has_body).options(
        load_only(*[getattr(delivery_row, column.key) for column in summary_columns], raiseload=True),
    ).select_from(counter).outerjoin(page_rows, true()).outerjoin(Webhook, and_(
        Webhook.id == delivery_row.webhook_id, Webhook.org_id == delivery_row.org_id,
    )).order_by(delivery_row.created_at.desc(), delivery_row.id.desc()))).all()
    response.headers["Cache-Control"] = "no-store"
    return WebhookDeliveryList(
        items=[
            WebhookDeliveryResponse.model_validate(delivery).model_copy(update={
                "can_replay": may_replay(delivery, subscription, has_body=has_body),
            })
            for _, delivery, subscription, has_body in rows if delivery is not None
        ],
        total=rows[0][0], page=page, per_page=per_page,
    )


@router.get("/deliveries/{delivery_id}", response_model=WebhookDeliveryDetail, summary="Read webhook delivery attempts")
async def get_delivery(
    delivery_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:read"),
) -> WebhookDeliveryDetail:
    row = (await db.execute(_delivery_rows().where(
        WebhookDelivery.id == delivery_id, WebhookDelivery.org_id == current_user.org_id,
    ))).one_or_none()
    if row is None:
        raise HTTPException(404, "Webhook delivery not found")
    delivery, subscription, has_body = row
    response.headers["Cache-Control"] = "no-store"
    return WebhookDeliveryDetail.model_validate(delivery).model_copy(update={
        "can_replay": may_replay(delivery, subscription, has_body=has_body),
    })


@router.post(
    "/deliveries/{delivery_id}/replay", response_model=WebhookDeliveryResponse,
    summary="Retry one terminal webhook delivery with the original delivery ID",
    responses={409: {"description": "Replay is unavailable or tenant delivery capacity is full"}},
)
async def replay_webhook_delivery(
    delivery_id: uuid.UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("webhook:write"),
) -> WebhookDeliveryResponse:
    delivery = await replay_delivery(db, current_user.org_id, delivery_id)
    await db.refresh(delivery, ["updated_at"])
    snapshot = WebhookDeliveryResponse.model_validate(delivery)
    await db.commit()
    response.headers["Cache-Control"] = "no-store"
    return snapshot


# ── Task creation (n8n → Sphere) ─────────────────────────────────────────────

class TaskCreate:
    """Inline schema — avoids touching TZ-04-owned schemas."""
    pass


from pydantic import BaseModel  # noqa: E402


class N8nTaskCreate(BaseModel):
    device_id: uuid.UUID
    script_id: uuid.UUID
    priority: int = 5
    webhook_url: str | None = None  # resumeUrl for suspend/resume pattern


class N8nTaskResponse(BaseModel):
    id: str
    status: str
    device_id: str
    script_id: str


@router.post(
    "/tasks",
    response_model=N8nTaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create task from n8n (supports webhook callback)",
)
async def create_task(
    body: N8nTaskCreate,
    db: AsyncSession = Depends(get_db),
    current_user=require_permission("script:execute"),
) -> N8nTaskResponse:
    """
    Create a Task for execution on a device.
    Pass `webhook_url` = $execution.resumeUrl to enable the Suspend/Resume pattern:
    Sphere will POST to this URL when the task completes, resuming the waiting n8n workflow.

    The webhook_url is stored in input_params and called by the task result handler.
    """
    from backend.services.task_service import TaskService
    task = await TaskService(db).create_task(
        org_id=current_user.org_id,
        device_id=body.device_id,
        script_id=body.script_id,
        priority=body.priority,
        webhook_url=body.webhook_url,
    )
    await db.commit()
    await db.refresh(task)
    return N8nTaskResponse(
        id=str(task.id),
        status=task.status,
        device_id=str(task.device_id),
        script_id=str(task.script_id),
    )


@router.get(
    "/tasks/{task_id}",
    response_model=N8nTaskResponse,
    summary="Poll task status",
)
async def get_task_status(
    task_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> N8nTaskResponse:
    """Used by SphereExecuteScript node to poll task status."""
    task = await db.get(Task, task_id)
    if task is None or task.org_id != current_user.org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return N8nTaskResponse(
        id=str(task.id),
        status=task.status,
        device_id=str(task.device_id),
        script_id=str(task.script_id),
    )


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _get_webhook_or_404(
    db: AsyncSession,
    webhook_id: uuid.UUID,
    org_id: uuid.UUID,
) -> Webhook:
    webhook = await db.get(Webhook, webhook_id)
    if webhook is None or webhook.org_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return webhook
