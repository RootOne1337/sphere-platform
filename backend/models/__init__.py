# backend/models/__init__.py
# КРИТИЧНО: импорт всех моделей здесь обязателен для Alembic autogenerate.
# Alembic env.py делает `from backend.models import *` — без этого файла
# генерация миграций будет пропускать таблицы.
#
# Порядок импортов не важен (SQLAlchemy резолвит FK через строки),
# но группировка по TZ-этапам помогает навигации.

# --- Core (TZ-00) ---
from backend.models.api_key import APIKey  # noqa: F401
from backend.models.audit_log import AuditLog  # noqa: F401
from backend.models.base_model import TimestampMixin, UUIDMixin  # noqa: F401
from backend.models.device import Device, DeviceStatus, device_group_members  # noqa: F401

# --- Device Registry (TZ-02) ---
from backend.models.device_group import DeviceGroup  # noqa: F401
from backend.models.ldplayer_instance import LDPlayerInstance  # noqa: F401

# --- Auth (TZ-01) ---
from backend.models.organization import Organization  # noqa: F401
from backend.models.refresh_token import RefreshToken  # noqa: F401

# --- Script Engine (TZ-04) ---
from backend.models.script import Script, ScriptVersion  # noqa: F401
from backend.models.task import Task, TaskStatus  # noqa: F401
from backend.models.task_batch import TaskBatch, TaskBatchStatus  # noqa: F401
from backend.models.user import User  # noqa: F401

# --- VPN (TZ-06) ---
from backend.models.vpn_peer import VPNPeer, VPNPeerStatus  # noqa: F401

# --- n8n Integration (TZ-09) ---
from backend.models.webhook import Webhook  # noqa: F401

# --- PC Agent (TZ-08) ---
from backend.models.workstation import Workstation  # noqa: F401

# --- Orchestrator + Scheduler (TZ-12) ---
from backend.models.pipeline import (  # noqa: F401
    Pipeline,
    PipelineBatch,
    PipelineRun,
    PipelineRunStatus,
    StepType,
)
from backend.models.schedule import (  # noqa: F401
    Schedule,
    ScheduleConflictPolicy,
    ScheduleExecution,
    ScheduleExecutionStatus,
    ScheduleTargetType,
)

__all__ = [
    "TimestampMixin",
    "UUIDMixin",
    "Organization",
    "User",
    "APIKey",
    "RefreshToken",
    "AuditLog",
    "DeviceGroup",
    "Device",
    "DeviceStatus",
    "device_group_members",
    "Script",
    "ScriptVersion",
    "TaskBatch",
    "TaskBatchStatus",
    "Task",
    "TaskStatus",
    "VPNPeer",
    "VPNPeerStatus",
    "Workstation",
    "LDPlayerInstance",
    "Webhook",
    # TZ-12 Orchestrator
    "Pipeline",
    "PipelineRun",
    "PipelineBatch",
    "PipelineRunStatus",
    "StepType",
    "Schedule",
    "ScheduleExecution",
    "ScheduleConflictPolicy",
    "ScheduleTargetType",
    "ScheduleExecutionStatus",
]
