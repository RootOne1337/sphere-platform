# SPLIT-2 — Grafana Dashboards (Визуализация метрик)

**ТЗ-родитель:** TZ-11-Monitoring  
**Ветка:** `stage/11-monitoring`  
**Задача:** `SPHERE-057`  
**Исполнитель:** DevOps  
**Оценка:** 1 день  
**Блокирует:** TZ-11 SPLIT-3
**Зависит от:** TZ-11 SPLIT-1 (Prometheus Metrics)

---

## Шаг 0 — Изоляция рабочего пространства (ПЕРВОЕ действие)

> **Принцип:** Ты работаешь в ОТДЕЛЬНОЙ папке `sphere-stage-11` — НЕ в `sphere-platform`.
> Ветка `stage/11-monitoring` зафиксирована в этой папке. `git checkout` не нужен и ЗАПРЕЩЁН.

**Открой в IDE папку:** `C:\Users\dimas\Documents\sphere-stage-11`

**Файловое владение этапа:**

| ✅ Твои файлы — пиши сюда | 🔴 Чужие файлы — НЕ ТРОГАТЬ |
|---|---|
| `infrastructure/monitoring/grafana/` | `backend/main.py` 🔴 |
| `infrastructure/monitoring/provisioning/` | `backend/core/` 🔴 |

---

## Цель Сплита

Создать 4 Grafana дашборда (JSON provisioning, не ручные): Fleet Overview, Performance, VPN, Android Agents. Auto-provisioning через docker-compose.

---

## Шаг 1 — Docker Compose для Monitoring стека

```yaml
# infrastructure/monitoring/docker-compose.monitoring.yml
services:
  prometheus:
    image: prom/prometheus:v2.48.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./alert-rules.yml:/etc/prometheus/alert-rules.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
      - '--web.enable-lifecycle'
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:10.2.0
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-sphere_grafana_2026}
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /var/lib/grafana/dashboards/fleet-overview.json
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
      - ./grafana/dashboards:/var/lib/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      - prometheus
    networks:
      - monitoring-net

  alertmanager:
    image: prom/alertmanager:v0.26.0
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro
    ports:
      - "9093:9093"
    networks:
      - monitoring-net

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring-net:
    driver: bridge
```

---

## Шаг 2 — Prometheus Config

```yaml
# infrastructure/monitoring/prometheus.yml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

rule_files:
  - "alert-rules.yml"

alerting:
  alertmanagers:
    - static_configs:
        - targets: ["alertmanager:9093"]

scrape_configs:
  - job_name: "sphere-backend"
    metrics_path: /metrics
    static_configs:
      - targets: ["backend:8000"]
    # При горизонтальном масштабировании:
    # dns_sd_configs:
    #   - names: ["tasks.sphere-backend"]
    #     type: A
    #     port: 8000

  - job_name: "prometheus"
    static_configs:
      - targets: ["localhost:9090"]
```

---

## Шаг 3 — Grafana Provisioning

```yaml
# infrastructure/monitoring/grafana/provisioning/datasources/datasource.yml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
    editable: false
```

```yaml
# infrastructure/monitoring/grafana/provisioning/dashboards/dashboard.yml
apiVersion: 1
providers:
  - name: Sphere Platform
    type: file
    disableDeletion: true
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
```

---

## Шаг 4 — Dashboard: Fleet Overview

