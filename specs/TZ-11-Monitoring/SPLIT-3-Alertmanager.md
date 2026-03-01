# SPLIT-3 — Alertmanager (Правила алертинга и уведомления)

**ТЗ-родитель:** TZ-11-Monitoring  
**Ветка:** `stage/11-monitoring`  
**Задача:** `SPHERE-058`  
**Исполнитель:** DevOps  
**Оценка:** 0.5 дня  
**Блокирует:** —
**Зависит от:** TZ-11 SPLIT-1 (Prometheus), SPLIT-2 (Grafana)

---

## Цель Сплита

Настройка Prometheus alert rules и Alertmanager: маршрутизация алертов, Telegram/Webhook уведомления, группировка, подавление шума.

---

## Шаг 1 — Alert Rules (Prometheus)

```yaml
# infrastructure/monitoring/alert-rules.yml
groups:
  # ━━━ КРИТИЧЕСКИЕ (P0) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - name: sphere.critical
    rules:
      - alert: HighAgentOfflineRate
        # FIX 11.4: Добавлен `and sum(...) > 0` — без этого при пустом fleet
        # PromQL вернёт +Inf → ложный алерт critical
        expr: |
          (sum(sphere_devices_total) - sum(sphere_devices_online))
          / sum(sphere_devices_total) > 0.2
          and sum(sphere_devices_total) > 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "{{ $value | humanizePercentage }} устройств оффлайн"
          description: "Более 20% устройств потеряли связь за последние 2 минуты"
          runbook: "https://wiki.sphere.internal/runbooks/agent-offline"

      - alert: DatabasePoolExhausted
        expr: sphere_db_pool_checked_out >= sphere_db_pool_size * 0.9
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "DB pool заполнен на {{ $value | humanize }}%"
          description: "Пул БД почти исчерпан — риск каскадного отказа"

      - alert: BackendDown
        expr: up{job="sphere-backend"} == 0
        for: 30s
        labels:
          severity: critical
        annotations:
          summary: "Backend недоступен"
          description: "Prometheus не может достучаться до /metrics endpoint"

  # ━━━ ВЫСОКИЕ (P1) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - name: sphere.high
    rules:
      - alert: HighAPILatency
        expr: |
          histogram_quantile(0.95, rate(sphere_http_request_duration_seconds_bucket[5m]))
          > 2.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API p95 latency > 2s ({{ $value | humanize }}s)"

      - alert: HighTaskQueueDepth
        expr: sphere_task_queue_depth > 500
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Очередь задач: {{ $value }} (> 500)"
          description: "Задачи накапливаются — устройства не успевают обрабатывать"

      - alert: VPNPoolLow
        expr: |
          (sphere_vpn_pool_total - sphere_vpn_pool_allocated)
          / sphere_vpn_pool_total < 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "VPN пул почти исчерпан (< 10% свободных IP)"

      - alert: HighVPNReconnectRate
        expr: rate(sphere_vpn_reconnects_total[5m]) > 1
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "Частые VPN reconnect: {{ $value | humanize }}/s"
          description: "VPN туннели нестабильны — проверить WG Router"

      - alert: HighErrorRate
        expr: |
          rate(sphere_http_requests_total{status_code=~"5.."}[5m])
          / rate(sphere_http_requests_total[5m]) > 0.05
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "HTTP 5xx ошибки > 5% ({{ $value | humanizePercentage }})"

  # ━━━ СРЕДНИЕ (P2) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  - name: sphere.medium
    rules:
      - alert: HighRedisErrorRate
        expr: rate(sphere_redis_errors_total[5m]) > 0.5
        for: 5m
        labels:
          severity: info
        annotations:
          summary: "Redis ошибки: {{ $value | humanize }}/s"

      - alert: StreamQualityDegraded
        expr: sphere_stream_fps < 15
        for: 1m
        labels:
          severity: info
        annotations:
          summary: "Стрим устройства {{ $labels.device_id }}: FPS={{ $value }}"
```

---

## Шаг 2 — Alertmanager Config

