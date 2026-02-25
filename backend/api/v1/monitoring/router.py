# backend/api/v1/monitoring/router.py
# TZ-11 SPLIT-3: Webhook receiver для Alertmanager.
# Alertmanager POST-ит алерты сюда при срабатывании/разрешении.
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel

logger = structlog.get_logger()

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


class AlertAnnotations(BaseModel):
    summary: str = ""
    description: str = ""
    runbook: str = ""


class Alert(BaseModel):
    status: str                     # "firing" | "resolved"
    labels: dict[str, str] = {}
    annotations: AlertAnnotations = AlertAnnotations()


class AlertmanagerPayload(BaseModel):
    version: str = ""
    receiver: str = ""
    status: str = ""                # "firing" | "resolved"
    alerts: list[Alert] = []
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""


@router.post("/alerts")
async def receive_alerts(payload: AlertmanagerPayload) -> dict[str, Any]:
    """
    Webhook-ресивер для Alertmanager.

    Принимает алерты, логирует их структурированно.
    В будущем: трансляция в Fleet Events WebSocket (TZ-03 SPLIT-5).

    Alertmanager конфигурация:
        webhook_configs:
          - url: 'http://backend:8000/api/v1/monitoring/alerts'
    """
    for alert in payload.alerts:
        severity = alert.labels.get("severity", "unknown")
        alertname = alert.labels.get("alertname", "unknown")

        log_fn = logger.error if severity == "critical" else logger.warning
        if alert.status == "resolved":
            log_fn = logger.info

        log_fn(
            "alertmanager.alert",
            alertname=alertname,
            severity=severity,
            status=alert.status,
            summary=alert.annotations.summary,
            description=alert.annotations.description,
            labels=alert.labels,
        )

        # TODO (TZ-03 SPLIT-5): транслировать в Fleet Events WebSocket
        # await events_publisher.emit(FleetEvent(
        #     event_type=EventType.ALERT_TRIGGERED,
        #     org_id="system",
        #     payload={
        #         "alertname": alertname,
        #         "severity": severity,
        #         "status": alert.status,
        #         "summary": alert.annotations.summary,
        #     },
        # ))

    logger.info(
        "alertmanager.batch_processed",
        total=len(payload.alerts),
        status=payload.status,
        receiver=payload.receiver,
    )

    return {"status": "ok", "processed": len(payload.alerts)}
