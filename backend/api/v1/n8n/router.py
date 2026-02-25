# backend/api/v1/n8n/router.py
# TZ-09 SPLIT-5 — n8n integration: webhook CRUD + task creation endpoints
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.dependencies import get_current_user, get_db
from backend.models.task import Task, TaskStatus
from backend.models.webhook import Webhook
from backend.schemas.webhook import (
    WebhookCreate,
    WebhookListResponse,
    WebhookResponse,
    WebhookUpdate,
)
from backend.services.n8n_webhook_service import n8n_webhook_service

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
    current_user=Depends(get_current_user),
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
    data = WebhookResponse.model_validate(webhook)
    data.secret = plain_secret  # expose plain secret once on creation
    return data


@router.get(
    "/webhooks",
    response_model=WebhookListResponse,
    summary="List registered webhooks",
)
async def list_webhooks(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> WebhookListResponse:
    webhooks = await n8n_webhook_service.get_org_webhooks(db, current_user.org_id)
    items = [WebhookResponse.model_validate(w) for w in webhooks]
    return WebhookListResponse(items=items, total=len(items))


@router.get(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Get webhook by ID",
)
async def get_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> WebhookResponse:
    webhook = await _get_webhook_or_404(db, webhook_id, current_user.org_id)
    return WebhookResponse.model_validate(webhook)


@router.patch(
    "/webhooks/{webhook_id}",
    response_model=WebhookResponse,
    summary="Update webhook",
)
async def update_webhook(
    webhook_id: uuid.UUID,
    body: WebhookUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> WebhookResponse:
    webhook = await _get_webhook_or_404(db, webhook_id, current_user.org_id)
    if body.name is not None:
        webhook.name = body.name
    if body.events is not None:
        webhook.events = body.events
    if body.tags is not None:
        webhook.tags = body.tags
    if body.is_active is not None:
        webhook.is_active = body.is_active
    db.add(webhook)
    await db.commit()
    await db.refresh(webhook)
    return WebhookResponse.model_validate(webhook)


@router.delete(
    "/webhooks/{webhook_id}",
    response_model=None,
    summary="Delete webhook",
)
async def delete_webhook(
    webhook_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
) -> Response:
    deleted = await n8n_webhook_service.delete_webhook(db, webhook_id, current_user.org_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
    current_user=Depends(get_current_user),
) -> N8nTaskResponse:
    """
    Create a Task for execution on a device.
    Pass `webhook_url` = $execution.resumeUrl to enable the Suspend/Resume pattern:
    Sphere will POST to this URL when the task completes, resuming the waiting n8n workflow.

    The webhook_url is stored in input_params and called by the task result handler.
    """
    task = Task(
        org_id=current_user.org_id,
        device_id=body.device_id,
        script_id=body.script_id,
        priority=body.priority,
        status=TaskStatus.QUEUED,
        input_params={"webhook_url": body.webhook_url} if body.webhook_url else {},
    )
    db.add(task)
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
