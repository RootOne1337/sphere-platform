# Sphere Platform: аудит готовности к эксплуатации

Статус на 11 сентября 2026: **аудит продолжается; production readiness не подтверждена**.
Исходная ревизия: `28f8cc46ab65496e00297960fd94d87d1605cc83`.
Ветка исправлений: `codex/enterprise-audit-20260905`; [draft PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

Проверка разрешена владельцем. Воспроизведения выполнялись на локальных искусственных
данных, выделенных PostgreSQL/Redis и подменённых транспортных границах. Внешняя
инфраструктура не является целью тестирования. Целевая конфигурация — сотни/тысячи APK в парке, ориентировочно 10–64 эмулятора
на станции, затем физические Android-устройства. Ёмкость пока не измерена.

Текущий порядок работ: автоматический reconnect и независимый от GitHub recovery,
сохранность исполнения, достоверный startup, диагностика инцидентов, реальные UI
данные. [Эксплуатационная матрица](../../operations/READINESS.md) отделяет
подтверждённые дефекты от проектируемых возможностей; историческая severity ниже
не означает, что сейчас исправления идут в порядке номеров AUD.

Главные подтверждённые риски: повышение tenant-пользователя до платформенного
администратора, нарушение изоляции устройств и задач, повторное выполнение DAG,
потеря результата при сбое транспорта и несогласованность PostgreSQL с Redis.
Исправления ниже включают регрессионные проверки. Успешная сборка отдельно от
runtime-проверок и не считается доказательством работоспособности системы.

## Результаты проверок

| Проверка | Результат | Практическое ограничение |
| --- | --- | --- |
| Android enterprise debug unit suite | 485 passed, 0 failed | JVM/MockWebServer и OkHttp interceptors; не проверяет ОС, codec, батарею или смерть процесса на телефоне |
| Объединённая Backend/PC/production/deployment suite (Linux `ea8e606`) | **1424 passed, 0 failed**; coverage **69,38%** | Строгий coverage gate 65% пройден. Load suite исключена; 44 deployment cases включают Compose renderer/subprocess probes без запуска сервисов |
| Python dependency scan | **0 known vulnerabilities** в совместном backend/PC resolution | Pip-audit snapshot, не проверка frontend/Gradle/container/application security; [версии и ограничения](DEPENDENCY-REVIEW.md) |
| Проверки PostgreSQL/Redis | **505 passed**, включены в общий прогон, 0 xfail | Реальные row locks/commits/cache; transport effects подменены, полного APK↔API нет |
| Миграции | Применены до **20260910_device_refresh_retry** включительно | Только изолированная БД; конфликтные данные/downgrade проверены в throwaway schema; production не мигрировался |
| Backend image | Собирается; исходная запись OpenAPI воспроизведённо падает с PermissionError | Исправлен lifespan; полный deployment runtime ещё не подтверждён |
| Frontend | **198 Jest tests passed**, tsc passed; Next production build exit 0 на Node 24.19.0 | React/JSDOM + Axios adapters; настоящий browser runtime не проверен. Windows standalone tracing выдал ENOENT warning, artifact packaging ещё не подтверждён |
| APK ↔ реальный локальный backend | Не завершено | Автоматическая проверка разрешений отклонила запуск локального API: `blocked by policy`; обход не выполнялся |
| 10–64 эмулятора на станции, сотни/тысячи APK, физические телефоны | Не измерено | Нет подтверждённых CPU/RAM/FPS/энергопотребления и совместимости со всеми Android |

Последний полный Linux вывод: [CI `ea8e606`](evidence/ci-ea8e606-tests.txt).
Последний полный Windows вывод: [1413 cases](evidence/pilot-combined.txt).
Предыдущий отдельный DAG benchmark однажды занял 127,1 ms при пороге 100 ms;
изолированный повтор и последующие общие прогоны прошли. На первой CI попытке
`d828a62` этот же неизменённый тест измерил 363,2 ms: **1 failed / 1213 passed**,
все 22 новых JWT cases прошли. [Сохранённый CI excerpt](evidence/ci-d828a62-attempt1.txt).
[Локальные 24 DAG cases прошли](evidence/dag-timing-d828a62-local.txt). Порог 100 ms
не ослаблялся, тест не исключался; причина timing variance на runner не установлена.
Файл production-regressions-after.txt сохраняет более ранний standalone snapshot
с 41 тестом; актуальные 505 входят в общий прогон.

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

### AUD-14 / F14 — High: runtime-владелец обходит RLS; startup сообщает ложную защищённость

- **Root cause:** проверка учитывала только `rolsuper` и `rolbypassrls`. Обычный владелец таблицы и участник owner-role обходят RLS; владелец может отменить даже FORCE RLS. TRUNCATE не проверяет строки. Отсутствующие политики не проверялись.
- **Evidence:** [rls-startup-before.txt](evidence/rls-startup-before.txt) — **9 failed, 1 passed**. На PostgreSQL обычный owner читает обе организации; FORCE owner выполняет ALTER, NOINHERIT member выполняет SET ROLE, runtime с TRUNCATE удаляет обе синтетические строки (транзакция откатывается).
- **Affected files:** `backend/core/startup_checks.py:39`, `tests/production/test_rls_startup.py:56`.
- **Fix (частичный):** `48948cd` — production startup отклоняет owner/member, privileged membership, TRUNCATE, неактивный RLS и отсутствие политик на видимых mapped tables. Development явно предупреждает. Сообщение об успешной проверке ограничено prerequisites и не утверждает корректность tenant isolation.
- **Regression:** 10 PostgreSQL cases, включая разрешённую non-owner роль, видящую только свою организацию; вместе с lifespan — [13 passed](evidence/rls-startup-after.txt).
- **Residual risk / blocker:** это защита от опасной конфигурации, а не завершение RLS rollout. Политики схемы дополнены в AUD-54, восстановление bound Session после commit — в AUD-55; user JWT lookup исправлен в AUD-57; нужны tenant boundaries для opaque auth bootstrap, перевод unscoped callers и tenant-aware jobs и отдельное provision runtime/migration ролей. Текущий production superuser/owner конфиг должен отказать при запуске; автоматически повышать права или отключать проверку нельзя. Проверка каталога сама по себе не доказывает семантику политик и полноту миграций.

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

### AUD-19 — High: оркестратор менял чужой аккаунт и переписывал terminal outcome

- **Root cause:** lookup игрового аккаунта не ограничивался организацией; признаком обработки результата служил статус CANCELLED вместо отдельной квитанции. Повторный tick мог повторно учитывать завершение после переназначения аккаунта.
- **Affected files:** `backend/services/orchestrator/orchestration_engine.py:339`, `backend/models/task.py`, миграция `alembic/versions/20260906_task_accounting.py`.
- **Evidence:** [orchestrator-results-before.txt](evidence/orchestrator-results-before.txt): 2 failures исходных проверок.
- **Fix:** `2b61bb3` — tenant lookup и account row lock; `orchestration_processed_at` фиксируется атомарно с изменением аккаунта; terminal Task.status/result сохраняются; конкурентные workers используют SKIP LOCKED.
- **Regression:** 3 сценария `test_orchestrator_results.py`: повтор после переназначения, чужая организация, конкуренция и rollback/retry.
- **Residual risk:** прежние CANCELLED не реконструированы; конкурентное создание аккаунтов и pipeline recovery ещё открыты. In-memory статистика оркестратора не является транзакционным счётчиком.

### AUD-20 — High: чтение и подмена live-прогресса чужих задач

- **Root cause:** HTTP read проверял только `script:read`; агентская запись доверяла task_id. Redis keys общие для всей платформы. Некорректные counters могли вызвать исключение обработки WS.
- **Affected files:** `backend/api/v1/tasks/router.py:234`, `backend/api/ws/android/router.py:142`.
- **Evidence:** [progress-isolation-before.txt](evidence/progress-isolation-before.txt): 12 failed, 1 passed. Реальные JWT/ASGI, PostgreSQL и Redis; чужой пользователь получал приватный node ID.
- **Fix:** `a92e18d` — ownership по организации при чтении; по task/device/org и активному статусу перед записью/event; ограниченная типизированная валидация входного сообщения.
- **Regression:** [progress-isolation-after.txt](evidence/progress-isolation-after.txt), 13 passed: cross-tenant read, sibling device, unknown/terminal task, malformed payload и разрешённый сценарий.
- **Residual risk:** один indexed PostgreSQL lookup на progress frame; throughput для 64 APK ещё не измерен. Cache не является долговечным журналом, поздний progress при конкурентном terminal commit остаётся телеметрией.

### AUD-21 — High: retry и конкурентные producers создавали повторное выполнение

- **Root cause:** проверка дубликата и INSERT не сериализованы; missing Redis presence или возраст записи >24 ч объявляли предыдущую задачу TIMEOUT без доказательства остановки APK.
- **Affected files:** `backend/services/task_service.py:144`, `backend/services/task_service.py:172`.
- **Evidence:** [creation-recovery-before.txt](evidence/creation-recovery-before.txt): 5 failures; два перекрывающихся запроса создавали две QUEUED задачи, retry менял QUEUED/ASSIGNED/RUNNING на TIMEOUT.
- **Fix:** `f240a6a` — device row lock до duplicate lookup, удерживаемый до commit/rollback; существующая активная задача возвращает 409 без изменения результата.
- **Regression:** [creation-recovery-after.txt](evidence/creation-recovery-after.txt), 5 passed, реальные перекрывающиеся PostgreSQL-транзакции и потеря presence.
- **Residual risk:** контракт dedup действует для одного device/script version через TaskService; это не общий idempotency-key API. Watchdog, force-stop, ручные producers и старые зависшие задачи требуют отдельного reconciliation.

### AUD-22 — High: неверный watchdog deadline на хосте вне UTC

- **Root cause:** UTC cutoff лишался tzinfo ради SQLite. asyncpg интерпретировал его как локальное время хоста для timestamptz; на проверенном UTC+5 часовое ожидание очереди увеличивалось на 5 часов.
- **Affected files:** `backend/tasks/task_heartbeat_watchdog.py:86`.
- **Evidence:** [watchdog-runtime-before.txt](evidence/watchdog-runtime-before.txt): overdue QUEUED/ASSIGNED не переходили в TIMEOUT, 2 failures на реальном PostgreSQL.
- **Fix:** `810b243` — timezone-aware UTC во входном параметре; SQLite также принимает такое значение.
- **Regression:** 2 deadline/rollback tests после fix; `473db53` добавляет 2 проверки commit failure и Redis release failure. [watchdog-faults-after.txt](evidence/watchdog-faults-after.txt): 4 passed. На Unix тест временно задаёт TZ=Etc/GMT-5 и восстанавливает его.
- **Residual risk:** этот fix не делает CANCEL_DAG долговечным и не доказывает остановку действия на телефоне. Task-specific cancellation, повтор отмены и подтверждение остановки остаются открыты.

### AUD-23 — High: потеря batch counters при одновременных результатах

- **Root cause:** блокировка разных Task rows не защищала общий TaskBatch. Несколько workers читали старый счётчик и перезаписывали increment друг друга; watchdog использовал тот же небезопасный read-modify-write.
- **Affected files:** `backend/services/task_service.py:472`, `backend/tasks/task_heartbeat_watchdog.py:306`.
- **Evidence:** [batch-concurrency-before.txt](evidence/batch-concurrency-before.txt): 3 failures с перекрывающимися транзакциями и заранее загруженной ORM-моделью.
- **Fix:** `42f222f` — общий batch row lock с populate_existing для result handler и watchdog; стабильный порядок блокировок нескольких batches.
- **Regression:** success/success, success/failure, success/watchdog; [batch-concurrency-after.txt](evidence/batch-concurrency-after.txt): 5 passed вместе с deadline slice.
- **Residual risk:** исторические неверные counters не пересчитаны. Надёжность всего wave/pipeline жизненного цикла требует дальнейших сценариев.

### AUD-24 — High: APK оставался невидимым после потери Redis presence

- **Root cause:** handle_pong обновлял только существующую Redis-запись. После eviction/restart живой WS продолжал обмен, но dispatcher не видел online presence до reconnect. Ошибка Redis или неверный latency timestamp прерывали cache update.
- **Affected files:** `backend/websocket/heartbeat.py:87`, `backend/api/ws/android/router.py:546`.
- **Evidence:** [presence-recovery-before.txt](evidence/presence-recovery-before.txt): 5 failures; удалялся только ключ устройства текущего fixture в реальном Redis, без FLUSHDB.
- **Fix:** `a5587f2` — восстановление online presence по authenticated pong с session ID; busy сохраняется; известная новая сессия не перезаписывается старой. Ошибка Redis повторяется на следующем pong; некорректная telemetry не записывается, latency timestamp ограничен.
- **Regression:** расширенные 7 recovery cases и существующие heartbeat/authorization tests: [presence-recovery-after.txt](evidence/presence-recovery-after.txt), 18 passed.
- **Residual risk:** это проверка server handler/cache, не реального Android network stack. Атомарное fencing между несколькими workers, PubSub recovery и физический APK после полного Redis restart ещё не доказаны.

### DEPLOY-01 / DEPLOY-02 — High: production наследовал открытые порты и dev runtime

- **Root cause:** пустой ports list объединялся с base вместо удаления mappings. Документированный base/full/production merge также сохранял команды разработки, root frontend, прямые application ports и bind mounts исходников.
- **Affected files:** `docker-compose.production.yml:8`, `docs/deployment.md:150`.
- **Evidence:** [compose-production-before.txt](evidence/compose-production-before.txt): 3 failed, 1 passed; настоящий `docker compose config` с синтетическими переменными, без запуска контейнеров.
- **Fix:** `5444a44` — явные `!reset` для DB/Redis/application ports и application command/user/volumes, явное отключение dev-auth flags; актуализированы запуск и требования Compose 2.24.4+. Поведение подтверждено [официальными merge rules Docker](https://docs.docker.com/reference/compose-file/merge/).
- **Regression:** расширенная матрица обоих Compose stack и обоих applications: [compose-production-after.txt](evidence/compose-production-after.txt), 6 passed.
- **Residual risk:** n8n/MinIO base ports остаются опубликованными и требуют отдельного ingress/access design. RLS runtime-role rollout, OTA/log persistence, root filesystem policy, backup restore и фактическая доступность после запуска не закрыты. Удалённые dev mounts не заменяются гарантией сохранности production-артефактов.

### TEST-01 — Medium: SQLite suites портили PostgreSQL проверки; CI пропускал runtime regressions

- **Root cause:** восемь conftests глобально заменяли ARRAY/JSONB/INET модели на SQLite-типы; PostgreSQL получал JSON вместо varchar[]. CI одновременно собирал длительные load/soak профили без API-стенда и не включал opt-in production suite.
- **Affected files:** `tests/conftest.py:50` и дочерние conftests; `.github/workflows/ci-backend.yml`.
- **Evidence:** [combined-suite-coverage.txt](evidence/combined-suite-coverage.txt): 872 passed, 3 DatatypeMismatchError. Старый GitHub run `34025311501` оставался на общей pytest-команде.
- **Fix:** `ad4fc27` — централизованные SQLite-only variants и SQLite UUID function; native PostgreSQL metadata сохраняется. CI включает изолированные PG/Redis regression tests, применяет миграции, ограничивает test job 20 минутами и сохраняет JUnit/coverage при ошибках. Load suite требует отдельного подготовленного стенда.
- **Regression:** первый общий повтор после type fix: 875 passed; последующие полные результаты приведены в таблице выше. Порог покрытия 65% не снижался; его прежнее округление исправлено отдельно в TEST-02.
- **Residual risk:** статический RLS job не проверяет runtime isolation; mypy CI без backend dependencies слабее dependency-aware проверки. Security advisories и отдельный load job остаются открыты; зелёный build не закрывает аудит.

### AUD-25 / AUD-26 — High: VPN назначался чужому устройству и терял PSK при retry

- **Root cause:** assign_vpn доверял device_id без проверки организации; повторная сборка конфигурации не расшифровывала сохранённый preshared_key_enc.
- **Affected files:** `backend/services/vpn/pool_service.py:79` и `_peer_to_assignment`.
- **Evidence:** [vpn-contract-before.txt](evidence/vpn-contract-before.txt): 2 failures. Чужой device ID приводил к выделению peer; повторный config терял строку PresharedKey.
- **Fix:** `92869ac` — active device/org lookup и device row lock до pool/router effects; повтор возвращает исходный PSK.
- **Regression:** `test_vpn_contract.py`: запрет чужого устройства, идентичный повтор, две перекрывающиеся assignment-транзакции с единственным router call. [vpn-contract-after.txt](evidence/vpn-contract-after.txt): 84 passed вместе с прежней VPN suite.
- **Residual risk:** router transport подменён; параметры AWG и настоящий handshake не проверены. Глобальные reservations и удержание неизвестного provisioning реализованы следующим исправлением AUD-11; provider reconciliation остаётся открытым.

### AUD-27 — High: revoke освобождал IP при отказе роутера или конкурентном повторе

- **Root cause:** DELETE helper подавлял timeout и ошибки HTTP, после чего peer считался FREE; параллельные revoke читали один ASSIGNED peer и повторно возвращали адрес.
- **Affected files:** `backend/services/vpn/pool_service.py`, `_get_existing_peer`, `_remove_peer_from_server`.
- **Evidence:** [vpn-revoke-before.txt](evidence/vpn-revoke-before.txt): 5 failures, включая timeout, 500, 403, незавершённый 202 и перекрывающиеся транзакции.
- **Fix:** `caa9faa` — ошибка/неподтверждённый DELETE сохраняет peer и lease; peer row lock с refresh сериализует revoke. Первоначально сохранялся контракт 200/204/404; последующий AUD-30 исключает неоднозначный 404.
- **Regression:** 8 revoke cases, 3 assignment cases и старая VPN suite: [vpn-revoke-after.txt](evidence/vpn-revoke-after.txt), 92 passed. Ошибка не освобождает IP даже если caller ловит её и делает commit.
- **Residual risk:** первоначальный fix сохранял окно Redis release перед SQL commit. Последующее исправление AUD-11 заменяет этот путь SQL ownership и долговечным REVOKING; provider reconciliation и реальный HTTP adapter ещё не закрыты.

### TEST-02 — Medium: округление coverage давало ложный зелёный статус

- **Root cause:** precision=0 округлял 64,98% до 65 при вычислении exit code. При этом terminal summary сравнивал неокруглённое значение и печатал FAIL.
- **Evidence:** GitHub Tests job на `ecac8a1` имел success при строке `FAIL ... 64.98%`; [coverage-boundary-before.txt](evidence/coverage-boundary-before.txt): 1 failed, 1 passed на синтетических границах 6498/10000 и 6500/10000 statements.
- **Affected files:** `pyproject.toml`, `tests/deployment/test_coverage_gate.py`.
- **Fix:** `1335a72` — report precision=2, порог остаётся 65%; исправление замечания mypy к numeric narrowing heartbeat — `31077b3`.
- **Regression:** [coverage-boundary-after.txt](evidence/coverage-boundary-after.txt): coverage CLI отклоняет 64,98% с exit code 2 и принимает 65,00%.
- **Residual risk / correction:** прежняя формулировка этого отчёта и PR «gate остаётся блокирующим при 64,98%» была неточной: она основывалась на stdout, а не exit code. Этот дефект теперь проверяется отдельно. Coverage не является доказательством безопасности или полноты аудита.

### AUD-28 — High: health-check повторно создавал peers при отказе роутера

- **Root cause:** HTTP status не проверялся; timeout/ошибка JSON возвращали пустой snapshot. Отсутствующий или нулевой handshake трактовался как удалённый peer и запускал POST /peers без PSK. Health client и background factory не передавали router API key; reconnect собирал отдельную конфигурацию без сохранённого PSK.
- **Affected files:** `backend/services/vpn/health_monitor.py`, `backend/services/vpn/pool_service.py`, `backend/tasks/vpn_health.py`.
- **Evidence:** [vpn-health-before.txt](evidence/vpn-health-before.txt): 13 failures на PostgreSQL и httpx.MockTransport; router mutation после timeout/401/503/невалидного snapshot, peer без handshake, отсутствие auth header и потеря PSK. Внешний router не вызывался.
- **Fix:** `10141ee` — валидируются status, форма snapshot и timestamps; неизвестное состояние сохраняет последние данные и возвращает checked=0/error. Health-check больше не создаёт peers по handshake API. API key передаётся в background service/client. Retry и reconnect используют общий config builder с сохранённым PSK, без лишней генерации QR при reconnect.
- **Regression:** `tests/production/test_vpn_health_recovery.py` — 16 cases, включая NaN/future timestamps и восстановление после неудачного poll. Прежний тест «missing peer» проверял только первоначальный assignment call; теперь проверяет отсутствие POST из monitor.
- **Residual risk:** отсутствие peer требует отдельной сверки с authoritative provider inventory. EventPublisher остаётся stub, фактическая доставка reconnect и handshake не доказаны. Commit фонового health-check и overlap revoke разобраны в AUD-29; SQL intents добавлены в AUD-11. Provider reconciliation и маршруты ещё открыты.

### AUD-29 — High: фоновая проверка VPN теряла данные и использовала отозванный peer

- **Root cause:** get_db_session не делает автоматический commit, а health loop ограничивался flush. После router poll обновлялась старая ORM-модель без повторной проверки status/device; конкурентный revoke уже мог завершиться. Это позволяло вернуть is_active=True для FREE peer или сформировать reconnect с отозванной конфигурацией.
- **Affected files:** `backend/tasks/vpn_health.py`, `backend/services/vpn/health_monitor.py`.
- **Evidence:** [vpn-health-transaction-before.txt](evidence/vpn-health-transaction-before.txt): 3 failures — свежий/stale snapshot, перекрытый подтверждённым SQL revoke, и потеря observation при закрытии background session.
- **Fix:** `2d752bf` — условный SQL UPDATE проверяет прежнюю организацию, устройство и ASSIGNED непосредственно при записи; изменённый peer пропускается. Background job использует отдельную tenant-context session и явный commit для каждой организации, продолжает после ошибки одной организации.
- **Regression:** расширенная VPN suite: [vpn-health-transaction-after.txt](evidence/vpn-health-transaction-after.txt), 112 passed. 20 новых health cases включают реальный PostgreSQL commit/rollback и отказ commit первой организации с успешной обработкой второй.
- **Дополнительное evidence/fix:** поздний stale/empty ответ параллельного poll перезаписывал более свежую SQL observation; [vpn-health-ordering-before.txt](evidence/vpn-health-ordering-before.txt): 2 failures. `a85f5d2` — SQL update запрещает уменьшение last_handshake_at и применяет missing observation только если исходный timestamp не изменился. [vpn-health-ordering-after.txt](evidence/vpn-health-ordering-after.txt): 31 passed, включая расширенные 22 production health cases и прежние monitor tests.
- **Residual risk:** polling и reconnect не имеют долговечного outbox; доставка после commit/revoke и stop acknowledgement требуют отдельного протокола с fencing. Redis lease фонового цикла пока не продлевается; длительные циклы могут пересекаться. Тест организации задаёт изолированную enumeration boundary и не доказывает полный rollout RLS.

### AUD-11 / F11 — High: повторная выдача VPN IP и потеря ownership после сетевого/SQL отказа

- **Root cause:** tenant Redis ZSET покрывали одну subnet, а reinit возвращал извлечённые адреса. POST выполнялся до SQL записи; exception возвращал IP даже после применения запроса роутером. Revoke возвращал IP в Redis до SQL commit.
- **Affected files:** `backend/models/vpn_peer.py`, `backend/services/vpn/ip_pool.py`, `pool_service.py`, `dependencies.py`, `backend/api/v1/vpn/router.py`, `backend/schemas/vpn/peer.py`, `alembic/versions/20260906_vpn_intents.py`.
- **Evidence:** F11 исходного аудита; [vpn-lease-before.txt](evidence/vpn-lease-before.txt): 5 failures — одинаковый IP у разных tenants, отсутствие видимого SQL intent перед POST, потерянный ответ, отказ intent/final commit.
- **Fix:** `a9cb944` — глобальная unique constraint non-FREE INET, короткий advisory lock при выборе IP; PROVISIONING/REVOKING intent commit до provider IO. SQL generation check перед финальным commit; rollback/cancellation не удаляет intent. IP освобождается только commit FREE. Production DI выделяет сессию lifecycle отдельно от caller; API stats читают SQL, а Redis не участвует в ownership. Retry незавершённого peer возвращает 409 без нового provider call; новый split_tunnel сохраняется.
- **Regression:** `test_vpn_durable_leases.py` — 19 случаев, включая 64 параллельных назначения, потерю/poisoned cache Redis, cancellation, generation mismatch, сохранение route/PSK, pool exhaustion, независимость caller transaction. `test_vpn_migration.py` — 5 проверок реальной миграции в PostgreSQL throwaway schema. [vpn-lease-after.txt](evidence/vpn-lease-after.txt) и общий прогон включают прежние VPN contracts/revoke/health tests.
- **Migration evidence:** [vpn-migration-conflicts.txt](evidence/vpn-migration-conflicts.txt): миграция атомарно отказала на накопленных дублях тестового стенда, исходный head и строки сохранились. После удаления только 227 старых artificial Audit A/B peers в выделенной sphere_audit выполнен успешный upgrade. Production не менялся. Автотесты теперь удаляют VPN rows только своих двух UUID организаций. Invalid addresses/network prefixes и downgrade с pending intent также отклоняются без потери данных.
- **Residual risk:** automatic provider reconciliation отсутствует. Pending intent удерживает IP до управляемой сверки, что снижает доступность при отказе, но исключает слепое повторное выделение. Старые writers нельзя запускать одновременно с новым allocator; orphan router peers вне SQL должны быть сверены до rollout. Полный RLS/runtime-role design, HTTP adapter, reserved router IP, AWG settings/routes и физический handshake остаются открытыми. 64 SQL assignments не измеряют ёмкость 64 APK. Подробности: [VPN-LEASE-DESIGN.md](VPN-LEASE-DESIGN.md).

### AUD-30 — High: DELETE менял путь для base64 key, а generic 404 освобождал peer

- **Root cause:** public key вставлялся в путь без percent encoding; символ `/` создавал дополнительный route segment. Любой 404, включая proxy/route Not Found, трактовался как доказательство отсутствия peer.
- **Affected files:** `backend/services/vpn/pool_service.py`, `_remove_peer_from_server`.
- **Evidence:** [vpn-router-path-before.txt](evidence/vpn-router-path-before.txt): 2 failures — raw HTTP path отличался от единого encoded key; generic 404 принимался без ошибки. MockTransport локальный, реальный роутер не вызывался.
- **Fix:** `9b28dc6` — percent encoding ключа как одного URL component; DELETE принимает только 200/204. При 404 intent остаётся REVOKING, адрес не освобождается.
- **Regression:** `test_vpn_router_path.py` и существующий real-SQL revoke matrix, включая 404, проверяют path/error и удержание адреса.
- **Residual risk:** корректный already-absent результат провайдера требует отдельного authoritative contract. Encoded slash должен поддерживаться router/proxy; автоматическое разрешение 404 без этой проверки запрещено. Реальный deployed provider всё ещё не обследован.

### AUD-31 — High: обычное чтение аккаунта раскрывало пароль

- **Root cause:** `show_password=true` проверял только account:read; viewer/script_runner/device_manager могли получить reusable credential. У ответа с паролем отсутствовал запрет HTTP caching.
- **Affected files:** `backend/core/rbac.py`, `backend/api/v1/game_accounts/router.py`.
- **Evidence:** [account-credentials-before.txt](evidence/account-credentials-before.txt): 6 failures, 2 controls passed на реальном JWT/SQL/ASGI API. Три operational/read roles получали password; три разрешённые административные роли не получали no-store.
- **Fix:** отдельное account:credentials:read для org_admin/org_owner/super_admin; проверка до service reveal, Cache-Control: no-store. Обычные account:read ответы и org filter сохраняются.
- **Regression:** 8 новых role/tenant/header cases и прежние delegation checks: [account-credentials-after.txt](evidence/account-credentials-after.txt), 13 passed.
- **Residual risk:** хранение новых паролей исправлено отдельно в AUD-32; старым данным требуется явный перенос. Общий audit middleware не фиксирует reveal GET, HTTP no-store не очищает frontend query memory/уже полученные копии. Credential-bearing DAG и доступ через разрешённое выполнение скриптов требуют дальнейшей проверки. Политика и границы: [account-credentials.md](../../security/account-credentials.md).

### AUD-32 — High: все writers игровых аккаунтов сохраняли пароль открытым текстом

- **Root cause:** create/update/import присваивали входную строку `password_encrypted` напрямую; auto-registration делала то же для сгенерированного пароля. Reveal и task variables читали столбец без decrypt. Имя столбца ошибочно подразумевало защиту: SQL read/dump давал готовый reusable credential.
- **Evidence:** [account-storage-before.txt](evidence/account-storage-before.txt): четыре падения на ревизии `7cb77d5`, по одному на каждый writer. После commit новый DB session выполнял raw SQL и получал исходный пароль. Только синтетические аккаунты изолированной БД, включая случайно сгенерированный пароль тестового orchestrator.
- **Affected files:** `backend/services/game_account_service.py:169` (также 301/487), `backend/services/orchestrator/orchestration_engine.py:216`, `backend/services/task_service.py:97`, `backend/models/game_account.py:100`, `backend/core/config.py:36`; новые `backend/services/account_credentials.py:31`, `account_credential_migration.py:27`, `backend/cli/account_credentials.py:12`, `alembic/versions/20260906_account_ciphertext.py`; `.env.example` и Compose full/production.
- **Fix:** независимый Fernet key ring, authenticated envelope v1 с UUID tenant/account, новый ciphertext столбец и очистка старого plaintext в одной записи. Чтение и dispatch используют decrypt; неизвестные/legacy/повреждённые credentials блокируются без plaintext fallback. Отдельный bounded CLI по умолчанию только проверяет; `--apply` переносит legacy, `--rotate` перепаковывает под первый ключ. Schema downgrade отказывает при encrypted rows.
- **Regression:** [account-storage-after.txt](evidence/account-storage-after.txt): 41 focused test — raw SQL всех четырёх writers, исходный пароль в dispatch, недоступный ключ/legacy API, tamper и подмена identities, rotation/new-key-only, SQL rollback при commit/cancel/corrupt row, повторный запуск, ограниченные пачки, реальный CLI и Alembic upgrade/downgrade. Набор включает 8 прежних permission cases и прежний DAG cache test.
- **Residual risk:** production data не мигрировались, ключ не provisioned. Нужен maintenance rollout с остановкой старых writers и сверкой scope/количества строк; RLS visibility не доказывается этим CLI. Старые backups/WAL/MVCC могут содержать plaintext, DB+key/backend-memory compromise остаётся, replay старого токена для того же аккаунта не предотвращён. APK/cache/logs/reveal audit и restore требуют продолжения. [Полная процедура и ограничения](../../security/account-credentials.md).

### AUD-33 — High: APK включал вводимые пароли в выгружаемые диагностические логи

- **Root cause:** `AdbActionExecutor.typeText` передавал в `Timber.d` исходный ввод и shell-encoded представление. `SphereApp` подключает `FileLoggingTree` без условия DEBUG; tree сохраняет сообщения всех уровней, `LogUploadWorker` включает последние file logs в upload. Серверное чтение device logs требует `device:read`, а не отдельного credential permission.
- **Evidence:** [android-credential-log-before.txt](evidence/android-credential-log-before.txt): два теста вызывают настоящий executor с fake Runtime/Process и настоящим Timber sink. Команда ввода доставлена, но проверка отсутствия raw input в sink падает; обычный пароль и текст с кавычкой/пробелом. Сам `su` не запускается. Доставка файлов через физический APK не воспроизводилась; путь file/upload установлен по коду.
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt:199`; путь распространения — `SphereApp.kt:33`, `logging/FileLoggingTree.kt:70`, `workers/LogUploadWorker.kt:82`, `backend/api/v1/logs/router.py:141`.
- **Fix:** событие `typeText: input requested` не содержит raw/encoded text. Сам shell input command и задержка не меняются; диагностика остальных событий сохраняется.
- **Regression:** `AdbCredentialLoggingTest` проверяет действительную запись команды в output stream и отсутствие обеих форм credentials во всех захваченных Timber сообщениях. Повторный Android suite: [android-credential-log-after.txt](evidence/android-credential-log-after.txt).
- **Residual risk:** старые локальные/uploaded логи не очищались. Если в них были реальные credentials, нужны ограничение доступа, контролируемая очистка по retention и оценка смены самих паролей. Это исправление одного подтверждённого источника; общие log redaction, action outputs, screenshots, Unicode/IME и совместимость root-команд на физических устройствах ещё не закрыты.

### AUD-34 — High: APK повторял root-команду после неопределённого результата записи

- **Root cause:** `executeRootCommand` при IOException уничтожала root process, открывала новый и повторяла ту же команду. Ошибка flush может наступить после передачи строки с newline; исход действия неизвестен. На следующих уровнях общий DAG retry и loop catch продолжали execution, а LuaJ оборачивал host exception в обычный LuaError.
- **Evidence:** [android-root-delivery-before.txt](evidence/android-root-delivery-before.txt): 4 failures на `d710587`; fake pipe принимает полный `input tap 10 20`, затем flush падает, второй process получает ту же строку. Проверяются также recovery следующей команды, DAG retry/on_failure и nested loop. В промежуточном исправлении [android-root-propagation-before.txt](evidence/android-root-propagation-before.txt) выявлены 3 integration failures: Lua повторяла DAG, live tap/swipe выпускали исключение в application coroutine scope (13 tests, 3 failures).
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt:127`, `DagRunner.kt` (node/loop exception paths), `CommandDispatcher.kt` (live touch paths), `lua/LuaEngine.kt:73`.
- **Fix:** сломанная root session явно инвалидируется независимо от isAlive; команда не переотправляется. RootCommandOutcomeUnknownException останавливает текущий DAG без retry/on_failure/продолжения loop. Непойманная LuaJ host error сохраняет исходный тип. Live input обрабатывает unknown без повторения и без uncaught child failure. Новый root process допускается только для следующей отдельной команды.
- **Regression:** 5 real executor/DAG/Lua tests и 3 dispatcher tests, включая durable failed receipt и повтор того же command_id. [android-root-delivery-after.txt](evidence/android-root-delivery-after.txt): **326 Android JVM tests passed**, 0 failures/errors/skips. Root process/input/output полностью подменены; su и реальный input на устройстве не запускались.
- **Residual risk:** успешный flush всё ещё не является подтверждением выполнения/exit status команды; нужен отдельный root execution acknowledgement protocol. Завершение дочернего input process после kill и реальные Android recovery не проверены. Live touch пока без явного ACK. Lua pcall/custom scripts могут сами обработать ошибку и продолжить действия; автоматизация с новым command_id также требует отдельной политики unknown outcome. Это не exactly-once гарантия физических эффектов.

### AUD-35 — High: cancel/force-stop перезаписывали результат конкурирующей транзакции

- **Root cause:** TaskService читал задачу без FOR UPDATE и без обновления identity map. Между чтением и изменением result handler/watchdog мог зафиксировать COMPLETED/FAILED/TIMEOUT; cancel затем записывал CANCELLED поверх результата. Stop мог отправляться до освобождения строки конкурирующим result handler.
- **Affected files:** `backend/services/task_service.py`, `_get_task`, `cancel_task`, `force_stop_task`.
- **Evidence:** [cancellation-serialization-before.txt](evidence/cancellation-serialization-before.txt): 8 failures, 6 controls passed. Две настоящие PostgreSQL сессии воспроизводят как уже закоммиченный terminal state при устаревшем ORM object, так и незавершённую транзакцию с удерживаемым row lock.
- **Fix:** `d7839fb` — оба mutation path получают tenant-scoped FOR UPDATE и populate_existing перед проверкой статуса и внешними эффектами. После конкурирующего terminal commit возвращается 409; result сохраняется, Redis/command publisher не вызываются. Обычные GET не получают write lock.
- **Regression:** `tests/production/test_cancellation_serialization.py`: 14 passed — три terminal outcomes, два cancellation path, блокировка конкурирующим result owner, tenant 404 и разрешённая отмена активных задач. [cancellation-serialization-after.txt](evidence/cancellation-serialization-after.txt).
- **Residual risk:** это сериализация серверного решения, а не подтверждение физической остановки APK. Pre-commit CANCEL_DAG, Redis failure, durable cancellation/stop ACK, отдельные batch/scheduler cancellation paths и остановка уже доставленной ASSIGNED задачи требуют продолжения проверки.

### AUD-36 — High: ACK остановки мог ложно завершить DAG после rollback

- **Root cause:** user force-stop отправлял CANCEL_DAG с command_id, равным UUID задачи. Android отвечал completed на принятие control; backend считал любой такой UUID ACK результатом DAG. Если после отправки stop происходил отказ Redis или SQL commit, задача оставалась RUNNING, а запоздалый ACK записывал COMPLETED и подтверждал чужой журнал результата.
- **Affected files:** `backend/services/task_service.py`, `backend/api/ws/android/router.py` (граница обработки ACK, без изменения handler).
- **Evidence:** [cancellation-commands-before.txt](evidence/cancellation-commands-before.txt): два PostgreSQL runtime failures при injected redis_release/sql_commit; ACK проходит через настоящий handle_command_result, stored status становится COMPLETED вместо RUNNING.
- **Fix:** `3a7fcc8` — user stop использует отдельный `user_cancel_<task_id>` command_id, а UUID цели остаётся в payload.task_id. Такой receipt не попадает в DAG result persistence и не вызывает result_ack для журнала задачи.
- **Regression:** оба отказа после delivery + проверка неизменённого результата/отсутствия DAG result_ack. [cancellation-commands-after.txt](evidence/cancellation-commands-after.txt): 24 связанных backend cases passed.
- **Residual risk:** stop всё ещё может быть принят APK до SQL rollback; здесь исправлена ложная успешная запись, но не согласование остановки после отказа. Нужны durable intent/outbox и отдельный stop ACK. На wire distinct ID — обязательный контракт; произвольные новые control producers не должны использовать UUID задачи.

### AUD-37 — High: запоздалое управление старой задачей воздействовало на новый DAG

- **Root cause:** Android CANCEL_DAG/PAUSE_DAG/RESUME_DAG не использовали payload.task_id; TTL не предотвращал доставку устаревшей команды внутри допустимого окна. Watchdog вообще не передавал task_id в payload.
- **Affected files:** `android/.../commands/CommandDispatcher.kt`, `DagRunner.kt`, `backend/tasks/task_heartbeat_watchdog.py`.
- **Evidence:** [android-control-target-before.txt](evidence/android-control-target-before.txt): 6 failures, 1 positive control passed. Настоящие dispatcher/journal/runner исполняют task A, затем task B; отмена A прерывает B. Отдельно воспроизведены late pause/resume, malformed/missing target и ложный ACK после завершения/ошибки DAG. Третий случай в cancellation-commands-before.txt доказывает отсутствие target у watchdog.
- **Fix:** `3a7fcc8` — обязательный строковый target; проверка ID активного execution и изменение flags атомарны относительно start/finally cleanup. Неактивная цель получает task_not_running, неверная — invalid_task_target. Watchdog передаёт task_id. ACK явно содержит control_accepted и не утверждает физическую остановку.
- **Regression:** 7 новых Android integration-on-JVM случаев, **333 Android tests passed**, 0 failures/errors/skips; [android-control-target-after.txt](evidence/android-control-target-after.txt). Реальный PostgreSQL watchdog test проверяет target после TIMEOUT commit.
- **Residual risk:** нет durable cancellation и ordering controls внутри одного task_id; delayed resume той же задачи всё ещё требует sequence/generation. Между claim и началом execution control может быть отклонён; текущая нода останавливается кооперативно. Для rollout сначала обновляются все backend writers, затем APK: старый watchdog не передаёт target и новый APK его отвергает. Физические устройства не тестировались. [Контракт и rollout](../../security/task-control-protocol.md).

### AUD-38 — Medium: Host подменял audit path и скрывал подтверждённые изменения

- **Root cause:** audit skip/action/resource и request-log/metrics path использовали request.url.path. Установленная Starlette 0.50.0 собирала этот URL из Host без валидации; path внутри Host отличался от фактически маршрутизированного ASGI scope.path. Upstream: [GHSA-86qp-5c8j-p5mr](https://github.com/Kludex/starlette/security/advisories/GHSA-86qp-5c8j-p5mr).
- **Affected files:** `backend/middleware/audit.py`, `metrics.py`, `request_id.py`.
- **Evidence:** [audit-path-before.txt](evidence/audit-path-before.txt): 3 failures, 1 valid-host control passed. Авторизованный PUT устройства сохраняет новое имя, но Host с `/metrics?` или `/api/v1/auth/refresh?` исключает audit entry. Host с `/api/v1/tasks/<UUID>?` записывает put.tasks и чужой resource_id вместо реального устройства. ASGITransport и PostgreSQL локальные; ingress/nginx не тестировался.
- **Fix:** `422c9c7` — все три middleware используют исходный ASGI scope.path, не зависящий от реконструкции URL по Host.
- **Regression:** четыре real API/DB cases проверяют сам mutation, audit actor/action/resource/status, metric label и request context. [audit-path-after.txt](evidence/audit-path-after.txt): 28 связанных cases passed.
- **Residual risk:** разрешения endpoint не обходятся этим сценарием; требуется право выполнить сам mutation. Подмена заголовка на реальном ingress зависит от proxy validation. Background audit всё ещё может теряться при остановке процесса/ошибке SQL; обновление уязвимых dependencies и остальные URL consumers требуют отдельной проверки. Этот fix не делает security CI зелёным автоматически.

### AUD-39 — Medium: уязвимые Python pins и несовместимая совместная установка

- **Root cause:** PyJWT/pytest были закреплены до security fixes; старая связка Pydantic/FastAPI разрешала Starlette 0.50.0. PC agent требовал pydantic-settings==2.2, backend — ==2.2.1; последовательные CI installs скрывали противоречие.
- **Affected files:** `backend/requirements.txt`, `pc-agent/requirements.txt`, `.github/workflows/ci-backend.yml`.
- **Evidence:** CI на d7839fb выдаёт 17 advisory records / 3 packages, включая повторные записи (11 уникальных GHSA). Joint resolver отказывает на конфликтующих exact pins. [Разбор reachability и upstream sources](DEPENDENCY-REVIEW.md); только Host→audit сценарий доказан как application defect (AUD-38), JWT auth bypass не утверждается.
- **Fix:** `748bb3e` — PyJWT 2.13.0, Starlette 1.3.1, pytest 9.0.3; совместимые FastAPI 0.136.3, Pydantic 2.9.2, pytest-asyncio 1.3.0. Единый settings pin 2.2.1; CI разрешает оба requirements одновременно, выполняет pip check и сканирует backend+PC.
- **Regression:** полный runtime/SQL/Redis suite в отдельном окружении; 12 сохранённых JWT negative/positive controls; существующие auth, refresh, logout, WebSocket и API tests. Pip-audit остаётся обязательным, исключения advisory/снижение gates не добавлялись.
- **Residual risk:** нулевой scan относится к конкретному Python resolution, не ко всему репозиторию. Frontend/Android/container advisories, hash lock/SBOM и будущие обновления остаются открыты. Production dependencies не менялись. Подробные версии/сканы: [DEPENDENCY-REVIEW.md](DEPENDENCY-REVIEW.md).

### AUD-40 — High: лимит журнала APK молча обрывал действия цикла

- **Root cause:** `MAX_LOOP_LOGS=200` ограничивал исполнение через `break` из body, а не только сохранение диагностики. Счётчик итераций продолжал расти; оставшиеся действия и их ошибки не выполнялись, итог мог быть успешным.
- **Evidence/reproduction:** на `a1636ff` реальные `DagRunner.execute` с 75 × 3 tap и 500 key events останавливались после 200 действий. В сценарии с ошибкой на 201-м действии ошибка не возникала и loop возвращал успех. При ровно 200 записях `logs_truncated` ошибочно был true. [До исправления: 5 failed](evidence/android-loop-before.txt), включая отдельный AUD-41.
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt:845`, `android/app/src/test/kotlin/com/sphereplatform/agent/commands/DagLoopExecutionTest.kt:45`.
- **Fix:** `9fbfa73` — ограничено только создание/добавление diagnostic entries; body продолжает исполняться и применять `abort_on_failure`. Truncation устанавливается только при фактически пропущенной записи, предупреждение выдаётся один раз на loop.
- **Regression:** `diagnosticLimitCannotSkipRemainingActions`, `failureAfterDiagnosticLimitStillStopsAnAbortingLoop`, `diagnosticsStayBoundedWithoutAllocatingAnUnboundedLoopResult`, `exactLogCapacityIsNotReportedAsTruncation`. Проверяются 225/500 реальных вызовов runner→fake executor, ошибка на вызове 201, размер журнала 200 и точная граница флага. [После исправления: 338 passed](evidence/android-loop-after.txt), 0 failed/errors/skipped во всех 27 JVM suites.
- **Residual risk:** сохранённые `max_iterations`, глубина рекурсии и таймауты по-прежнему ограничивают исполнение; это лимит числа записей конкретного loop, а не доказательство общего RAM budget для вложенных результатов. Фактическая доставка root-команды и замеры устройства не подтверждены. Обычные ошибки при `abort_on_failure=false` продолжают loop по существующему контракту.

### AUD-41 — High: loop APK продолжал команды после отмены корутины

- **Root cause:** общий `catch (Exception)` внутри loop перехватывал `CancellationException` из suspend action. При стандартном `abort_on_failure=false` обработчик переходил к следующему действию устройства даже после отмены execution scope.
- **Evidence/reproduction:** на `a1636ff` запустить loop `[sleep(10000), tap(9,9)]`, дождаться suspension через `runCurrent`, вызвать `cancelAndJoin` execution job. Проверка нулевого числа tap падала: отмена sleep превращалась в обычную ошибку body. [Исходный прогон](evidence/android-loop-before.txt).
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt:874`, `android/app/src/test/kotlin/com/sphereplatform/agent/commands/DagLoopExecutionTest.kt:71`.
- **Fix:** `9fbfa73` — `CancellationException` пробрасывается до общего обработчика ошибок body; cleanup активного execution остаётся в `finally`. Защита от повторной root-команды с неизвестным outcome сохранена.
- **Regression:** `coroutineCancellationDoesNotRunTheNextLoopAction` отменяет настоящую coroutine runner, проверяет отсутствие tap и очистку active task identity. Общий JVM прогон: **338 passed**, включая прежние root outcome/control/journal проверки.
- **Residual risk:** это распространение coroutine cancellation на suspend boundary, не подтверждение физической остановки и не durable `CANCEL_DAG`; дополнительные checkpoints wire-команд описаны в AUD-42. Wire cancel по-прежнему cooperative; текущая синхронная команда и действия до следующей проверки флага могут завершиться. Не добавлены generation ordering, stop outbox или device execution ACK.

### AUD-42 — High: APK принимал CANCEL/PAUSE, но продолжал loop/retry и мог вернуть успех

- **Root cause:** cancel/pause проверялись только между верхнеуровневыми узлами, cancel дополнительно между целыми итерациями loop. Тело цикла, вложенные действия и retry после backoff не имели общей точки проверки. После последнего действия результат формировался без повторной проверки отмены.
- **Evidence/reproduction:** на `9fbfa73` через реальный WebSocket callback диспетчера: принять CANCEL во время sleep внутри `[sleep, tap]` → tap всё равно исполнялся; PAUSE не удерживал loop; вложенный loop также продолжался. CANCEL во время retry backoff допускал второй tap. CANCEL во время последнего sleep подтверждался control ACK, но DAG выдавал `completed`. [13 tests, 6 failed / 7 existing passed](evidence/android-control-boundaries-before.txt).
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt:143`, `:237`, `:335`, `:388`, `:890`; `android/app/src/test/kotlin/com/sphereplatform/agent/commands/ControlCommandTargetTest.kt:150`.
- **Fix:** `71b2d2c` — общая suspend-проверка перед каждым действием/повтором и внутри вложенных loop; PAUSE ждёт RESUME либо CANCEL. Отдельное исключение принятой wire-отмены проходит мимо retry/loop error policy к terminal DAG outcome `success=false`, `CANCELLED`, `cancelled_by_user`. Проверка после действия исключает успешный результат, когда stop наблюдается во время последнего действия. Coroutine cancellation сохраняет отдельную обработку.
- **Regression:** шесть новых сценариев `ControlCommandTargetTest`: cancel loop + durable duplicate replay, nested loop, pause/resume body, cancel paused body, cancel final action, cancel retry backoff. Используются реальные dispatcher/runner/journal и virtual coroutine time, подменены только OS/storage/network. [Полная JVM suite: 344 passed](evidence/android-control-boundaries-after.txt), 0 failures/errors/skips в 27 suites; прежние target isolation/root unknown-outcome проверки также прошли.
- **Residual risk:** cooperative checkpoint не прерывает уже выполняемый синхронный/root/Lua вызов и не подтверждает физический эффект. Между проверкой флага и запуском действия возможна гонка; нет атомарной остановки внешнего shell. PAUSE не замораживает node/global timeout budgets. Durable server cancellation/outbox, stop ACK и ordering controls той же задачи остаются открыты. Формат wire-команд не меняется; production rollout не выполнялся.

### AUD-43 — High: batch cancellation перезаписывал terminal outcome и повторял queue effects

- **Root cause:** `cancel_batch` читал eligible tasks и batch без блокировок/обновления ORM snapshot, вызывал Redis до решения владельца строки и затем писал CANCELLED. Guard пропускал FAILED/PARTIAL, а stale RUNNING обходил остальные terminal states. Отменённым tasks не выставлялся `finished_at`.
- **Evidence/reproduction:** на `3f4ea2d` реальный `TaskService.handle_task_result` удерживает Task/TaskBatch с незакоммиченным completed/failed результатом, вторая DB session запускает batch cancel, затем result owner коммитит. Итоговый task и batch становились CANCELLED поверх результата; два cancel повторяли queue call. Первичный прогон: [11 failed / 4 passed](evidence/batch-cancellation-before.txt). Тест наблюдает `pg_stat_activity.wait_event_type`, а не предполагает конкуренцию по случайной задержке.
- **Affected files:** `backend/services/batch_service.py:261`, `:279`; `tests/production/test_batch_cancellation.py`.
- **Fix:** `d4bb4d5` — eligible tasks выбираются с tenant filter, стабильным порядком UUID, FOR UPDATE и `populate_existing`; затем блокируется/обновляется batch и повторно допускаются только PENDING/RUNNING. Terminal batch возвращает 409 до queue effects. Отмена записывает UTC `finished_at`; RUNNING tasks сохраняются.
- **Regression:** 16 новых PostgreSQL cases: result/cancel, fresh/stale terminal states, repeated cancellation, active task timestamps, tenant rejection и RUNNING semantics. Дополнительный тест сначала удерживает только Task, затем запускает cancel и result aggregation: обе транзакции завершаются в пределах deadline без инверсии Task → Batch. [41 related tests passed](evidence/batch-cancellation-after.txt). Общий прогон с первыми 15 cases: **1062 passed, 66,72%**; дополнительный lock-order case входит в последующий targeted прогон.
- **Residual risk:** Redis effects остаются до commit API; нет durable cancellation outbox/stop ACK. ASSIGNED мог уже попасть на APK, RUNNING намеренно не останавливается этим API. Преждевременный COMPLETED producer исправлен отдельно в AUD-45; cancellation между волнами закрыта отдельно в AUD-47; durable recovery ещё открыт. Scheduler/pipeline cancellation проверяются отдельно. Это не blanket guarantee отсутствия всех deadlocks.

### AUD-44 — High: scheduler cancellation терял результаты задач и pipeline runs

- **Root cause:** `_cancel_previous_tasks` получал eligible Task/PipelineRun без FOR UPDATE и без обновления ORM snapshot, затем посылал queue/CANCEL_DAG effects и сохранял CANCELLED. Результат конкурирующего writer между SELECT и commit не защищался; selector также полагался на batch link без явного org filter.
- **Evidence/reproduction:** на `d4bb4d5` отдельная PostgreSQL session удерживает terminal result задачи (через настоящий `handle_task_result`) либо pipeline run; scheduler выполняет cancellation до её commit. После commit owner статус перезаписывался на CANCELLED, terminal timestamp pipeline терялся. Семь таких concurrency cases падали. Ещё два теста с явно созданной некорректной legacy tenant-связью показали отсутствие query boundary; это не доказательство возможности создать такую связь через публичный API. Полный исходный набор: [9 failed / 6 passed](evidence/scheduler-cancellation-before.txt).
- **Affected files:** `backend/services/scheduler/scheduler_engine.py:525`, `:541`, `:569`, `:624`; `tests/production/test_scheduler_cancellation.py`.
- **Fix:** `753f67c` — Task и PipelineRun читаются со стабильным порядком ID, FOR UPDATE, `populate_existing` и org predicate; latest execution ограничен организацией schedule. После ожидания terminal rows больше не eligible, поэтому не изменяются и не вызывают queue/stop. Timestamp каждой stop-команды формируется после ожидания блокировки, а не до SELECT.
- **Regression:** 16 PostgreSQL cases: четыре task result races, три pipeline outcome races, шесть разрешённых active transitions, два tenant-link guards и дополнительный fake-clock тест задержки 120 s при TTL 30 s. [49 related tests passed](evidence/scheduler-cancellation-after.txt); полный объединённый прогон: **1079 passed, 67,27%**, включая 211 PostgreSQL/Redis cases. Mock transport не затрагивает внешних устройств.
- **Residual risk:** lock сохраняется на время queue/publisher вызовов; потеря Redis/сети или commit может оставить неоднозначную отмену. Нет outbox/physical stop ACK; pipeline executor и другие writers требуют отдельного fencing/recovery, а in-flight child task не останавливается одной сменой PipelineRun.status. PAUSED pipeline и конкуренция creation ticks не закрыты. Scalar batch IDs в legacy data требуют собственной проверки/восстановления.

### AUD-45 — High: волновой producer объявлял успех до выполнения задач

- **Root cause:** `_execute_waves` безусловно записывал COMPLETED и отправлял `batch.completed` после SQL создания задач. Локальный `succeeded` всегда оставался нулём; `failed` не сохранялся в batch. Любое исключение создания перехватывалось, включая ошибку SQL, после которой транзакция уже непригодна. Последняя запись producer могла перезаписать FAILED/PARTIAL, уже установленный обработчиком результатов.
- **Evidence/reproduction:** на `b64adce` новая QUEUED task сопровождалась COMPLETED batch и ложным webhook; `cancel_batch` возвращал 409, хотя выполнение ещё не начиналось. Реальные result handlers между commit волны и выходом producer теряли terminal status. Неизвестное/чужое устройство не увеличивало `failed`. Ошибка PostgreSQL `SELECT 1 / 0` во второй волне подавлялась, а batch объявлялся успешным. [Исходные 13 сценариев: 12 failed / 1 passed](evidence/batch-wave-outcomes-before.txt).
- **Affected files:** `backend/services/batch_service.py`, `backend/services/task_service.py`; `tests/production/test_batch_wave_outcomes.py`.
- **Fix:** `788a625` — убрана безусловная финализация и преждевременная отправка callback. Отказы допуска 4xx учитываются в SQL через общий FOR UPDATE aggregation lock, после создания задач и в транзакции той же волны. DB/неожиданные ошибки выходят из producer и откатывают текущую волну; предыдущие commit сохраняются. Финальный статус рассчитывается по outcomes, а не факту постановки в очередь.
- **Regression:** 13 новых PostgreSQL cases: success/failure после QUEUED, отсутствие false webhook, три terminal outcome interleavings, смешанные/полные отказы допуска, возможность отмены после enqueue, реальная SQL ошибка и два конкурентных increment с владельцем result lock. [56 related tests passed](evidence/batch-wave-outcomes-after.txt). Полный прогон: **1092 passed**, coverage **67,60%**, включая **224 PostgreSQL/Redis cases**. Никакие реальные устройства/webhooks не вызываются.
- **Residual risk:** `webhook_url` пока только принимается/хранится; корректный post-commit completion callback с durable outbox ещё не реализован. Нет durable wave cursor, безопасного restart/replay и reconciliation после неизвестного commit outcome. Startup ordering исправлен отдельно в AUD-46; fencing с cancel между волнами — в AUD-47. RUNNING batch после аварии требует расследования, а не слепого повтора. Повторяющиеся device IDs и иные writers требуют проверки. Исторические ложные статусы/счётчики автоматически не исправляются.

### AUD-46 — High: worker batch запускался до commit родительской записи

- **Root cause:** `start_batch` делал flush и `asyncio.create_task`, а commit выполнялся позже в HTTP router. Независимая worker session могла не видеть родителя; ошибка commit в router не отменяла уже запущенную работу.
- **Evidence/reproduction:** отдельная PostgreSQL session фонового worker читает batch до caller commit и получает `None`; при инъекции ошибки commit в реальный endpoint coroutine worker уже запущен. Контрольный сценарий ошибки mapping не запускает фоновые задачи. [До fix: 2 failed / 1 passed](evidence/batch-startup-before.txt) на `788a625`.
- **Affected files:** `backend/services/batch_service.py`, `backend/api/v1/batches/router.py`, `tests/production/test_batch_startup.py`.
- **Fix:** `841904f` — сервис явно владеет transaction boundary: сначала проверяет/подготавливает волны, коммитит parent, затем запускает worker. Оба HTTP start/broadcast paths используют этот commit, лишний commit router убран. Ошибка commit выходит до создания coroutine worker.
- **Regression:** три исходных сценария проходят; добавлен четвёртый через ASGI HTTP POST /batches с настоящим worker и TaskService на выделенной БД: 202, ровно один launch и QUEUED task. [25 related tests passed](evidence/batch-startup-after.txt). Все четыре cases также входят в последующий полный прогон AUD-47.
- **Residual risk:** окно process crash между успешным commit и launch остаётся; нужны durable wave plan/cursor и recovery worker. Неизвестный commit outcome нельзя автоматически повторять. Это не доказательство доставки задач APK или cancellation fencing между волнами.

### AUD-47 — High: отменённый batch продолжал допускать новые задачи

- **Root cause:** producer не проверял актуальный статус batch перед волной. Выборка cancel видела только committed Task rows и пропускала ещё создаваемые задачи. Обычная проверка статуса без общего transaction fence не закрывает эту гонку. Task result/watchdog aggregation также меняли CANCELLED на COMPLETED/FAILED при завершении оставшейся RUNNING task.
- **Evidence/reproduction:** на `841904f` отмена между commit волн оставляет следующую task QUEUED; отмена во время незакоммиченного insert завершается раньше producer и пропускает task. В обратном порядке producer начинает create до commit cancellation. Четыре terminal batch состояния не запрещают новую волну; success/failure/timeout отменённого batch меняют его статус. Внутренний worker с явно неверным org context меняет счётчики чужого batch (test fixture, не доказанный публичный API exploit). [Исходные 11 cases: 11 failed](evidence/batch-wave-cancellation-before.txt).
- **Affected files:** `backend/services/batch_service.py`, `backend/services/task_service.py`, `backend/tasks/task_heartbeat_watchdog.py`; `tests/production/test_batch_wave_cancellation.py`.
- **Fix:** `87092d2` — producer и cancel берут общий PostgreSQL transaction advisory lock по batch до task/device row locks. После ожидания producer заново читает tenant-scoped scalar status и допускает только PENDING/RUNNING. Cancel сначала ждёт admission, затем выбирает уже committed tasks и сохраняет прежний Task → TaskBatch порядок. Devices внутри волны блокируются по UUID. Result/watchdog увеличивают counters, но сохраняют CANCELLED.
- **Regression:** все 11 исходных cases проходят. Ещё два теста проверяют освобождение advisory lock после настоящей SQL ошибки/rollback и два конкурирующих batch с обратным входным порядком общих устройств. [73 related tests passed](evidence/batch-wave-cancellation-after.txt), включая прежние проверки Task → Batch deadlock и result/cancel serialization. Полный прогон: **1109 passed, coverage 67,64%**, включая **241 PostgreSQL/Redis cases**; строгий gate 65% сохранён. Ruff, configured Bandit (0 Medium/High) и API docs --check прошли.
- **Residual risk:** гарантия действует для обновлённых BatchService producer/cancel и указанных aggregation writers; перед использованием требуется обновить все backend workers, старый worker advisory fence не соблюдает. Другие scheduler/pipeline writers, durable wave replay/cursor, неизвестный commit outcome и stop outbox остаются открыты. Cancel может ждать текущую волну/SQL lock; прикладной deadline ожидания не добавлен. Redis effects остаются до commit; отмена SQL не доказывает физическую остановку ASSIGNED/RUNNING на APK. Исторические данные и производственная инфраструктура не изменялись.

### AUD-48 — High: logout сохранял cookie и оставлял fallback refresh-token рабочим

- **Root cause:** endpoint добавлял cookie deletion к injected Response, затем возвращал другой Response(204), теряя Set-Cookie. При отзыве токена учитывалась только cookie, хотя frontend и refresh endpoint поддерживают `X-Refresh-Token` для сред без cookie.
- **Evidence/reproduction:** на `9bb33ad` HTTP logout возвращает 204 без Set-Cookie для valid/invalid/absent Bearer. Logout с действительным Bearer и refresh в header оставляет этот refresh рабочим: последующий настоящий POST /auth/refresh возвращает 200. Cookie-вариант SQL отзыва уже работал. [До fix: 4 failed / 1 passed](evidence/session-logout-before.txt).
- **Affected files:** `backend/api/v1/auth/router.py`, `tests/production/test_session_logout.py`, generated API contracts.
- **Fix:** возвращается тот же Response с удалением cookie и 204; параметры удаления согласованы с выдачей cookie. При valid signed Bearer отзыв получает cookie либо fallback header. В OpenAPI указан фактический 204.
- **Regression:** пять реальных ASGI/PostgreSQL/Redis cases проверяют атрибуты удаления cookie, пустой 204, сохранённый SQL revoke и 401 при повторном refresh/доступе со старым access. [71 related auth tests passed](evidence/session-logout-after.txt), включая JWT forgery/expired-token contract checks. Исторический прогон на `efe9be8`: **1114 passed**, coverage **67,77%**, включая **246 PostgreSQL/Redis cases**; строгий gate 65% сохранён.
- **Residual risk:** при отсутствующем/некорректном Bearer endpoint только удаляет cookie, не выполняя SQL revoke. Redis/DB failure не подтверждает завершение серверного отзыва. Frontend Sign Out/guard/cache и поздние auth responses исправлены в AUD-49–51; single-use SQL refresh — в AUD-52. Session-family revocation остаётся открытым. XSS exposure localStorage fallback не устраняется этим fix; HTTP transport подменён, живой сервер не запускался.

### AUD-49 — High: браузер показывал закрытые страницы и кэш предыдущей организации

- **Root cause / affected files:** `frontend/app/providers.tsx` содержал постоянный `DEV_SKIP_AUTH = true`; один `QueryClient` переживал смену identity. Redirect после render сам по себе также не препятствует запуску private hooks. Публичность определялась по prefix `/login`.
- **Evidence / reproduction:** React/JSDOM с настоящими Zustand и React Query: private children монтируются при pending/отсутствующей сессии; после logout остаются; `/login-private` открыт; переход A → B продолжает показывать cached account credential A, пока B ещё не ответил. [До исправления: 6 failed](evidence/frontend-boundary-before.txt).
- **Fix:** закрытые children не монтируются до готовности и наличия token + user; login — точный public route; смена identity создаёт новый query client до отображения страницы. Retired client отменяет запросы и очищается при unmount.
- **Regression:** `frontend/__tests__/session/providers.test.tsx` — 6 runtime cases, включая позднюю запись в retired cache. [Все 176 frontend tests проходят](evidence/frontend-boundary-after.txt); `tsc --noEmit` проходит на Node 24.19.0.
- **Residual risk:** доказано отображение браузерного кэша, а не обход серверных tenant checks. Refresh/login races и logout handler исправлены в AUD-50–51. Другие Zustand/browser stores, multiple tabs и browser-level reload ещё требуют отдельных проверок. Production browser/APK runtime этим не подтверждён.

### AUD-50 — High: задержанные auth/HTTP ответы пересекали границу сессии

- **Root cause / affected files:** `frontend/lib/api.ts` повторял 401 с текущим token без привязки к исходной identity. `lib/store.ts` и API имели независимые refresh writers без fencing/timeout; поздний успех восстанавливал logout, поздняя ошибка очищала новый login. `app/(auth)/login/page.tsx` также принимал устаревшие результаты login/MFA и записывал user/token раздельно.
- **Evidence / reproduction:** реальные Axios interceptors и управляемые in-memory adapters: delayed startup/API refresh после logout, delayed 401 мутации после A → B, delayed successful account response, старый refresh failure после login B, refresh timeout=0. [6 failed / 2 passed до fix](evidence/frontend-refresh-before.txt). Отдельно старый login восстанавливал logout и публиковал промежуточное token-without-user состояние: [2 failed](evidence/frontend-login-before.txt). JSDOM предупреждение о navigation связано со старым `window.location.href`; дефекты подтверждены assertions токенов/ответов, а не этим предупреждением.
- **Fix:** версия сессии проверяется перед отправкой/retry и обработкой любого HTTP response; login/logout инвалидируют старую работу. Startup/401 используют один ограниченный 5 секундами refresh. Ротация сохраняет версию identity, каждый исходный запрос повторяется максимум один раз. Identity mismatch refresh закрывает сессию. Login/MFA применяются атомарно и только к актуальной попытке; client navigation не вызывает лишнюю ротацию. Query cache key включает версию сессии, включая повторный вход того же пользователя. Browser marker после logout предотвращает silent restore оставшейся cookie при remount/reload в среде с доступным localStorage.
- **Regression:** `frontend/__tests__/session/refresh-races.test.tsx` (12 cases), `login.test.tsx` (4 cases), существующие 176 tests: [192 passed](evidence/frontend-refresh-after.txt), `tsc --noEmit` passed. Дополнительные cases: два initializers + API 401, обе повторные 401, чужая cookie identity, remount после logout, MFA success/back. Тест кнопки logout намеренно ещё не включён в этот commit: её fix отдельный AUD-51.
- **Дополнительное boundary evidence:** Axios request interceptor по умолчанию запускался в следующей microtask; смена A → B сразу после `api.post` привязывала запрос уже к B. [Один новый regression failed](evidence/frontend-call-boundary-before.txt). Interceptor теперь синхронный: snapshot фиксируется в момент вызова API, до следующей microtask. Этот case расширяет AUD-50, а не закрывает серверную idempotency.
- **Residual risk:** запрос уже мог исполниться сервером до logout; fencing не отменяет side effects и не даёт общей idempotency мутаций. Browser не может отменить поздний Set-Cookie: mismatch закрывается, но cookie ordering/concurrent server rotation и refresh-family revocation требуют серверной проверки. Отказ browser storage при logout проверен в AUD-51; multiple tabs, полная перезагрузка без доступного storage, альтернативные stores и настоящий браузер ещё не проверены. Сбой refresh требует повторного входа.

### AUD-51 — High: кнопка выхода не завершала сессию

- **Root cause / affected files:** `frontend/src/features/navigation/NOCSidebar.tsx` содержал только закомментированный placeholder logout handler. Даже серверный AUD-48 fix не вызывался интерфейсом.
- **Evidence / reproduction:** реальный React click Sign out оставляет `access-a` в Zustand; [1 failed до fix](evidence/frontend-logout-before.txt). Это без внешнего сервера: исходящий transport записывается в adapter.
- **Fix:** клик синхронно очищает local session и переходит на login; новый `signOut` в `frontend/lib/store.ts` отправляет captured Bearer и fallback refresh напрямую на `/auth/logout`, с cookie и timeout 5 секунд, без перехвата 401. Неподтверждённый remote logout отражается предупреждением на login. Late failure старого logout не меняет новую сессию. Недоступный localStorage не мешает удалить memory credentials; cookie fallback и memory logout intent сохраняются.
- **Regression:** `frontend/__tests__/session/logout.test.tsx` проверяет реальный клик/захваченные headers, network failure, late failure после нового login, отказ browser storage. `login.test.tsx` проверяет видимость предупреждения. [Текущий полный прогон: 198 tests passed](evidence/frontend-session-current.txt), tsc passed; [Next build exit 0](evidence/frontend-session-build.txt).
- **Residual risk:** при offline timeout SQL revoke не подтверждён — UI сообщает об этом. Logout требует валидно подписанного Bearer для server revocation (AUD-48); late Set-Cookie/refresh-family и multiple tabs остаются открыты. Memory-only logout marker не переживёт полный reload при заблокированном storage; серверная cookie должна быть удалена успешным logout. Build на Windows содержит tracing ENOENT warning: exit 0 не подтверждает корректность standalone artifact или deployment.

### AUD-52 — High: конкурентная ротация принимала один refresh-токен дважды

- **Root cause / affected files:** `backend/services/auth_service.py::_get_refresh_token_by_hash` выполнял обычный SELECT. Два запроса читали `revoked=False`, затем оба коммитили новый токен; ожидающий UPDATE не перепроверял committed revoke/expiry. Ранее загруженный ORM объект также сохранял старое состояние.
- **Evidence / reproduction:** выделенный PostgreSQL, два независимых AsyncSession и настоящий row owner; тест наблюдает `pg_stat_activity.wait_event_type=Lock`, затем освобождает транзакцию. Оба refresh возвращали 200 вместо одного 200 + одного 401. Отдельные committed revoke/expiry также обходились: [6 failed / 2 rollback controls passed](evidence/session-rotation-before.txt). Транспорт внешних систем не используется.
- **Fix:** общий lookup refresh/logout захватывает `SELECT ... FOR UPDATE` и `populate_existing=True` до проверки revoked/expiry. Успешная ротация коммитит потребление родителя и новый токен вместе. После ожидания проверяется свежая строка, включая ранее загруженный ORM snapshot.
- **Regression:** `tests/production/test_session_rotation.py` — 8 PostgreSQL cases: двойное потребление fresh/preloaded, revoke/expiry после ожидания fresh/preloaded, rollback revocation, искусственный commit failure до durability. Победивший child дополнительно проверяется через ASGI HTTP refresh; replay родителя возвращает 401. [61 related auth tests passed](evidence/session-rotation-after.txt); полный прогон **1122 passed / 67,77%**, включая 254 PostgreSQL/Redis cases. Ruff и Bandit gate проходят.
- **Residual risk:** блокируется одна token row, а не вся refresh family. Logout старого родителя после уже завершившейся ротации не гарантирует отзыв ранее выданного child; lineage/family protocol ещё не реализован. Commit с потерянным подтверждением может потребовать повторного login; нет безопасного replay выдачи токенов. Concurrent user deactivation/role changes, Redis outage during logout и browser multi-tab coordination требуют отдельной проверки. Существующие ранее размноженные токены автоматически не отзываются.

### AUD-53 — Medium: MFA challenge допускал повторное потребление

- **Root cause / affected files:** `backend/services/auth_service.py::complete_mfa_login` выполнял GET → TOTP verify → DEL, но не проверял результат DEL. `backend/services/cache_service.py::delete` отбрасывал Redis count. Поэтому два запроса, прочитавшие один state, оба выпускали токены; истёкший после GET challenge также принимался.
- **Evidence / reproduction:** реальные PostgreSQL/Redis и настоящий pyotp: барьер обеспечивает два завершённых GET до продолжения проверок; обе попытки отвечают 200. В отдельном сценарии реальный Redis TTL истекает после чтения, но до consumption — выдача также 200. [До fix: 2 failed / 3 controls passed](evidence/mfa-consumption-before.txt).
- **Fix:** после успешного TOTP продолжает только запрос, которому атомарный Redis DEL вернул 1. Отсутствующий/уже использованный state возвращает InvalidTokenError/HTTP 401. Неверный TOTP не потребляет challenge; ошибка Redis не допускает выдачу SQL credentials.
- **Regression:** `tests/production/test_mfa_consumption.py` — 5 cases: concurrent valid submissions, actual TTL expiry, invalid TOTP then success, потеря ответа Redis после реального удаления, SQL failure после flush до commit. [97 related auth/cache tests passed](evidence/mfa-consumption-after.txt); общий прогон **1127 passed / 67,74%**, включая 259 PostgreSQL/Redis cases. Ruff и Bandit gate проходят. Unit mock успешного consumption теперь явно возвращает count=1.
- **Residual risk:** оба исходных запроса требовали действительный state и TOTP — обход второго фактора не доказан. Redis consumption и SQL issuance не являются общей транзакцией: после consume/commit failure требуется новый password/MFA flow, старый challenge не восстанавливается. Rate limiting MFA, повтор TOTP между разными challenges, Redis failover consistency, secrets at rest и concurrent deactivation требуют отдельного аудита.


### AUD-54 — High: миграции оставляли tenant-таблицы без RLS или без рабочих политик

- **Root cause:** baseline включал RLS без создания политик; отдельный ручной SQL не вызывался Alembic. `pipeline_settings` и обе M2M-таблицы не получили RLS вообще. Старый CI сверял 15 вручную перечисленных таблиц с ручным SQL и ошибочно исключал ассоциации как защищённые FK.
- **Evidence/reproduction:** схема `20260906_account_ciphertext`, non-owner/NOBYPASSRLS роль с обычными CRUD grants, две синтетические организации и transaction-local tenant A. Прямой SELECT раскрывал чужие связи, INSERT соединял endpoints разных организаций, UPDATE изменял чужие настройки оркестратора. В 15 таблицах default deny скрывал даже собственные строки. [Исходные 19 failed, 2 passed](evidence/rls-policies-before.txt). Это доказанная SQL boundary failure, не заявление об отдельном публичном HTTP exploit для каждой таблицы.
- **Affected files:** `alembic/versions/0001_baseline_initial_schema.py:418`, `alembic/versions/20260309_pipeline_settings.py`, `infrastructure/postgres/rls_policies.sql`, `infrastructure/postgres/audit_log_policies.sql`, `scripts/check_rls.py`; исправление — `alembic/versions/20260908_tenant_policies.py:34`.
- **Fix:** `297bb01` — новая migration устанавливает политики всех 28 mapped tables. USING/WITH CHECK защищают чтение и запись; обе стороны M2M проверяются явно. Restrictive tenant boundary не позволяет дополнительной permissive policy открыть чужие строки. Старые repository-owned policy names заменяются, неизвестные operator restrictions сохраняются. Audit допускает только tenant SELECT/INSERT и запрещает UPDATE/DELETE; NULL-org runtime INSERT закрыт. Tenant setting приводится к UUID без преобразования индексируемого org_id; missing/empty отказывает, malformed вызывает ошибку до записи. Небезопасный downgrade запрещён.
- **Regression:** [33 passed](evidence/rls-policies-after.txt): 25 cases реальной полной схемы под отдельной ролью; четыре migration cases для legacy, permissive/restrictive operator policies и downgrade; четыре inventory cases, включая пропущенную M2M. Дополнительные сценарии расширяют исходный before proof; malformed-context test уточнён до отказа записи. Общий прогон **1170 passed / 67,94%**, включая **298 PostgreSQL/Redis cases**. Ruff, Bandit gate и static inventory проходят.
- **Documentation/rollout:** ручные SQL entry points явно отклоняют старый способ установки; актуальный [RLS runbook](../../security/postgresql-rls.md) содержит условия rollout, модель ролей, ограничения контекста и rollback. Developer/deployment guides и README больше не утверждают гарантированную RLS/production readiness.
- **Residual risk:** AUD-14 остаётся открытым для auth/bootstrap/refresh/device lookup до выбора tenant, повторной установки context после commit/rollback, глобальных jobs и provisioning migration/runtime ролей. Текущий Compose использует общий PostgreSQL bootstrap user и не готов к безопасному переключению. Не проверены все cross-tenant FK и конкурентная смена org родителя; SQL policy tests не заменяют HTTP/worker runtime. Migration применена только в выделенной БД; production и ключи не изменялись. RLS с GUC не защищает от произвольного SQL, который сам выбирает tenant.

### AUD-55 — High: tenant-контекст терялся после commit/recovery; Session могла смешивать организации

- **Root cause:** get_tenant_db/get_db_session устанавливали set_config(..., true) однократно. PostgreSQL LOCAL setting сбрасывается при завершении транзакции; последующие запросы под безопасной ролью не видят свои строки. Повторный вызов helper менял tenant той же Session, сохраняя ORM identity map первой организации.
- **Evidence/reproduction:** [14 failed, 2 passed](evidence/tenant-transactions-before.txt). Реальные отдельные non-owner LOGIN credentials, полная схема, две организации и pool_size=1. После commit/rollback/SQL error/Session.invalidate собственный SELECT возвращал пустой набор; после смены tenant одна Session одновременно возвращала cached Device A и загружала Device B. Два контрольных теста доказывают, что переноса LOCAL setting в новую Session через pool до fix не было.
- **Affected files:** `backend/database/engine.py:48`, `backend/core/dependencies.py:87`, совместимый helper `backend/middleware/tenant_middleware.py:set_tenant_context`; новая общая реализация `backend/database/tenant.py:19`.
- **Fix:** `7c02be2` — Session привязывается к одному валидированному UUID; after_begin восстанавливает LOCAL setting через Connection на каждой транзакции/новом соединении. Смена tenant в Session запрещена. Первая привязка внутри savepoint запрещена, повторная привязка того же tenant допустима. Параметризованный общий helper заменяет однократный set_config и старый raw-SQL helper.
- **Regression:** 16 новых cases в `tests/production/test_tenant_transactions.py`: HTTP dependency helper/background context manager, commit/rollback, SQL error, connection invalidation, interleaving A/B через один pg_backend_pid, fresh-session isolation, ORM identity retention, savepoint и invalid UUID. Вместе с обновлённой проверкой transaction-local setting — [17 passed](evidence/tenant-transactions-after.txt). Старый тест ошибочно требовал потери контекста в продолжающей работу Session; теперь проверяется очистка в новой Session и сохранение привязки в текущей.
- **Общая проверка:** **1186 passed / 68,01%**, включая 314 PostgreSQL/Redis cases; Ruff и Bandit gate пройдены.
- **Residual risk:** unscoped get_db/auth/bootstrap/jobs автоматически не защищены. Вызов dependency helper напрямую не является end-to-end ASGI проверкой. Invalidation проверяет замену собственного соединения, не network partition/server failover; запрет повторной привязки не очищает объекты, прочитанные до первой привязки. Arbitrary SQL/SET, global enumeration, RLS role provisioning и полный rollout остаются открытыми. [Контракт и ограничения](../../security/postgresql-rls.md).


### AUD-56 — High: фоновый audit INSERT терялся под runtime-ролью после успешного HTTP запроса

- **Root cause:** audit middleware создавал отдельную DB-сессию после request transaction и не устанавливал tenant context. Политика audit_logs отклоняла INSERT; HTTP-операция уже могла завершиться успешно, а вместо записи оставался только error log.
- **Evidence/reproduction:** [5 failed, 1 passed](evidence/audit-tenant-before.txt): реальные PUT /devices через ASGI, фоновый writer подключён отдельными non-owner LOGIN credentials. HTTP 200/403/404 возвращаются ожидаемо, но audit row отсутствует, PostgreSQL сообщает row-level security violation. Контрольный unauthenticated request не создаёт tenant audit согласно существующему контракту.
- **Affected files:** `backend/middleware/audit.py:126`; `tests/production/test_audit_tenant_runtime.py`.
- **Fix:** `063a9d5` — свежая Session привязывается к заранее сохранённому principal.org_id до add/INSERT. Она использует общий transaction-aware binder из AUD-55; неизвестный/отсутствующий tenant не превращается в unscoped INSERT.
- **Regression:** шесть новых ASGI/PostgreSQL cases: успешное изменение, forbidden/not-found, одновременные A/B writers через один pool, SQL failure после реального flush с recovery следующего tenant, unauthenticated control. [26 related tests passed](evidence/audit-tenant-after.txt), включая Host/audit-path integrity и transaction recovery. Общий прогон: **1192 passed / 67,99%**, включая 320 PostgreSQL/Redis cases; Ruff, Bandit gate и HTTP schema check проходят.
- **Residual risk:** request/auth DB в этих тестах остаётся прежней привилегированной fixture, отдельно проверяется именно non-owner audit writer. Полный HTTP auth/bootstrap под runtime credentials ещё не закрыт. BackgroundTask не является durable outbox: тест SQL failure явно подтверждает отсутствие первой audit row при уже успешном HTTP изменении. Crash/retry/unknown commit, audit delivery metrics и неаутентифицированные/platform события требуют отдельного решения. RLS policy и tenant filtering не обеспечивают глобальную неизменяемость от DB owner.


### AUD-57 — High: JWT lookup выполнялся до tenant context; старый токен следовал за переносом пользователя

- **Root cause:** `get_current_user` проверял подпись и blacklist, затем выполнял `db.get(User, sub)` до установки PostgreSQL tenant context. Non-owner роль с RLS не видела даже разрешённого пользователя. Под owner-подключением отсутствовал контроль соответствия `User.org_id` подписанному `org_id`; токен организации A продолжал давать профиль пользователя после его переноса в B. Некорректный UUID subject также выходил необработанной ошибкой.
- **Evidence/reproduction:** [17 failed, 5 passed](evidence/jwt-tenant-before.txt). Настоящие ASGI `/auth/me` и PUT `/devices/{id}` с отдельными non-owner LOGIN credentials отклоняли корректные JWT кодом 401. Owner-control получает 200 и профиль с новой организацией по реально выпущенному до переноса токену. Дополнительные подписанные тестовые claims без организации/с чужой организацией/неверным purpose принимались; это проверки контракта, а не доказательство возможности подделать подпись или получить user access через существующий issuer другого типа токена.
- **Affected files:** `backend/core/dependencies.py::get_current_user`; `tests/production/test_jwt_tenant_runtime.py`; SQL-адаптер SQLite в `tests/conftest.py`; per-request fixture в `tests/n8n/conftest.py`.
- **Fix:** `d828a62` — до доступа к БД проверяются purpose `access` и UUID `sub`/`org_id`; после проверки blacklist подписанная организация привязывается к Session. User выбирается по **id и org_id**, с обновлением ORM snapshot. Активность и права берутся из текущей строки БД. Общий JWT decoder и форматы device/refresh flow не изменены.
- **Regression:** 10 случаев с non-owner HTTP credentials и 12 owner-controls — [22 ASGI/PostgreSQL/Redis cases passed](evidence/jwt-tenant-after.txt): обе организации, порядок tenant binding перед SELECT users, 200/403/404 при записи устройства и audit через один runtime pool, concurrent requests, чистая новая Session, перенос/деактивация/понижение роли после выдачи токена, invalid/missing claims и неизвестный user. SQLite unit tests имеют только SQL-адаптер `set_config`: он не эмулирует RLS и не считается доказательством изоляции; production dialect bypass не добавлялся.
- **Validation:** [116 related auth/n8n/tenant tests passed](evidence/jwt-tenant-related.txt). Общий прогон **1214 passed / 67,95%**, включая **342 PostgreSQL/Redis cases**, четыре прежних warnings; неизменный gate 65%. Ruff, Bandit и generated API check проходят. Пять n8n unit fixtures-сценариев исправлены переходом на Session per request: прежняя fixture пыталась привязать разные организации к одной ORM identity map. Проверено существование 203 локальных ссылок в девяти руководствах; это не сертификация всего содержания документации.
- **Residual risk:** проверена цепочка уже выданного user access JWT и выбранные HTTP handlers. Email login, MFA/refresh/API-key/device bootstrap, WebSocket и глобальные jobs требуют отдельных проверенных tenant boundaries. Совпадение JWT claims не заменяет подпись; произвольный GUC SQL остаётся вне threat boundary. Изменение прав после SELECT в уже идущем запросе не блокируется. Durable audit outbox, полный rollout непривилегированных ролей, listening APK↔API и нагрузка 10–64 не закрыты.


### AUD-58 — High: enrollment и device refresh не работали под непривилегированной PostgreSQL ролью

- **Root cause:** API-key и device-refresh lookup требовали доступа к RLS-таблицам до определения tenant. Валидный opaque secret возвращал 401, поэтому APK не мог зарегистрироваться или продлить credentials после перехода на runtime-role.
- **Evidence/reproduction:** [7 failed / 6 negative controls passed](evidence/device-bootstrap-before.txt), реальные HTTP ASGI запросы под отдельными non-owner LOGIN credentials. Привилегированное подключение применяется только для подготовки/верификации тестовых данных.
- **Affected files:** `alembic/versions/20260909_credential_lookup.py`, `backend/database/credential_lookup.py`, `backend/services/api_key_service.py`, `backend/services/device_registration_service.py`; production/SQLite fixtures и `tests/production/test_device_bootstrap_runtime.py`.
- **Fix:** `880ab30` — две SECURITY DEFINER функции возвращают только org UUID по полному хешу активного credential; PUBLIC access отозван, search_path закреплён, таблицы fully-qualified, dynamic SQL отсутствует. Runtime получает только explicit USAGE/EXECUTE. Затем Session привязывается к tenant и выполняет обычный credential lookup под RLS с org/hash проверками. Application role не получает BYPASSRLS или table ownership.
- **Regression:** [18 runtime cases passed](evidence/device-bootstrap-runtime-after.txt), включая реальные параллельные SQL lock waits, re-enrollment, single-use refresh/child, denied credentials, scoped pool reuse, SQL error после flush/retry, function grants/owner protection и temp-table shadowing. Первоначальный related snapshot — [83 passed](evidence/device-bootstrap-after.txt). Более строгая проверка SQL concurrency добавлена после исходного 13-case before proof.
- **Residual risk:** это явно ограниченная привилегированная DB-функция; её owner/DDL/grants требуют защиты. Hash holder с EXECUTE может определить org соответствующего credential. Provisioning production roles, opaque user auth и jobs остаются открытыми; неизвестный результат commit и потерянный refresh response не получают автоматического replay. Fingerprint re-enrollment по сохранённому enrollment key не является device attestation. [Контракт, migration/grants и rollback](../../security/device-credential-bootstrap.md).


### AUD-59 — High: Android WebSocket и agent HTTP отвергали валидные credentials под RLS

- **Root cause:** Android WS загружал target device до аутентификации, а общий `authenticate_ws_token` читал Device/User по subject без tenant context и без сверки подписанной организации. Agent logs/OTA используют тот же verifier, поэтому исправление только user HTTP JWT не восстанавливало работу APK.
- **Evidence/reproduction:** [7 failed / 7 negative controls passed](evidence/agent-tenant-before.txt): настоящие ASGI WebSocket events и HTTP запросы с реальным non-owner SQL. Device/refreshed/API-key/user credentials не доходили до manager.connect; agent HTTP получал 401. Очереди/стрим/heartbeat заменены test doubles, сетевой listener и APK процесс не запускались.
- **Affected files:** `backend/api/ws/android/router.py`; `tests/production/test_agent_tenant_runtime.py`.
- **Fix:** `9f439fd` — verifier проверяет purpose и UUID claims, связывает подписанный tenant до Device/User SQL, обновляет ORM snapshot и сверяет org_id явно. WS сначала аутентифицирует principal и только затем выбирает активное целевое устройство в его организации, сохраняя device-subject matching и проверку user permission. DB session закрывается до длительного receive loop.
- **Regression:** [21 related cases passed](evidence/agent-tenant-after.txt): 16 новых ASGI/PG/Redis cases и пять прежних unit auth tests. Проверены подключение и повторное подключение с четырьмя видами credentials, own/foreign/same-org-other-device log upload, OTA, inactive/moved/revoked/viewer/invalid identities, runtime enrollment → refresh → WS → OTA и SQL error → close1011 → новая успешная сессия. Проверка log evidence после первоначального proof уточнена до реальной вложенной директории; протокол/ожидаемые HTTP коды не ослаблялись.
- **Residual risk:** защищена server-side auth chain, не измерен реальный APK/OS/кодек. Уже открытый WS не отзывает principal автоматически при изменении ключа/роли. Post-auth task results/progress/events исправлены в AUD-61; глобальные фоновые сессии ещё требуют tenant propagation. API-key enrollment bootstrap исправлен отдельно в AUD-58; неизвестный refresh commit/replay остаётся открытым.


### AUD-60 — High: ожидающий enrollment принимал уже отозванный ключ и удалённое право

- **Root cause:** `APIKeyService.authenticate` читал key обычным SELECT, а затем блокировался на UPDATE last_used_at. После ожидания он возвращал ранее загруженные active/permissions/expiry, не учитывая изменение, закоммиченное владельцем строки. Комментарий об UPDATE «без блокировки» был неверен.
- **Evidence/reproduction:** [3 failed](evidence/enrollment-revocation-before.txt): два настоящих ASGI enrollment запроса через независимые runtime connections; тест наблюдает два `pg_stat_activity.wait_event_type=Lock`. После admin commit revoke/permission removal/expiry оба запроса возвращали 201 и создавали устройства вместо 401/403.
- **Affected files:** `backend/services/api_key_service.py::authenticate`; `tests/production/test_enrollment_revocation.py`.
- **Fix:** `bd7ad7a` — SELECT FOR UPDATE с populate_existing захватывает и обновляет key snapshot до проверки полномочий. Active/expiry проверяются после ожидания; UPDATE last_used_at выполняется по id+org_id под той же блокировкой. Метод не добавляет скрытый commit; транзакцией владеет caller.
- **Regression:** три concurrency regressions проходят; [31 related cases passed](evidence/enrollment-revocation-after.txt) включает runtime bootstrap, function security и API-key service unit tests. Исходный before был снят после AUD-58: исправление tenant bootstrap позволило проверить реальную конкурентную авторизацию вместо прежнего default-deny.
- **Residual risk:** отзыв, закоммиченный после успешной проверки уже исполняющейся операции, не отменяет её. Существующие WS sessions не закрываются автоматически при revoke. Один общий ключ сериализует concurrent authentication; UPDATE уже требовал блокировку до исправления, но latency на 10–64 эмуляторах отдельно не измерена. Идемпотентный replay credential выдачи/unknown commit остаётся отдельным контрактом.


### AUD-61 — High: подключённый APK не мог сохранять задачи и события под runtime ролью

- **Root cause:** успешная WebSocket-аутентификация закрывает свою SQL Session до receive loop. Четыре post-auth блока открывали новые unbound Sessions: progress ownership lookup, received/running receipt, terminal result и EventReactor. Под реальной непривилегированной ролью RLS скрывала task rows и запрещала INSERT device_events. Task оставался ASSIGNED/RUNNING, batch не учитывал результат, result_ack не отправлялся; сервер не освобождал retained result в Android journal.
- **Evidence/reproduction:** [12 failed / 3 negative controls passed до исправления](evidence/agent-messages-runtime-before.txt). Реальный ASGI WS router сначала принимает выданный device JWT, затем получает APK-сообщения. PostgreSQL/Redis локальные, отдельный LOGIN без ownership/BYPASSRLS. Receipt оставался ASSIGNED, terminal ACK count был ноль, progress cache пуст, event INSERT отклоняла row-level security. Конкурентный тест не наблюдал ожидаемые Task row locks, поскольку RLS скрывала обеим сессиям задачу.
- **Affected files:** `backend/api/ws/android/router.py::handle_task_progress`, `handle_command_result`, `handle_device_event`; `tests/production/test_agent_messages_runtime.py`; ASGI helper в `test_agent_tenant_runtime.py`.
- **Fix:** `f272360` — перед первым tenant SQL каждого из четырёх блоков вызван существующий `bind_tenant_context` с организацией authenticated connection. Поля org_id/device_id из входящего сообщения не определяют этот контекст. Сохраняются task/device/org filters, row locks, caller-owned commit и отправка result_ack после завершённого SQL commit. Миграция и изменение протокола APK не нужны.
- **Regression:** 15 новых non-owner cases; [47 related checks passed](evidence/agent-messages-runtime-after.txt). Оба формата receipt (с type и без него), received/running с неизменным started_at при повторе; completed/failed с проверкой committed Task/Batch/DeviceEvent непосредственно при ACK; противоречащий replay после reconnect не меняет первый результат и не удваивает counters/events. Два независимых runtime connections реально ожидают блокировку Task; duplicate completion учитывается один раз. Проверены Redis method failures, реальный SQL abort `SELECT 1/0` после flush → rollback/no ACK → успешный replay, запреты foreign/same-org-other-device, terminal progress, authenticated event identity и отсутствие tenant context в fresh pooled Session.
- **Residual risk:** ASGI выполняется без сетевого listener; manager/heartbeat/stream/publisher — doubles, настоящего APK/OS/network failover здесь нет. Redis failures вводятся на границе методов, не остановкой Redis. PubSub/Fleet events и освобождение Redis task lock по-прежнему могут предшествовать SQL commit; это не durable outbox. Не проверены все EventTrigger/account/pipeline ссылки и эффекты. Live socket revocation, глобальные jobs, crash/unknown-commit recovery и нагрузка 10–64 остаются открыты. Исходный before был снят после AUD-58–60: работающая auth chain сделала post-auth дефект достижимым под runtime ролью.


### AUD-62 — High: login, user refresh/MFA и SQL logout не работали под runtime ролью

- **Root cause:** login выбирал User по email до tenant binding; refresh/logout искали opaque token hash в unscoped Session; Redis MFA state содержал лишь user UUID, а второй HTTP request открывал новую unscoped Session. RLS скрывала валидные строки. Logout при этом мог вернуть 204, оставив refresh token неотозванным в SQL.
- **Evidence/reproduction:** [10 failed / 8 passing denial controls](evidence/user-bootstrap-before.txt) на actual non-owner PostgreSQL LOGIN. Валидные login/MFA/refresh возвращали 401, cookie/header logout не менял revoked, два refresh не достигали ожидаемых SQL row locks. Проверка использует реальные ASGI endpoints и только изолированные PostgreSQL/Redis.
- **Affected files:** `backend/services/auth_service.py`; `backend/database/credential_lookup.py`; `alembic/versions/20260909_user_auth_bootstrap.py`; `tests/production/test_user_bootstrap_runtime.py`; runtime-grant/SQLite/AsyncMock/MFA fixtures.
- **Fix:** `d642273` — две закрытые для PUBLIC функции возвращают только org UUID по точному globally unique email или полному active refresh hash; после этого Session привязывается до обычных scoped SELECT. Refresh сохраняет FOR UPDATE и проверяет соответствие user/refresh organization. MFA v2 server-side JSON хранит user/org, второй шаг связывает tenant, перепроверяет active/MFA/org и сохраняет одноразовое DEL consumption. Credentials возвращаются после SQL commit. Миграция требует отдельных runtime EXECUTE grants; [runbook](../../security/user-auth-bootstrap.md) описывает threat boundary, cutover и rollback.
- **Regression:** [105 related cases passed](evidence/user-bootstrap-after.txt), включая 34 новых real-service cases. Login → me → refresh → replay denial → logout для A/B, ложный org header, cookie/header/JSON refresh, SQL revoke, current active/moved identity, два refresh SQL waiters и один winner/usable child; concurrent MFA GET/DEL, invalid/legacy state, moved/disabled user; SQL abort после flush и recovery для login/refresh/MFA; exact narrow lookup, temp shadowing, explicit EXECUTE и owner protection. Исходный before включает 18 HTTP cases; дополнительные function/MFA/failure tests добавлены при реализации механизма.
- **Residual risk:** email угадываем, поэтому EXECUTE раскрывает database caller организацию активного известного email; это не HTTP auth или проверка пароля. MFA namespace v2 требует нового password step для legacy challenges и согласованного cutover workers; client wire format не меняется. После успешного DEL и неуспешного SQL commit нужен новый challenge, а после потерянного ответа на успешный commit сохраняется unknown-outcome риск. Refresh-family revocation, MFA guessing/recovery policy, admin changes после авторизации, остальные auth callers и глобальные jobs остаются открыты. Доказательств полного browser/production/network failover нет.


### AUD-63 — High: PC-agent auth и workstation registration теряли tenant context

- **Root cause:** PC endpoint использовал собственный unscoped APIKey SELECT вместо общего credential bootstrap; после auth receive loop открывал новую Session, а workstation registration не связывал её с authenticated organization. Под runtime RLS валидный ключ отвергался, существующие Workstation/LDPlayerInstance не обновлялись.
- **Evidence/reproduction:** [6 failed / 6 passing controls](evidence/pc-tenant-before.txt) на настоящих non-owner credentials: valid connect отказан; foreign-workstation проверка не достигалась после key auth; собственные registration/recovery/cache-failure сценарии не сохраняли SQL; concurrency не достигала ожидаемых key row locks.
- **Affected files:** `backend/api/ws/agent/router.py::authenticate_agent_token`, `handle_workstation_register`; `tests/production/test_pc_tenant_runtime.py`.
- **Fix:** `4222b14` — PC auth использует `APIKeyService.authenticate` с tenant discovery и проверкой после row lock, сохраняя agent type/device:register constraints. Registration связывает fresh Session до Workstation/LDPlayerInstance SQL. Redis-only telemetry/result сообщения не получают лишнего SQL binding. Новая миграция, PC wire change или production grants не выполнялись; нужны ранее введённые API-key function grants.
- **Regression:** 12 новых actual runtime-role cases; [45 related cases passed](evidence/pc-tenant-after.txt). Endpoint connect/reconnect с receive-loop registration, invalid/expired/inactive/wrong-type/unprivileged key, foreign workstation, два настоящих SQL lock waiters при отзыве key, instance persistence, post-flush SQL abort → rollback → retry, Redis failure после SQL commit и fresh pooled Session без tenant. Existing socket double расширен последовательностью сообщений; normal ASGI disconnect этим не моделируется.
- **Residual risk:** socket/manager — doubles, это не полный PC↔server network/ADB/LDPlayer запуск. Нужны provisioning workstation/instance rows, live key revocation, durable PC command/result contract (routing исправлен в AUD-64), topology replay, normal ASGI disconnect и runtime/process recovery. Key является org-level credential, не hardware-bound identity; API-key last_used_at в auth-only Session не гарантированно сохраняется. Обновлён [PC guide](../../pc-agent.md): действительные `.env`/SPHERE_ settings, endpoint, команды и непроверенные ограничения вместо несуществующих API/config примеров.


### AUD-64 — High: PC-команды выполнялись, но сервер отбрасывал их результаты

- **Root cause:** обе ветки `CommandDispatcher.dispatch` отправляли `command_id` и terminal `status` без `type`. PC backend выбирал обработчик только по `type == "command_result"`; успешное выполнение и ошибка попадали в default logging, не в Redis result channel. Даже исправный Redis не получал результат для ожидающего подписчика.
- **Evidence/reproduction:** [4 failed / 6 passing controls](evidence/pc-result-protocol-before.txt). Настоящий PC dispatcher выполняет `ping` или получает искусственную ошибку от LDPlayer boundary; transport adapter передаёт его точный ответ в настоящий backend handler. Подписка на изолированном Redis подтверждает отсутствие ответа. Отдельно воспроизведены обе старые untyped terminal формы. Typed reply, nonterminal и telemetry controls проходят до исправления.
- **Affected files:** `pc-agent/agent/dispatcher.py`, `backend/api/ws/agent/router.py::handle_agent_message`, `tests/production/test_pc_result_protocol.py`.
- **Fix:** `eda33a7` — PC dispatcher явно отправляет `type: command_result` в success/error ответах. Backend совместим с установленными старыми клиентами: только сообщение без discriminator, с непустым string `command_id` и `completed`/`failed` считается legacy result. Payload сохраняется; telemetry и промежуточные статусы не переклассифицируются. Новая миграция не требуется.
- **Regression:** [24 related cases passed](evidence/pc-result-protocol-after.txt), включая 10 новых runtime cases: реальная success/error пара dispatcher → handler → Redis subscriber, legacy success/error, typed reply, четыре nonterminal controls и явно типизированная telemetry с похожими полями. Проверка type в исходящем payload не позволяет backend compatibility скрыть возврат дефекта в клиенте.
- **Residual risk:** это проверка протокола и Redis publication, не реальный PC network/OS/ADB/LDPlayer запуск. PubSub остаётся недолговечным: отсутствие подписчика, потеря подключения, client queue drop и Redis failure могут потерять результат. Receipt/ACK, retry, durable outbox, idempotency и command authorization/correlation требуют отдельных сценариев. Unknown command отдельно исправлен в AUD-66; исходный AUD-64 проверял только доставку результата. Существующие ограничения AUD-63 на RLS rollout, provisioning и real disconnect сохраняются.


### AUD-65 — High: PC transport failure не запускал recovery и оставлял некорректное состояние

- **Impact/root cause:** `_send_loop` ловил send error и завершался отдельно от receive loop. Клиент оставался connected, новые ответы копились в очереди без отправщика, reconnect не начинался до независимого завершения приёмника. Auth write находился до cleanup `try/finally`, поэтому его failure/cancellation оставлял `_ws` и `_connected`. Shielded stop waiters не отменялись при timeout, circuit sleep не реагировал на stop до пяти минут, а clean peer close обходил reconnect delay.
- **Evidence/reproduction:** [6 failed / 3 controls](evidence/pc-client-recovery-before.txt). Настоящий client run получает искусственную ошибку send при открытом приёмнике и не устанавливает второе соединение. Отдельно проверены stale auth state, cancellation, stop при открытом circuit, накопление Event.wait после 20 отказов и немедленный reconnect после clean close. WebSocket boundary — управляемый in-process double; listener/DNS/внешние подключения отсутствуют.
- **Affected files:** `pc-agent/agent/client.py:40` (`run`), `_connect_once`, `_receive_loop`, `_send_loop`; `tests/test_pc_client_recovery.py`, `tests/test_pc_agent_arch.py`.
- **Fix:** `e216980` — Session владеет sender/receiver tasks и завершается при окончании любого направления. Send errors доходят до reconnect loop; cleanup включает auth write, сбрасывает состояние и отменяет/собирает обе transport tasks. Ожидания backoff/circuit отменяемы через stop без shield; clean closes тоже выдерживают delay. Queue ordering сохранён, взятые элементы отмечаются task_done.
- **Regression:** [91 PC cases passed](evidence/pc-client-recovery-after.txt), включая девять новых lifecycle cases. После send error устанавливается новое соединение и следующий результат отправляется; auth failure/cancel очищаются; stop прерывает circuit; 20 reconnect delays не оставляют waiter tasks; clean/abrupt receive termination собирает transport tasks; 20 конкурентных producers сохраняют auth-first/order и один sender. Старый backoff test мог пройти с пустым списком наблюдений: теперь исполняется настоящий run и проверяется вся последовательность 1→2→4→8→16→30.
- **Residual risk:** socket implementation — double, это не реальная сеть или TLS/WebSocket handshake failure matrix. `_connected` означает отправленный auth frame, не server auth ACK. Failed send имеет неизвестный исход и автоматически не повторяется; оставшаяся in-memory очередь, durable receipts, command idempotency, topology replay и server ASGI disconnect остаются отдельными задачами. Dispatch tasks не ограничены и могут жить дольше WS-сессии; их отмена/дренирование и OS subprocess cleanup этим изменением не решены. Stop во время ещё не завершённого connect handshake отдельно не проверен.


### AUD-66 — Medium: неизвестная PC-команда возвращала ложный completed

- **Root cause/impact:** default branch `_handle` возвращала `None`, а `dispatch` считала любое обычное завершение success. Опечатка, устаревшее имя команды или несовместимая новая операция давали `status: completed, result: null` без вызова LDPlayer/ADB. Ожидающий result subscriber получал ложное подтверждение выполнения. Severity Medium: затронуты неподдерживаемые типы, а не успешность всех поддерживаемых команд.
- **Evidence/reproduction:** [3 failed / 10 controls](evidence/pc-unsupported-command-before.txt). Реальные dispatcher/backend handler публикуют в выделенный Redis `completed` для `ld_lauch`, старого документированного `adb_exec` и `unsupported_future_command`; execution boundaries не вызываются. Успешные/ошибочные поддерживаемые команды и legacy protocol controls продолжают проходить.
- **Affected files:** `pc-agent/agent/dispatcher.py:139` (default branch), `dispatch` на строке 28; `tests/production/test_pc_result_protocol.py`.
- **Fix:** `8692a58` — default branch поднимает явный `ValueError("Unsupported command type: ...")`; существующая error path формирует `command_result`, тот же command ID и `failed` с причиной. No-ID сообщения по-прежнему не создают ответ. Новая миграция, backend protocol change или execution retry не нужны.
- **Regression:** три новых реальных Redis cases; [95 related cases passed](evidence/pc-unsupported-command-after.txt), включая 13 protocol cases и 82 PC unit cases. Проверены тип/ID/error, отсутствие result/success и отсутствие LDPlayer/ADB calls, одновременно сохранены supported/legacy controls.
- **Residual risk:** это корректность отчёта об unsupported type, не доказательство прав на произвольные команды, корректности payload, реального subprocess outcome или durable receipt. Отсутствующий type/ID, malformed/non-object messages и ограничения concurrency остаются отдельными путями аудита. Поддержка новой команды всё ещё требует обновления клиента; silent success не является механизмом совместимости.


### AUD-67 — High: APK reconnect синхронизировал парк и обходил задержку после server close

- **Root cause/impact:** `SphereWebSocketClient.reconnectLoop` сбрасывал attempt в 0 после обычного закрытия, поэтому следующий socket открывался без ожидания. `calculateBackoff` возвращал одну и ту же задержку для любого устройства с одинаковым attempt. После общего рестарта сети/сервера клиенты формировали одинаковые retry deadlines; repeated clean closes не имели pacing. Нагрузочный коллапс не измерен, но оба дефекта политики воспроизведены.
- **Evidence/reproduction:** [3 failed / 6 passing controls](evidence/android-reconnect-fleet-before.txt). Настоящий reconnect loop с virtual time повторно открывает socket сразу после server close 1000/1001; stop не завершает ожидаемый paced retry. 128 вызовов production backoff имеют один срок вместо распределения. OkHttp socket — double, real listener не создаётся.
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt` (`reconnectLoop`, `calculateBackoff`); `WebSocketLifecycleTest.kt`, `SphereWebSocketClientTest.kt`.
- **Fix:** normal close переводит цикл на первый retry; delay получает equal jitter в пределах половины экспоненциального ceiling и самого ceiling. Первый повтор — 1–2 s, максимальное окно — 15–30 s. Положительный минимум исключает busy retry; существующий stop/force-reconnect канал сохраняется. Credentials, persisted server URL и wire contract не меняются.
- **Regression:** [полный Android unit run](evidence/android-reconnect-fleet-after.txt), [347 tests / 27 suites, 0 failures/errors/skips](evidence/android-reconnect-fleet-summary.json). Три новых теста проверяют реальный client loop и production delay; прежние тесты backoff/констант теперь читают production implementation вместо копирования формулы и сравнений константы с самой собой. Проверка network retry использует границы окна и не зависит от случайного точного значения.
- **Residual risk:** jitter уменьшает синхронизацию retry, но это не capacity test, SLO или полноценный secondary channel. Initial connect/config polling, wall-clock circuit/debounce, auth-ACK distinction, delayed refresh, смена endpoint и отказ Redis/PG остаются в [эксплуатационном плане](../../operations/READINESS.md). Реальные сотни APK, TLS/network/OS и ручной recovery не проверены. Новая APK версия нужна для этой политики; старые APK продолжают использовать прежние задержки.


## Открытые подтверждённые блокеры

| ID / severity | Root cause и evidence | Необходимое продолжение |
| --- | --- | --- |
| AUD-11 / High, частично исправлен | SQL ownership/uniqueness/intents исправлены и проверены; реальные orphan peers и provider unknown outcomes не reconciled | Inventory contract, controlled reconciliation/rollout, HTTP adapter и AWG конфигурация; незавершённые intents пока удерживаются |
| AUD-14 / High | Startup guard исправлен; политики всех 28 tables и runtime CRUD проверены (AUD-54). Восстановление bound Session после commit/recovery исправлено (AUD-55); user JWT, API-key/device-refresh/Android WS auth и post-auth task/event sessions исправлены (AUD-57–61); user login/refresh/logout/MFA исправлены в AUD-62; PC key auth/registration исправлены в AUD-63; остальные auth callers и глобальные jobs требуют проверки | Разделение migration/runtime ролей, перевод HTTP/auth/jobs на bound Sessions, разрешённые/запрещённые runtime API/worker сценарии |
| DEPLOY-03 / High | Effective Compose оставляет n8n/MinIO host ports; production persistence и DB roles не согласованы | Ingress/access design, роли, долговечные artifacts, runtime/restore проверка |

## Следующие компоненты аудита

Следующие пункты — кандидаты/недостаточное покрытие, а не автоматически доказанные
эксплуатируемые уязвимости: Android FGS/boot/timeout, root-only действия на обычных
телефонах, screen codec recovery; PC-agent
durable delivery, unknown commands и normal disconnect; orchestrator/pipeline crash recovery; rollout/restore credentials и APK cache/logs;
MFA/session/logout races; VPN revoke/PSK/маршруты; backup/restore; webhook/n8n contract;
frontend runtime; метрики и multiprocess; зависимости и CI.

GitHub checks на первой ревизии PR: Android build и lint проходили, security job
падал. Эти результаты нельзя переносить на новую ревизию без проверки. Зависимости
не считаются исправленными до анализа advisory, обновления и повторного запуска.

На ревизии `554df5d` CI обнаружил пять lint diagnostics и уязвимые зависимости.
Lint исправлен в `3767de1`, локальный Ruff проходит. На опубликованном `4c8f066`
Android build и lint успешны, security job падает; эти результаты исторические
и не подменяют проверки нового head. Dependency-aware mypy на Windows
также выявил прежние diagnostics вне исправленного owner count; они не подавлялись.
Security job показывает PyJWT/Starlette/pytest advisories; проверки upstream и
совместимых обновлений продолжаются. Список приоритетов: [ROADMAP.md](ROADMAP.md).

На `1e9bc63` GitHub backend run `34029730768` завершился: Tests, Lint, Alembic и
статический RLS job успешны; Security/pip-audit — failure. Android run `34029730717`
успешно собрал APK и выполнил unit tests. Это проверенный snapshot предыдущего
head; последующие коммиты требуют собственных CI результатов.

На `5cbeb55` backend run `34031085035` завершился с успешными Tests/Lint/Alembic/
статическим RLS job и failure Security/pip-audit. Android run `34031085117` успешен.
Эти результаты не распространяются автоматически на последующие SQL lifecycle fixes.

На `b9c12bf` Ruff 0.16.6 в GitHub выявил I001 в `test_vpn_migration.py`: локальный
Ruff 0.3 классифицировал Alembic иначе из-за одноимённой папки миграций. Явный
known-third-party для установленной библиотеки и упорядоченные imports проходят
на обеих версиях; правила lint не отключались. На `7c3cf28` backend run
`34045859924`: Tests/Lint/Alembic/статический RLS успешны, Security/pip-audit
падает. Android run `34045859946` успешен; новые коммиты требуют своих checks.

Для AUD-11 реализованы [SQL reservations и generation fencing](VPN-LEASE-DESIGN.md);
документ описывает границы транзакций, обязательный migration preflight и ещё
не реализованный provider reconciliation. Это не означает готовность всего VPN.

На `7cb77d5` backend run `34046802288` завершился: Tests/Lint/Alembic/статический
RLS успешны, Security/pip-audit падает; Android `34046802281` успешен.
Это snapshot перед шифрованием credentials, не результат последующего head.

На серверном fix `d966f15` backend run `34047657701`: Tests/Lint/Alembic/статический
RLS успешны, Security/pip-audit падает; Android `34047657671` успешен.
Это проверка encryption revision до отдельного Android logging fix.

На Android logging fix `d710587` backend `34048071044`: Tests/Lint/Alembic/
статический RLS успешны, Security/pip-audit падает; Android `34048071041`
успешен. На root delivery fix `7aea90f` backend `34048960771`: Tests/Lint/Alembic/
статический RLS успешны, Security/pip-audit падает; Android `34048960802` успешен.
Это snapshot перед последующими cancellation fixes.

PR остаётся draft до завершения открытых блокеров, повторного runtime обследования
и финализации отчёта. Merge и deployment не выполнялись.

После dependency fix `748bb3e` **все backend jobs успешны**, включая Security,
Tests, Lint, Alembic и статический RLS:
[GitHub run 34050895738](https://github.com/RootOne1337/sphere-platform/actions/runs/34050895738).
Android build/tests также успешны:
[run 34050895681](https://github.com/RootOne1337/sphere-platform/actions/runs/34050895681).
Сохранены [backend snapshot](evidence/ci-748bb3e-backend.json) и
[Android snapshot](evidence/ci-748bb3e-android.json). Это проверка конкретной
ревизии исправлений; зелёный CI не закрывает перечисленные runtime/RLS/rollout риски.

На Android control fix `71b2d2c` **все backend jobs успешны**, включая Tests,
Security, Lint, Alembic и статический RLS:
[run 34066563090](https://github.com/RootOne1337/sphere-platform/actions/runs/34066563090).
Android PR build/unit tests также успешны:
[run 34066563159](https://github.com/RootOne1337/sphere-platform/actions/runs/34066563159).
Сохранены [backend snapshot](evidence/ci-71b2d2c-backend.json) и
[Android snapshot](evidence/ci-71b2d2c-android.json). Последующие изменения документации
требуют своих checks; это результаты конкретного code head, не подтверждение runtime.

[Руководство APK](../../android-agent.md) сверено с кодом: исправлены endpoint и
first-message auth, имена DI/dispatcher, build flavors/artifact paths, signing env,
источники provisioning и фактический command/ACK формат. Удалены неподтверждённые
утверждения о 100% uptime и application-level OTA certificate pinning. Ограничения
физических устройств, остановки, OTA recovery и замеров нагрузки обозначены явно.


Справочник HTTP API теперь имеет воспроизводимую выгрузку: `python -m
scripts.export_api_docs` обновляет `docs/openapi.json` и `docs/api-endpoints.md`,
`--check` проверяет их без запуска lifespan. Старый snapshot содержал 96 paths,
актуальный — **162 HTTP operations / 126 paths** (добавлены 30 отсутствовавших
маршрутов). [До обновления](evidence/api-docs-before.txt) check отклонял оба файла;
[после](evidence/api-docs-after.txt) проходит. В CI добавлен отдельный шаг проверки
документации. Это полнота объявленных HTTP routes/schemas, а не runtime/permission
сертификация; ручные разделы остальных компонентов ещё требуют сверки.


На `753f67c` backend [run 34104984521](https://github.com/RootOne1337/sphere-platform/actions/runs/34104984521)
прошёл все jobs, включая Tests/Lint/Security/Alembic/static RLS. Android
[run 34104984710](https://github.com/RootOne1337/sphere-platform/actions/runs/34104984710)
также успешен. Сохранены [backend](evidence/ci-753f67c-backend.json) и
[Android](evidence/ci-753f67c-android.json) snapshots конкретного code head;
последующий documentation CI gate требует собственного прогона.

На `788a625` [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34131800743)
и [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34131800736)
прошли полностью. Снимки: [backend](evidence/ci-788a625-backend.json),
[Android](evidence/ci-788a625-android.json). Следующий снимок ниже включает startup/cancellation fixes.

На финальном code revision `87092d2` [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34133092803)
прошёл Tests, Lint, Security, RLS static coverage и Alembic; [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34133092736)
прошёл сборку APK и unit tests. Сохранены [backend snapshot](evidence/ci-87092d2-backend.json)
и [Android snapshot](evidence/ci-87092d2-android.json). Это проверка указанного кода;
последующие documentation commits имеют собственные PR checks. Preview guard прошёл,
сам deployment был пропущен. APK на физическом устройстве не запускался.

Отдельный [dependency review](DEPENDENCY-REVIEW.md#github-alert-triage--7-september-2026)
фиксирует 137 manifest-level alerts основной ветки и границы применимости к этой
ветке. Critical Handlebars относится к dev dependency; HTTP exploit не доказан.
Frontend production dependencies, npm/Gradle/container проверка остаются открыты.

На `5d2f331` (frontend session + SQL refresh fixes, до MFA consumption fix) успешно
завершены [backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175292665),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175292639)
и [Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34175292637).
Снимки: [backend](evidence/ci-5d2f331-backend.json),
[frontend](evidence/ci-5d2f331-frontend.json), [Android](evidence/ci-5d2f331-android.json).
Frontend проверяет 198 tests, tsc, production build и Linux standalone entry point.
Это не проверка настоящего browser/APK runtime; следующий code head требует своих checks.

На `3630a63` (включая AUD-53) все code checks успешны:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662279),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662261),
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34175662252).
Сохранены [backend snapshot](evidence/ci-3630a63-backend.json),
[frontend snapshot](evidence/ci-3630a63-frontend.json) и
[Android snapshot](evidence/ci-3630a63-android.json). Preview guard успешен, deployment
пропущен. Проверено существование 151 локальной Markdown-ссылки в восьми актуализируемых
руководствах/отчётах; это не означает проверки всего содержания всех документов проекта.
Последующий documentation commit имеет собственные checks; этот snapshot относится
к точной проверенной ревизии кода. Контракт браузерной сессии описан отдельно в
[frontend-sessions.md](../../security/frontend-sessions.md).

На `1b9fce4` (предыдущий documentation head) полностью прошли
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34176043929),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34176043928) и
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34176043952).
RLS code head `297bb01` также полностью прошёл
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030440),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030378) и
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34212030360).
Снимки: [backend](evidence/ci-297bb01-backend.json),
[frontend](evidence/ci-297bb01-frontend.json), [Android](evidence/ci-297bb01-android.json).
Linux CI: **1170 passed, 4 warnings / 67,90%**; локальный Windows прогон:
**1170 passed / 67,94%**. Оба проходят неизменный 65% gate. Backend Actions
сообщает Node 20→24 deprecation warnings у прежних action versions; их обновление
остаётся отдельной CI задачей. Последующий documentation commit запускает свои
checks и не меняет проверенный код. PR остаётся draft без независимого review;
merge/deploy не выполнены.

