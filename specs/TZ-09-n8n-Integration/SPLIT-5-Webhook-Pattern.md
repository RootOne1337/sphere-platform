# SPLIT-5 — Webhook Suspend/Resume Pattern

**ТЗ-родитель:** TZ-09-n8n-Integration  
**Ветка:** `stage/9-n8n`  
**Задача:** `SPHERE-050`  
**Исполнитель:** Backend/Node.js + Python  
**Оценка:** 1 день  
**Блокирует:** —
**Интеграция при merge:** TZ-10 Frontend работает с mock webhooks; при merge подключить реальные n8n webhooks

---

## Цель Сплита

Паттерн: n8n запускает задачу на устройстве, приостанавливает выполнение workflow (Wait node), бэкенд вызывает webhook при завершении задачи — workflow продолжает с результатом.

---

## Шаг 1 — Webhook модель на бэкенде

```python
# backend/schemas/webhook.py
from pydantic import BaseModel, HttpUrl, field_validator

class WebhookCreate(BaseModel):
    url: HttpUrl
    events: list[str]
    tags: list[str] = []
    secret: str | None = None  # если не указан — генерируем

class WebhookResponse(BaseModel):
    id: str
    url: str
    events: list[str]
    tags: list[str]
    secret: str  # возвращаем один раз при создании
    created_at: str
```

> ⚠️ **ВНИМАНИЕ АГЕНТУ: НЕ СОЗДАВАЙ КЛАСС МОДЕЛИ `Webhook`!**
>
> Модель `Webhook` **уже определена** в **TZ-00 SPLIT-2 Шаг 4** (файл `backend/models/webhook.py`).
> Дублирование вызовет `SAWarning: Table 'webhooks' already exists` и конфликт при merge!
>
> **Используй только импорт:**
>
> ```python
> from backend.models.webhook import Webhook
> ```
>
> **Поля Webhook (справка):** `org_id`, `url`, `events`, `tags`, `secret_hash`, `is_active`

---

## Шаг 2 — WebhookService на бэкенде

```python
# backend/services/webhook_service.py
import hmac
import hashlib
import secrets
import httpx
from loguru import logger

class WebhookService:
    RETRY_DELAYS = [5, 30, 120]  # секунды
    
    async def deliver(
        self,
        webhook: Webhook,
        event_type: str,
        payload: dict,
    ) -> bool:
        if event_type not in webhook.events and "*" not in webhook.events:
            return True  # не наш тип события
        
        if webhook.tags and not self._tags_match(webhook.tags, payload):
            return True  # не наши теги
        
        body = {
            "event": event_type,
            "data": payload,
            "timestamp": int(time.time()),
        }
        body_json = json.dumps(body, separators=(",", ":"))
        signature = self._sign(body_json, webhook.secret_hash)
        
        for attempt, delay in enumerate([0] + self.RETRY_DELAYS):
            if delay > 0:
                await asyncio.sleep(delay)
            
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.post(
                        webhook.url,
                        content=body_json.encode(),
                        headers={
                            "Content-Type": "application/json",
                            "X-Sphere-Signature": f"sha256={signature}",
                            "X-Sphere-Event": event_type,
                        },
                    )
                if resp.status_code < 300:
                    logger.info(f"Webhook delivered: {event_type} → {webhook.url}")
                    return True
                logger.warning(f"Webhook attempt {attempt+1} failed: {resp.status_code}")
            except Exception as e:
                logger.warning(f"Webhook attempt {attempt+1} exception: {e}")
        
        logger.error(f"Webhook delivery failed after {len(self.RETRY_DELAYS)+1} attempts")
        return False
    
    def _sign(self, body: str, secret: str) -> str:
        return hmac.new(
            secret.encode(),
            body.encode(),
            hashlib.sha256,
        ).hexdigest()
    
    def _tags_match(self, filter_tags: list[str], payload: dict) -> bool:
        device_tags = payload.get("device", {}).get("tags", [])
        return any(t in device_tags for t in filter_tags)
```

---

## Шаг 3 — n8n Workflow: Suspend/Resume

```json
{
  "name": "Sphere Platform — Suspend/Resume Pattern",
  "nodes": [
    {
      "name": "Trigger",
      "type": "n8n-nodes-base.scheduleTrigger",
      "position": [200, 300]
    },
    {
      "name": "Get Devices",
      "type": "n8n-nodes-sphereplatform.sphereDevicePool",
      "parameters": { "operation": "getByTags", "tags": "farm", "outputMode": "each" },
      "position": [400, 300]
    },
    {
      "name": "Execute Script (no wait)",
      "type": "n8n-nodes-sphereplatform.sphereExecuteScript",
      "parameters": {
        "deviceId": "={{ $json.id }}",
        "scriptId": "{{SCRIPT_UUID}}",
        "waitForResult": false,
        "webhookUrl": "={{ $execution.resumeUrl }}"
      },
      "position": [600, 300]
    },
    {
      "name": "Wait for Webhook",
      "type": "n8n-nodes-base.wait",
      "parameters": {
        "resume": "webhook",
        "options": { "webhookSuffix": "/result" }
      },
      "position": [800, 300]
    },
    {
      "name": "Process Result",
      "type": "n8n-nodes-base.set",
      "parameters": {
        "values": {
          "string": [
            { "name": "task_status", "value": "={{ $json.data.status }}" },
            { "name": "device_id", "value": "={{ $json.data.device_id }}" }
          ]
        }
      },
      "position": [1000, 300]
    }
  ]
}
```

---

## Шаг 4 — Бэкенд вызывает `resumeUrl` при завершении задачи

```python
# backend/services/task_service.py (в handle_task_result)
async def handle_task_result(self, task_id: UUID, result: dict):
    task = await self._get_task(task_id)
    task.status = TaskStatus.COMPLETED
    task.result = result
    # ⚠️ ВАЖНО: datetime.now(timezone.utc) вместо datetime.utcnow() — timezone-aware
    from datetime import timezone
    task.completed_at = datetime.now(timezone.utc)
    await self.db.commit()
    
    # Доставить webhook если есть
    if task.webhook_url:
        payload = {
            "task_id": str(task_id),
            "device_id": str(task.device_id),
            "status": "completed",
            "result": result,
        }
        # FIX 9.2: БЫЛО — await client.post(...) БЛОКИРОВАЛ event loop
        #   → При медленном/зависшем webhook — весь сервер стоит
        # СТАЛО — asyncio.create_task + global set (защита от GC)
        async def _deliver_webhook(url: str, data: dict):
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    await client.post(url, json={"event": "task_completed", "data": data})
            except Exception as e:
                logger.warning(f"Webhook failed для task {task_id}: {e}")
        
        t = asyncio.create_task(_deliver_webhook(str(task.webhook_url), payload))
        _background_tasks.add(t)
        t.add_done_callback(_background_tasks.discard)
```

---

## Критерии готовности

- [ ] `webhookUrl = $execution.resumeUrl` передаётся при создании задачи
- [ ] Wait node `resume: webhook` приостанавливает workflow до POST
- [ ] Бэкенд POST на `webhook_url` при завершении задачи (success и failure)
- [ ] HMAC подпись на исходящих webhook calls (X-Sphere-Signature)
- [ ] Retry: 3 попытки с 5→30→120s задержкой
- [ ] Tags filter в WebhookService: хотя бы один тег совпадает (OR логика)