```yaml
# infrastructure/monitoring/alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'severity']
  group_wait: 30s          # ждать 30с для группировки
  group_interval: 5m       # промежуток между группами
  repeat_interval: 4h      # повтор нерешённого алерта
  receiver: 'default'
  routes:
    # Критические → Telegram + Webhook немедленно
    - match:
        severity: critical
      receiver: 'critical-telegram'
      group_wait: 10s
      repeat_interval: 15m

    # Предупреждения → только Webhook
    - match:
        severity: warning
      receiver: 'warning-webhook'
      repeat_interval: 1h

receivers:
  - name: 'default'
    webhook_configs:
      - url: 'http://backend:8000/api/v1/monitoring/alerts'

  - name: 'critical-telegram'
    telegram_configs:
      - bot_token: '${TELEGRAM_BOT_TOKEN}'
        chat_id: ${TELEGRAM_CHAT_ID}
        parse_mode: 'HTML'
        message: |
          🔴 <b>CRITICAL: {{ .GroupLabels.alertname }}</b>
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          {{ .Annotations.description }}
          {{ end }}
    webhook_configs:
      - url: 'http://backend:8000/api/v1/monitoring/alerts'

  - name: 'warning-webhook'
    webhook_configs:
      - url: 'http://backend:8000/api/v1/monitoring/alerts'

inhibit_rules:
  # Если backend down — подавить все другие алерты
  - source_match:
      alertname: 'BackendDown'
    target_match_re:
      alertname: '.*'
    equal: ['job']
```

---

## Шаг 3 — Backend: Alert Webhook Receiver

```python
# backend/api/v1/metrics/alert_receiver.py
from fastapi import APIRouter, Request
import structlog

logger = structlog.get_logger()
router = APIRouter(prefix="/monitoring", tags=["monitoring"])

@router.post("/alerts")
async def receive_alerts(request: Request):
    """
    Принимает алерты от Alertmanager webhook.
    Логирует и транслирует в Fleet Events WebSocket.
    """
    payload = await request.json()
    alerts = payload.get("alerts", [])
    
    for alert in alerts:
        severity = alert.get("labels", {}).get("severity", "unknown")
        alertname = alert.get("labels", {}).get("alertname", "unknown")
        status = alert.get("status", "unknown")  # firing | resolved
        summary = alert.get("annotations", {}).get("summary", "")
        
        logger.info(
            "Alert received",
            alertname=alertname,
            severity=severity,
            status=status,
            summary=summary,
        )
        
        # Транслировать в Fleet Events для Dashboard (TZ-03 SPLIT-5)
        # await events_publisher.emit(FleetEvent(
        #     event_type=EventType.ALERT_TRIGGERED,
        #     org_id="system",
        #     payload={
        #         "alertname": alertname,
        #         "severity": severity,
        #         "status": status,
        #         "summary": summary,
        #     }
        # ))
    
    return {"status": "ok", "processed": len(alerts)}
```

---

## Стратегия тестирования

### Тестирование alert rules

```bash
# Валидация синтаксиса alert rules
promtool check rules infrastructure/monitoring/alert-rules.yml
# Выход: SUCCESS

# Тест unit-правил (promtool)
promtool test rules tests/alert_test.yml
```

### Пример промтул-теста

```yaml
# tests/alert_test.yml
rule_files:
  - ../infrastructure/monitoring/alert-rules.yml
evaluation_interval: 1m
tests:
  - interval: 1m
    input_series:
      - series: 'sphere_devices_total{org_id="test"}'
        values: "100 100 100 100"
      - series: 'sphere_devices_online{org_id="test"}'
        values: "100 50 50 50"
    alert_rule_test:
      - eval_time: 3m
        alertname: HighAgentOfflineRate
        exp_alerts:
          - exp_labels:
              severity: critical
```

---

## Критерии готовности

- [ ] `promtool check rules alert-rules.yml` → SUCCESS
- [ ] Critical алерты → Telegram за 10-30s
- [ ] Warning алерты → webhook за 30s-5m
- [ ] `BackendDown` подавляет все остальные алерты (inhibit)
- [ ] Алерт `HighAgentOfflineRate` срабатывает при > 20% оффлайн за 2 мин
- [ ] `VPNPoolLow` срабатывает при < 10% свободных IP
- [ ] Повторные алерты: critical каждые 15 мин, warning каждый час