Code head `063a9d5` (AUD-55 и AUD-56) полностью прошёл
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757065),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757456) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34252757061).
Сохранены [backend](evidence/ci-063a9d5-backend.json),
[frontend](evidence/ci-063a9d5-frontend.json) и [Android](evidence/ci-063a9d5-android.json)
snapshots. Linux: **1192 passed / 67,95%**; Windows: **1192 passed / 67,99%**,
по четыре warnings, неизменный coverage gate 65% пройден. 22 новых cases используют
реальные runtime LOGIN credentials: 16 DB-session проверок и шесть ASGI/audit-writer
проверок. Весь набор из 320 PostgreSQL/Redis cases не является полной
runtime-role suite. После локального прогона не осталось тестовых LOGIN-ролей
`audit_runtime_user_*` и их соединений. Preview guard успешен, deployment пропущен.
Documentation-only snapshot запускает свои checks; код с указанной ревизии не менялся.


На code head `d828a62` (AUD-57) завершены
[backend CI, попытка 2](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838423/attempts/2),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838431) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34282838503).
Сохранены compact snapshots: [backend](evidence/ci-d828a62-backend.json),
[frontend](evidence/ci-d828a62-frontend.json), [Android](evidence/ci-d828a62-android.json).
[Linux повтор](evidence/ci-d828a62-attempt2-tests.txt): **1214 passed / 67,99%**;
Windows: **1214 passed / 67,95%**, включая 342 PostgreSQL/Redis cases, четыре warnings.
Первый CI отказ и неизменённый порог DAG benchmark описаны выше. Повтор не менял
код, тест или gate. Это не доказывает стабильность latency под будущей нагрузкой.
Preview guard завершился успешно, deploy пропущен. После локального прогона осталось
ноль temporary runtime LOGIN roles и ноль их соединений. PR #19 остаётся draft;
merge/deployment не выполнялись. Последующий commit добавляет только документацию
и сохранённые CI evidence, его проверки относятся к новой ревизии.


