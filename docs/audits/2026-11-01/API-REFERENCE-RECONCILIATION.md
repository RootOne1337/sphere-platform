# Сверка ручного API-справочника

Срез от 1 ноября 2026: рабочее дерево проекта и зарегистрированный снимок
[OpenAPI](../../openapi.json). Это анализ исходного кода и деклараций; запросов
к работающему API, Android или внешним сервисам не выполняли. Схема содержит
160 путей и 201 HTTP-операцию; счётчик включает методы GET/POST/PUT/PATCH/DELETE
и не подтверждает исполнение, deployment или WebSocket. Числа относятся к
прочитанному снимку, не к будущим сборкам.

Ниже — реестр существенных исправлений в [ручном справочнике](../../api-reference.md).
Пути относительны к `/api/v1`. Права взяты из исследованных обработчиков, а не
выведены только из OpenAPI; типичные ошибки, влияние повторного запроса и
состояние запуска нужно рассматривать в контексте конкретного маршрута.

| Маршрут или область | Подтверждённое расхождение и исправленная граница | Источник |
| --- | --- | --- |
| GET /devices; PUT /devices/{id}; GET /devices/{id}/status | Убран несуществующий фильтр tag, устаревшие поля ответов и неверный PATCH в примере. Чтение `device:read`, изменение `device:write`; данные присутствия отдельно от подтверждения действия. | [router](../../../backend/api/v1/devices/router.py), [каталог](../../operations/DEVICE-CATALOG.md) |
| GET /audit/logs, GET /audit/logs/export | Ранее был указан путь `/audit`, устаревшие поля и пример. `audit:read`, tenant filter, CSV до 5000 с признаком усечения. | [router](../../../backend/api/v1/audit/router.py), [схемы](../../../backend/schemas/audit.py) |
| Rate limits | Удалены вымышленные универсальные 10/60/300 req/min, отсутствие WebSocket-лимита и обязательные заголовки; приведены значения проверенного nginx и отдельная защита login из исходников. Эффективная конфигурация среды может отличаться. | [nginx](../../../infrastructure/nginx/nginx.conf), [auth service](../../../backend/services/auth_service.py), [router](../../../backend/api/v1/auth/router.py) |
| GET /health и подмаршруты | Исправлен вымышленный ответ c checks; базовый handler отдаёт status/version, liveness и проверки зависимостей — отдельные маршруты. | [main](../../../backend/main.py), [router](../../../backend/api/v1/health/router.py) |
| GET/POST /schedules, GET/PATCH/DELETE /schedules/{id} | Заменены неактуальные примеры на реально именованные trigger, target и result поля. Delete делает деактивацию, не физическое удаление. | [router](../../../backend/api/v1/schedules/router.py), [схема](../../../backend/schemas/schedule.py), [service](../../../backend/services/scheduler/schedule_service.py) |
| POST /schedules/{id}/toggle и /fire-now | Toggle принимает обязательный query `active`, не JSON `enabled`. Fire-now изменяет next_fire_at; это ещё не подтверждение выполнения. Ранее описанный POST /schedules/{id}/dry-run в снимке отсутствует. | [router](../../../backend/api/v1/schedules/router.py), [service](../../../backend/services/scheduler/schedule_service.py) |
| GET/POST /game-accounts, GET/PATCH/DELETE /game-accounts/{id} | Исправлен PUT на PATCH, ложное обещание случайного nickname и поля фильтра/ответа. Раскрытие пароля отдельно требует `account:credentials:read`; response handler DELETE возвращает 204, хотя snapshot декларирует 200. | [router](../../../backend/api/v1/game_accounts/router.py), [схема](../../../backend/schemas/game_accounts.py), [service](../../../backend/services/game_account_service.py) |
| GET/POST /event-triggers, GET/PATCH/DELETE /event-triggers/{id}, POST /event-triggers/{id}/toggle | Исправлены PUT, фильтры, форма правила и query `active`; права `pipeline:read/write`, удаление физическое. Сохранение триггера не доказывает выполнение pipeline. | [router](../../../backend/api/v1/event_triggers/router.py), [схема](../../../backend/schemas/event_trigger.py) |
| GET/PATCH /pipeline-settings, POST /pipeline-settings/toggle/* | Убраны фиктивные POST на коллекции и DELETE элемента: возвращается настройка организации, а GET может создать defaults с commit; toggle принимает JSON `enabled`. | [router](../../../backend/api/v1/pipeline_settings/router.py), [service](../../../backend/services/pipeline_settings_service.py) |
| GET/POST /account-sessions; POST /account-sessions/{id}/end | Исправлены фильтры и поля; завершение — POST с обязательным `end_reason`, а не PUT. Права `session:read/write`. | [router](../../../backend/api/v1/account_sessions/router.py), [схема](../../../backend/schemas/account_sessions.py) |
| GET/POST /device-events; POST /device-events/{id}/processed | Исправлены фильтры и поля; обработчик processed отвечает 204, хотя snapshot декларирует 200. `event:read/write`; отметка не означает действие устройства. | [router](../../../backend/api/v1/device_events/router.py), [схема](../../../backend/schemas/device_events.py) |
| POST /streaming/{device_id}/start, /stop, /keyframe; GET /streaming/{device_id}/status | Старые пути без device_id и список sessions отсутствуют. Права `stream:control/read`, проверка tenant; requested — не подтверждение работы Android или видеокадров. Ошибка транспорта может означать неизвестный результат. | [router](../../../backend/api/v1/streaming/router.py) |
| GET /monitoring/metrics, /nodes, /fleet-coverage; POST /monitoring/alerts | Metrics — защищённый `monitoring:read` JSON, а не Prometheus text; `/health` и `/pool-stats` в этом router отсутствуют. Alert handler не заявляет user permission dependency и логирует, будущая WebSocket-трансляция не реализована. | [router](../../../backend/api/v1/monitoring/router.py) |

Также убраны заголовки, представлявшие незарегистрированный execute скрипта и
`batch_id` как контракт task progress: пояснение об их отсутствии сохранено.

## Дополнительный проход по примерам и операциям

На `92e10cbd154dc9254a64d4945a580c8a22ba3496` и в менявшемся рабочем дереве
повторно изучены следующие **описанные в справочнике** области; это не утверждение
о пооперационной проверке всех 201 маршрута:

| Область | Сверенные источники и результат |
| --- | --- |
| Agent config и регистрация | [config router](../../../backend/api/v1/config/router.py), [config schema](../../../backend/schemas/agent_config.py), [registration schema](../../../backend/schemas/device_register.py), [devices router](../../../backend/api/v1/devices/router.py): необязательный ключ, 401 для невалидного, принимаемый, но не используемый handler `X-Agent-Fingerprint`; результат регистрации не является доказательством подключения. |
| Devices и bulk | [devices router](../../../backend/api/v1/devices/router.py), [device service](../../../backend/services/device_service.py), [bulk schema](../../../backend/schemas/bulk.py) и [bulk service](../../../backend/services/bulk_service.py): методы/поля примеров, `device:read/write/delete`, screenshot/cache stub, агентские команды и различие transport error/неизвестного исхода. Native capture и UI hierarchy отдельно описаны в связанных контрактных аудитах; на устройстве не повторялись. |
| Groups | [router](../../../backend/api/v1/groups/router.py), [schema](../../../backend/schemas/groups.py): таблица CRUD/tag/move, роли, тело и лимит move, нормализация/лимит тегов; бизнес-гарантии и concurrent behavior в [профильном контракте](../../operations/GROUP-HIERARCHY.md). |
| Scripts | [router](../../../backend/api/v1/scripts/router.py), [DAG schema](../../../backend/schemas/dag.py): каталоги/версионирование, `include_dag`, optimistic условия и пример минимального DAG. Локальная schema validation примера прошла; она не запускает ни сеть, ни Android. Инварианты блокировок и результат live-записи этим не испытывались. |
| Tasks | [router](../../../backend/api/v1/tasks/router.py), [schema](../../../backend/schemas/task.py), [service](../../../backend/services/task_service.py): фильтры, admission, rerun, cancel/stop, сохранённый результат. Добавлено предупреждение, что сбой ответа после commit может сопровождать создание задачи; readback обязателен до повтора. Artifact security здесь не воспроизводилась. |
| Batches | [router](../../../backend/api/v1/batches/router.py), [schema](../../../backend/schemas/batch.py), [service](../../../backend/services/batch_service.py), [admission worker](../../../backend/services/batch_admission.py): исправлены устаревшие утверждения о одноразовом worker, ручном recovery, ответе без per-device admission receipts и немедленной отмене ASSIGNED. План/cursor/receipts сохраняются в БД; worker может повторить pending admission, но это не доказательство запуска или работоспособности установленного worker. Broadcast не определяет и не применяет version guard. |
| VPN | [router](../../../backend/api/v1/vpn/router.py), [контроль](../../operations/VPN-CONTROL-OUTCOMES.md), [profiles](../../operations/VPN-PROFILES.md): список/фильтры, assign/revoke/rotate/killswitch и чувствительные результаты. Для admin keypair/config-preview handler не объявляет user permission dependency; preview дополнительно заблокирован при `ENVIRONMENT=production` и `DEBUG=false`. Внешний gateway и доступность этих путей не проверены. |

В репозитории есть [batch recovery tests](../../../tests/production/test_batch_recovery.py),
[отмена batch](../../../tests/production/test_batch_cancellation.py),
[отмена задач](../../../tests/production/test_durable_task_cancellation.py),
[версии scripts](../../../tests/production/test_script_version_workflow.py),
[иерархия групп](../../../tests/production/test_group_hierarchy.py). Их наличие —
не результат запуска этого прохода; здесь интеграционные тесты не запускали.

## Дополнительная сверка orchestration и соседних маршрутов

На исходном срезе `c8c35253` и меняющемся рабочем дереве сопоставлены все
**47 зарегистрированных method/path** в шести группах со схемой, обработчиками,
основными схемами запросов и применимыми фрагментами сервисов. Это не означает
подтверждение всех ветвей кода, конкурентных транзакций или живого исполнения:

| Область | Охват и существенные границы |
| --- | --- |
| Pipeline: 13 операций | [Router](../../../backend/api/v1/pipelines/router.py), [schema](../../../backend/schemas/pipeline.py), [service](../../../backend/services/orchestrator/pipeline_service.py): CRUD/toggle, list/detail runs, run/run-batch и pause/resume/cancel. `run-batch` сохраняет настройки волн, но сразу создаёт `QUEUED` run для каждого выбранного устройства; глобальный поиск по backend не выявил их применения pipeline executor для задержки admission. Не обещаем поэтапную подачу. Cancel может ожидать child, resume возвращает 409 при занятом executor или неизвестном исходе; потерянный ответ не разрешает слепой повтор. |
| Schedules: 8 операций | [Router](../../../backend/api/v1/schedules/router.py), [schema](../../../backend/schemas/schedule.py), [service](../../../backend/services/scheduler/schedule_service.py): list/create/get/patch/delete, toggle, fire-now, executions. Неизвестный timezone в расчёте cron приводит к UTC fallback; fire-now меняет `next_fire_at`, сам по себе не доказывает запуск. Применение различных конфликтных политик и пограничных timezone на работающем scheduler не воспроизводилось. |
| Pipeline settings: 10 операций | [Router](../../../backend/api/v1/pipeline_settings/router.py), [schema](../../../backend/schemas/pipeline_settings.py): GET/PATCH, четыре toggle, status/servers, nick generate/check. Оба GET settings и status вызывают get-or-create с commit. Status-поля `registrations_completed`, `registrations_failed`, `bans_detected` в данном handler не заполняются и получают schema defaults 0; считать их измеренными счётчиками нельзя. |
| Device events: 5 операций | [Router](../../../backend/api/v1/device_events/router.py), [schema](../../../backend/schemas/device_events.py), [service](../../../backend/services/device_event_service.py): stats/list/create/get/processed. Неизвестный severity-фильтр игнорируется сервисом. Handler processed отдаёт 204 при декларации 200 в snapshot. Проверка создаваемого события и связанных идентификаторов в работающей среде не проводилась. |
| Event triggers: 6 операций | [Router](../../../backend/api/v1/event_triggers/router.py), [schema](../../../backend/schemas/event_trigger.py): CRUD и toggle. При PATCH явный null игнорируется, в том числе для description; `active` задаётся query. Создание правила не является доказательством запуска. |
| Account sessions: 5 операций | [Router](../../../backend/api/v1/account_sessions/router.py), [schema](../../../backend/schemas/account_sessions.py), [service](../../../backend/services/account_session_service.py): stats/list/start/get/end. Недопустимый фильтр end_reason молча игнорируется; end требует известную причину и возвращает 404 для отсутствующей или уже завершённой активной сессии. Операция записи не доказывает logout в игре. |

Ручной осмотр create session/event не обнаружил в соответствующих service-методах
явной проверки принадлежности связанных UUID организации. Эффективные RLS,
ограничения базы и внешние защиты этим осмотром не проверены: это открытый вопрос
для отдельной проверки, не подтверждение обхода изоляции.

## Дополнительные расхождения API и исходников

- [GET /config/agent](../../../backend/api/v1/config/router.py): при наличии
  `enrollment_api_key` в загруженной конфигурации он включается в базовый ответ
  без предъявления API-ключа. Это риск раскрытия credential при доступном endpoint;
  состояние фактического файла, ingress и развёрнутой среды не проверяли. Schema
  описывает `min_agent_version` как принудительный OTA, но поиск поля в коде не
  выявил соответствующего потребителя; enforcement не подтверждён.
- [GET /devices/me](../../../backend/api/v1/devices/router.py): docstring обещает
  404 при отсутствии устройства, но handler с валидным ключом возвращает 200/null
  при неразрешённом device и перехватывает ошибки lookup. Null не доказывает отсутствие.
- [DELETE /auth/mfa и DELETE /auth/api-keys/{id}](../../../backend/api/v1/auth/router.py),
  [PATCH /users/{id}/deactivate](../../../backend/api/v1/users/router.py),
  [DELETE /updates/{id}](../../../backend/api/v1/updates/router.py): snapshot
  декларирует 200, явный `Response` в каждом handler возвращает 204. Это разница
  source/schema, не проверка HTTP в deployment. Аналогичные 200/204 для game-account
  delete и device-event processed перечислены выше.
- [Release schema](../../../backend/api/v1/updates/router.py) допускает
  `version_name` до 128 символов; [recovery grant](../../../backend/services/device_ota_recovery.py)
  и [frontend validator](../../../frontend/src/features/updates/recovery.ts)
  ограничивают его 100. Совместимость длинного имени с адресным OTA не гарантирована.
- [GET /streaming/{id}/status](../../../backend/api/v1/streaming/router.py):
  `viewer_connected` равен `is_streaming`, а отсутствие bridge даёт `drop_ratio=0`;
  это не независимое подтверждение зрителя или отсутствия потерь. Runtime не исследовался.

Локально в `.venv-audit` проверена Pydantic-валидация выбранных примеров
`CreatePipelineRequest`, `RunPipelineBatchRequest`, `UpdateEventTriggerRequest`,
`EndSessionRequest` и `CreateDeviceEventRequest`: проверка прошла. Она касается
только форм запросов, не вызывает handlers и не подтверждает приведённые эффекты.

Найдены, но в этом проходе не запускались: [pipeline admission](../../../tests/production/test_pipeline_admission.py),
[pipeline recovery](../../../tests/production/test_pipeline_recovery.py),
[pipeline cancellation](../../../tests/production/test_pipeline_cancel_intent.py),
[scheduler runtime](../../../tests/production/test_scheduler_runtime.py),
[event triggers](../../../tests/orchestrator/test_event_triggers_api.py) и
[stream control](../../../tests/production/test_stream_control_routing.py).

## Сверка auth, пользователей, discovery и OTA

На `18fa932b` и меняющемся рабочем дереве исследованы все **29 описанных в
OpenAPI method/path** в пяти группах; для наиболее важных приведены конкретные
обработчики и сервисы. Права и эффекты извлечены из исходников, а не из одной
схемы. Проверки live ingress, credentials, PostgreSQL/Redis и Android не проводили.

| Область | Проверенные контракты и ограничения |
| --- | --- |
| Auth: 12 операций | [router](../../../backend/api/v1/auth/router.py), [schemas](../../../backend/schemas/auth.py), [auth service](../../../backend/services/auth_service.py), [dependencies](../../../backend/core/dependencies.py), [API key service](../../../backend/services/api_key_service.py): login/MFA, refresh/logout, profile/capabilities, MFA setup/verify/delete и key CRUD. Исправлен обязательный `is_active` в примере `/auth/me`, добавлен capabilities, уточнено что key list возвращает `is_active` записи (включая потенциально истёкшие) и defaults creation: пустые permissions, нет expires_at. Роль capabilities читается из БД; каждый маршрут авторизует своё действие. |
| Users: 5 операций | [router](../../../backend/api/v1/users/router.py), [RBAC](../../../backend/core/rbac.py): list/create/get/role/deactivate, разрешённые роли и защита последнего владельца. Для `super_admin` application-level list filter снят; effective RLS и присутствие других tenants в реальном ответе здесь не установлены. Создание по-прежнему использует организацию вызывающего. |
| Config: 1 операция | [router](../../../backend/api/v1/config/router.py), [schema](../../../backend/schemas/agent_config.py): optional X-API-Key, неиспользуемый fingerprint и риск исходного enrollment secret в unauthenticated base response; само live раскрытие не проверено. Поиск `min_agent_version` не подтвердил принудительный OTA. |
| Discovery: 1 операция | [router](../../../backend/api/v1/discovery/router.py), [schema](../../../backend/schemas/discovery.py), [service](../../../backend/services/discovery_service.py), поиск dispatcher в [PC agent](../../../pc-agent): `device:write`, bounded subnet/ports и default `auto_register=true`; `scanned` вычисляется из размеров сети и диапазона портов, включая отсутствие успешного ответа агента, поэтому не является счётчиком доказанных попыток. Отсутствие `discover_adb` в PC-agent dispatcher — source observation, не live scan. |
| OTA: 10 операций | [router](../../../backend/api/v1/updates/router.py), [Android authenticator](../../../backend/api/ws/android/router.py), [recovery service](../../../backend/services/device_ota_recovery.py): list/create/delete, agent latest/artifact, operator download и create/read/dispatch/revoke grant. Восстановление требует managed опубликованный SHA; wake/202 не доказывают установку. Внешний HTTPS release handler не загружает и не сверяет; отдельный operator download отказывается подменять внешний latest старым managed APK. |

[AuthService.logout](../../../backend/services/auth_service.py) после проверки
подписанного Bearer в router ищет переданный refresh по его hash; явного сравнения
user/org этого refresh с Bearer principal в самом методе нет. Эффективные RLS и
наличие эксплуатируемого обхода данным чтением не установлены; требуется отдельная
проверка с изолированными пользователями и фактической DB ролью. Потеря ответа
после токенной ротации/изменения и wake после grant не доказывают отказ операции.

В `.venv-audit` прошла локальная Pydantic-проверка примера `UserResponse`,
defaults `CreateAPIKeyRequest` и нормализации/defaults `DiscoverRequest`.
Handlers, сеть и состояние сервера она не проверяет.

Найдены релевантные tests, которые в этом проходе **не запускались**:
[session rotation](../../../tests/production/test_session_rotation.py),
[MFA consumption](../../../tests/production/test_mfa_consumption.py),
[session capabilities](../../../tests/production/test_session_capabilities.py),
[device registration](../../../tests/test_agent_discovery/test_device_register.py),
[config endpoint](../../../tests/test_agent_discovery/test_config_endpoint.py),
[discovery](../../../tests/discovery/test_discovery.py),
[OTA API](../../../tests/test_updates/test_updates_api.py),
[OTA live delivery](../../../tests/production/test_ota_live_delivery.py).

## VPN и n8n: оставшиеся зарегистрированные пути

На `05594674` и меняющемся рабочем дереве сверены группы `/vpn` (**23 операции**)
и `/n8n` (**7 операций**) по зарегистрированному OpenAPI, router и указанным
service/schema. Покрытие обозначает чтение method/path, основных permissions,
параметров и видимых эффектов, а не исчерпывающее воспроизведение каждой ветки.
Изменён [ручной справочник](../../api-reference.md).

| Область | Источники и границы |
| --- | --- |
| VPN catalog: 10 операций | [profile router](../../../backend/api/v1/vpn/profile_router.py), [input bounds](../../../backend/api/v1/vpn/profile_input.py), [schema](../../../backend/schemas/vpn/catalog.py), [batch schema](../../../backend/schemas/vpn/bulk_profiles.py), [batch service](../../../backend/services/vpn/profile_batch.py), [operator contract](../../operations/VPN-PROFILES.md). `vpn:read/write`; single/batch preflight, import/status, list/detail/history, append и archive. `persisted` не означает применение; status `null`/404 не исключает поздний commit. Batch до 100 уникальных request ID, 4 MiB, единая транзакция. |
| VPN runtime и capabilities: 3 операции | [runtime router](../../../backend/api/v1/vpn/runtime_router.py), [runtime schema](../../../backend/schemas/vpn/runtime.py), [router](../../../backend/api/v1/vpn/router.py): providers/read, runtime/read, profile-preflight/write. Метка freshness относится к времени выборки и текущей WS-сессии, не подтверждает сквозной трафик или применённый профиль. |
| VPN admin/peers/control: 10 операций | [router](../../../backend/api/v1/vpn/router.py), [control contract](../../operations/VPN-CONTROL-OUTCOMES.md). Сверены keypair/preview, assign/revoke/bulk, health/peers/pool/rotate/killswitch; часть sender-результатов — unsupported/unknown, provider response не подтверждает Android. У admin-обработчиков не объявлена отдельная user permission dependency; effective ingress здесь не исследован. |
| n8n registry: 5 операций | [router](../../../backend/api/v1/n8n/router.py), [schema](../../../backend/schemas/webhook.py), [service](../../../backend/services/n8n_webhook_service.py): CRUD требует get_current_user, но не отдельный require_permission; список показывает только активные записи, GET/PATCH по owned ID работают и с выключенными. Delete handler даёт 204, OpenAPI декларирует 200. Plain secret выдаётся при создании; для HMAC используется hex SHA-256 секрета как UTF-8 ключ. В backend не найден вызов dispatch_event, поэтому подписка/доставка по этому реестру не подтверждена. |
| n8n task bridge: 2 операции | [router](../../../backend/api/v1/n8n/router.py), [task service](../../../backend/services/task_service.py), [callback service](../../../backend/services/webhook_service.py): create требует `script:execute`, poll использует get_current_user и owned ID без отдельного `script:read`. Task callback отличается от registry: передаётся без signing secret, event_type остаётся task.completed и при success=false. Это in-process delivery, не проверка результата получателя и не durable outbox. |

Проверка в `.venv-audit`: `python -m pytest
 tests/vpn/test_profile_preflight.py::test_valid_config_is_never_an_activation_or_secret_receipt -q`
с временным тестовым JWT secret — **1 passed**, одно FastAPI deprecation warning.
Тест запрещает внешние DNS/subprocess вызовы и проверяет preflight, а не live VPN.
Отдельная локальная проверка `N8nWebhookService._sign` с тестовой строкой
подтвердила использование UTF-8 hex digest вместо raw secret; сеть не вызывалась.
Другие найденные [n8n API tests](../../../tests/n8n/test_n8n_api.py),
[VPN batch tests](../../../tests/vpn/test_profile_batch.py) и
[VPN runtime tests](../../../tests/production/test_vpn_app_runtime.py) здесь не
запускались; внешний webhook receiver, БД и Android не изменялись.

## Устройства, команды, группы и локации

На `eb1ee551` и в изменявшемся рабочем дереве сопоставлены **38 method/path**:
24 `/devices` (включая bulk и direct-probe), 7 `/groups`, 7 `/locations`.
Проверены зарегистрированная схема, используемые зависимости в обработчиках и
основные ветви сервисов, перечисленные ниже. Это не проверка каждой ошибки,
взаимодействия компонентов в сети или физического исполнения команд.

| Область | Источники и результаты |
| --- | --- |
| Device CRUD и статусы | [device router](../../../backend/api/v1/devices/router.py), [schema](../../../backend/schemas/devices.py), [service](../../../backend/services/device_service.py), [status cache](../../../backend/services/device_status_cache.py). PUT с `group_id=null` не очищает membership; непустой group ID заменяет группы. DELETE — soft retirement с очисткой device refresh credentials, не уничтожение истории и не физический stop. Неизвестный legacy status игнорируется при листинге. |
| Fleet и viewers | [router](../../../backend/api/v1/devices/router.py), [status schema](../../../backend/schemas/device_status.py), [cache](../../../backend/services/device_status_cache.py), [viewers](../../../backend/services/device_viewers.py). `/devices/status/bulk` и `/status/fleet`: `online` и `busy` раздельно, отсутствующие cache records считаются offline; при отсутствии клиента Redis этот счётчик не доказывает offline. Основной `/devices` при недоступном presence использует unknown, а его online включает busy. Viewer pulse — регистрация/наблюдение, не доказательство воспроизведения. |
| Команды, capture и diagnostics | [device router](../../../backend/api/v1/devices/router.py), [bulk service](../../../backend/services/bulk_service.py), [direct probe router](../../../backend/api/v1/direct_probe/router.py). `connect` и старый GET screenshot — cache stubs; reboot может вернуть 200/error, успешный receipt не равен завершению; таймаут не исключает эффект. Shell/logcat возвращают output или error, probe capabilities не доказывают reachability. Native capture и UI hierarchy не воспроизводились на устройстве. |
| Device registration/refresh | [router](../../../backend/api/v1/devices/router.py), [registration service](../../../backend/services/device_registration_service.py), [bootstrap contract](../../security/device-credential-bootstrap.md). Refresh читает отдельную device cookie; same request UUID и старый токен позволяют восстановить один ещё не потреблённый successor в описанной исходной ветке. Это не доказывает успешную recovery в развёрнутой среде. |
| Groups | [router](../../../backend/api/v1/groups/router.py), [schema](../../../backend/schemas/groups.py), [service](../../../backend/services/group_service.py). CRUD/move/tags и permissions проверены по коду; фильтр `GET /devices?group_id=…` не делает отдельного lookup существования target, поэтому прежнее обобщение про 404 для любого чужого group ID удалено. |
| Locations | [router](../../../backend/api/v1/locations/router.py), [schema](../../../backend/schemas/locations.py), [service](../../../backend/services/location_service.py). Проверены CRUD, conditional update/delete, additive assignment и removal с `device:read/write/delete`; детали конкурентности и фактическая SQL isolation остались за пределами этого прохода. |

Локальная проверка `DeviceStatusCache(None).get_fleet_summary` на искусственном ID
подтвердила null observation и offline aggregate без Redis; валидация
`UpdateDeviceRequest` подтвердила принятие null group, семантика ненулевого
присваивания исследована по service. Сеть, DB и устройства не вызывались. Найдены,
но в этом проходе не запускались [bulk retirement](../../../tests/production/test_device_bulk_retirement.py),
[device refresh recovery](../../../tests/production/test_device_refresh_recovery.py),
[location hierarchy](../../../tests/production/test_location_hierarchy.py),
[UI hierarchy endpoint](../../../tests/production/test_ui_hierarchy_endpoint.py)
и [direct probe capabilities](../../../tests/test_ws/test_direct_probe_capabilities.py).

## Game accounts, account sessions, audit и device logs

На `fb91e487` и изменявшемся рабочем дереве сопоставлены **20 зарегистрированных
method/path**: 10 game accounts, 5 account sessions, 2 audit, 3 device logs.
Сопоставление учитывает доступ, параметры схем, основные эффекты сервисов и
статус ответа. Это не проверка всех конкурентных сценариев или работающей среды.

| Область | Изученные источники и результаты |
| --- | --- |
| Game accounts — 10 | [router](../../../backend/api/v1/game_accounts/router.py), [schema](../../../backend/schemas/game_accounts.py), [service](../../../backend/services/game_account_service.py), [credentials](../../security/account-credentials.md). Read/write и отдельное credentials:read, list/stats/servers/create/import/get/patch/delete/assign/release. Неверный status игнорируется, неизвестная сортировка откатывается к created_at. Assign требует free и owned device; release снимает назначение, увеличивает total_sessions и устанавливает free/cooldown, но не доказывает завершение игры или отдельной session. Null в PATCH пропускается; переход в free снимает назначение. Delete возвращает source 204 при schema 200. |
| Account sessions — 5 | [router](../../../backend/api/v1/account_sessions/router.py), [schema](../../../backend/schemas/account_sessions.py), [service](../../../backend/services/account_session_service.py), [Web](../../../frontend/app/%28dashboard%29/sessions/page.tsx). Особая граница: manual UI посылает только reason; схема подставляет два нулевых счётчика и три null, сервис присваивает их записи, потенциально перезаписывая прежние данные. Это описано и в [операторском руководстве](../../operations/USER-ADMIN-GUIDE.md). Только started_at/ended_at/created_at поддержаны для сортировки; неизвестные поля возвращаются к started_at. Отсутствие ответа не доказывает, что завершение не произошло. |
| Audit — 2 | [router](../../../backend/api/v1/audit/router.py), [schema](../../../backend/schemas/audit.py), [query](../../../backend/services/audit_query.py), [investigation](../../operations/AUDIT-INVESTIGATION.md). `audit:read`, организация, валидированные интервалы и поисковые условия, общий фильтр для списка и CSV; экспорт ограничен 5000, не содержит произвольных old/new/meta. Проверка не устанавливает полноту самого журнала. |
| Device logs — 3 | [router](../../../backend/api/v1/logs/router.py), [read schema](../../../backend/schemas/device_logs.py), [reader](../../../backend/services/device_log_reader.py), [upload](../../../backend/services/device_log_upload.py), [операторский контракт](../../operations/DEVICE-LOG-STORAGE.md). Upload проверяет device principal и ограничивает body 512 KiB; GET требует device:read и возвращает bounded tail с read metadata; DELETE требует device:delete. Handlers upload/delete возвращают 204 при OpenAPI 200. Удаление использует `ignore_errors=True`, потому 204 не доказывает удаление всех файлов. |

Локально в `.venv-audit` проверены defaults `EndSessionRequest` для `manual` и
верхняя граница `ReleaseAccountRequest.cooldown_minutes`: проверка прошла;
сервис, DB и HTTP не вызывались. Найдены, но в этом проходе не запускались
[account credentials](../../../tests/production/test_account_credentials.py),
[audit investigation](../../../tests/production/test_audit_investigation.py),
[log read budget](../../../tests/devices/test_log_read_budget.py),
[log upload budget](../../../tests/devices/test_log_upload_budget.py). Сценарии
записи существующих session-метрик и проверки реального удаления логов требуют
отдельной проверки в изолированной среде.

## Scripts и tasks: источники, версии и управление

На `3ccac757` и менявшемся рабочем дереве изучены **22 зарегистрированных
method/path**: 11 `/scripts` и 11 `/tasks`. Сверялись OpenAPI, handlers, схемы,
основные ветви сервиса и действующие руководства. Это не доказательство работы
installed backend или физического результата Android.

| Область | Сверенные источники и пределы |
| --- | --- |
| Scripts: 11 операций | [router](../../../backend/api/v1/scripts/router.py), [schemas](../../../backend/schemas/script.py), [service](../../../backend/services/script_service.py), [action parameters](../../../backend/schemas/action_parameters.py), [versions guide](../../operations/SCRIPT-VERSIONS.md), [catalog guide](../../operations/SCRIPT-CATALOG.md). Read/write, validate/action-contract/catalog, create/read/update/archive и version history/rollback. Исправлено утверждение: PUT с тем же нормализованным DAG hash не создаёт новую version, хотя metadata может измениться. Документированы текущие поля parameter-validation receipt и отдельный read-only action contract. Expected-current — условие на просмотренную версию, а не idempotency key; rollback создаёт новую version. |
| Tasks: 11 операций | [router](../../../backend/api/v1/tasks/router.py), [schema](../../../backend/schemas/task.py), [service](../../../backend/services/task_service.py), [task protocol](../../security/task-control-protocol.md). Проверены list/create/detail/rerun/delete/stop, stored logs, progress/live logs и screenshot manifest/content. Отсутствие Redis progress key даёт нули, а не подтверждение нулевой работы; повтор create/rerun может создать новую задачу после terminal. QUEUED stop и ASSIGNED/RUNNING cancellation имеют разные receipts, terminal device outcome — отдельное свидетельство. |
| Artifact status | [private screenshot configuration](../../configuration.md#private-task-screenshot-reads), [task artifact audit](../2026-10-02/TASK-ARTIFACTS-AND-RERUN.md). Утверждение о выключенных pilot reads помечено как историческое; текущие settings/deployment не исследовались. Локальный путь Android не доказывает загрузку в объектное хранилище. |

Локально в `.venv-audit` с временным тестовым JWT secret выполнено
`python -m pytest tests/test_scripts/test_action_parameters.py tests/test_scripts/test_draft_validation.py -q`:
**125 passed**, одно FastAPI deprecation warning. Это локальные проверки схем,
валидатора и изолированного ASGI с подставными зависимостями, без команд устройств.
Тесты [script version workflow](../../../tests/production/test_script_version_workflow.py)
и [durable task cancellation](../../../tests/production/test_durable_task_cancellation.py)
в этом проходе не запускались; доступность PostgreSQL/Redis, race outcomes и
физический stop не подтверждены.

## Проверки и остаток

Машинное сравнение HTTP method/path во **всех заголовках** справочника с JSON,
с приведением имён `{parameter}` и исключением query string, на этом срезе не
нашло несовпадений. Это проверка заголовков, а не каждого inline-примера, формы
запроса, зависимости, статуса ответа или поведения в CI. Существование локальных
путей Markdown-переходов проверено отдельно; anchors, внешние ресурсы и ссылки из
иных форматов эта проверка не доказывает. `git diff --check` выполнен.

Описанные выше обработчики и связанные схемы/сервисы изучены выборочно. Остальные
маршруты snapshots, все permissions и tenants, stubs, ошибки, схемы, побочные
эффекты и конкурентные ситуации не получили пооперационной сверки. Интеграционные backend-тесты и проверка работающего экземпляра не выполнялись.
`python -m scripts.export_api_docs --check` в `.venv-audit` с временным тестовым
`JWT_SECRET_KEY` прошёл: текущие schema и endpoint catalog совпадают с импортированным
приложением без запуска lifespan или HTTP-запросов. Это не runtime-приёмка.
Первый запуск без тестового значения прервался на обязательной настройке;
проверочный ключ не использовался для развёртывания. Изменяющую файлы регенерацию
не выполняли. Следующая
работа: сопоставить каждую inline/table операцию и параметры с соответствующими
router/service, затем отдельно проверить декларации ответов против реальных
обработчиков и покрыть существенные различия тестами. Декларации 200 против
фактических 204 являются вопросом синхронизации кода и схемы, не исправлены
изменением документации.
