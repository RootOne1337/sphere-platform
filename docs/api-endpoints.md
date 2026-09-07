# Generated HTTP endpoint catalog

Generated from `backend.main.app.openapi()` by `scripts/export_api_docs.py`.
Regenerate with `python -m scripts.export_api_docs`; verify with `--check`.
The exporter does not run startup hooks or send HTTP requests.

**162 HTTP operations across 126 paths.**

Full parameters, request bodies, response schemas and declared security schemes:
[OpenAPI JSON](openapi.json). Manual explanations:
[API reference](api-reference.md), [task controls](security/task-control-protocol.md).

Only declared HTTP operations are listed. OpenAPI omits WebSocket protocols,
plain ASGI routes such as /metrics, and some runtime authorization/error behavior.
A listed response does not prove runtime success or production readiness.
See [Android guide](android-agent.md) and [audit report](audits/2026-09-05/AUDIT-REPORT.md)
for tested behavior and remaining limits.

| Method | Path | Tags | Declared responses | Summary |
| --- | --- | --- | --- | --- |
| `GET` | `/api/v1/account-sessions` | account-sessions | 200, 422 | List Account Sessions |
| `POST` | `/api/v1/account-sessions` | account-sessions | 201, 422 | Start Session |
| `GET` | `/api/v1/account-sessions/stats` | account-sessions | 200, 422 | Get Session Stats |
| `GET` | `/api/v1/account-sessions/{session_id}` | account-sessions | 200, 422 | Get Session |
| `POST` | `/api/v1/account-sessions/{session_id}/end` | account-sessions | 200, 422 | End Session |
| `GET` | `/api/v1/audit/logs` | audit | 200, 422 | SPLIT-5: Журнал аудита |
| `GET` | `/api/v1/auth/api-keys` | auth | 200 | SPLIT-4: Список API ключей |
| `POST` | `/api/v1/auth/api-keys` | auth | 201, 422 | SPLIT-4: Создать API ключ |
| `DELETE` | `/api/v1/auth/api-keys/{key_id}` | auth | 200, 422 | SPLIT-4: Отозвать API ключ |
| `POST` | `/api/v1/auth/login` | auth | 200, 422 | Login: получить access token + refresh cookie |
| `POST` | `/api/v1/auth/login/mfa` | auth | 200, 422 | Второй шаг MFA login: подтвердить TOTP-код |
| `POST` | `/api/v1/auth/logout` | auth | 204, 422 | Logout: инвалидировать токены |
| `GET` | `/api/v1/auth/me` | auth | 200 | Информация о текущем пользователе |
| `DELETE` | `/api/v1/auth/mfa` | auth | 200 | SPLIT-2: Отключить MFA |
| `POST` | `/api/v1/auth/mfa/setup` | auth | 200 | SPLIT-2: Шаг 1 — Сгенерировать TOTP QR-код |
| `POST` | `/api/v1/auth/mfa/verify-setup` | auth | 200, 422 | SPLIT-2: Шаг 2 — Подтвердить TOTP-код и включить MFA |
| `POST` | `/api/v1/auth/refresh` | auth | 200, 422 | Обновить access token по refresh cookie или header |
| `POST` | `/api/v1/batches` | batches | 202, 422 | Запустить скрипт на N устройствах волнами (202 Accepted) |
| `POST` | `/api/v1/batches/broadcast` | batches | 202, 422 | Запустить скрипт на ВСЕХ онлайн-устройствах организации (202 Accepted) |
| `DELETE` | `/api/v1/batches/{batch_id}` | batches | 204, 422 | Отменить батч (незапущенные задачи → CANCELLED) |
| `GET` | `/api/v1/batches/{batch_id}` | batches | 200, 422 | Статус и прогресс батча |
| `GET` | `/api/v1/config/agent` | config | 200, 422 | Конфигурация для агента (zero-touch provisioning) |
| `GET` | `/api/v1/device-events` | device-events | 200, 422 | List Device Events |
| `POST` | `/api/v1/device-events` | device-events | 201, 422 | Create Device Event |
| `GET` | `/api/v1/device-events/stats` | device-events | 200, 422 | Get Event Stats |
| `GET` | `/api/v1/device-events/{event_id}` | device-events | 200, 422 | Get Device Event |
| `POST` | `/api/v1/device-events/{event_id}/processed` | device-events | 200, 422 | Mark Event Processed |
| `GET` | `/api/v1/devices` | devices | 200, 422 | Список устройств с пагинацией и фильтрацией |
| `POST` | `/api/v1/devices` | devices | 201, 422 | Создать устройство |
| `DELETE` | `/api/v1/devices/bulk` | devices, bulk | 200, 422 | Массовое удаление устройств (требует org_admin или выше) |
| `POST` | `/api/v1/devices/bulk/action` | devices, bulk | 200, 422 | Массовая операция над устройствами (max 500 за раз) |
| `GET` | `/api/v1/devices/me` | devices, devices | 200, 422 | Информация об устройстве по X-API-Key (для агента) |
| `POST` | `/api/v1/devices/refresh` | devices | 200, 422 | Refresh Device |
| `POST` | `/api/v1/devices/register` | devices | 201, 422 | Автоматическая регистрация устройства (для агентов) |
| `POST` | `/api/v1/devices/status/bulk` | devices | 200, 422 | Live статус для batch устройств (MGET — одна RTT до Redis) |
| `GET` | `/api/v1/devices/status/fleet` | devices | 200 | Сводный статус всего fleet организации |
| `DELETE` | `/api/v1/devices/{device_id}` | devices | 204, 422 | Удалить устройство |
| `GET` | `/api/v1/devices/{device_id}` | devices | 200, 422 | Получить устройство по ID |
| `PUT` | `/api/v1/devices/{device_id}` | devices | 200, 422 | Обновить устройство |
| `POST` | `/api/v1/devices/{device_id}/connect` | devices | 204, 422 | Инициировать ADB подключение через PC Agent (TZ-03 stub) |
| `POST` | `/api/v1/devices/{device_id}/logcat` | devices | 200, 422 | Запросить logcat устройства |
| `POST` | `/api/v1/devices/{device_id}/reboot` | devices | 200, 422 | Перезагрузить устройство через агент |
| `GET` | `/api/v1/devices/{device_id}/screenshot` | devices | 200, 422 | Запросить скриншот устройства (TZ-03 stub) |
| `POST` | `/api/v1/devices/{device_id}/shell` | devices | 200, 422 | Выполнить команду shell на устройстве |
| `GET` | `/api/v1/devices/{device_id}/status` | devices | 200, 422 | DB данные + live Redis статус устройства |
| `POST` | `/api/v1/discovery/scan` | discovery | 200, 422 | Сканировать подсеть через PC Agent для обнаружения ADB-устройств |
| `GET` | `/api/v1/event-triggers` | event-triggers | 200, 422 | Список EventTrigger'ов с фильтрацией |
| `POST` | `/api/v1/event-triggers` | event-triggers | 201, 422 | Создать EventTrigger |
| `DELETE` | `/api/v1/event-triggers/{trigger_id}` | event-triggers | 204, 422 | Удалить EventTrigger (жёсткое удаление) |
| `GET` | `/api/v1/event-triggers/{trigger_id}` | event-triggers | 200, 422 | Получить EventTrigger по ID |
| `PATCH` | `/api/v1/event-triggers/{trigger_id}` | event-triggers | 200, 422 | Обновить EventTrigger |
| `POST` | `/api/v1/event-triggers/{trigger_id}/toggle` | event-triggers | 200, 422 | Включить / выключить EventTrigger |
| `GET` | `/api/v1/game-accounts` | game-accounts | 200, 422 | Список игровых аккаунтов с пагинацией, фильтрацией и сортировкой |
| `POST` | `/api/v1/game-accounts` | game-accounts | 201, 422 | Создать игровой аккаунт |
| `POST` | `/api/v1/game-accounts/import` | game-accounts | 200, 422 | Массовый импорт аккаунтов (до 1000 за раз) |
| `GET` | `/api/v1/game-accounts/servers` | game-accounts | 200 | Список всех игровых серверов (90 серверов Black Russia) |
| `GET` | `/api/v1/game-accounts/stats` | game-accounts | 200 | Статистика аккаунтов: количество по статусам + список игр |
| `DELETE` | `/api/v1/game-accounts/{account_id}` | game-accounts | 200, 422 | Удалить аккаунт |
| `GET` | `/api/v1/game-accounts/{account_id}` | game-accounts | 200, 422 | Получить аккаунт по ID |
| `PATCH` | `/api/v1/game-accounts/{account_id}` | game-accounts | 200, 422 | Обновить поля аккаунта (PATCH-семантика) |
| `POST` | `/api/v1/game-accounts/{account_id}/assign` | game-accounts | 200, 422 | Назначить аккаунт на устройство |
| `POST` | `/api/v1/game-accounts/{account_id}/release` | game-accounts | 200, 422 | Освободить аккаунт (снять с устройства) |
| `GET` | `/api/v1/groups` | groups | 200 | Список групп с количеством устройств online/total |
| `POST` | `/api/v1/groups` | groups | 201, 422 | Создать группу устройств |
| `PUT` | `/api/v1/groups/devices/{device_id}/tags` | groups | 204, 422 | Заменить теги устройства (идемпотентно) |
| `GET` | `/api/v1/groups/tags` | groups | 200 | Все теги в организации (для автодополнения) |
| `DELETE` | `/api/v1/groups/{group_id}` | groups | 204, 422 | Удалить группу устройств |
| `PUT` | `/api/v1/groups/{group_id}` | groups | 200, 422 | Обновить группу устройств |
| `POST` | `/api/v1/groups/{group_id}/devices/move` | groups | 200, 422 | Переместить устройства в группу |
| `GET` | `/api/v1/health` | health | 200 | Health Check |
| `GET` | `/api/v1/health/full` | health | 200 | Full Health |
| `GET` | `/api/v1/health/healthz` | health | 200 | Liveness |
| `GET` | `/api/v1/health/ready` | health | 200 | Readiness Check |
| `GET` | `/api/v1/health/readyz` | health | 200 | Readiness |
| `GET` | `/api/v1/locations` | locations | 200 | Список локаций с количеством устройств online/total |
| `POST` | `/api/v1/locations` | locations | 201, 422 | Создать локацию |
| `DELETE` | `/api/v1/locations/{location_id}` | locations | 204, 422 | Удалить локацию |
| `PUT` | `/api/v1/locations/{location_id}` | locations | 200, 422 | Обновить локацию |
| `DELETE` | `/api/v1/locations/{location_id}/devices` | locations | 200, 422 | Убрать устройства из локации |
| `POST` | `/api/v1/locations/{location_id}/devices` | locations | 200, 422 | Назначить устройства в локацию (аддитивно) |
| `POST` | `/api/v1/logs/upload` | logs | 200, 422 | Upload Logs |
| `DELETE` | `/api/v1/logs/{device_id}` | logs | 200, 422 | Delete Device Logs |
| `GET` | `/api/v1/logs/{device_id}` | logs | 200, 422 | Get Device Logs |
| `POST` | `/api/v1/monitoring/alerts` | monitoring | 200, 422 | Receive Alerts |
| `GET` | `/api/v1/monitoring/metrics` | monitoring | 200 | Агрегированные метрики инфраструктуры |
| `GET` | `/api/v1/monitoring/nodes` | monitoring | 200 | Топология кластера (список нод) |
| `POST` | `/api/v1/n8n/tasks` | n8n | 201, 422 | Create task from n8n (supports webhook callback) |
| `GET` | `/api/v1/n8n/tasks/{task_id}` | n8n | 200, 422 | Poll task status |
| `GET` | `/api/v1/n8n/webhooks` | n8n | 200 | List registered webhooks |
| `POST` | `/api/v1/n8n/webhooks` | n8n | 201, 422 | Register n8n webhook |
| `DELETE` | `/api/v1/n8n/webhooks/{webhook_id}` | n8n | 200, 422 | Delete webhook |
| `GET` | `/api/v1/n8n/webhooks/{webhook_id}` | n8n | 200, 422 | Get webhook by ID |
| `PATCH` | `/api/v1/n8n/webhooks/{webhook_id}` | n8n | 200, 422 | Update webhook |
| `GET` | `/api/v1/pipeline-settings` | pipeline-settings | 200 | Получить настройки оркестрации |
| `PATCH` | `/api/v1/pipeline-settings` | pipeline-settings | 200, 422 | Обновить настройки оркестрации (partial update) |
| `POST` | `/api/v1/pipeline-settings/nick/check` | pipeline-settings | 200, 422 | Проверить доступность никнейма |
| `POST` | `/api/v1/pipeline-settings/nick/generate` | pipeline-settings | 200, 422 | Сгенерировать уникальные никнеймы |
| `GET` | `/api/v1/pipeline-settings/servers` | pipeline-settings | 200 | Список доступных игровых серверов |
| `GET` | `/api/v1/pipeline-settings/status` | pipeline-settings | 200 | Текущий статус оркестрации (runtime) |
| `POST` | `/api/v1/pipeline-settings/toggle/farming` | pipeline-settings | 200, 422 | Вкл/выкл авто-фарм |
| `POST` | `/api/v1/pipeline-settings/toggle/orchestration` | pipeline-settings | 200, 422 | Вкл/выкл оркестрацию |
| `POST` | `/api/v1/pipeline-settings/toggle/registration` | pipeline-settings | 200, 422 | Вкл/выкл авто-регистрацию |
| `POST` | `/api/v1/pipeline-settings/toggle/scheduler` | pipeline-settings | 200, 422 | Вкл/выкл планировщик задач |
| `GET` | `/api/v1/pipelines` | pipelines | 200, 422 | Список pipeline с фильтрацией |
| `POST` | `/api/v1/pipelines` | pipelines | 201, 422 | Создать pipeline |
| `GET` | `/api/v1/pipelines/runs` | pipelines | 200, 422 | Список pipeline runs с фильтрацией |
| `GET` | `/api/v1/pipelines/runs/{run_id}` | pipelines | 200, 422 | Получить pipeline run по ID |
| `POST` | `/api/v1/pipelines/runs/{run_id}/cancel` | pipelines | 200, 422 | Отменить pipeline run |
| `POST` | `/api/v1/pipelines/runs/{run_id}/pause` | pipelines | 200, 422 | Приостановить pipeline run |
| `POST` | `/api/v1/pipelines/runs/{run_id}/resume` | pipelines | 200, 422 | Возобновить pipeline run |
| `DELETE` | `/api/v1/pipelines/{pipeline_id}` | pipelines | 204, 422 | Деактивировать pipeline |
| `GET` | `/api/v1/pipelines/{pipeline_id}` | pipelines | 200, 422 | Получить pipeline по ID |
| `PATCH` | `/api/v1/pipelines/{pipeline_id}` | pipelines | 200, 422 | Обновить pipeline |
| `POST` | `/api/v1/pipelines/{pipeline_id}/run` | pipelines | 201, 422 | Запустить pipeline на одном устройстве |
| `POST` | `/api/v1/pipelines/{pipeline_id}/run-batch` | pipelines | 201, 422 | Массовый запуск pipeline на нескольких устройствах |
| `POST` | `/api/v1/pipelines/{pipeline_id}/toggle` | pipelines | 200, 422 | Включить / выключить pipeline |
| `GET` | `/api/v1/schedules` | schedules | 200, 422 | Список расписаний |
| `POST` | `/api/v1/schedules` | schedules | 201, 422 | Создать расписание |
| `DELETE` | `/api/v1/schedules/{schedule_id}` | schedules | 204, 422 | Деактивировать расписание |
| `GET` | `/api/v1/schedules/{schedule_id}` | schedules | 200, 422 | Получить расписание по ID |
| `PATCH` | `/api/v1/schedules/{schedule_id}` | schedules | 200, 422 | Обновить расписание |
| `GET` | `/api/v1/schedules/{schedule_id}/executions` | schedules | 200, 422 | История срабатываний расписания |
| `POST` | `/api/v1/schedules/{schedule_id}/fire-now` | schedules | 200, 422 | Принудительно запустить расписание сейчас |
| `POST` | `/api/v1/schedules/{schedule_id}/toggle` | schedules | 200, 422 | Включить / выключить расписание |
| `GET` | `/api/v1/scripts` | scripts | 200, 422 | Список скриптов с пагинацией |
| `POST` | `/api/v1/scripts` | scripts | 201, 422 | Создать скрипт с DAG |
| `DELETE` | `/api/v1/scripts/{script_id}` | scripts | 204, 422 | Архивировать скрипт (soft delete, не удаляет версии) |
| `GET` | `/api/v1/scripts/{script_id}` | scripts | 200, 422 | Получить скрипт с историей версий |
| `PUT` | `/api/v1/scripts/{script_id}` | scripts | 200, 422 | Обновить скрипт (создаёт новую версию при изменении DAG) |
| `GET` | `/api/v1/scripts/{script_id}/versions` | scripts | 200, 422 | История версий скрипта |
| `POST` | `/api/v1/scripts/{script_id}/versions/{version_id}/rollback` | scripts | 200, 422 | Откатить скрипт к указанной версии (создаёт новую версию) |
| `POST` | `/api/v1/streaming/{device_id}/keyframe` | streaming | 200, 422 | Request Keyframe |
| `POST` | `/api/v1/streaming/{device_id}/start` | streaming | 200, 422 | Request Stream Start |
| `GET` | `/api/v1/streaming/{device_id}/status` | streaming | 200, 422 | Get Stream Status |
| `POST` | `/api/v1/streaming/{device_id}/stop` | streaming | 200, 422 | Request Stream Stop |
| `GET` | `/api/v1/tasks` | tasks | 200, 422 | Список задач с фильтрацией |
| `POST` | `/api/v1/tasks` | tasks | 201, 422 | Поставить задачу в очередь |
| `DELETE` | `/api/v1/tasks/{task_id}` | tasks | 204, 422 | Отменить задачу (только QUEUED/ASSIGNED) |
| `GET` | `/api/v1/tasks/{task_id}` | tasks | 200, 422 | Получить задачу по ID |
| `GET` | `/api/v1/tasks/{task_id}/live-logs` | tasks | 200, 422 | Live node execution log entries (from Redis, for running tasks) |
| `GET` | `/api/v1/tasks/{task_id}/logs` | tasks | 200, 422 | Логи выполнения задачи (per-node) |
| `GET` | `/api/v1/tasks/{task_id}/progress` | tasks | 200, 422 | Live-прогресс выполнения задачи (из Redis кэша) |
| `GET` | `/api/v1/tasks/{task_id}/screenshots` | tasks | 200, 422 | Presigned URLs к скриншотам задачи (TTL 1 час) |
| `POST` | `/api/v1/tasks/{task_id}/stop` | tasks | 200, 422 | Принудительно остановить задачу (QUEUED/ASSIGNED/RUNNING) |
| `GET` | `/api/v1/updates/` | updates | 200, 422 | List Releases |
| `POST` | `/api/v1/updates/` | updates | 201, 422 | Create Release |
| `GET` | `/api/v1/updates/latest` | updates | 200, 422 | Get Latest |
| `DELETE` | `/api/v1/updates/{release_id}` | updates | 200, 422 | Delete Release |
| `GET` | `/api/v1/users` | users | 200, 422 | Список пользователей организации |
| `POST` | `/api/v1/users` | users | 201, 422 | Создать пользователя |
| `GET` | `/api/v1/users/{user_id}` | users | 200, 422 | Профиль пользователя |
| `PATCH` | `/api/v1/users/{user_id}/deactivate` | users | 200, 422 | Деактивировать пользователя |
| `PUT` | `/api/v1/users/{user_id}/role` | users | 200, 422 | Изменить роль пользователя |
| `POST` | `/api/v1/vpn/admin/config-preview` | vpn | 200, 422 | Preview AWG config (dev/test only) |
| `POST` | `/api/v1/vpn/admin/keypair` | vpn | 200 | Generate WireGuard keypair |
| `POST` | `/api/v1/vpn/assign` | vpn | 200, 422 | Assign VPN peer to device |
| `GET` | `/api/v1/vpn/health` | vpn | 200 | VPN subsystem health check |
| `POST` | `/api/v1/vpn/killswitch` | vpn | 200, 422 | Enable/disable Kill Switch on devices |
| `GET` | `/api/v1/vpn/peers` | vpn | 200, 422 | List VPN peers |
| `GET` | `/api/v1/vpn/pool/stats` | vpn | 200 | VPN pool statistics |
| `DELETE` | `/api/v1/vpn/revoke/{device_id}` | vpn | 204, 422 | Revoke VPN peer of device |
| `POST` | `/api/v1/vpn/rotate` | vpn | 200, 422 | Bulk rotate VPN IPs |