Проверка AUD-58–60 на code head `bd7ad7a`: локально **1251 passed / 68,48%**,
включая **379 PostgreSQL/Redis cases**, четыре прежних warnings, неизменный gate 65%.
[Общий вывод](evidence/combined-suite-current.txt). Три дефекта имеют отдельные
атомарные commits и before/after evidence. 37 новых cases: 18 bootstrap/function
boundary, 16 ASGI agent auth/reconnect/failure и три enrollment-key race.
Ruff (включая новую migration), Bandit gate и generated API check проходят.
Новая revision применена только к выделенной audit-БД; временных runtime LOGIN
ролей и соединений после прогона осталось ноль. 227 локальных Markdown targets
в десяти руководствах существуют; это не утверждение о проверке всего содержания.


Code head `bd7ad7a` полностью прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111441),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111373) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34288111362).
Снимки: [backend](evidence/ci-bd7ad7a-backend.json),
[frontend](evidence/ci-bd7ad7a-frontend.json), [Android](evidence/ci-bd7ad7a-android.json).
[Linux test summary](evidence/ci-bd7ad7a-tests.txt): **1251 passed / 68,44%**;
Windows: **1251 passed / 68,48%**. Четыре warnings, неизменный gate 65% пройден.
Preview guard успешен, deploy пропущен. Независимых PR reviews пока нет; PR остаётся
open draft. Следующий документационный commit сохраняет доказательства и запускает
свои checks; перечисленные результаты относятся к указанной ревизии кода.


