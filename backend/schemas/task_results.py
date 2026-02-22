# backend/schemas/task_results.py
# ВЛАДЕЛЕЦ: TZ-04 SPLIT-5. Схемы для детальных логов выполнения задач.
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class NodeExecutionLog(BaseModel):
    """Лог выполнения одного узла DAG."""
    node_id: str
    action_type: str
    started_at: datetime
    duration_ms: int
    success: bool
    error: str | None = None
    output: dict | None = None          # Результат (позиция элемента, текст и т.п.)
    screenshot_key: str | None = None   # S3/MinIO ключ скриншота (если action=screenshot)


class TaskExecutionResult(BaseModel):
    """Сводный результат выполнения задачи (хранится в Task.result)."""
    task_id: uuid.UUID
    device_id: str
    success: bool
    total_nodes: int
    completed_nodes: int
    failed_node: str | None = None      # ID узла, на котором произошла ошибка
    duration_ms: int
    node_logs: list[NodeExecutionLog] = []
    final_screenshot_key: str | None = None
    error: str | None = None
