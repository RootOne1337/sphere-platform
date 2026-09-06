# Sphere Platform: аудит готовности к эксплуатации

Статус на 6 сентября 2026: **аудит продолжается; production readiness не подтверждена**.
Исходная ревизия: `28f8cc46ab65496e00297960fd94d87d1605cc83`.
Ветка исправлений: `codex/enterprise-audit-20260905`; [draft PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

Проверка разрешена владельцем. Воспроизведения выполнялись на локальных искусственных
данных, выделенных PostgreSQL/Redis и подменённых транспортных границах. Внешняя
инфраструктура не является целью тестирования. Целевая конфигурация — 10–64 эмулятора
на станции с последующим использованием физических Android-устройств.

Главные подтверждённые риски: повышение tenant-пользователя до платформенного
администратора, нарушение изоляции устройств и задач, повторное выполнение DAG,
потеря результата при сбое транспорта и несогласованность PostgreSQL с Redis.
Исправления ниже включают регрессионные проверки. Успешная сборка отдельно от
runtime-проверок и не считается доказательством работоспособности системы.

## Результаты проверок

| Проверка | Результат | Практическое ограничение |
| --- | --- | --- |
| Android enterprise debug unit suite | 316 passed, 0 failed | JVM/MockWebServer; не проверяет ОС, codec, батарею или смерть процесса на телефоне |
| Backend/PC существующая suite и lifespan regressions | Предыдущий полный прогон: 834 passed. Последний: 833 passed, 1 performance failure; отдельный повтор этого теста прошёл | Порог DAG validation 100 ms: последний замер 127.1 ms на общей станции. Порог не ослаблялся; load suite исключена |
| Новые проверки PostgreSQL/Redis | 38 passed, 0 xfail | Включены rollback, dispatch recovery и n8n/orchestrator producers |
| Миграции | Исходные миграции и device refresh применены к изолированной БД | Данные production не мигрировались |
| Backend image | Собирается; исходная запись OpenAPI воспроизведённо падает с PermissionError | Исправлен lifespan; полный deployment runtime ещё не подтверждён |
| Frontend build | Успешно | Type-check/Jest и браузерный runtime требуют отдельного завершения проверки |
| APK ↔ реальный локальный backend | Не завершено | Автоматическая проверка разрешений отклонила запуск локального API: `blocked by policy`; обход не выполнялся |
| 10–64 эмулятора, физические телефоны | Не измерено | Нет подтверждённых CPU/RAM/FPS/энергопотребления и совместимости со всеми Android |

Команды запуска и предохранители изоляции: [tests/production/README.md](../../../tests/production/README.md).
Исходные `14 passed` в [reproductions.txt](evidence/reproductions.txt) означают
**успешное воспроизведение дефектов исходной версии**, а не успешную защиту.
Файлы `*-before.txt` фиксируют падение будущих защитных проверок; `*-after.txt` — результат исправлений.

## Подтверждённые дефекты и исправления

### AUD-01 / F01 — Critical: повышение до платформенного администратора

- **Root cause:** операции над пользователями проверяли общее право записи, но не право делегировать конкретную роль. `org_admin` мог создать `super_admin` и получить доступ за пределами своей организации.
- **Evidence:** F01 исходного воспроизведения и [security-before.txt](evidence/security-before.txt).
- **Affected files:** `backend/core/rbac.py:143`, `backend/api/v1/users/router.py:80`.
- **Fix:** `4af9a89` — матрица управляемых ролей, проверки текущей и новой роли, защита последнего активного владельца с блокировкой строки организации.
- **Regression:** `tests/production/test_role_boundaries.py`; отрицательные и разрешённые сценарии делегирования.
- **Residual risk:** остальные административные операции и конкурентное изменение полномочий требуют продолжения аудита; это не сертификат корректности всего RBAC.

### AUD-02 / F02 — Critical: выпуск привилегированного агентского ключа пользователем viewer

- **Root cause:** выпуск ключей и их scopes не были ограничены полномочиями создателя.
- **Evidence:** F02 исходного воспроизведения; viewer создавал ключ с агентскими полномочиями.
- **Affected files:** `backend/api/v1/auth/router.py:343`, `backend/core/rbac.py`.
- **Fix:** `4af9a89` — отдельные права API-key read/write, запрет неизвестных и wildcard scopes, запрет делегирования недоступных разрешений.
- **Regression:** `test_role_boundaries.py`: отказ viewer, запрет wildcard, разрешённый ограниченный agent scope владельца.
- **Residual risk:** исправление не отзывает автоматически ранее выпущенные ключи; перед rollout требуется инвентаризация существующих credentials.

### AUD-03 / F03 — High: PC-agent принимал чужой идентификатор; регистрация не соответствовала схеме

- **Root cause:** агентский ключ не связывался с организацией workstation; SQL регистрации использовал отсутствующие столбцы.
- **Evidence:** F03; [pc-registration-before.txt](evidence/pc-registration-before.txt) с ошибкой схемы.
- **Affected files:** `backend/api/ws/agent/router.py:61`.
- **Fix:** `c2d8250` — проверка типа/scopes ключа и принадлежности workstation, короткие DB-сессии, ORM-сохранение метаданных, подписка на команды, корректное отключение текущей сессии.
- **Regression:** `tests/production/test_pc_contract.py`: отказ чужому ID и сохранение регистрации в настоящем PostgreSQL.
- **Residual risk:** реальный PC-agent reconnect/recovery и все команды управления эмуляторами ещё не подтверждены end-to-end.

### AUD-04 / F04 и AUD-05 / F05 — High: подмена устройства и управление экраном от viewer

- **Root cause:** device JWT подтверждал организацию, но не соответствие subject идентификатору в URL; просмотр и управление стримом использовали одинаковую авторизацию.
- **Evidence:** F04/F05 и `tests/production/test_agent_authorization.py`.
- **Affected files:** `backend/api/ws/android/router.py:25`, `backend/api/ws/stream/router.py:68`.
- **Fix:** `9b34d00` — активность и совпадение device subject/URL/org, допустимые agent principals, отдельное `stream:control` для управляющих сообщений.
- **Regression:** отказ device JWT для другого устройства; viewer не может отправлять touch/text-команды; обновлены WebSocket auth tests.
- **Residual risk:** отзыв и истечение токена на уже открытом соединении, права всех дополнительных типов сообщений требуют отдельной проверки.

### AUD-06 / F06 — High: чужой и повторный результат задачи изменял состояние

- **Root cause:** поиск задачи только по ID; отсутствие блокировки и полного запрета изменения терминального результата.
- **Evidence:** F06; `tests/production/test_result_isolation.py` проверяет чужое устройство и конфликтующий повтор.
- **Affected files:** `backend/services/task_service.py:408`, `backend/api/ws/android/router.py`.
- **Fix:** `9febb43`, `0f717b1` — фильтры device/org, `FOR UPDATE`, неизменяемые terminal states; подтверждение только после DB commit.
- **Regression:** `test_result_isolation.py`, `test_result_receipts.py`: повтор, чужой task, Redis outage, отказ PostgreSQL commit, чтение зафиксированного результата отдельной DB-сессией непосредственно при ACK.
- **Residual risk:** event/webhook side effects, task progress и агрегирование batch требуют дальнейшей проверки транзакционности и конкурентности.

### AUD-07 / F07 — High: подстановка данных чужого игрового аккаунта

- **Root cause:** account lookup по переданному ID без фильтра организации.
- **Evidence:** F07 — в DAG попадал искусственный пароль аккаунта другой организации.
- **Affected files:** `backend/services/task_service.py:105` и создание задачи.
- **Fix:** `9febb43` — tenant filter для явной и автоматической привязки аккаунта.
- **Regression:** `tests/production/test_result_isolation.py`.
- **Residual risk:** хранение паролей и раскрытие их через другие API пока не закрыты. Ошибка cache identity после подстановок исправлена отдельно в APK-05.

### AUD-08 / F08 — High: два одновременных задания одному устройству и снятие чужой lease

- **Root cause:** `GET` выполнялся до атомарного Lua, а завершение делало безусловный `DEL`. При ошибке Lua включался неатомарный fallback.
- **Evidence:** [queue-before.txt](evidence/queue-before.txt): две параллельные выдачи и исчезновение lease новой задачи после старого результата.
- **Affected files:** `backend/services/task_queue.py:90`, `backend/requirements.txt`.
- **Fix:** `10af834` — проверка занятости внутри Lua, compare-and-delete при завершении, отказ от fallback после неоднозначного сетевого сбоя; fakeredis исполняет тот же Lua.
- **Regression:** `tests/production/test_queue_recovery.py`: конкурентность, старый результат, потеря ответа Redis после исполнения команды.
- **Residual risk:** этот коммит сам по себе не решал потерю Redis. В `8367979` основной диспетчер переведён на PostgreSQL ownership; Redis queue остаётся вспомогательным API. Старые Redis-пути scheduler и startup требуют очистки при завершении rollout.

### AUD-12 / F12 — High: неограниченное ожидание ответа команды и преждевременное завершение

- **Root cause:** дедлайн проверялся только после сообщения Pub/Sub; при тишине он не исполнялся. `received/running` принимались за конечный ответ.
- **Evidence:** F12, [command-deadline-before.txt](evidence/command-deadline-before.txt).
- **Affected files:** `backend/websocket/pubsub_router.py`, метод `send_command_wait_result`.
- **Fix:** `00d86a2` — общий timeout подписки/отправки/ожидания, фильтрация промежуточных ACK, единый `command_id`, закрытие отдельного Pub/Sub-соединения.
- **Regression:** `tests/production/test_pubsub_deadline.py`: молчащий канал, зависшая отправка, два промежуточных ACK перед результатом.
- **Residual risk:** временный Pub/Sub-канал не является долговечным хранилищем результатов.

### AUD-13 / F13 — High: tenant DB helper падал на PostgreSQL

- **Root cause:** параметризация `SET LOCAL` в синтаксисе, который PostgreSQL не поддерживает.
- **Evidence:** F13, `tests/production/test_tenant_context.py`.
- **Affected files:** `backend/core/dependencies.py`, `backend/database/engine.py`.
- **Fix:** `e07f4cd` — `SELECT set_config(..., true)`.
- **Regression:** корректный tenant context внутри транзакции и отсутствие его после commit.
- **Residual risk:** helper используется не повсеместно; роль владельца таблиц обходит RLS. Полная RLS-изоляция остаётся открытой.

### AUD-15 — High: успешный образ не запускал API из-за записи OpenAPI

- **Root cause:** startup писал файл в root-owned каталог приложения от непривилегированного пользователя.
- **Evidence:** [image-write-before.txt](evidence/image-write-before.txt), воспроизведённый `PermissionError` в исходном образе.
- **Affected files:** `backend/main.py:18`.
- **Fix:** `24043e9` — штатный endpoint OpenAPI вместо runtime export; проверка DB role до фоновых задач; shutdown в `finally`.
- **Regression:** `tests/test_lifespan_safety.py`, 3 сценария с запрещённой записью/частичным startup/небезопасной ролью.
- **Residual risk:** Compose credentials и привилегии production DB всё ещё требуют исправления; тесты lifespan подменяют запускаемые сервисы.

### AUD-16 — High: APK не мог обновить истёкшую авторизацию

- **Root cause:** enrollment выпускал refresh token без серверной записи; APK отправлял его в endpoint пользовательских сессий.
- **Evidence:** runtime contract regressions; точный MockWebServer-тест заменяет прежнее разрешение результата «старый либо новый токен».
- **Affected files:** `backend/services/device_registration_service.py:131`, `backend/api/v1/devices/router.py`, `backend/models/device.py`, миграция `20260906_device_refresh.py`, Android `store/AuthTokenStore.kt:69`.
- **Fix:** `aee432a` — digest/expiry refresh token, отдельный device endpoint, rotation под row lock; APK сохраняет новую пару токенов и ограничивает HTTP body до чтения.
- **Regression:** `test_device_refresh.py`, `AuthTokenStoreTest.kt`: enrollment → rotation → отказ повторному старому token.
- **Residual risk:** ранее выданные refresh tokens нельзя восстановить — нужна повторная регистрация; потеря ответа refresh и revocation открытых WS ещё не закрыты.

### AUD-17 — High: чужие логи и несовместимый агентский HTTP-контракт

- **Root cause:** отсутствие проверки принадлежности device при чтении/удалении; upload ожидал другой способ авторизации и другой источник device ID.
- **Evidence:** `tests/production/test_agent_http.py`: межорганизационные read/delete и подмена ID при device JWT.
- **Affected files:** `backend/api/v1/logs/router.py:28`, Android `workers/LogUploadWorker.kt`.
- **Fix:** `46085f5` — ownership, device JWT, `X-Device-Id`, запрет конфликтующих ID; append вместо перечитывания и перезаписи растущего файла.
- **Regression:** запрещённые чужие операции и успешная загрузка своего лога.
- **Residual risk:** локальные временные файлы не обеспечивают долговечность и согласованность между контейнерами; ротация/нагрузка требуют проверки.

### AUD-18 — High: tenant-администратор мог публиковать глобальный OTA-релиз

- **Root cause:** общая таблица релизов защищалась tenant-правом `device:write`.
- **Affected files:** `backend/api/v1/updates/router.py:130`, Android `workers/UpdateCheckWorker.kt`.
- **Fix:** `46085f5` — публикация/удаление требуют платформенной роли; polling принимает device JWT; worker обновляет credentials и ограничивает размер ответа.
- **Evidence/regression:** `test_agent_http.py` плюс существующая update API suite.
- **Residual risk:** временный каталог, атомарность публикации, signing/package verification APK и production rollout требуют продолжения аудита.

### APK-01 — High: зависание/утечки WebSocket при reconnect и отмене

- **Root cause:** отмена корутины не гарантировала закрытие транспорта, callbacks старого соединения влияли на новое, ошибки после открытия обходили backoff.
- **Affected files:** `android/.../ws/SphereWebSocketClient.kt:94`.
- **Fix:** `c008d09` — cancellation-safe lifecycle, handshake deadline, close-handshake, игнорирование устаревших callbacks, backoff и ограничение video queue.
- **Evidence/regression:** [android-lifecycle-before.txt](evidence/android-lifecycle-before.txt), `WebSocketLifecycleTest.kt`, 6 сценариев.
- **Residual risk:** real-device recovery и поведение H.264 при backpressure не подтверждены этим тестом.

### APK-02 — High: токен управляющего сервера попадал в сторонние HTTP-запросы

- **Root cause:** один OkHttp client используется и управлением, и DAG HTTP actions; interceptor безусловно добавлял bearer token.
- **Affected files:** `android/.../di/AppModule.kt`, network interceptor.
- **Fix:** `34e702a` — сравнение scheme/host/port при каждом сетевом обмене, удаление перенесённого platform token для другого origin.
- **Evidence/regression:** [android-credential-before.txt](evidence/android-credential-before.txt), `ServerCredentialScopeTest.kt`: 3 failures до, 4 passes после; транспорт подменён, внешних запросов нет.
- **Residual risk:** настройка management URL, pinning и другие каналы передачи credentials требуют дальнейшего аудита.

### APK-03 — High: повторное исполнение DAG, неверный статус и потеря результата

- **Root cause:** отсутствие command journal; duplicate отменял уже работающий DAG; `success=false` превращался в completed; pending удалялись после постановки кадра в очередь WS, до commit на сервере.
- **Affected files:** `android/.../commands/CommandDispatcher.kt:293`, `CommandJournal.kt:34`, `DagRunner.kt`, backend result handler/service.
- **Fix:** `0f717b1` — durable receipt до действия, terminal receipt до отправки, replay без исполнения, повтор до `result_ack`, подтверждение после PostgreSQL commit. После перезапуска незавершённая receipt превращается в явный unknown outcome; старые валидные pending мигрируют.
- **Evidence/regression:** [android-delivery-before.txt](evidence/android-delivery-before.txt); `CommandDeliveryTest.kt` и `CommandJournalTest.kt`; `test_result_receipts.py`.
- **Residual risk:** это не exactly-once гарантия. Журнал: 512 receipts, 7 дней dedup, до 1 MiB; переполнение останавливает приём новых DAG. Oversized result сохраняет статус и признак truncation. Для высокой частоты задач нужен измеренный бюджет и масштабируемое хранилище. JVM restart simulation не заменяет Android process-death test.

### APK-04 — Low: явный discriminator CommandAck и уточнение первоначальной оценки

`7993dc9` всегда сериализует `type=command_result`, включая serializer без encodeDefaults.
`IncomingCommandTest.kt` проверяет контракт. **Сообщение этого коммита переоценивает
последствия:** основной WebSocket loop исходной версии уже имел fallback по
`command_id + status`. Поэтому отсутствие `type` не доказывает потерю всех ответов.
Изменение устраняет неоднозначность и несовместимость со строгим helper-router;
реальные ошибки статуса/повторов/сохранения доказаны отдельно в APK-03.

### APK-05 — High: использование DAG с данными предыдущего аккаунта

- **Root cause:** сервер вычислял hash шаблона до подстановки аккаунта; APK предпочитал cache hit явно переданному новому DAG.
- **Affected files:** `backend/services/task_service.py`, Android `commands/CommandDispatcher.kt`.
- **Evidence:** [dag-cache-before.txt](evidence/dag-cache-before.txt), [android-cache-before.txt](evidence/android-cache-before.txt).
- **Fix:** `8246cd9` — hash разрешённого payload; явное тело команды имеет приоритет над кэшем, включая совместимость со старым сервером.
- **Regression:** `test_dag_cache_identity.py` и `CommandDeliveryTest.explicitDagPayloadTakesPrecedenceOverStaleCache`.
- **Residual risk:** пароль ещё хранится в разрешённом DAG/локальном кэше; политика хранения secrets рассматривается отдельно.

### AUD-09 — High: потеря/дублирование задач при разрыве между PostgreSQL и Redis

- **Root cause:** Redis enqueue до commit создавал ghost task при rollback; потеря Redis уничтожала очередь; отправка до фиксации назначения и неоднозначный send не имели надёжного recovery.
- **Evidence:** [durable-dispatch-before.txt](evidence/durable-dispatch-before.txt): четыре падения; F09 и queue-before.txt.
- **Affected files:** `backend/services/task_service.py:279`, Android WS receipt handler.
- **Fix:** `8367979` — PostgreSQL QUEUED/ASSIGNED являются долговечным намерением; device/task row locks; ASSIGNED commit до отправки; повтор через 30 секунд с тем же ID до receipt; переход RUNNING только по receipt устройства. Presence читается пакетами вне DB locks.
- **Regression:** 7 сценариев `test_durable_dispatch.py`; rollback regression теперь проходит без xfail. Проверены быстрый terminal result, конкурентные workers, отсутствие Redis queue/lease и потеря transport response.
- **Residual risk:** rollout требует APK с durable journal. Старые RUNNING/ASSIGNED нуждаются в reconciliation; восстановление всей presence-информации после сброса Redis и полноценный network chaos пока не подтверждены.

### AUD-10 — High: задачи оркестратора без версии; n8n обходил права исполнения

- **Root cause:** ручное создание Task не проверяло общий контракт: версия отсутствовала; n8n допускал viewer и чужой device ID. Оркестратор копировал пароль в читаемые task input_params.
- **Affected files:** `backend/services/orchestrator/orchestration_engine.py`, `backend/api/v1/n8n/router.py`.
- **Fix:** `81b2c6b` — общий TaskService, закрепление текущей версии, `script:execute` и tenant lookup, account_id вместо копии пароля, отсутствие pre-commit Redis enqueue в исправленных producer paths.
- **Evidence/regression:** [task-producers-before.txt](evidence/task-producers-before.txt), `test_task_producers.py`, 24 существующих n8n API tests с опубликованной версией в fixture.
- **Residual risk:** старые task input_params и GameAccount passwords не мигрированы; pipeline/scheduler и конкурентность orchestration engine обследуются отдельно.

## Открытые подтверждённые блокеры

| ID / severity | Root cause и evidence | Необходимое продолжение |
| --- | --- | --- |
| AUD-11 / High | Независимые tenant VPN pools выделяют одинаковый IP в общей subnet; reinit возвращает уже занятые адреса. F11 | Глобальная согласованная аренда IP, атомарность, отказоустойчивое revoke, проверка конфигурации |
| AUD-14 / High | Несуперпользователь-владелец таблиц обходит RLS. F14 на PostgreSQL; tenant context не установлен повсеместно | Разделение migration/runtime ролей, политики и контекст для HTTP/auth/jobs, реальные cross-tenant проверки |
| DEPLOY-01 / High | `ports: []` в override не очищает base mappings; effective Compose сохраняет host ports PostgreSQL/Redis | Исправить merge и проверить итоговую конфигурацию, сеть и runtime доступность |

## Продолжение обследования: ещё не закрытые компоненты

Следующие пункты — кандидаты/недостаточное покрытие, а не автоматически доказанные
эксплуатируемые уязвимости: Android FGS/boot/timeout, root-only действия на обычных
телефонах, screen codec recovery; PC-agent
protocol; orchestrator/pipeline crash recovery; сохранение паролей игровых аккаунтов;
MFA/session/logout races; VPN revoke/PSK/маршруты; backup/restore; webhook/n8n contract;
frontend runtime; метрики и multiprocess; зависимости и CI.

GitHub checks на первой ревизии PR: Android build и lint проходили, security job
падал. Эти результаты нельзя переносить на новую ревизию без проверки. Зависимости
не считаются исправленными до анализа advisory, обновления и повторного запуска.

На ревизии `554df5d` CI обнаружил пять lint diagnostics и уязвимые зависимости.
Lint исправлен в `3767de1`, локальный Ruff проходит. Dependency-aware mypy на Windows
также выявил прежние diagnostics вне исправленного owner count; они не подавлялись.
Security job показывает PyJWT/Starlette/pytest advisories; проверки upstream и
совместимых обновлений продолжаются. Список приоритетов: [ROADMAP.md](ROADMAP.md).

PR остаётся draft до завершения открытых блокеров, повторного runtime обследования
и финализации отчёта. Merge и deployment не выполнялись.