Локальная проверка AUD-61: **1266 passed / 68,71%**, включая **394 PostgreSQL/Redis cases**; четыре прежних warnings, gate 65% сохранён. После общего прогона усилен guard тестового ACK callback: caught AssertionError не может дать ложный pass; повторены все 47 связанных cases. Production code после общего прогона не менялся. Ruff, Bandit (0 Medium/High) и API schema/catalog check прошли. Результаты GitHub для точной ревизии приведены ниже.


Code head `f272360` (AUD-61) полностью прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705525),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705438) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705527).
Сохранены [backend](evidence/ci-f272360-backend.json),
[frontend](evidence/ci-f272360-frontend.json) и [Android](evidence/ci-f272360-android.json)
snapshots. [Linux summary](evidence/ci-f272360-tests.txt): **1266 passed / 68,65%**;
Windows: **1266 passed / 68,71%**, четыре warnings; неизменный 65% gate пройден.
Все 15 новых cases входят в CI. Preview guard успешен, deploy пропущен. Временных
runtime LOGIN-ролей и соединений после локальных прогонов осталось ноль. Проверены
222 локальные Markdown-ссылки в 11 руководствах перед добавлением CI-снимков.
Независимых PR reviews нет; PR остаётся draft. Следующий documentation-only commit
сохраняет результаты и запускает собственные checks; production code не меняется.


