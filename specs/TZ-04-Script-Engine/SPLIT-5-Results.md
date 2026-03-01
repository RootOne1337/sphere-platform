# SPLIT-5 — Execution Results & Logs

**ТЗ-родитель:** TZ-04-Script-Engine  
**Ветка:** `stage/4-scripts`  
**Задача:** `SPHERE-025`  
**Исполнитель:** Backend  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-10 Frontend работает с mock results API; при merge подключить реальные результаты

---

## Цель Сплита

Хранение и просмотр детальных логов выполнения. Скриншоты, per-node результаты, webhook доставка.

---

## Шаг 1 — Execution Log Schema

```python
# backend/schemas/task_results.py
class NodeExecutionLog(BaseModel):
    node_id: str
    action_type: str
    started_at: datetime
    duration_ms: int
    success: bool
    error: str | None = None
    output: dict | None = None     # Результат (element position, screenshot key и т.п.)
    screenshot_key: str | None = None   # S3/MinIO ключ скриншота

class TaskExecutionResult(BaseModel):
    task_id: uuid.UUID
    device_id: str
    success: bool
    total_nodes: int
    completed_nodes: int
    failed_node: str | None = None
    duration_ms: int
    node_logs: list[NodeExecutionLog]
    final_screenshot_key: str | None = None
    error: str | None = None
```

---

## Шаг 2 — Screenshot Storage (MinIO/S3)

```python
# backend/services/screenshot_storage.py
class ScreenshotStorage:
    """
    Хранит скриншоты в MinIO (локально) или S3 (production).
    Возвращает временные presigned URL для просмотра.
    """
    
    BUCKET = "sphere-screenshots"
    TTL_DAYS = 7
    
    def __init__(self, minio_client, presign_ttl: int = 3600):
        self.client = minio_client
        self.presign_ttl = presign_ttl
    
    async def upload_screenshot(
        self,
        task_id: str,
        device_id: str,
        node_id: str,
        image_bytes: bytes,
    ) -> str:
        """Загрузить скриншот, вернуть ключ объекта."""
        key = f"tasks/{task_id}/{device_id}/{node_id}/{int(time.time())}.jpg"
        
        await asyncio.to_thread(
            self.client.put_object,
            self.BUCKET,
            key,
            io.BytesIO(image_bytes),
            len(image_bytes),
            content_type="image/jpeg",
        )
        return key
    
    async def get_presigned_url(self, key: str) -> str:
        return await asyncio.to_thread(
            self.client.presigned_get_object,
            self.BUCKET,
            key,
            expires=timedelta(seconds=self.presign_ttl),
        )
```

---

## Шаг 3 — Webhook Delivery

```python
# backend/services/webhook_service.py
#
# ⚠️ MERGE CONFLICT WARNING:
# TZ-09 SPLIT-5 (Telemetry Pipeline) также определяет backend/services/webhook_service.py
# с другой реализацией (httpx вместо aiohttp, для n8n suspend/resume интеграции).
#
# РЕШЕНИЕ при merge TZ-04 + TZ-09:
#   — Объединить в единый WebhookService (рекомендуется httpx — уже используется в остальном backend)
#   — Сохранить оба метода доставки: task completions (этот файл) + n8n suspend/resume (TZ-09)
#   — Канонический файл: backend/services/webhook_service.py (один на всё приложение)
#   — Добавить роутер регистрации из TZ-09 SPLIT-5 в единый сервис
#
class WebhookService:
    MAX_RETRIES = 3
    RETRY_BACKOFF = [5, 30, 120]   # Секунды
    TIMEOUT = 10.0
    
    async def deliver(self, url: str, payload: dict, secret: str | None = None):
        """
        Доставить webhook с HMAC-SHA256 подписью.
        Retry с exponential backoff при 5xx или сетевой ошибке.
        """
        body = json.dumps(payload, default=str).encode()
        
        headers = {
            "Content-Type": "application/json",
            "X-Sphere-Event": payload.get("event_type", "unknown"),
            "X-Sphere-Delivery": secrets.token_hex(8),
        }
        
        if secret:
            # HMAC-SHA256 подпись для верификации на стороне получателя
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            headers["X-Sphere-Signature"] = f"sha256={sig}"
        
        for attempt, delay in enumerate([0] + self.RETRY_BACKOFF):
            if delay:
                await asyncio.sleep(delay)
            try:
                # CRIT-2: httpx вместо aiohttp — единый HTTP-клиент для всего backend
                async with httpx.AsyncClient(timeout=httpx.Timeout(self.TIMEOUT)) as client:
                    resp = await client.post(url, content=body, headers=headers)
                    if resp.status_code < 500:
                        logger.info("Webhook delivered", url=url, status=resp.status_code)
                        return
                    logger.warning(f"Webhook server error {resp.status_code}, retry {attempt}")
            except httpx.HTTPError as e:
                logger.warning(f"Webhook network error: {e}, retry {attempt}")
        
        logger.error("Webhook delivery failed after retries", url=url)
```

---

## Шаг 4 — Results Router

```python
# backend/api/v1/tasks.py
router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.get("", response_model=PaginatedResponse[TaskResponse])
async def list_tasks(
    device_id: str | None = None,
    script_id: uuid.UUID | None = None,
    status: TaskStatus | None = None,
    batch_id: uuid.UUID | None = None,
    page: int = Query(1, ge=1),
    ...
): ...

@router.get("/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: uuid.UUID, include_logs: bool = False, ...): ...

@router.get("/{task_id}/logs", response_model=list[NodeExecutionLog])
async def get_task_logs(task_id: uuid.UUID, ...): ...

@router.get("/{task_id}/screenshots")
async def get_task_screenshots(task_id: uuid.UUID, ...):
    """Вернуть список presigned URL к скриншотам задачи."""
    keys = await svc.get_screenshot_keys(task_id, current_user.org_id)
    urls = [await screenshot_storage.get_presigned_url(k) for k in keys]
    return {"screenshots": urls}

@router.delete("/{task_id}", status_code=204)
async def cancel_task(task_id: uuid.UUID, ...): ...
```

---

## Критерии готовности

- [ ] Логи каждого узла DAG сохраняются с duration_ms и error
- [ ] Скриншот из задачи — presigned URL с TTL 1 час
- [ ] Webhook с HMAC-SHA256 подписью для верификации
- [ ] Webhook retry 3 раза с backoff 5→30→120s при 5xx ответе
- [ ] Задачи другой org → 404 (не 403 для security)
- [ ] `GET /tasks?status=running` возвращает только active задачи
