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
| Объединённая Backend/PC/production/deployment suite | **948 passed, 0 failed**; coverage **65,30%** | Строгий coverage gate 65% пройден с precision=2. Load suite исключена; 6 Compose config tests не запускают сервисы |
| Проверки PostgreSQL/Redis | **106 passed**, включены в общий прогон, 0 xfail | Реальные row locks/commits/cache; transport effects подменены, полного APK↔API нет |
| Миграции | Применены до **20260906_task_accounting** включительно | Только изолированная БД; production не мигрировался |
| Backend image | Собирается; исходная запись OpenAPI воспроизведённо падает с PermissionError | Исправлен lifespan; полный deployment runtime ещё не подтверждён |
| Frontend build | Успешно | Type-check/Jest и браузерный runtime требуют отдельного завершения проверки |
| APK ↔ реальный локальный backend | Не завершено | Автоматическая проверка разрешений отклонила запуск локального API: `blocked by policy`; обход не выполнялся |
| 10–64 эмулятора, физические телефоны | Не измерено | Нет подтверждённых CPU/RAM/FPS/энергопотребления и совместимости со всеми Android |

Последний общий вывод: [combined-suite-current.txt](evidence/combined-suite-current.txt).
Предыдущий отдельный DAG benchmark однажды занял 127,1 ms при пороге 100 ms;
изолированный повтор и последующие общие прогоны прошли. Порог не ослаблялся.
Файл production-regressions-after.txt сохраняет более ранний standalone snapshot
с 41 тестом; актуальные 106 входят в общий прогон.

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
- **Fix:** глобальная unique constraint non-FREE INET, короткий advisory lock при выборе IP; PROVISIONING/REVOKING intent commit до provider IO. SQL generation check перед финальным commit; rollback/cancellation не удаляет intent. IP освобождается только commit FREE. Production DI выделяет сессию lifecycle отдельно от caller; API stats читают SQL, а Redis не участвует в ownership. Retry незавершённого peer возвращает 409 без нового provider call; новый split_tunnel сохраняется.
- **Regression:** `test_vpn_durable_leases.py` — 19 случаев, включая 64 параллельных назначения, потерю/poisoned cache Redis, cancellation, generation mismatch, сохранение route/PSK, pool exhaustion, независимость caller transaction. `test_vpn_migration.py` — 5 проверок реальной миграции в PostgreSQL throwaway schema. [vpn-lease-after.txt](evidence/vpn-lease-after.txt) и общий прогон включают прежние VPN contracts/revoke/health tests.
- **Migration evidence:** [vpn-migration-conflicts.txt](evidence/vpn-migration-conflicts.txt): миграция атомарно отказала на накопленных дублях тестового стенда, исходный head и строки сохранились. После удаления только 227 старых artificial Audit A/B peers в выделенной sphere_audit выполнен успешный upgrade. Production не менялся. Автотесты теперь удаляют VPN rows только своих двух UUID организаций. Invalid addresses/network prefixes и downgrade с pending intent также отклоняются без потери данных.
- **Residual risk:** automatic provider reconciliation отсутствует. Pending intent удерживает IP до управляемой сверки, что снижает доступность при отказе, но исключает слепое повторное выделение. Старые writers нельзя запускать одновременно с новым allocator; orphan router peers вне SQL должны быть сверены до rollout. Полный RLS/runtime-role design, HTTP adapter, reserved router IP, AWG settings/routes и физический handshake остаются открытыми. 64 SQL assignments не измеряют ёмкость 64 APK. Подробности: [VPN-LEASE-DESIGN.md](VPN-LEASE-DESIGN.md).

### AUD-30 — High: DELETE менял путь для base64 key, а generic 404 освобождал peer

- **Root cause:** public key вставлялся в путь без percent encoding; символ `/` создавал дополнительный route segment. Любой 404, включая proxy/route Not Found, трактовался как доказательство отсутствия peer.
- **Affected files:** `backend/services/vpn/pool_service.py`, `_remove_peer_from_server`.
- **Evidence:** [vpn-router-path-before.txt](evidence/vpn-router-path-before.txt): 2 failures — raw HTTP path отличался от единого encoded key; generic 404 принимался без ошибки. MockTransport локальный, реальный роутер не вызывался.
- **Fix:** percent encoding ключа как одного URL component; DELETE принимает только 200/204. При 404 intent остаётся REVOKING, адрес не освобождается.
- **Regression:** `test_vpn_router_path.py` и существующий real-SQL revoke matrix, включая 404, проверяют path/error и удержание адреса.
- **Residual risk:** корректный already-absent результат провайдера требует отдельного authoritative contract. Encoded slash должен поддерживаться router/proxy; автоматическое разрешение 404 без этой проверки запрещено. Реальный deployed provider всё ещё не обследован.

## Открытые подтверждённые блокеры

| ID / severity | Root cause и evidence | Необходимое продолжение |
| --- | --- | --- |
| AUD-11 / High, частично исправлен | SQL ownership/uniqueness/intents исправлены и проверены; реальные orphan peers и provider unknown outcomes не reconciled | Inventory contract, controlled reconciliation/rollout, HTTP adapter и AWG конфигурация; незавершённые intents пока удерживаются |
| AUD-14 / High | Несуперпользователь-владелец таблиц обходит RLS. F14 на PostgreSQL; tenant context не установлен повсеместно | Разделение migration/runtime ролей, политики и контекст для HTTP/auth/jobs, реальные cross-tenant проверки |
| DEPLOY-03 / High | Effective Compose оставляет n8n/MinIO host ports; production persistence и DB roles не согласованы | Ingress/access design, роли, долговечные artifacts, runtime/restore проверка |

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

Для AUD-11 реализованы [SQL reservations и generation fencing](VPN-LEASE-DESIGN.md);
документ описывает границы транзакций, обязательный migration preflight и ещё
не реализованный provider reconciliation. Это не означает готовность всего VPN.

PR остаётся draft до завершения открытых блокеров, повторного runtime обследования
и финализации отчёта. Merge и deployment не выполнялись.