Code head `d642273` (AUD-62) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906033),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906010) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906047).
Снимки: [backend](evidence/ci-d642273-backend.json),
[frontend](evidence/ci-d642273-frontend.json), [Android](evidence/ci-d642273-android.json).
[Linux summary](evidence/ci-d642273-tests.txt): **1300 passed / 68,77%**;
Windows: **1300 passed / 68,80%**, включая **428 PostgreSQL/Redis cases**, четыре
warnings. Неизменный 65% gate пройден. Новая миграция и все 34 user-bootstrap cases
проверены в CI. Preview guard успешен, deploy пропущен. После локальных тестов
временных runtime LOGIN-ролей и соединений ноль. PR остаётся draft без независимого
review; production grants/cutover не выполнялись. Следующий документационный commit
сохраняет эти результаты и запускает собственные checks, не меняя production code.


Локальная проверка AUD-63–64: **1322 passed / 69,30%**, включая **450 PostgreSQL/Redis cases**; четыре прежних warnings, неизменный 65% gate. Общий прогон занял 253,67 s. 12 новых PC tenant cases и 10 protocol cases входят в этот прогон. Ruff, Bandit (0 Medium/High) и generated API check прошли. Проверены 230 локальных Markdown targets в семи затронутых руководствах. Результат точной GitHub code revision приведён ниже; локальный pass не заменяет CI или реальные OS/ADB/LDPlayer/device измерения.