```json
{
  "dashboard": {
    "title": "Sphere Platform — Fleet Overview",
    "uid": "sphere-fleet-overview",
    "tags": ["sphere", "fleet"],
    "timezone": "browser",
    "refresh": "10s",
    "panels": [
      {
        "title": "Устройства онлайн",
        "type": "gauge",
        "gridPos": {"h": 8, "w": 6, "x": 0, "y": 0},
        "targets": [
          {"expr": "sum(sphere_devices_online)", "legendFormat": "Online"}
        ],
        "fieldConfig": {
          "defaults": {
            "thresholds": {
              "steps": [
                {"value": 0, "color": "red"},
                {"value": 100, "color": "yellow"},
                {"value": 500, "color": "green"}
              ]
            }
          }
        }
      },
      {
        "title": "Подключения WebSocket",
        "type": "stat",
        "gridPos": {"h": 8, "w": 6, "x": 6, "y": 0},
        "targets": [
          {"expr": "sum(sphere_ws_connections_active)", "legendFormat": "WS Active"}
        ]
      },
      {
        "title": "Задачи в очереди",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [
          {"expr": "sphere_task_queue_depth", "legendFormat": "Queue Depth"}
        ]
      },
      {
        "title": "HTTP Requests RPS",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "targets": [
          {"expr": "rate(sphere_http_requests_total[5m])", "legendFormat": "{{method}} {{endpoint}} {{status_code}}"}
        ]
      },
      {
        "title": "VPN Пул",
        "type": "piechart",
        "gridPos": {"h": 8, "w": 6, "x": 12, "y": 8},
        "targets": [
          {"expr": "sphere_vpn_pool_allocated", "legendFormat": "Allocated"},
          {"expr": "sphere_vpn_pool_total - sphere_vpn_pool_allocated", "legendFormat": "Free"}
        ]
      },
      {
        "title": "Ошибки (5xx)",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 6, "x": 18, "y": 8},
        "targets": [
          {"expr": "rate(sphere_http_requests_total{status_code=~\"5..\"}[5m])", "legendFormat": "5xx/s"}
        ],
        "fieldConfig": {"defaults": {"color": {"mode": "fixed", "fixedColor": "red"}}}
      }
    ]
  }
}
```

---

## Шаг 5 — Dashboard: Performance

```json
{
  "dashboard": {
    "title": "Sphere Platform — Performance",
    "uid": "sphere-performance",
    "tags": ["sphere", "performance"],
    "panels": [
      {
        "title": "API Latency (p50 / p95 / p99)",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0},
        "targets": [
          {"expr": "histogram_quantile(0.50, rate(sphere_http_request_duration_seconds_bucket[5m]))", "legendFormat": "p50"},
          {"expr": "histogram_quantile(0.95, rate(sphere_http_request_duration_seconds_bucket[5m]))", "legendFormat": "p95"},
          {"expr": "histogram_quantile(0.99, rate(sphere_http_request_duration_seconds_bucket[5m]))", "legendFormat": "p99"}
        ]
      },
      {
        "title": "DB Pool Usage",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 0},
        "targets": [
          {"expr": "sphere_db_pool_size", "legendFormat": "Pool Size"},
          {"expr": "sphere_db_pool_checked_out", "legendFormat": "Checked Out"}
        ]
      },
      {
        "title": "DB Query Duration",
        "type": "heatmap",
        "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8},
        "targets": [
          {"expr": "rate(sphere_db_query_duration_seconds_bucket[5m])"}
        ]
      },
      {
        "title": "Redis Commands/s",
        "type": "timeseries",
        "gridPos": {"h": 8, "w": 12, "x": 12, "y": 8},
        "targets": [
          {"expr": "rate(sphere_redis_commands_total[5m])", "legendFormat": "{{command}}"},
          {"expr": "rate(sphere_redis_errors_total[5m])", "legendFormat": "errors"}
        ]
      }
    ]
  }
}
```

---

## Шаг 6 — Dashboard: VPN

```json
{
  "dashboard": {
    "title": "Sphere Platform — VPN Dashboard",
    "uid": "sphere-vpn",
    "tags": ["sphere", "vpn"],
    "panels": [
      {
        "title": "VPN Pool (Allocated vs Free)",
        "type": "stat",
        "targets": [
          {"expr": "sphere_vpn_pool_allocated", "legendFormat": "Allocated"},
          {"expr": "sphere_vpn_pool_total", "legendFormat": "Total"}
        ]
      },
      {
        "title": "VPN Reconnects",
        "type": "timeseries",
        "targets": [
          {"expr": "rate(sphere_vpn_reconnects_total[5m])", "legendFormat": "Reconnects/s"}
        ]
      },
      {
        "title": "Stale Handshakes",
        "type": "timeseries",
        "targets": [
          {"expr": "rate(sphere_vpn_handshake_stale_total[5m])", "legendFormat": "Stale/s"}
        ]
      }
    ]
  }
}
```

---

## Критерии готовности

- [ ] `make monitoring` → Prometheus + Grafana + Alertmanager стартуют
- [ ] Grafana авто-загружает 4 дашборда при старте (provisioning)
- [ ] Fleet Overview: gauges обновляются в real-time (10s refresh)
- [ ] Performance: p50/p95/p99 latency отображается корректно
- [ ] VPN dashboard: pool stats актуальны
- [ ] Prometheus scrape target `sphere-backend` — status UP
