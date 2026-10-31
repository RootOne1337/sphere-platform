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