Code head `eda33a7` (AUD-63–64) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128767),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128758) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128765).
Сохранены [backend](evidence/ci-eda33a7-backend.json),
[frontend](evidence/ci-eda33a7-frontend.json) и [Android](evidence/ci-eda33a7-android.json)
snapshots. [Linux summary и все 22 новых PC cases](evidence/ci-eda33a7-tests.txt):
**1322 passed / 69,27%**, 264,00 s; Windows: **1322 / 69,30%**, включая **450
PostgreSQL/Redis cases**, четыре warnings. Порог 65% сохранён; lint/mypy, dependency
security, RLS и миграции прошли. Preview guard успешен, deploy пропущен. Временных
локальных runtime LOGIN-ролей и соединений ноль. Документационный commit сохраняет
эти результаты и запускает собственные checks; production code после `eda33a7`
не меняется. PR остаётся draft без независимого review; OS/ADB/LDPlayer/APK/network
и нагрузка 10–64 не объявлены проверенными. Merge/deployment не выполнялись.


Локальная проверка AUD-65–66: **1334 passed / 69,31%**, включая **453 PostgreSQL/Redis
cases**, четыре прежних warnings, 262,84 s; строгий порог 65% сохранён. Девять новых
PC lifecycle cases и три новых Redis unknown-command cases входят в общий прогон.
После удаления неиспользуемого import повторены все 13 protocol cases; исполняемая
логика после полного прогона не менялась. Ruff, generated API export и Bandit для
обоих изменённых PC modules (0 Medium/High) прошли. 246 локальных Markdown targets
существуют. GitHub CI для новой code revision проверяется отдельно; реальные
listeners/OS/process/10–64-device измерения этим результатом не подтверждаются.


Code head `8692a58` (AUD-65–66) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387311587),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387311505) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387314911).
Сохранены [backend](evidence/ci-8692a58-backend.json),
[frontend](evidence/ci-8692a58-frontend.json) и [Android](evidence/ci-8692a58-android.json)
snapshots. [Linux summary, 12 новых cases и исправленный backoff test](evidence/ci-8692a58-tests.txt):
**1334 passed / 69,27%**, 266,92 s; Windows: **1334 / 69,31%**, включая **453
PostgreSQL/Redis cases**, четыре прежних warnings. Порог 65% сохранён; lint/mypy,
security, RLS и миграции прошли. Preview guard успешен, deploy пропущен. Временных
локальных runtime LOGIN-ролей и соединений ноль. Документационный commit сохраняет
результаты и запускает собственные checks; исполняемый код после `8692a58` не
меняется. PR остаётся draft без независимого review, merge или deployment. Реальные
PC/APK sockets, OS/subprocess и нагрузка 10–64 устройств не объявлены проверенными.


### AUD-68 — High: development launcher сообщал успех после неудачного старта

- **Root cause:** `docker info/build/up` проверялись как PowerShell exceptions,
  хотя native CLI возвращает ненулевой exit code. Результаты двух health waits
  отбрасывались, container names были привязаны к одному project. Backend/frontend
  в full Compose вообще не имели health probes; missing `.env` копировался и запуск
  продолжался без заполнения конфигурации.
- **Evidence/reproduction:** [10 failing launcher cases](evidence/dev-launcher-before.txt)
  выполняют настоящий `start-dev.ps1` в дочернем PowerShell, в отдельной копии пути
  с пробелами, подставляя Docker CLI как Python process с exit 17. Ошибки info,
  config, build, up и readiness дают ложный успех до исправления. Ещё [7 failing
  probe cases](evidence/dev-readiness-before.txt) обнаруживают отсутствие healthchecks
  в реальном `docker compose config` merge. Docker daemon/services не запускались.
- **Affected files:** `scripts/start-dev.ps1`, `docker-compose.full.yml`;
  `tests/deployment/test_dev_launcher.py`, `tests/deployment/test_dev_readiness.py`.
- **Fix:** `7d47c61` — явная проверка native exit code; quiet config до build/up; обязательная
  подготовка созданного `.env`; `up --wait --wait-timeout` вместо fixed-name inspect.
  Backend проверяет `/api/v1/health/readyz` и ready body; frontend — HTTP 200 `/login`,
  с network timeout и отказом на redirect. Failed startup сохраняет containers/volumes
  для диагностики. Default wait — 180 s, параметр `-ReadyTimeoutSec`.
- **Regression:** [25 deployment tests passed](evidence/dev-launcher-after.txt),
  включая 17 новых. Probe expressions исполняются реальными Python/Node processes
  с подменой только HTTP boundary: ready/unready/network failure и 200/302/503.
  PowerShell subprocess tests проверяют exit status, прекращение последующих шагов,
  config-before-up и отсутствие fixed container lookup. CI требует pwsh/Node/Docker,
  при отсутствии в CI тесты падают, а не молча пропускаются.
- **Residual risk:** тесты не являются реальным Docker failure drill. Ready endpoint
  не проверяет Alembic head/runtime grants/задачи/WS, `/login` не проверяет браузерные
  операции, остальные services без probes требуют только running. Wait timeout не
  ограничивает build/pull/зависший Docker CLI. Старые `-Tunnel`, `-Down`, `-Status`
  не входят в исправленный startup path. Full recipe остаётся development; подробный
  [startup contract](../../operations/STARTUP.md) не обещает production autostart.


## Эксплуатационный срез 10 сентября 2026

AUD-67 (`f99a310`) исправляет APK retry pacing/jitter. AUD-68 (`7d47c61`)
исправляет ложный development startup success. Общий локальный прогон после этих
изменений: **1351 passed / 69,32%**, 273,07 s, включая **453 PostgreSQL/Redis**
и **25 deployment** cases, четыре прежних warnings. Coverage gate 65% сохранён.
Android enterprise JVM suite: **347 passed**, 27 suites; before/after evidence
хранится отдельно. Ruff 0.15.2 и API schema/catalog check проходят. Старый Ruff
0.3.0 из backend test dependencies сообщает E721 в неизменённом exact-int check;
CI использует отдельный новый Ruff, guard против bool→int не ослаблялся.

[README](../../../README.md), [documentation index](../../README.md), runbooks,
[operational matrix](../../operations/READINESS.md) и
[AI readiness assessment](../../architecture/AI-READINESS.md) описывают текущие
контракты и ограничения. Monitoring wiring и synthetic VPN metrics зафиксированы
как открытые пробелы. LAN primary/saved secondary/optional GitHub — направление
будущего изменения, а не существующий резервный канал. AI не внедряется.

Ревизия **`769aec3`**, включающая оба исправления, прошла с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34407474578),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34407474747) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34407474584).
Сохранены [backend](evidence/ci-769aec3-backend.json),
[frontend](evidence/ci-769aec3-frontend.json), [Android](evidence/ci-769aec3-android.json)
и [preview](evidence/ci-769aec3-preview.json) snapshots.
[Linux summary и все 17 новых случаев](evidence/ci-769aec3-tests.txt):
**1351 passed / 69,27%**, 252,65 s, четыре прежних warnings. Backend lint/mypy,
security, RLS и миграции успешны. Preview guard успешен, deployment skipped.
Временных runtime SQL-ролей и оставшихся тестовых соединений ноль.

Этот documentation-only commit сохраняет результаты и запускает собственные checks;
исполняемый код после `769aec3` не меняется. PR остаётся draft без независимого
review, merge и deployment. Runtime APK/OS/браузера, реальный Docker restart,
аппаратная нагрузка и incident ingestion не объявлены проверенными.


### AUD-69 — High: потеря refresh-ответа навсегда расходовала единственный device credential

- **Root cause:** сервер заменял единственный refresh hash при commit, до доставки
  HTTP response. Retry исходного токена всегда получал 401. SQL rollback был покрыт,
  но успешный commit с неизвестным результатом клиенту — нет.
- **Evidence:** [baseline](evidence/device-refresh-recovery-before.txt), 7 failures /
  9 controls. Transport выполняет фактический ASGI request до commit и теряет ответ;
  новая runtime SQL session получает отказ. Дополнительные cases моделируют lost
  commit acknowledgement после реального commit и наблюдают pg_stat_activity Lock
  waiters при одновременных HTTP requests.
- **Affected files:** `backend/services/device_registration_service.py`,
  `backend/api/v1/devices/router.py`, `backend/schemas/device_register.py`,
  `backend/models/device.py`, `alembic/versions/20260910_device_refresh_retry.py`.
- **Fix:** `83585d3` — необязательный UUID `X-Refresh-Request-Id`, одна previous-hash/ID-hash
  receipt на device, восстановление того же HKDF-SHA256 refresh-преемника из исходного
  секрета/ID/context. Retry не продлевает refresh expiry; JWT выпускается свежий.
  RLS lookup возвращает только tenant; row lock и повторная expiry-проверка после
  ожидания сохраняют актуальность. Re-enrollment блокирует Device и очищает receipt.
- **Regression:** 24 новых cases в `test_device_refresh_recovery.py`; [43 related
  passed](evidence/device-refresh-recovery-after.txt). SQL non-owner, pool restart,
  commit/abort/lock races, разные ID, активность/expiry/re-enrollment, tenant/device
  scope, hash-only denial, migration/grant rollback и actual ASGI WS auth/reconnect.
- **Residual risk:** нужен rollout migration→все workers→APK; old clients остаются
  одноразовыми. Recovery действует лишь до expiry/consumption/re-enrollment преемника,
  не восстанавливает ранее потерянные legacy операции. Устройство с украденными
  bearer+ID не отличимо без attestation. Нет доказательства real APK/network/OS load.
  [Полный контракт и rollback](../../security/device-refresh-recovery.md).

### AUD-70 — High: APK терял refresh intent при crash и применял устаревшие credentials

- **Root cause:** refresh не имел persist-before-send операции; `apply()` credentials
  не гарантировал диск до следующей ротации. Reply записывался без проверки, не
  заменены/очищены ли credentials за время HTTP; catch возвращал захваченный старый token.
- **Evidence:** [7 failing JVM cases](evidence/android-refresh-recovery-before.txt),
  включая разделённые disk/memory preferences, loss→recreation, failed commit,
  concurrent re-enrollment/clear. HTTP interceptor не использует сеть.
- **Affected files:** `android/.../store/AuthTokenStore.kt`,
  `android/.../store/RefreshRecoveryTest.kt`, прежняя preference fixture в
  `AuthTokenStoreTest.kt` теперь явно поддерживает успешный commit.
- **Fix:** `484cca6` — UUID intent синхронно сохраняется на IO перед HTTP, повторяет commit при
  каждой попытке, передаётся в новый header. Сохранение пары credentials и удаление
  intent — одна edit. Смена auth state и проверка reply сериализованы; stale reply
  не перезаписывает новые credentials. При ошибке возвращается текущее состояние.
- **Regression:** [354 tests / 28 suites, 0 failures/errors/skips](evidence/android-refresh-recovery-summary.json),
  [полный Gradle run](evidence/android-refresh-recovery-after.txt). Семь новых cases
  проверяют durability ordering и stale replies; остальные 347 сохранились.
- **Residual risk:** SharedPreferences/HTTP boundaries — doubles; фактическое падение
  Android процесса/keystore/disk и сотни APK пока не проверены. Старый backend не
  обеспечивает recovery. Blocking HTTP cancellation/timeout остаётся отдельной работой;
  initial enrollment durability и одновременная смена server origin этим fix не закрыты.


## Проверка AUD-69/70 — 10 сентября 2026

После backend `83585d3` и APK `484cca6`: общий локальный прогон **1375 passed**,
coverage **69,35%**, 275,04 s, четыре прежних warnings. Включены **477 PostgreSQL/Redis**
и **25 deployment** cases. Coverage gate 65% сохранён. Android — **354 tests / 28
suites**, без failures/errors/skips. Ruff 0.15.2, API export check и backend Bandit
(0 Medium/High) проходят. [Локальный dependency-aware mypy без incremental cache](evidence/device-refresh-local-mypy.txt)
сообщил 13 ошибок в семи неизменённых файлах/импортах; это не проходящий локальный gate. Отдельный CI mypy
запускается в собственном окружении без полного dependency set, его результат
должен учитываться отдельно. Результат новой CI revision приведён ниже.

Миграция применена только к выделенному loopback audit PostgreSQL. Downgrade/upgrade
новой миграции проверены в транзакции с rollback: текущие grants и данные сохраняются
после теста; production не изменялся. API documentation отражает optional UUID header.
Runtime OS/network/keystore/process-death и fleet capacity не измерены; reserve route
и hard cancellation deadline refresh остаются следующими эксплуатационными задачами.


Code revision **`9177769`** с AUD-69/70 прошла attempt 1:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34416514477),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34416514436),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34416514460)
и отдельный [Android push run](https://github.com/RootOne1337/sphere-platform/actions/runs/34416509416).
[Linux excerpt](evidence/ci-9177769-tests.txt): **1375 passed / 69,30%**, 233,43 s,
четыре прежних warnings; все 24 новых SQL/ASGI случая проходят. Backend lint/mypy,
security, RLS coverage и Alembic успешны. CI mypy не заменяет отражённый выше локальный
dependency-aware результат. Preview guard прошёл, deployment skipped.

Сохранены snapshots [backend](evidence/ci-9177769-backend.json),
[frontend](evidence/ci-9177769-frontend.json), [Android PR](evidence/ci-9177769-android.json),
[Android push](evidence/ci-9177769-android-push.json) и [preview](evidence/ci-9177769-preview.json).
После локального прогона runtime SQL-ролей и соединений — ноль, migration head —
`20260910_device_refresh_retry`. Этот документационный commit фиксирует результат;
исполняемый код после `9177769` не меняется, его собственные checks идут отдельно.
PR остаётся draft; review, merge, production migration и deployment не выполнены.

## AUD-71 — High: зависший APK refresh задерживал stop/reconnect и сохранял ответ после отмены

**Эксплуатационный приоритет P0.** При зависании refresh HTTP вызовы reconnect,
OTA/log workers ожидали общий token mutex дольше заявленного дедлайна. Остановка
вызывающей coroutine тоже ждала HTTP; поздний ответ мог менять credentials после отмены.

- **Root cause:** `withTimeout(10_000)` оборачивал `withContext(IO)` с блокирующим
  `OkHttp.execute()`/чтением body. Отмена coroutine не вызывала `Call.cancel()`, а
  structured concurrency ждала завершения IO. `catch(Exception)` поглощал также
  `CancellationException`. Запись credentials происходила внутри блокирующей операции,
  до проверки отмены при возврате из IO. Общий HTTP client имеет read timeout 60 s,
  который не равен end-to-end deadline и не ограничивает всю длительность ответа.
- **Evidence/reproduction:** baseline `eb22477` + первые пять regression tests:
  [4 failures / 1 passing control](evidence/android-refresh-cancellation-before-summary.txt),
  [Gradle output](evidence/android-refresh-cancellation-before.txt). Interceptor
  удерживает headers до latch release; через 12 s refresh ещё не вернулся. Stop
  не завершился за 1 s. Отменённое чтение body после release заменило parent на
  child token. Внешний timeout позволил исполнить код после `getFreshToken()`.
  Отмена mutex waiter не повреждала первый запрос — passing control.
- **Affected files:**
  [`AuthTokenStore.kt`](../../../android/app/src/main/kotlin/com/sphereplatform/agent/store/AuthTokenStore.kt),
  [`RefreshCancellationTest.kt`](../../../android/app/src/test/kotlin/com/sphereplatform/agent/store/RefreshCancellationTest.kt).
- **Fix:** `fec0c5f` — `enqueue` + `suspendCancellableCoroutine`, cancellation handler отменяет
  конкретный Call. Собственный 10 s deadline возвращает stored token, внешняя
  cancellation пробрасывается. Per-call HTTP timeout не меняет shared WS client.
  Callback закрывает bounded body и возвращает только parsed values; активная
  coroutine проверяет cancellation и credentials перед edit. Pending ID сохраняется,
  поэтому следующий вызов восстанавливает прежнюю операцию через AUD-69/70.
- **Regression:** восемь новых случаев, включая три дополнительных controls для
  invalid JSON, oversized body и missing rotation token. Проверяются настоящий
  `Call.isCanceled`, возврат при удерживаемых headers, same-ID retry, поздний body,
  caller timeout, один refresh для 64 ожидающих вызовов с отменённым waiter и закрытие
  body при ошибках. [362 tests / 29 suites, 0 failures/errors/skips](evidence/android-refresh-cancellation-summary.json),
  [полный прогон](evidence/android-refresh-cancellation-after.txt). В том числе все
  семь прежних recovery cases. Deadline case занял 10,009 s в локальном JVM run;
  это время одного теста, не Android SLO. Reproduce из `android/`:
  `./gradlew --no-daemon :app:testEnterpriseDebugUnitTest --tests '*RefreshCancellationTest'`.
- **Residual risk:** transport/Source и preferences — управляемые doubles; нет
  нового listener, Android OS/сокетов или аппаратного парка. Очередь mutex находится
  до собственного deadline, блокирующий disk/keystore commit не становится
  прерываемым. Начавшаяся preference edit не откатывается при одновременной отмене.
  Нестандартный interceptor/Source может игнорировать cancel и удерживать HTTP thread,
  но не refresh mutex. Отмена не гарантирует server rollback — для uncertain commit
  необходим прежний recovery-протокол. LAN reserve route, expiry/enrollment loss и
  реальные OS/load drills остаются отдельными P0 задачами.

Backend/PC/SQL/schema этим изменением не менялись; последний их локальный общий
прогон — **1375 / 69,35%** на AUD-69/70, отдельно от текущего Android run.

### Проверка ревизии `fec0c5f` с AUD-71

Все CI runs прошли с первой попытки:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34418225844),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34418225854),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34418225845),
[Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34418223069).
Linux backend — **1375 passed / 69,30%**, 279,86 s, четыре прежних warnings;
[excerpt](evidence/ci-fec0c5f-tests.txt) включает все 24 SQL refresh-recovery cases.
Lint/mypy в окружении CI, security, RLS coverage и Alembic прошли. Ранее описанные
13 ошибок локального dependency-aware mypy этим результатом не закрываются.

Android CI выполнил [все четыре test tasks](evidence/ci-fec0c5f-android-tests.txt):
Dev/Enterprise × Debug/Release. Per-case count **362 / 29 suites** относится к
локальному EnterpriseDebug XML, а не к аппаратному парку. Preview guard прошёл,
deployment skipped. Снимки: [backend](evidence/ci-fec0c5f-backend.json),
[frontend](evidence/ci-fec0c5f-frontend.json), [Android PR](evidence/ci-fec0c5f-android.json),
[Android push](evidence/ci-fec0c5f-android-push.json), [preview](evidence/ci-fec0c5f-preview.json).
Документационный commit сохраняет эти результаты, не меняя исполняемый код;
его checks идут отдельно. PR остаётся draft, без независимого review, merge или deployment.


## AUD-72 — High: transport open выдавал ложный connected, поздние callbacks переживали сеанс

**Эксплуатационный приоритет P0; предпосылка оценки резервного маршрута.** APK
запускал `onConnected` и повторную отправку результатов сразу после `onOpen`, до
проверки identity сервером. Silent auth переставал ограничиваться handshake deadline.
Завершившаяся попытка сохраняла generation до следующего reconnect, поэтому во
время backoff поздние callbacks могли включить connected или передать команды.

- **Root cause:** `connected.complete(Unit)` находился в `onOpen`; backend не
  отправлял явного auth acknowledgement. `finally` очищал поля, но не инвалидировал
  generation. После добавления ожидания ACK нужно также сохранять auth close codes
  и первую terminal completion, включая callbacks до запуска coroutine cleanup.
- **Evidence/reproduction:** baseline `5204e1f` + первые regression tests:
  [Android 10 failures / 2 controls](evidence/android-auth-ack-before.txt),
  [backend 5 failures / 3 controls](evidence/backend-auth-ack-before.txt).
  JVM вызывает настоящие loop/listeners с virtual time: transport open без ACK,
  тишина после open, неверный device/version, команда до ACK, callback во время
  backoff. ASGI с реальным non-owner SQL проверяет первый server frame и немедленную
  публикацию команды при регистрации socket; при потере ACK registry не должен меняться.
- **Affected files:** `backend/api/ws/android/router.py`,
  `android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt`,
  `tests/production/test_agent_tenant_runtime.py`, новый
  `android/app/src/test/kotlin/com/sphereplatform/agent/ws/WebSocketAuthenticationTest.kt`;
  прежние `WebSocketLifecycleTest.kt` fixtures теперь подтверждают авторизацию.
- **Fix:** `70c6a21` — backend отправляет `auth_ok` с device ID и числовой protocol version 1
  после авторизации/закрытия DB session, до публикации соединения. Отправка ограничена
  5 s; при ошибке registry не меняется. APK разрешает application traffic и
  однократный `onConnected` только после корректного ACK. Общий WS deadline 20 s
  охватывает ACK; close-коды авторизации сразу запускают прежний refresh path.
  Ended generation инвалидируется до backoff; первая failure completion не может
  стать успешной от позднего ACK даже до coroutine cleanup.
- **Дополнительное воспроизведение:** [callback внутри `socket.cancel()`](evidence/android-auth-ack-cleanup-before.txt)
  передал одну команду в уже останавливаемый handler. Перенос invalidation перед
  внешним transport teardown устраняет окно; отдельный regression сохранён.
- **Regression:** итоговые 16 новых JVM и восемь SQL/ASGI cases.
  [378 tests / 30 suites](evidence/android-auth-ack-summary.json),
  [полный Gradle output](evidence/android-auth-ack-after.txt);
  [48 связанных backend auth/refresh cases](evidence/backend-auth-ack-after.txt).
  `./gradlew --no-daemon :app:testEnterpriseDebugUnitTest --tests '*WebSocketAuthenticationTest'`
  из `android/`; backend — `pytest tests/production/test_agent_tenant_runtime.py -k auth_ack`
  с изолированными runtime credentials по README harness.
- **Residual risk:** ACK подтверждает identity, не readiness всех services/SQL result
  commit. Обязателен rollout **все backend workers → APK**; rollback в обратном
  порядке. Старый сервер без ACK не подключит новый клиент. Старый audited APK
  отклоняет неизвестный frame с parser warning и сохраняет ранний connected до
  своего обновления. Delivery/registry/heartbeat и Android WS — doubles; actual
  APK sockets/OS/fleet/latency не проверены. Post-auth setup failures, общий budget
  reconnect, запасной route и local discovery остаются отдельной работой.
  [Полный wire/rollout contract](../../architecture/ANDROID-CONNECTION-PROTOCOL.md).

Локальный полный прогон: **1383 passed / 69,39%**, 281,40 s, четыре прежних warnings;
включает **485 PostgreSQL/Redis** и 25 deployment cases. Load/soak исключены.
[Лог](evidence/auth-ack-combined-suite.txt). Ruff и API export check прошли;
[Bandit по существующей `.bandit` конфигурации](evidence/auth-ack-bandit.txt) —
0 Medium/High. [Dependency-aware mypy](evidence/auth-ack-local-mypy.txt) повторён:
те же 13 ошибок в семи неизменённых файлах; локальный gate не объявлен проходящим.
Schema head не менялся; merge/deployment не выполнялись, PR остаётся draft.

### Проверка ревизии `70c6a21` с AUD-72

Все CI runs прошли с первой попытки:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34463225417),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34463225399),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34463225418),
[Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34463221343).
Linux backend — **1383 passed / 69,34%**, 298,47 s, четыре прежних warnings;
[excerpt](evidence/ci-70c6a21-tests.txt) включает все восемь новых SQL/ASGI auth-ack
cases. Lint/mypy в окружении CI, security, RLS coverage и Alembic прошли. Это не
закрывает 13 ошибок локального dependency-aware mypy, указанных выше.

Android CI собрал debug APK и выполнил [все четыре test tasks](evidence/ci-70c6a21-android-tests.txt):
Dev/Enterprise × Debug/Release. Счётчик **378 / 30 suites** относится к локальному
EnterpriseDebug XML. Это не проверка установленного APK, Android OS или нагрузки
парка. Preview guard прошёл, deployment skipped. Снимки:
[backend](evidence/ci-70c6a21-backend.json), [frontend](evidence/ci-70c6a21-frontend.json),
[Android PR](evidence/ci-70c6a21-android.json), [Android push](evidence/ci-70c6a21-android-push.json),
[preview](evidence/ci-70c6a21-preview.json). Локальная очистка подтверждена отдельно:
[0 временных runtime LOGIN-ролей и 0 других DB connections](evidence/auth-ack-runtime-cleanup.json).

Документационный commit сохраняет результаты для точной code revision `70c6a21`,
не меняя исполняемый код; его checks идут отдельно. Резервный маршрут остаётся
открытым P0. PR остаётся draft, без независимого review, merge или deployment.


## AUD-73 — High: discovery терял связь после enrollment и переживал остановку сервиса

**Эксплуатационный P0: существующий канал обновления адреса, без нового failover.**
После enrollment/refresh watchdog отправлял device JWT как `X-API-Key`; config
endpoint отклонял его с 401. При outage десятки сигналов запускали отдельные запросы.
`stop()` менял только boolean; поздний ответ мог заменить локально выбранный URL и
вызвать reconnect после остановки сервиса. Blocking HTTP не отменялся вместе с
coroutine; `body.string().take(64 KiB)` читал весь ответ и принимал валидный префикс.

- **Root cause:** смешение device JWT и config API key, `execute()` вне cancellable
  bridge, независимые application-scope jobs без single-flight/владельца и отсутствие
  проверки revision перед записью адреса. Ограничение body применялось после чтения.
- **Evidence/reproduction:** baseline `02f55b4` + constructor seam для изолированного
  client/URL, без изменения алгоритма до запуска tests: [9 failures / 4 controls](evidence/android-config-recovery-before-summary.json),
  [Gradle](evidence/android-config-recovery-before.txt). Реальный OkHttp с synthetic
  interceptors: 64 уведомления породили 64 запроса; held headers не отпустили caller
  за 12 s; stop не отменил Call; поздний JSON перезаписал локально выбранный адрес.
  [Два non-owner SQL/ASGI cases](evidence/backend-config-recovery-contract.txt)
  подтверждают issued/refreshed JWT: старый request 401, публичный request 200,
  прежняя identity по-прежнему получает WS `auth_ok`. Это серверный contract control,
  он проходит до и после APK fix; backend permissions не меняются.
- **Affected files:** `ZeroTouchProvisioner.kt`, `ConfigWatchdog.kt`, `AuthTokenStore.kt`;
  suspend call sites в `SetupActivity.kt` / `AutoEnrollmentWorker.kt` и fixtures
  `KeepAliveWorkerTest.kt`; новый `ConfigRecoveryTest.kt`, два cases в
  `tests/production/test_agent_tenant_runtime.py`.
- **Fix:** `e68ec0a` — discovery без credentials; async OkHttp bridge с отменой Call и собственным
  10 s budget, ограниченное чтение HTTP body и валидация URL. Один periodic owner и
  одна активная проверка; stop/отмена owner закрывают поколение и принудительный job.
  Store snapshot включает локальную revision; сравнение и запись сериализованы с
  обычным `saveServerUrl`, включая A → B → A. Только принятый response вызывает reconnect.
- **Regression:** 21 новый Android case, в том числе late body cleanup, service
  restart, duplicate owner, cancellation periodic owner и ABA. [399 passed / 31 suites](evidence/android-config-recovery-summary.json),
  [полный Gradle run](evidence/android-config-recovery-after.txt). Воспроизведение:
  `./gradlew --no-daemon :app:testEnterpriseDebugUnitTest --tests '*ConfigRecoveryTest'`
  из `android/`; SQL contract — `pytest tests/production/test_agent_tenant_runtime.py -k discovery`
  по README изолированного harness.
- **Residual risk:** Robolectric/HTTP interceptors/preferences doubles, не реальный
  APK/OS/сокеты или ёмкость парка. 64 сигнала одного watchdog не равны 64 устройствам.
  Некооперативный HTTP Source может переживать cancel в своём thread, без права
  записи route. Disk/keystore и legacy file reading не входят в HTTP deadline.
  Revision процесса не является durable/server config version. Синтаксически валидный
  недоступный endpoint всё ещё может заменить работающий адрес; health trial/rollback,
  сохранённый secondary route и независимый discovery остаются следующими P0.
  [Полный контракт](../../architecture/ANDROID-DISCOVERY-RECOVERY.md).

Backend code и schema этим изменением не меняются. Новый APK сохраняет прежнее
требование AUD-72: сначала обновить все backend workers. Полный локальный backend/PC
прогон: **1385 passed / 69,42%**, 268,55 s, четыре прежних warnings, включая **487
PG/Redis** и 25 deployment cases. [Лог](evidence/config-recovery-combined-suite.txt).
Ruff 0.15.2 и API export check прошли. [Очистка](evidence/config-recovery-runtime-cleanup.json):
0 временных runtime LOGIN-ролей и 0 других DB connections. Новый dependency-aware
mypy здесь не запускался: последний результат AUD-72 — 13 ошибок в семи неизменённых
файлах. Backend code не менялся. Результаты новой CI ревизии приведены ниже.


### Проверка ревизии `e68ec0a` с AUD-73

Все CI runs прошли с первой попытки:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34466367344),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34466367307),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34466367295),
[Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34466363373).
Linux backend — **1385 passed / 69,36%**, 296,30 s, четыре прежних warnings;
[excerpt](evidence/ci-e68ec0a-tests.txt) включает оба новых discovery contract cases.
Lint/mypy в окружении CI, security, RLS и миграции прошли. CI использует более лёгкое
mypy-окружение, поэтому прежние локальные 13 type errors не объявляются закрытыми.

Android собрал APK и выполнил [четыре test tasks](evidence/ci-e68ec0a-android-tests.txt)
Dev/Enterprise × Debug/Release. Счётчик **399 tests / 31 suites** получен отдельно
из локальных EnterpriseDebug XML. Preview guard успешен, deploy skipped. Снимки:
[backend](evidence/ci-e68ec0a-backend.json), [frontend](evidence/ci-e68ec0a-frontend.json),
[Android PR](evidence/ci-e68ec0a-android.json), [Android push](evidence/ci-e68ec0a-android-push.json),
[preview](evidence/ci-e68ec0a-preview.json). Все snapshot SHA совпадают с `e68ec0a`.

Документационный commit сохраняет результаты этой code revision; его checks идут
отдельно, исполняемый код не меняется. PR остаётся draft без независимого review,
merge или deployment. Saved-secondary/health-trial и реальный APK/fleet recovery
остаются открытыми; это не подтверждение production readiness.


## AUD-74 — High: APK оставался на недоступном адресе и терял рабочий LAN route

**Эксплуатационный P0: сохранить управление без переустановки и GitHub discovery.**
Связь зависела от одного `server_url`; резерв из JSON не доходил до WS/refresh.
Discovery заменял рабочий адрес до проверки, а registration мог подменить
доступный LAN URL недоступным public URL из response.

- **Root cause:** store хранил только выбранный URL; WS и refresh независимо читали
  его, без списка кандидатов. Watchdog применял синтаксически валидный URL сразу
  и вызывал reconnect. Registration доверял advertised URL вместо адреса запроса.
  `fallback_server_url` отсутствовал в API schema/генераторе/ProvisionConfig;
  локальный parser требовал `api_key`, а генератор писал `enrollment_api_key`.
- **Evidence/reproduction:** на `9ead4f2` с добавленными regression cases:
  [первые шесть JVM cases — 5 failures / 1 control](evidence/android-saved-routes-before.txt),
  [optional config API — 1 failure / 1 control](evidence/backend-saved-routes-before.txt).
  Для воспроизведения будущего route storage baseline fixtures заполняют synthetic
  primary/fallback preference keys; исходный runtime их не использует.
  Отдельно до соответствующих исправлений:
  [генератор теряет fallback — 1 failure / 1 control](evidence/config-generator-routes-before.txt),
  [APK не читает generated enrollment key — 1 failure](evidence/android-generated-config-before.txt).
  Это проверки реального кода с изолированными HTTP/WS/Android boundaries.
- **Affected files:** Android `AuthTokenStore`, `SphereWebSocketClient`,
  `ConfigWatchdog`, `ZeroTouchProvisioner`, `DeviceRegistrationClient`,
  `SetupActivity`, `AutoEnrollmentWorker`, `KeepAliveWorker`, новый
  `network/ManagementRoute.kt` и MDM resources; backend config router/schema,
  agent-config schema/generator/template, сгенерированный OpenAPI.
- **Fix:** `5f7900e` — primary/fallback сохраняются одной записью с commit; последний выбранный
  адрес остаётся кандидатом. WS выбирает следующий URL после failure, refresh идёт
  через тот же URL с прежним pending operation ID. Только target-bound `auth_ok`
  текущей revision продвигает адрес до connected/result replay. Discovery сохраняет
  кандидатов без разрыва здорового WS. При старте сервиса доступны route-only
  MDM/файл без enrollment key. Registration сохраняет request URL, advertised URL
  становится резервом при отсутствии явного. Поле проходит через API/JSON/MDM/
  генератор; parser принимает оба имени bootstrap key. Derived management clients
  сохраняют pool/dispatcher, применяют загруженные installation pins к маршруту
  и не следуют redirects.
- **Regression tests:** `SavedRouteFailoverTest` — **27 новых JVM cases**, включая
  оба route failures, auth denial, lost/stale ACK, late callback, pending refresh ID,
  process-recreation preference doubles, failed commit, route-only config,
  normalization, TLS pin mapping, generated key и LAN registration. Полный
  [Android run](evidence/android-saved-routes-after.txt):
  [426 tests / 32 suites](evidence/android-saved-routes-summary.json), 0 failures/errors/skips.
  Три новых PostgreSQL/ASGI cases в `test_agent_tenant_runtime.py`: optional field
  и lost post-commit refresh response на primary с повтором через secondary origin,
  тем же child, отказом неверного operation ID и foreign-device WS. Два pure Python
  cases в `test_agent_config_routes.py` проверяют реальный генератор.
- **Residual risk:** два адреса одной установки не дают HA базы/хоста или отдельный
  command transport. Identity/task state и signing keys должны быть общими;
  принадлежность установки до передачи credentials задаётся оператором. Durable
  config version/rollback и несколько HTTP discovery источников не реализованы.
  Active URL `apply()` может потеряться при crash, но сохранённая пара остаётся;
  реальные disk/keystore/process death не эмулируются JVM doubles полностью.
  Не загруженные при bootstrap TLS pins этим fix не появляются. Фоновые enrollment
  paths и потерянный registration response требуют отдельного runtime аудита;
  совместимость generator/parser не доказывает полный запуск клона. Нет live local
  config reload, измеренного OS/network/fleet recovery SLA или resource profile.

### Локальная проверка AUD-74

[Общий Windows прогон](evidence/saved-routes-combined-suite.txt): **1390 passed /
69,38%**, 273,72 s, четыре прежних warnings; **490 PG/Redis** и **25 deployment**
cases включены. Дополнительный [целевой SQL/ASGI набор](evidence/backend-saved-routes-after.txt):
53 passed. Ruff и API export check прошли. [Bandit gate](evidence/saved-routes-bandit.txt):
0 Medium/High. [Dependency-aware mypy](evidence/saved-routes-local-mypy.txt) остаётся
неуспешным: **13 errors / 7 неизменённых файлов**, поэтому полный type-check pass
не заявлен. [Cleanup](evidence/saved-routes-runtime-cleanup.json): migration head
не изменён, временных runtime LOGIN roles и иных соединений к audit DB нет.

[Контракт, настройка и rollout](../../architecture/ANDROID-SAVED-ROUTES.md).
Новая SQL migration не нужна. Все backend маршруты должны поддерживать существующие
ACK/refresh-recovery протоколы до обновления APK. Сохраняются signing identity и
app data. PR остаётся draft; merge, deployment и реальный fleet drill не выполнены.
CI предыдущего `e68ec0a` выше не является проверкой нового AUD-74; его ревизия
и результаты CI фиксируются отдельно после push.


### CI `5f7900e`: успешный backend и воспроизведённая гонка Android test harness

[Backend](evidence/ci-5f7900e-backend.json),
[frontend](evidence/ci-5f7900e-frontend.json) и
[Android push](evidence/ci-5f7900e-android-push.json) прошли с первой попытки.
Linux: **1390 passed / 69,38%**, 289,08 s, четыре warnings; все пять новых
Python cases PASSED: [excerpt](evidence/ci-5f7900e-tests.txt).
Android push выполнил все четыре variant test tasks: [excerpt](evidence/ci-5f7900e-android-tests.txt).
[Preview guard](evidence/ci-5f7900e-preview.json) прошёл, deploy пропущен.

Однако [Android PR attempt 1](evidence/ci-5f7900e-android-attempt1.json) имеет
**426 tests / 1 failure в DevDebug**: `ConfigRecoveryTest` проверял reconnect count
до завершения coroutine, [CI excerpt](evidence/ci-5f7900e-android-attempt1.txt).
Наличие committed preference не означает, что следующий вызов reconnect уже
выполнен. Это race проверки, не доказанный отказ runtime маршрутизации.

Перед исправлением ожидания в тест добавлен gate на чтение `isConnected` между
commit и reconnect. Он детерминированно воспроизвёл `expected 1, was 0`:
[локальный baseline](evidence/android-config-check-race-before.txt).
Исправленный тест проверяет нулевой счётчик во время паузы, освобождает gate,
дожидается завершения фоновой проверки и только затем ожидает один reconnect.
Cleanup освобождает gate до захвата state lock. Runtime-код и таймауты не ослаблены,
тест не исключён. [Полный повтор](evidence/android-config-check-race-after.txt):
[426 tests / 32 suites](evidence/android-config-check-race-summary.json), без failures/errors/skips.

Неуспешная первая CI попытка сохранена; «все CI зелёные» для `5f7900e` не заявляется.
Следующий commit исправляет harness и поясняющие docs/comments, его CI проверяется
отдельно. Legacy `UPDATE_CONFIG` по-прежнему задаёт один URL и очищает резерв;
настройка пары описана через MDM/JSON/discovery.


### Проверка ревизии `2bbd9a5` с AUD-74

Все CI завершились успешно с первой попытки:
[backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836701),
[frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836636),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836418),
[Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34490829634).
[Preview guard](https://github.com/RootOne1337/sphere-platform/actions/runs/34490836570) успешен, deploy пропущен.

Linux backend: **1390 passed / 69,38%**, 294,70 s,
четыре прежних warnings. Все пять новых config/refresh-origin/generator cases
прошли: [точный excerpt](evidence/ci-2bbd9a5-tests.txt).
[Backend snapshot](evidence/ci-2bbd9a5-backend.json) содержит head SHA, attempt и jobs.
CI mypy в лёгком окружении проходит; локальные 13 ошибок с полными зависимостями
выше этим не отменяются.

Android собрал debug APK и выполнил все четыре Dev/Enterprise × Debug/Release
unit-test tasks: [excerpt](evidence/ci-2bbd9a5-android-tests.txt),
[PR snapshot](evidence/ci-2bbd9a5-android.json),
[push snapshot](evidence/ci-2bbd9a5-android-push.json).
Счётчик 426 / 32 suites относится к отдельному локальному enterprise debug run.
[Frontend](evidence/ci-2bbd9a5-frontend.json) и
[preview](evidence/ci-2bbd9a5-preview.json) сохранены отдельно.

Ревизия `2bbd9a5` содержит исправление harness, runtime fix остаётся `5f7900e`.
Неуспешный PR run `5f7900e` и управляемое воспроизведение сохранены выше.
После проверенной ревизии изменены только evidence и документация. Уточнено ограничение legacy `UPDATE_CONFIG`: он задаёт один URL и
очищает резерв; для пары используйте MDM/JSON/discovery. Полный command update
и unattended background enrollment требуют следующей проверки. Не выполнены
физический fleet drill, production rollout, merge или независимый review.

## AUD-75 — High: фоновая регистрация не давала APK рабочую identity

**Эксплуатационный P0: unattended boot и возврат управления без переустановки.**

- **Root cause:** оба workers входили в registration только при пустом API key.
  Supplied bootstrap key сохранялся как session, marker появлялся без assigned ID.
  Файловый parser терял `features.auto_register` и превращал JSON null в строку.
  KeepAlive запускал root/service перед enrollment; WS запоминал ID из раннего boot
  навсегда. Раздельные workers не сериализовали registration. Missing config и
  rejected service start могли завершать одноразовую работу без следующей попытки.
- **Evidence/reproduction:** на `334b3e7` [8 cases — 7 failures / 1 control](evidence/android-background-enrollment-before.txt).
  На промежуточном candidate после первого worker fix, до mutex/activation/null-key
  исправлений: [12 cases — 4 failures / 8 controls](evidence/android-background-enrollment-races-before.txt).
  До WS fix [обе проверки late identity и stale ACK падают](evidence/android-enrollment-identity-before.txt).
  Это разные наборы и рабочие состояния; их нельзя складывать как число уникальных
  production дефектов. HTTP responses, OS и preferences изолированы doubles.
- **Affected files:** `ZeroTouchProvisioner.kt`, `AuthTokenStore.kt`,
  `AutoEnrollmentWorker.kt`, `KeepAliveWorker.kt`, `SphereAgentService.kt`,
  `SphereWebSocketClient.kt`; worker/lifecycle/authentication/route fixtures.
- **Fix:** registration при auto-register или отсутствии валидного UUID; supplied
  key используется первым, discovery требуется лишь без него. Parser принимает
  generated flag и настоящие nullable fields. Workers используют общий mutex и
  перепроверяют credentials после ожидания; activation повторяется без регистрации
  после пропавшего marker/отказа service start. Missing config/transient failures
  остаются retryable, cancellation не превращается в success. KeepAlive запрашивает
  root/service после identity. WS читает текущий assigned ID на каждой попытке и
  проверяет его повторно перед принятием ACK.
- **Regression tests:** `BackgroundEnrollmentTest` — 22 новых cases, включая
  generated local file без discovery HTTP, 401/408/429/503, повторный periodic tick,
  legacy UUID/static key, held registration с двумя workers, cancellation waiter,
  missing marker и rejected start. `SavedRouteFailoverTest` — ещё два identity cases.
  [Полный Gradle run](evidence/android-background-enrollment-after.txt):
  [450 tests / 33 suites](evidence/android-background-enrollment-summary.json),
  0 failures/errors/skips, 1m 53s. В старом KeepAlive fixture исправлена неактуальная
  заглушка `saveServerUrl` на реально вызываемый `saveServerRoutes`; прежний тест
  storage error мог проходить без нужного failure. CI новой ревизии фиксируется отдельно.
- **Residual risk:** настоящий installed APK, force-stop/reboot/permissions/root,
  sockets, CPU/RAM/battery и fleet capacity не проверены. Blocking registration,
  response loss после server commit и atomic durable identity/tokens/marker открыты.
  Mutex охватывает два workers в одном процессе, не ручной SetupActivity. Нет
  немедленного сигнала enrollment→WS reconnect или fencing уже активного WS после
  поздней identity replacement. Start API не доказывает service readiness.

[Подробный контракт и rollout](../../architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
Backend/schema не менялись; предыдущие 1390 Python / 490 PG+Redis cases не называются
новым установленным APK→SQL smoke. Полный запрос владельца не завершён: текущий
порядок оставшихся работ указан в [матрице готовности](../../operations/READINESS.md).

### Проверка ревизии `be75f57` с AUD-75

Runtime/fixtures/docs commit: **`be75f575d7130e0f3f757ffee6a60e089007df0f`**. Все checks ниже
относятся к этой ревизии, attempt 1:

| Workflow | Результат |
| --- | --- |
| [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536085) | Все jobs success; **1390 passed / 69.38%**, 286.11 s, четыре существующих warnings |
| [Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536209) | Все jobs success |
| [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536769) | Build и четыре Dev/Enterprise × Debug/Release unit-test tasks success |
| [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34497528849) | Build и те же четыре test tasks success |
| [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34497536756) | Guard success, deploy skipped |

[Backend summary](evidence/ci-be75f57-tests.txt),
[Android PR tasks](evidence/ci-be75f57-android-tests.txt),
[Android push tasks](evidence/ci-be75f57-android-push-tests.txt).
Полные job snapshots: [backend](evidence/ci-be75f57-backend.json),
[frontend](evidence/ci-be75f57-frontend.json), [Android](evidence/ci-be75f57-android.json),
[push](evidence/ci-be75f57-android-push.json), [preview](evidence/ci-be75f57-preview.json).

Число **450 / 33 suites** получено из отдельного локального XML run; build success
не выдаётся за runtime proof. Локальные before/after логи сохранены с нормализованными
концами строк и удалёнными trailing spaces. Migration head не менялся. Ни Android
OS/fleet/network measurements, ни deployment, ни независимое review не выполнены.
Следующий commit только фиксирует evidence/docs; он имеет отдельные checks.

## AUD-76 — High: registration удерживал worker и записывал поздний ответ после отмены

**Эксплуатационный P0: остановка и повторная попытка первичного подключения.**

- **Root cause:** blocking OkHttp `execute()` внутри `withContext(IO)` не был связан
  с coroutine cancellation и не имел отдельного registration budget. После чтения
  body шли записи route/ID/tokens без проверки отмены. `body.string().take(64 KiB)`
  сначала выделял память под весь ответ, затем мог принять валидный обрезанный JSON.
  Известный non-2xx status тоже ждал полного error body перед retry classification.
- **Evidence/reproduction:** на неизменённом production коде `f9cccbc` новый набор
  дал [5 failures / 2 controls](evidence/android-registration-http-before.txt),
  [XML summary с точными сообщениями](evidence/android-registration-http-before-summary.json).
  Held headers не завершаются в 12 s, cancel не завершает caller за 1 s, поздний
  success body пишет preferences; valid JSON + 1 MiB whitespace принимается; HTTP
  503 с задержанным body не возвращает уже известный status.
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/DeviceRegistrationClient.kt`;
  новый `RegistrationRecoveryTest.kt` и расширенный `BackgroundEnrollmentTest.kt`.
- **Fix:** async enqueue/cancellable continuation + отдельные coroutine/Call budgets
  10 s. Callback владеет response, закрывает его и отдаёт только значения; активность
  coroutine проверяется до store writes. Success body ограничен байтами до parse,
  non-2xx бросает typed status без error body. Собственный timeout — IOException
  для worker retry; parent cancellation не поглощается. Shared WS timeouts/pool/
  dispatcher сохранены, новый внешний сервис не добавлен.
- **Regression:** 13 новых registration cases + два worker cases с настоящими
  parser/client/store/worker и synthetic transport/preferences/device metadata.
  Проверены headers/body deadlines, отмена caller/queued Call, сохранение новых
  credentials после late cancelled reply, IO retry, 64 KiB boundary, освобождение
  enrollment mutex при отмене/timeout и успешная следующая попытка.
  [Итог: 465 / 34 suites](evidence/android-registration-http-summary.json),
  [полный run](evidence/android-registration-http-after.txt), 0 fail/error/skip, 2m 11s.
- **Fixture correction:** первый расширенный прогон [465 / 1 failure](evidence/android-registration-http-fixture-before.txt)
  считал application interceptor invocation сетевым send. Отменённый queued Call
  может войти в interceptor, оставаясь cancelled. [Ошибка assertion сохранена](evidence/android-registration-http-fixture-before-summary.json);
  финальный test дожидается callbacks и проверяет отсутствие записей и сохранность
  другого Call. Production policy ради прохождения этого assertion не менялась.
- **Residual risk:** HTTP budget не охватывает mutex wait, metadata/keystore и
  начатую синхронную persistence. Route/ID/tokens всё ещё не единый durable commit;
  неотменённый response не fenced от manual re-enrollment/clear. Initial server
  commit response loss, initial fallback traversal, clone identity и OS/network/
  fleet/resource behavior остаются открытыми. RegistrationException сохраняет
  httpCode, но больше не удерживает error response body. Backend/schema не менялись.

[Актуальный контракт и rollout](../../architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
CI нового runtime commit фиксируется отдельно; CI предыдущего `be75f57` не является
проверкой AUD-76. Сохраняется rollout backend→APK; deployment и merge не выполнялись.

### Проверка ревизии `2f17a85` с AUD-76

Runtime/fixtures/docs commit: **`2f17a85cf90fbb87ac5312fdfc2c4ff60dd324e0`**. Все checks ниже
относятся к этой ревизии, attempt 1:

| Workflow | Результат |
| --- | --- |
| [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34500318992) | Все jobs success; **1390 passed / 69.37%**, 291.44 s, четыре существующих warnings |
| [Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34500318999) | Все jobs success |
| [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34500319016) | Build и четыре Dev/Enterprise × Debug/Release unit-test tasks success |
| [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34500313633) | Build и те же четыре test tasks success |
| [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34500319000) | Guard success, deploy skipped |

[Backend summary](evidence/ci-2f17a85-tests.txt),
[Android PR tasks](evidence/ci-2f17a85-android-tests.txt),
[Android push tasks](evidence/ci-2f17a85-android-push-tests.txt).
Полные job snapshots: [backend](evidence/ci-2f17a85-backend.json),
[frontend](evidence/ci-2f17a85-frontend.json), [Android](evidence/ci-2f17a85-android.json),
[push](evidence/ci-2f17a85-android-push.json), [preview](evidence/ci-2f17a85-preview.json).

Число **465 / 34 suites** получено из отдельного локального XML run; build success
не выдаётся за runtime proof. Локальные before/after логи сохранены с нормализованными
концами строк и удалёнными trailing spaces. Migration head не менялся. Ни Android
OS/fleet/network measurements, ни deployment, ни независимое review не выполнены.
Следующий commit только фиксирует evidence/docs; он имеет отдельные checks.

## AUD-77 — High: раздельная запись регистрации теряла identity и допускала обратный порядок credentials

**Эксплуатационный P0: APK теряет возможность продолжить подключение после регистрации.**

- **Root cause:** registration сначала commit routes, затем отдельно apply ID и
  tokens. Возврат успеха не подтверждал их запись на диск. Mutex фоновых workers
  не охватывал ручной клиент и refresh; поздний ответ мог восстановить очищенные
  credentials или заменить более новые. JSON primitive.content принимал null как
  строку, а назначенный UUID/expiry не проверялись перед mutation.
- **Evidence/reproduction:** неизменённый runtime `fb6e908` дал
  [8 failures / 1 control](evidence/android-registration-state-before-summary.json),
  [полный вывод](evidence/android-registration-state-before.txt). Модель отдельных
  memory/disk теряет pending apply после успеха; route boundary содержит новый URL
  со старой identity; credential commit failure не замечается. Gate первого ответа
  показывает обратную запись двух issuances, overwrite после clear/route change,
  invalid UUID и JSON null token. HTTP 401 сохраняет прежнее состояние (control).
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/store/AuthTokenStore.kt`,
  `android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/DeviceRegistrationClient.kt`,
  новый `RegistrationPersistenceTest.kt`; preference doubles трёх прежних suites
  добавляют `contains` для сохранения отсутствующего expiry.
- **Fix:** один checked commit routes/UUID/tokens/expiry/remove refresh intent;
  failure восстанавливает предыдущую память и возвращает IOException. Monitor
  закрывает промежуточную память от читателей store. Общий token mutex сериализует
  регистрацию UI/workers с refresh; версии routes/credentials отклоняют stale reply,
  включая ABA. Проверены строковые credentials, UUID, positive nonoverflow expiry.
  Отмена проверяется под monitor до записи, ожидающий mutex caller отменяется отдельно.
- **Regression:** 20 новых cases: baseline + failure/exception recovery, сохранение
  отсутствующих ключей, ABA/ID fencing, cancelled waiter, оба порядка refresh и
  registration, malformed credentials/expiry, old WS route plan и blocked reader
  до rollback. [485 tests / 35 suites](evidence/android-registration-state-summary.json),
  [полный прогон](evidence/android-registration-state-after.txt): 0 fail/error/skip, 2m 19s.
- **Residual risk:** memory/disk и transport — doubles; реальный keystore/OS crash
  и backend issuance не тестируются этим набором. Уже начатый synchronous commit
  не отменяется и не имеет deadline. Если rollback тоже не удался, память неизвестна;
  suppressed exception сохраняется. Один mutex процесса не устраняет remote commit
  после отмены HTTP. Потеря initial reply/failed commit/stale rejection может оставить
  серверную rotation без сохранённого результата. Старые credentials после failed
  re-enrollment могут быть непригодны, а worker shortcut не распознаёт это. Требуется
  отдельный recovery protocol. Marker, legacy static setup, clones, initial fallback,
  настоящие sockets/OS/fleet/resource measurements остаются открытыми.

Backend/schema не менялись. [Текущий контракт](../../architecture/ANDROID-BACKGROUND-ENROLLMENT.md)
заменяет прежние замечания AUD-75/76 о раздельных registration writes и UI races;
исторические результаты сохранены. CI новой runtime ревизии фиксируется отдельно.
Merge, deployment и готовность всего проекта не заявлены.

### Проверка ревизии `93a4872` с AUD-77

Runtime/fixtures/docs commit: **`93a487268fe4505e5e6e9470bffaf9cd3a9799e6`**. Все checks ниже
относятся к этой ревизии, attempt 1:

| Workflow | Результат |
| --- | --- |
| [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711631) | Все jobs success; **1390 passed / 69.40%**, 296.33 s, четыре существующих warnings |
| [Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711638) | Все jobs success |
| [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711637) | Build и четыре Dev/Enterprise × Debug/Release unit-test tasks success |
| [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/34518706234) | Build и те же четыре test tasks success |
| [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34518711671) | Guard success, deploy skipped |

[Backend summary](evidence/ci-93a4872-tests.txt),
[Android PR tasks](evidence/ci-93a4872-android-tests.txt),
[Android push tasks](evidence/ci-93a4872-android-push-tests.txt).
Полные job snapshots: [backend](evidence/ci-93a4872-backend.json),
[frontend](evidence/ci-93a4872-frontend.json), [Android](evidence/ci-93a4872-android.json),
[push](evidence/ci-93a4872-android-push.json), [preview](evidence/ci-93a4872-preview.json).

Число **485 / 35 suites** получено из отдельного локального XML run; build success
не выдаётся за runtime proof. Локальные before/after логи сохранены с нормализованными
концами строк и удалёнными trailing spaces. Migration head не менялся. Ни Android
OS/fleet/network measurements, ни deployment, ни независимое review не выполнены.
Следующий commit только фиксирует evidence/docs; он имеет отдельные checks.

## AUD-78 — High: первый bootstrap не создавал рабочий доступ к пользователю и APK

**Приоритет владельца: пройти первый полный запуск.** [Остаток работ и оценка](../../operations/PILOT-ACCEPTANCE.md).

- **Root cause:** seed импортировал отсутствующие `async_engine/async_session_maker`,
  использовал `create_all` вместо migration contract и выбирал `default-org`, тогда
  как admin CLI выбирает `default`. Последнее расхождение обнаружено в коде: import
  failure до его исправления не позволял пройти до этого SQL. PowerShell создавал
  локальные admin values, но не передавал их в `exec -T`; Bash собирал inline Python
  с отсутствующими factory/model полями. Оба launcher превращали ошибки admin/key
  в предупреждения и печатали якобы рабочие credentials.
- **Evidence/reproduction:** baseline `3c66c28`: [8 seed tests](evidence/pilot-bootstrap-before-summary.json)
  останавливаются на одном ImportError (**не восемь разных дефектов**);
  [6 launcher failures](evidence/pilot-launchers-before-summary.json) фиксируют
  передачу старых/отсутствующих env values и возврат успеха после exit 17 процесса.
  [Seed log](evidence/pilot-bootstrap-before.txt), [launcher log](evidence/pilot-launchers-before.txt).
- **Affected files:** `scripts/seed_enrollment_key.py`, `scripts/create_admin.py`,
  `scripts/full-deploy.ps1`, `scripts/full-deploy.sh`; новые
  `tests/production/test_pilot_enrollment_bootstrap.py` и
  `tests/deployment/test_bootstrap_launchers.py`.
- **Fix:** реальный `AsyncSessionLocal`, существующая явно выбранная org/default,
  tenant bind и org/key locks, проверка повторного seed без reactivation/rebinding;
  отсутствие key/org — ошибка, без создания таблиц/второго tenant. Admin использует
  ту же org и отказывает при чужом email. Явные UUID/MFA defaults поддерживают
  также схему с ORM defaults. Bash вызывает общий admin CLI; оба launcher передают
  credentials через environment и прекращают bootstrap при ошибке. PS восстанавливает
  env; stderr содержит имена переменных, но не их secret values. Seed выводит ID.
- **Regression:** 15 реальных PostgreSQL/Redis/ASGI cases, включая отдельный процесс
  admin CLI, настоящий login, регистрацию и чтение device, существующего/нового
  пользователя/организацию, чужой tenant, повторный/concurrent seed, revoked/expired/
  changed permissions. Восемь случаев исполняют извлечённые неизменённые функции
  shipped Bash/PowerShell через отдельный Docker double. [Итог](evidence/pilot-bootstrap-summary.json):
  **1413 passed**, coverage **69.38%**, 279.97 s, 505 real-service и 33 deployment cases;
  [полный вывод](evidence/pilot-combined.txt). Android runtime не менялся: прежние 485 JVM tests.
- **Candidate corrections:** [7 failures / 7 passed](evidence/pilot-bootstrap-candidate-before-summary.json)
  выявили моё предположение об отсутствующем ORM `Organization.is_active` и неверный
  запрет имени `ADMIN_PASSWORD` в диагностике (имя не является secret value).
  Оба исправлены. Следующий [1 failure / 17 passed](evidence/pilot-admin-before-summary.json)
  показал зависимость admin INSERT от server UUID defaults, отсутствующих в существующей
  ORM-created audit DB; это **не доказательство отсутствия defaults в fresh Alembic DB**.
  UUID/MFA теперь передаются явно; legacy-схема проверена локально, fresh migrations — в CI.
- **Residual risk:** это части bootstrap, не полный Compose/real browser/APK/VPN.
  `.env`/`.env.local`, migration order, runtime roles/grants, autostart, final health
  и парольный файл legacy launcher остаются отдельной работой. Старые `default-org`
  ключи/устройства не переносятся автоматически. Privileged bootstrap connection
  не заменяет runtime RLS. Авто dev-key hook и deployment artifacts требуют проверки
  вместе с первым fresh-volume запуском. Initial registration lost response, clones,
  аппаратная нагрузка/сеть, VPN router/root tools, UI и наблюдаемость остаются открытыми.

Новый deployment/merge не выполнялся. CI фиксируется по runtime SHA отдельно.
Плановая оценка 1–3 дня / 1–2 недели / 3–6 недель условна и пересматривается после
первого полного прогона; эти сроки не являются результатами тестирования.

### Дополнительный blocker штатного входа в AUD-78

Оба launcher по умолчанию создавали `admin@sphere.local`, отвергаемый настоящим
`LoginRequest.email`. CLI также принимал env password короче восьми символов,
создавая учётную запись, с которой API не допускает login. [Четыре исходных failures](evidence/pilot-login-input-before-summary.json)
сняты после первого bootstrap fix, но до изменения этих прежних input paths;
[полный вывод](evidence/pilot-login-input-before.txt). Это не четыре независимых
уязвимости: два shell defaults и два несовместимых CLI inputs.

Default теперь `admin@example.com`; это локальный идентификатор для входа, никакое
письмо не отправляется. CLI до SQL использует ту же `LoginRequest` и сохраняет
нормализованный email. Ошибка не печатает отклонённый пароль. Невалидные старые
учётные записи не переименовываются автоматически. Четыре новых tests входят
в общий итог **23 новых / 1413 total / 505 real-service / 33 deployment** выше.

### Изоляция login rate-limit в regression fixture

Повторный combined candidate дал [1 failure / 1408 passed](evidence/pilot-rate-fixture-before-summary.json):
новые synthetic clients разных fixtures/runs делили `127.0.0.1` rate-limit key,
и третий login получил 429. [Вывод сохранён](evidence/pilot-rate-fixture-before.txt).
Fixture теперь добавляет свой UUID к Redis identifier, как существующий user-auth
набор. Реальные Redis pipeline/TTL и login limit сохранены; production limiter
не отключён и не ослаблен. Финальный полный run содержит все 23 новых cases.

Ruff 0.15.2 и API export check проходят. Старый `python -m ruff` из audit venv
выбирает 0.3.0 и сообщает E721 в неизменённом `account_credentials.py`; этот результат
не подменяется новым lint. Проверка 0.15.2 выполнена отдельным установленным CLI.

## AUD-79 — High: Bash full-deploy передавал весь Compose prefix одним аргументом

- **Root cause / affected file:** `scripts/full-deploy.sh` устанавливает
  `IFS=$'\n\t'`, но хранит `-f docker-compose.yml -f <overlay>` в строке.
  Некавыченное `$COMPOSE_FILES` больше не разделяется по пробелам: build, up,
  readiness, migration и seed получают один malformed argument вместо четырёх.
- **Evidence/reproduction:** [четыре failures на 0da40f1](evidence/compose-arguments-before-summary.json),
  [полный вывод с argv](evidence/compose-arguments-before.txt). Тест сохраняет весь
  shipped preamble, IFS и option parsing, включая `--production`; затем запускает
  настоящие `build_images`/`seed_data`. Отдельный процесс на границе Docker фиксирует
  `['compose', '-f docker-compose.yml -f docker-compose.full.yml', ...]` и exit 64.
  Это воспроизведение неправильных аргументов; Docker daemon не запускается.
- **Fix:** Bash array для обоих overlay choices и `"${COMPOSE_FILES[@]}"` во всех
  десяти вызовах Compose с file options. Глобальный IFS и смысл команд сохранены.
- **Regression:** четыре новых tests в `tests/deployment/test_full_deploy_compose_arguments.py`;
  прежний Bash bootstrap fixture также теперь загружает настоящий preamble вместо
  ручного объявления defaults. [Все 37 deployment cases проходят](evidence/compose-arguments-after-summary.json),
  [вывод](evidence/compose-arguments-after.txt), 19.84 s; Ruff и Bash syntax проходят.
  AUD-78 по-прежнему доказывает SQL/HTTP bootstrap, но его первый function-only
  harness не включал global IFS и потому не доказывал правильность полного launcher.
- **Residual risk:** полный Compose/APK/VPN ещё не принят. Выбор `.env.local` в
  PowerShell остаётся подтверждённым по коду пробелом; Bash `source .env.local`,
  migration ordering, readiness/roles, autostart и credentials file требуют следующих
  отдельных сценариев. Этот fix не меняет их и не объявляет весь launcher рабочим.

Изменены один runtime shell script и два regression files. Последний полный локальный
backend/PC run — AUD-78: 1413 passed, 69.38%; для изменения argv повторён целевой
полный deployment набор. Exact runtime revision CI сохраняется отдельно.

### Exact-revision CI для AUD-78/79

**AUD-78 runtime `0da40f1`:** [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34528723293), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34528723346), [android](https://github.com/RootOne1337/sphere-platform/actions/runs/34528723295), [preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34528723291) — все четыре workflows
завершились с первой попытки. Linux: **1413 passed / 69.37%**, 319.03 s,
4 warnings; [вывод](evidence/ci-0da40f1-tests.txt). Backend CI выполняет fresh
Alembic migrations и полный набор с выделенными PostgreSQL/Redis. Android PR
проходит все четыре unit-test variants; [вывод](evidence/ci-0da40f1-android-tests.txt).
Отдельного Android push workflow для этих script/test изменений нет. Preview guard
прошёл; deployment job пропущен. Snapshot каждого workflow сохранён в evidence.

**AUD-79 runtime `ac7a11f`:** [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567946), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567951), [android](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567922), [preview](https://github.com/RootOne1337/sphere-platform/actions/runs/34529567939) — все четыре workflows
завершились с первой попытки. Linux: **1417 passed / 69.37%**, 228.42 s,
4 warnings; [вывод](evidence/ci-ac7a11f-tests.txt). Backend CI выполняет fresh
Alembic migrations и полный набор с выделенными PostgreSQL/Redis. Android PR
проходит все четыре unit-test variants; [вывод](evidence/ci-ac7a11f-android-tests.txt).
Отдельного Android push workflow для этих script/test изменений нет. Preview guard
прошёл; deployment job пропущен. Snapshot каждого workflow сохранён в evidence.

Последний Windows combined run: 1413 passed / 69.38% / 279.97 s (AUD-78).
После Bash-only fix локально повторён deployment набор: 37 passed / 19.84 s;
новый полный combined run выполнен в Linux CI, без повторного локального SQL прогона.
Прежний local Android snapshot — 485 tests / 35 suites; Android runtime не менялся.
Ruff 0.15.2, API export check и Bash/PowerShell syntax проверены. Старые результаты
venv Ruff 0.3.0 и dependency-aware mypy описаны выше, они не скрываются lighter CI.
Далее идёт отдельный evidence/docs commit со своими checks. Merge, deployment,
installed APK, VPN handshake и fleet measurements не выполнялись.

### Проверка выданного APK artifact

[Android CI artifact `0da40f1`](evidence/apk-0da40f1-inspection.json) действительно
содержит dev/enterprise debug APK: 8 353 013 / 8 352 977 bytes, versionCode 10200,
min/target 26/35. `aapt` читает manifest, `apksigner` подтверждает v2 signature,
ZIP CRC проходит, SHA-256 и certificate fingerprint сохранены. Это отдельная
проверка фактического артефакта после сборки. Установка, постоянная signing identity,
update без потери данных, release shrink, APK/OS/VPN и performance не проверены.
Пакеты разных flavors имеют отдельное storage; пилот должен зафиксировать package
и update contract до массовой установки. [APK guide](../../../docs/android-agent.md).

## AUD-80 — High: Windows launcher игнорировал подготовленный .env.local

- **Root cause / affected files:** `scripts/full-deploy.ps1` генерирует `.env.local`,
  но `Invoke-Compose` не передавал `--env-file`. Compose выбирал `.env` либо ambient
  configuration. `scripts/start-dev.ps1` требовал только `.env`, при единственном
  готовом `.env.local` создавал template и останавливал запуск.
- **Evidence/reproduction:** baseline `f811320`: [5 failures / 12 passing controls](evidence/windows-env-before-summary.json),
  [полный вывод](evidence/windows-env-before.txt). Настоящий PowerShell wrapper
  вызывает настоящий `docker compose config --format json` с двумя synthetic YAML,
  synthetic dotenv и caller directory, отличающимся от checkout с пробелами в пути.
  При `.env.local`+`.env` выбран не local marker; local-only также не выбран;
  missing installation env не останавливал Docker. Два start-dev cases фиксируют
  отсутствие `--env-file` и ненужное создание template/exit.
- **Fix:** явный приоритет `.env.local` → `.env`, абсолютный env path. Все вызовы
  full-deploy wrapper используют выбранный файл и абсолютные YAML paths. Без файла
  wrapper отказывает до Docker. Штатные config/build/up в start-dev используют тот
  же выбор; template создаётся только при отсутствии обоих файлов и требует ручного
  заполнения. Dotenv разбирает Compose, значения не исполняются и не печатаются.
  Явный process environment сохраняет стандартный приоритет над dotenv.
- **Regression:** `tests/deployment/test_full_deploy_env.py` — пять cases с настоящим
  Compose renderer; две новые start-dev regressions и прежние startup/native failure
  cases. [Все 44 deployment cases проходят](evidence/windows-env-after-summary.json),
  [вывод](evidence/windows-env-after.txt), 25.55 s. PowerShell AST parse и Ruff проходят.
  Bootstrap process fixture получает synthetic `.env.local`, соответствующий новому
  контракту. Production backend/Android и схема БД не менялись.
- **Residual risk:** `.env.local` имеет приоритет целиком, файлы не объединяются.
  Старые installations должны явно выбрать источник; скрипт не переносит значения.
  Изменение файла между отдельными командами/запусками не блокируется. Legacy
  start-dev Status/Down/Tunnel, Bash dotenv `source`, генерация/rotation secrets,
  migration ordering, runtime DB roles и hard-coded health checks full-deploy
  остаются открытыми. Конфигурация Compose не является запуском контейнеров или
  приёмкой APK/VPN; никакой deployment/merge не выполнен.

Последний полный CI до этого fix: `ac7a11f`, 1417 cases / 69.37%. Для нового
PowerShell fix локально повторён полный deployment набор; его exact SHA CI будет
сохранён отдельно. Приоритет далее — migration→API bootstrap и первый device/task.

### AUD-80: CI по runtime revision

`ea8e60646926be657a1d1c42c7dcbbb446b8831c`: [backend](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302055), [frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302107),
[Android](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302056) и [preview guard](https://github.com/RootOne1337/sphere-platform/actions/runs/34546302095)
успешны с первой попытки; preview deployment пропущен. [Linux итог](evidence/ci-ea8e606-tests.txt):
**1424 passed / 69.38%**, 238.84 s, 4 warnings; 505 PostgreSQL/Redis
и 44 deployment cases. Fresh migrations и API export check проходят. Все четыре
Android variants прошли; [вывод](evidence/ci-ea8e606-android-tests.txt). Отдельного
Android push run для этого изменения нет.

Локальная проверка AUD-80: все 44 deployment cases / 25.55 s, Ruff 0.15.2,
оба PowerShell AST parsers. Backend/Android runtime не менялся; последний полный
Windows run остаётся 1413 / 69.38%, JVM 485 / 35 suites. Схема БД не менялась.
Последующий commit только сохраняет evidence/docs и имеет отдельные checks.
Installed APK, полный Compose/VPN/fleet, merge и deployment не заявляются.

## AUD-81 — High: production image не содержит bootstrap CLI

- **Root cause / affected file:** `backend/Dockerfile` копирует backend/alembic и
  agent-config, но исключает оба CLI, вызываемые full-deploy через container exec.
  Dev mount всего checkout скрывает отсутствие `/app/scripts` в собранном образе.
- **Evidence/reproduction:** собран unchanged baseline `ecce7f2`; [build log](evidence/image-bootstrap-build-before.txt).
  Настоящий image process без сети и source mount: [2 failures / 2 controls](evidence/image-bootstrap-before.txt).
  `python scripts/create_admin.py` получает file-not-found exit 2; `python -m
  scripts.seed_enrollment_key` получает ModuleNotFoundError. Alembic single head
  доступен, default user non-root и application directory недоступна для записи.
- **Fix:** `COPY scripts/create_admin.py scripts/seed_enrollment_key.py ./scripts/`.
  В image добавлены только два нужных CLI, не весь каталог вспомогательных скриптов.
- **Regression:** четыре standard-library unittest cases в
  `tests/containers/backend_bootstrap_probe.py`; новый обязательный job
  `Production image bootstrap` в backend CI строит настоящий Dockerfile и исполняет
  probe в container. [After build](evidence/image-bootstrap-build-after.txt),
  [4 passing cases](evidence/image-bootstrap-after.txt), [image IDs/изоляция](evidence/image-bootstrap-summary.json).
  Оба CLI доходят до собственной валидации synthetic inputs/config; Alembic читает
  packaged migration head. Ruff проходит. Эти 4 cases отдельны от pytest total 1424.
- **Harness correction:** первый probe дал [3 failures / 1 control](evidence/image-bootstrap-probe-assertion-before.txt).
  Третье падение было ошибкой теста: parser не принимал branch label `(main)` перед
  `(head)`. Исправлен parser, unchanged baseline повторён: два настоящих failures.
  Migration source и количество heads не изменялись.
- **Residual risk:** отсутствие файлов закрыто; реальное создание admin/key через
  SQL внутри image и fresh migration ещё не проверялись этим probe. Нет API socket,
  Compose rollout или APK/VPN. Package versions/base image не полностью locked;
  before/after image IDs и build logs сохранены. Schema head не менялся.

Проверка: default `sphere`, read-only rootfs, network none, capabilities dropped,
no-new-privileges; один readonly probe mount и временный `/tmp`. Ни source checkout,
ни host secrets, ни DB socket не монтируются. CI фиксируется отдельно по runtime SHA.
