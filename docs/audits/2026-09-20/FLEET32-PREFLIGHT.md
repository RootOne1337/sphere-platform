# Sphere: готовность к 32 одновременно видимым Android

**20 сентября 2026 · решение: NO-GO для длительного прогона 32 устройств с задачами и отказами.**
Причина — перечисленные ниже воспроизводимые дефекты и отсутствие приёмки на этой нагрузке.
Это не утверждение, что 32 подключения обязательно упадут: предел производительности ещё не измерен.

[Главная](../../../README.md) · [Документация](../../README.md) · [Readiness](../../operations/READINESS.md) · [История исправлений](../2026-09-05/AUDIT-REPORT.md)

**Текущий rollout, 21 сентября:** [backend/frontend `c42bb5b`, оба APK 1.2.8](CANARY-20260921.md)
установлены. 15 task receipts и два pipeline подтверждены; F32-01 продвинут native
stop/reconnect/restart проверками, но physical interruption и масштаб не закрыты.
Добавлен **F32-26 / P1 / Medium**: долгий sleep задерживает кооперативную отмену.
Предыдущие source-only формулировки ниже — история до rollout. Этот документ
по-прежнему не даёт допуска к 32: video/preview/Redis и полный fault/soak открыты.

**После исходного среза:** [AUD-129](DURABLE-CANCELLATION.md) добавляет сохранённую
отмену, APK fence до EXECUTE_DAG, ожидание child/nested runs и pending status в UI.
Он заменяет частичный [AUD-128](STOP-DELIVERY-FAILURE.md). Source fix не установлен;
F32-01 остаётся OPEN до native/root-path приёмки. Остальные данные ниже относятся к исходному
аудиту `1c93cf0`; они не заменены результатами более поздней работы.

**AUD-130, source-only:** [ограничен admission на executor](PIPELINE-ADMISSION.md):
десять принятых runs, остальные QUEUED; 9 baseline failures → 10 passing regressions.
Три дополнительных SQL runtime tests проверяют освобождение единственного connection
для delay/task/sub-pipeline с idle-timeout 900ms (изменение AUD-129). F32-04/05
продвинуты в исходном коде, но rollout и остаточные gates открыты; F32-02 не исправлен.

**Следующий source fix — AUD-131:** [lease/checkpoint recovery pipeline](PIPELINE-RECOVERY.md).
F32-02 теперь имеет проверенное восстановление безопасных checkpoint/child ожиданий,
generation fencing и явное `unknown` для неоднозначных эффектов. 120 связанных tests,
включая OS-kill изолированного worker; native rollout и nested capacity остаются OPEN.
Фраза о неисправленном F32-02 выше описывает checkpoint AUD-130, не текущий source.

**Актуализация 21 сентября — AUD-132:** [batch plan/recovery](BATCH-RECOVERY.md)
продвигает F32-03 в исходном коде: сохранены цели, version, cursor, Task IDs
и receipts; OS-kill между волнами проверен. Native rollout открыт.
**Дополнительный P0 F32-25** воспроизведён под non-owner RLS ролью:
pipeline startup не находит QUEUED без tenant context. Исходный реестр из
24 пунктов дополнен этим blocker; AUD-131 не закрывает данный путь.

**Последующий source fix — AUD-133:** [pipeline RLS](PIPELINE-RLS.md) исправляет
F32-25: ограниченный discovery и tenant-bound claim/renew/reconcile/recovery.
Три baseline failures → 76 связанных passing tests, включая non-owner OS-kill.
Другие background workers, nested capacity и native rollout остаются OPEN.

**Следующий source fix — AUD-134:** [durable nested waiting](PIPELINE-NESTED-WAIT.md)
устраняет подтверждённое насыщение родителями. 87 связанных tests и первоначальная
проба прошли; checkpointed nested wait освобождает слот и сохраняет child/deadline.
Compound loop/parallel, квоты и native rollout остаются OPEN.

**AUD-135/136, source-only:** [task dispatcher](TASK-DISPATCH-RLS.md) и
[scheduler](SCHEDULER-RUNTIME.md) находят работу под runtime RLS; проверены
dependency recovery, атомарность, commit failure и ограниченная обработка страниц.
Выявленный worker blocker — [watchdog RLS](evidence/watchdog-rls.json): startup tick
не видит просроченную QUEUED задачу. [AUD-137](WATCHDOG-STOP-RECOVERY.md) исправляет
это и premature timeout: stop intent сохраняется, устройство ждёт terminal APK
receipt. 22 новых backend и 239 frontend tests прошли. Native acceptance и общий
допуск остаются OPEN.

## Что проверяли в исходном срезе и что уже известно

Сценарий владельца: **32 настоящих эмулятора, 32 живых экрана в одном веб-интерфейсе,
параллельные локальные DAG и оркестрация, самостоятельное восстановление связи**.
64 экрана — следующий рубеж. В перспективе отдельные AI consumers получают примерно
два свежих наблюдения в секунду на устройство и возвращают команды. AI в этом этапе
не реализуем; проверяем, чтобы нынешние решения не мешали такому контуру.

Аудит охватывает backend/API/WebSocket, PostgreSQL, Redis, batch/pipeline/scheduler,
Android/OTA/boot/capture, активный frontend decoder/UI, PC-agent, VPN, ingress,
Compose/monitoring/backup и нагрузочный harness. Это проверка критических цепочек
и конкретных дефектов, а не доказательство отсутствия ошибок во всех строках проекта.
Старые `sphere-platform` и `sphere-tunnel` не изменялись. Новый runtime также не
обновлялся; fault injection выполнялся только в выделенной тестовой БД/процессах.

| Контрольная точка | Факт |
| --- | --- |
| Проверенный исходный код | `1c93cf0a04b07e6a005627d45be511364efe111d`, audit branch / draft PR19 |
| Установленный backend | `85fb1ea537c2f7961057432e8317f44a44c74c54`, четыре workers |
| Установленный frontend | `03b161e5faffda0a28d82eb2db94064e73b5360f` |
| Оба APK | 1.2.7 / 10207; два rooted Android 9, не матрица всех Android |
| Read-only snapshot | 20 сентября, 10:10:58 UTC; девять healthy контейнеров нового pilot, restart count 0 |
| SQL/API | 418 completed tasks, 0 active/failed в полученной сводке; readyz 200 |
| Android в этом snapshot | PID 2182 / 2187, захват выключен; PSS 48 830 / 57 129 KiB, **idle**, не streaming benchmark |
| Длительная приёмка | Последняя ночь **FAILED через 3 ч 33 мин**, не 8h passed; после исправлений полный новый прогон не выполнен |

Исторические улучшения действуют: [AUD-125](../2026-09-05/STREAM-START-DELIVERY.md),
[AUD-126](../2026-09-05/STREAM-MULTI-VIEWER.md),
[AUD-127](../2026-09-05/SOAK-VIEWER-MOTION.md),
[Android recovery](../2026-09-05/ANDROID-RECONNECT-DEBT.md),
[сетевая приёмка](../2026-09-05/NETWORK-RECOVERY-NATIVE.md).
223 DAG из неуспешной ночи независимо сверены; это полезный результат, но он не
закрывает оставшиеся часы и масштаб. Старая запись `media.codec SIGABRT` до той
ночи не считается новым crash Sphere. Текущий snapshot не заменяет новый crash-diff.

## Как читать реестр

- **R — воспроизведено:** реальный код с изолированной БД либо контролируемым transport/codec double. Ограничения указаны явно.
- **C — подтверждено кодом/конфигурацией:** путь существует; последствия при нагрузке ещё не измерены.
- **G — пробел приёмки:** необходимое свойство не доказано; это не автоматически найденный баг.
- **P0:** до допуска к смешанному 32-device fault/soak. **P1:** до включения соответствующего режима. **P2:** последующий этап 64/AI или улучшение.
- Severity описывает эксплуатационный ущерб, а не CVSS. Все F32 ниже **OPEN**. «Fix» означает необходимую работу, **не уже внесённое исправление**.

Некоторые пункты уточняют ранее записанный residual risk, а не объявляют его новой
регрессией. Доказательства: [runtime](evidence/runtime-summary.json),
[семь backend reproductions](evidence/reproductions.json),
[decoder](evidence/decoder-result.json), [исходники и запуск](evidence/README.md).
**7 failing assertions ожидаемы:** они фиксируют открытые дефекты; это не семь
прошедших regression tests и не падение стандартного CI. Пробы лежат вне `tests/`.

## Очередность

| ID | Приоритет / severity / основание | Что мешает эксплуатации |
| --- | --- | --- |
| F32-01 | P0 / High / R | UI/API сообщает отмену без доставки stop; дочерний task переживает отмену pipeline |
| F32-02 | P0 / High / R | RUNNING pipeline не восстанавливается после потери executor |
| F32-03 | P0 / High / R | Неотправленные волны batch существуют только в памяти |
| F32-04 | P0 / High / R | Ожидающий pipeline удерживает SQL-транзакцию и соединение |
| F32-05 | P0 / High / R | Pipeline admission захватывает больше работы, чем способен выполнять |
| F32-06 | P0 / High / R | Активный browser decoder не ограничивает очередь и не восстанавливает codec error |
| F32-07 | P0 / High / C | Профиль качества не доходит до APK; нет рабочего облегчённого режима 32 плиток |
| F32-08 | P0 / High / C | Команды и видео делят исходящую очередь APK; реальный возраст кадра не измеряется |
| F32-09 | P0 / High / C + runtime | Redis maxmemory 512 MiB при лимите контейнера 128 MiB |
| F32-10 | P0 / High / C + runtime | Fleet/WS метрики не подключены; scrape зависит от worker |
| F32-11 | P1, VPN / High / C | Kill switch и health reconnect подключены к publisher-заглушке |
| F32-12 | P1, VPN / High / C | Kill switch не согласован с резервными адресами, сменой DNS и IPv6 |
| F32-13 | P1, VPN UI; P2, 64 / Medium / C | Нулевые графики VPN выдают отсутствие измерений за данные; сетка 64 ограничена 50 |
| F32-14 | P1, OTA / High / R + C | Конкурентная публикация OTA теряет запись; JSON каталог не атомарный |
| F32-15 | P1, PC-agent / Medium / C | Topology отправляется однократно; результаты команд не durable |
| F32-16 | P1, webhook/n8n / High / C | Completion webhook запускается до подтверждённого commit, без durable outbox |
| F32-17 | P0, наблюдение / Medium / C | Monitoring compose не соответствует изолированному pilot |
| F32-18 | P0, fault/soak / High / C + runtime | Backup нацелен на старые имена; core Docker logs без настроенной ротации |
| F32-19 | P0 / gate / G | Harness рассчитан на 1–8 устройств; 8h и реальный browser decode на 32 не приняты |
| F32-20 | P1, WAN continuity / gate / G | Нет принятого независимого ingress/config host; recovery одного провайдера не равно failover |
| F32-21 | P1, VPN / gate / G | На pilot не настроен VPN provider; UDP/DNS/MTU/end-to-end не приняты |
| F32-22 | P0, профиль 32 / gate / G | Нет совместного CPU/GPU/RAM/network профиля станций, APK и браузера |
| F32-23 | P0, fault/soak / gate / G | Нет полной 32-device матрицы SQL/Redis/restart/idempotency/retention |
| F32-24 | P2, будущий AI / gate / G | Нет observation/action контракта свежести и владения управлением |
| F32-25 | P0, RLS runtime / High / R | Pipeline-worker без tenant context не видит сохранённую очередь |
| F32-26 | P1 / Medium / R, 21 сентября | Долгий sleep задерживает отмену до конца действия |

## Backend, оркестрация и БД

### F32-01 — отмена не подтверждает остановку

**Root cause / файлы:** [TaskService.force_stop_task](../../../backend/services/task_service.py)
игнорирует `False` из `send_command_live`, вызывает `mark_completed` и сохраняет
`CANCELLED`. [PipelineService.cancel_run](../../../backend/services/orchestrator/pipeline_service.py)
меняет только pipeline status. [execute_script](../../../backend/services/orchestrator/step_handlers.py)
ждёт task и не прекращает его по отмене run. APK `control_accepted` означает принятие
запроса, а не физическую остановку.

**Evidence:** реальные SQL-пробы `test_force_stop_does_not_claim_cancelled_when_delivery_failed`
и `test_pipeline_cancel_reconciles_current_child_task`: delivery=False → CANCELLED,
release вызван; pipeline=CANCELLED, child=RUNNING. Отказ transport задан double;
физическую остановку Android в этой пробе не имитируем.

**Fix:** durable cancel intent и промежуточное `cancelling/unknown`, доставка с
одним control ID, reconciliation конечного APK receipt; освобождение device lease
после подтверждения либо явно описанной процедуры восстановления. Pipeline cancel
должен управлять текущим child; поздний handler не должен переписать terminal state.
**Regression:** offline/Redis false/неизвестный SQL commit, поздний результат,
повтор cancel, cancel одновременно с новым task; затем native отмена долгого безопасного DAG.
**Residual:** root action может уже завершиться; нельзя обещать откат внешнего действия.

### F32-02 — осиротевшие RUNNING pipeline

**Последующий source status:** [AUD-131](PIPELINE-RECOVERY.md) добавляет lease,
generation и атомарные step/child checkpoints. Проверен OS-kill отдельного test worker,
сохранение одного child ID, fencing позднего результата, pause/resume и timeout.
Внешний неизвестный эффект переводится в review, не повторяется. Native rollout,
nested capacity и общая политика admission остаются открытыми. Ниже — исходная проблема.

**Root cause / файлы:** [PipelineExecutor](../../../backend/services/orchestrator/pipeline_executor.py)
выбирает только QUEUED; [PipelineRun](../../../backend/models/pipeline.py) не имеет
owner lease/heartbeat/fencing generation. Глобальный timeout проверяется внутри
живого `_execute_run`, а не независимым reconciler.

**Evidence:** persisted RUNNING возрастом 25h после poll нового executor остаётся
RUNNING, новых tasks=0. Это воспроизведение свежим объектом executor, **не OS kill**.
**Fix:** lease с generation, durable step/child identity, reclaim/reconcile истёкшего
lease; необратимый шаг с неизвестным исходом требует расследования, не слепого replay.
**Regression:** kill worker до/после SQL commit и child ACK, PAUSED/resume, два claimers,
поздний старый owner. **Residual:** exactly-once внешнего эффекта не получается одной SQL-блокировкой.

### F32-03 — batch теряет ещё не отправленные цели

**Последующий source status:** [AUD-132](BATCH-RECOVERY.md) сохраняет wave plan,
pinned version и atomic cursor/receipts; проверен настоящий worker OS-kill.
Смешанный rollout, legacy reconciliation и native acceptance остаются открытыми.
Ниже — исходная проблема, на основе которой внесён fix.

**Root cause / файлы:** [BatchService.start_batch/_execute_waves](../../../backend/services/batch_service.py)
коммитит batch и запускает `asyncio.create_task`; список целей/план волн остаются
в coroutine. В [TaskBatch](../../../backend/models/task_batch.py) сохранены total и
wave settings, но не полная адресуемая программа оставшихся волн.

**Evidence:** две цели, wave_size=1; отмена producer между волнами оставляет total=2,
один Task, RUNNING batch; вторую цель из записи восстановить нельзя. Это модель
утраты worker coroutine в isolated DB, без остановки pilot.
**Fix:** записать полный план, фиксированную версию script, cursor и уникальный ключ
элемента волны до запуска; lease worker и idempotent admission при восстановлении.
**Regression:** рестарт между волнами, неоднозначный commit, cancel против producer,
изменение script во время batch. **Residual:** admission не равен успешному исполнению;
счётчики должны строиться из terminal receipts, не факта отправки.

### F32-04 — SQL connection занят во время ожидания

**Последующий source status:** AUD-129 освобождает транзакции перед handler и между
child polls; AUD-130 добавляет три passing real-SQL regressions с маленьким пулом и
коротким timeout. [Доказательство и границы](PIPELINE-ADMISSION.md). Ниже — исходная проблема.

**Root cause / файлы:** `_execute_run` в [executor](../../../backend/services/orchestrator/pipeline_executor.py)
после commit читает Pipeline timeout, открывая следующую транзакцию, затем ждёт
[step handler](../../../backend/services/orchestrator/step_handlers.py). Delay допускает
до 300s. Task polling также выполняет refresh между ожиданиями в той же session.

**Evidence:** у реального delay-only run `pg_stat_activity` показывает одну
`idle in transaction` во время паузы. На pilot `idle_in_transaction_session_timeout=1min`;
срабатывание этого timeout здесь не инжектировалось. При 32 долгих pipeline это ещё
и конкуренция за connection pool, а не полезная SQL-работа.
**Fix:** короткие транзакции на чтение/изменение; освободить connection перед sleep,
сетевым вызовом и ожиданием child; повторная загрузка с проверкой generation/status.
**Regression:** delay > SQL idle timeout, pool меньшего размера, параллельные API/stop;
idle transaction=0 и ограниченное ожидание checkout. **Residual:** после сокращения
транзакций нужна явная защита от stale ORM state.

### F32-05 — semaphore не ограничивает admission

**Последующий source status:** AUD-130 ограничивает число claims свободными слотами
и сериализует poll/stop; 10 passing real-SQL regressions. Cluster/per-device limit,
nested WAITING/recovery и rollout открыты. [Исправление и evidence](PIPELINE-ADMISSION.md).

**Повторная проверка 21 сентября, source `d859a52`:** оставшаяся nested capacity
проблема теперь воспроизведена реальным executor/SQL. Десять родителей создают
десять пустых children и занимают все десять слотов. После восьми следующих polls
сохраняется 10 RUNNING parents / 10 QUEUED children / 0 completed parents.
Пустой child сам не требует Android и мог бы завершиться сразу, но не получает
слот. Это **1 ожидаемый failing assertion**, не часть passing backend-набора.
[Сводка и границы](evidence/pipeline-nested-capacity.json),
[сохранённая проба](evidence/pipeline_nested_capacity_probe.py).
Требуется сохраняемое ожидание с освобождением executor capacity, корректным
возвратом по child receipt/deadline и сохранением cancel/recovery fencing.
Просто поднять лимит или разрешить неограниченное число coroutine недостаточно.
**Последующий AUD-134** реализует сохраняемый WAITING для checkpointed sub_pipeline;
[исходная проба после fix](evidence/pipeline-nested-wait.json) завершается успешно.
Compound loop/parallel, общая квота и native runtime остаются отдельными gates.

**Root cause / файлы:** [PipelineExecutor._poll_and_dispatch](../../../backend/services/orchestrator/pipeline_executor.py)
на каждом poll помечает до десяти runs RUNNING и создаёт tasks **до** захвата semaphore.
**Evidence:** четыре poll, 32 queued runs → 32 RUNNING и 32 background tasks при
10 реально исполняемых. Число десять — на executor, не на весь четырёхпроцессный backend.
**Fix:** резервировать свободные слоты до SQL claim; bounded backlog, общий понятный
лимит и per-device admission, совместимые с lease F32-02. **Regression:** 32/1000 queued,
несколько workers, stop/restart/cancel; RUNNING соответствует принятой работе, очередь ограничена.
**Residual:** просто увеличить semaphore или DB pool — не исправление восстановления.

### F32-09 — Redis может получить OOM раньше прикладного лимита

**Root cause / файл:** [docker-compose.yml](../../../docker-compose.yml):
`--maxmemory 512mb`, memory limit `128M`; это подтверждено `docker inspect` и Redis CONFIG.
**Evidence:** maxmemory=536870912, container=134217728 bytes; policy=`allkeys-lru`,
AOF everysec. Сейчас used_memory≈1.7MB, RSS≈13.4MB, evictions=0: **OOM не наблюдался**.
**Fix:** согласованный container/maxmemory budget с запасом под RSS, buffers и fork;
инвентаризировать cache/presence/locks/queues, выбрать политику вытеснения по их смыслу.
Для управляющих ключей не считать произвольную eviction нормальным recovery.
**Regression:** давление памяти в отдельном Redis, bounded slow subscribers,
AOF/restart/reconnect и восстановление SQL intents. **Residual:** SQL уже хранит
durable task intent; нельзя объявлять все задачи потерянными из-за любой eviction.

### F32-16 — webhook не является надёжным завершением workflow

**Root cause / файлы:** [TaskService.handle_task_result](../../../backend/services/task_service.py)
запускает completion callback через `asyncio.create_task` до commit вызывающей
транзакции; [WebhookService](../../../backend/services/webhook_service.py) не заменяет
durable post-commit outbox. Batch callback ранее оставлен residual risk AUD-44.
**Evidence:** порядок вызовов в текущем коде; failure injection доставки webhook
в этом срезе не проводился. Возможны callback для откатившегося результата и потеря
уведомления вместе с worker.
**Fix:** transactional outbox, event ID, bounded retries, идемпотентный consumer,
видимый delivery status. **Regression:** rollback/worker exit до и после send,
duplicate delivery и недоступность n8n. **Residual:** внешний получатель обязан
дедуплицировать; n8n пока не входит в принятую цепочку 32 устройств.

## APK, видео и браузер

### F32-06 — неограниченные очереди и codec error

**Root cause / файлы:** страница использует [DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx)
и **[frontend/lib/h264-decoder.ts](../../../frontend/lib/h264-decoder.ts)**.
Другая реализация в `src/lib/streaming` не исправляет этот import. До SPS/PPS массив
`pendingFrames` растёт без лимита; после configure нет контроля `decodeQueueSize`.
Error callback только пишет console.error; состояние decoder не сбрасывается.

**Evidence:** настоящий TS код с намеренно зависшим codec double принимает 2048
NAL / 2 MiB полезной нагрузки без конфигурации и 1000 decode submissions без
backpressure; после ошибки следующий decode выбрасывает исключение наружу.
Это доказательство политики очередей, **не измерение GPU и не доказанный OOM браузера**.

**Fix:** лимиты bytes/count/age до конфигурации, ограниченная decode queue, сброс до
нового SPS/PPS/IDR при отставании, контролируемый codec recovery, `frame.close()` в finally.
Не выбрасывать произвольные H.264 reference frames без стратегии возобновления.
**Regression:** отсутствие SPS/PPS, slow/closed decoder, error после reconnect,
resize/unmount; затем 32 реальных decoders, движение и bounded memory на протяжении soak.
**Residual:** hardwareAcceleration preference не гарантирует 32 аппаратных сессии;
нужны измерения на компьютере оператора.

### F32-07 — команда качества не управляет encoder

**Root cause / файлы:** [StreamBridge](../../../backend/websocket/stream_bridge.py)
посылает `quality=720p, bitrate=2000000`; ветка `start_stream` в
[CommandDispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt)
запускает Activity без этих параметров.
[StreamingManagerImpl](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt)
задаёт только dimensions; defaults [H264Encoder](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/H264Encoder.kt)
— 30fps / 1.5Mbps. [VirtualDisplayManager](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/VirtualDisplayManager.kt)
выбирает 720p по ориентации. Выбор UI quality не образует сквозной контракт.

**Evidence:** трассировка аргументов по перечисленным вызовам; разные профили на
живом encoder в этом срезе не измерялись. **Fix:** validated profile UI→backend→APK,
ACK фактически применённых width/height/fps/bitrate, отдельные preview/focus,
координация требований нескольких viewers без постоянного restart capture.
**Regression:** 32 preview + один focus, смена профиля, rotation, reconnect и
несовместимый codec; сверка применённого профиля и настоящего bitrate.
**Residual:** ABR APK реагирует на его send queue, не на нагрузку decoder браузера.

### F32-08 — свежесть и задержка управления пока не контролируются

**Root cause / файлы:** [SphereWebSocketClient](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt)
отправляет JSON/видео через один WebSocket. Лимит binary queue 1 MiB полезен против
переполнения, но JSON command results/pong могут ждать за видео. Backend
[VideoFrameQueue](../../../backend/websocket/video_queue.py) уже ограничен 50 кадрами,
8 MiB и возрастом обычных P-frames 200ms — это не end-to-end latency guarantee.

[FramePackager](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/FramePackager.kt)
ставит wall-clock relative timestamp при упаковке, не capture presentation timestamp.
Browser decoder подставляет свой `performance.now()`; probe показывает
12345000 → 999999000 microseconds. Из этих значений нельзя восстановить время
«экран Android → показ оператору» и отделить frozen frame от здорового transport ping.

**Fix:** измеряемые capture/encode/send/receive/decode/render stages, stream epoch и
frame ID; оценка clock offset с uncertainty либо честный round-trip proxy. Ограничить
возраст video backlog; сначала проверить управление под насыщением, при нарушении
бюджета разделить control/video transport. Нельзя обещать приоритет JSON внутри
уже записанного TCP буфера. **Regression:** constrained uplink/downlink, slow viewer,
краткий blackhole, static и moving screen; команды не теряются, после восстановления
показывается свежий кадр, а не длинная очередь прошлого.
**Residual:** 1 MiB / 1.5Mbps ≈ 5.6s — оценка времени drain заполненного буфера,
не измеренная задержка нынешнего стенда. Показать ping вместо frame age недостаточно.

### F32-14 — OTA каталог теряет конкурентные публикации

**Root cause / файл:** [updates router](../../../backend/api/v1/updates/router.py):
`_load_releases` / `_save_releases` выполняют read-modify-write JSON без транзакции
или межпроцессной блокировки; `write_text` не atomic replace. Ошибка JSON чтения
маскируется пустым списком. Backend имеет четыре workers.

**Evidence:** два независимых чтения пустого временного каталога; каждый writer
добавляет свой release, затем два save → остаётся **один из двух**. Настоящие функции,
`tmp_path`, рабочий каталог APK не затронут. Torn read/kill-during-write здесь ещё
не инжектировались. **Fix:** SQL catalog с уникальностью и транзакционными изменениями
или строго сериализованное atomic file storage; отдельный статус ошибки чтения.
**Regression:** concurrent publish/delete/read, падение writer и сохранение последней
валидной версии. **Residual:** atomic rename сам по себе не устраняет lost update;
для fleet дополнительно нужны cohorts/canary и управляемый rollback. OTA на двух
rooted Android уже принят, fleet rollout этим не доказан. На нагрузочном прогоне
версии фиксировать, автоматическую публикацию новых releases исключить.

### F32-13 — UI показывает не все реальные ограничения

**Root cause / файлы:** [VPN page](../../../frontend/app/%28dashboard%29/vpn/page.tsx)
рисует массивы нулевого трафика и `0B` без измерения. Отсутствие данных должно иметь
явное состояние unavailable, а не выглядеть как измеренный ноль.
[Stream page](../../../frontend/app/%28dashboard%29/stream/page.tsx) предлагает 64,
но сначала ограничивает страницу 50 устройствами (`DEVICES_PER_PAGE`), затем сетку.

**Evidence:** текущие вычисления UI. **Fix:** реальные telemetry series или явное
«данных нет»; независимые корректные page/grid limits. **Regression:** known nonzero
VPN metrics, unavailable/stale data; 64 устройства действительно создают 64 плитки,
смена страниц освобождает viewers. **Residual:** ограничение 50 не мешает именно 32;
его приоритет ниже стабильности и управления.

## VPN, PC-agent, deployment и наблюдаемость

### F32-11 — VPN управляющие команды идут в stub

**Root cause / файлы:** фактический `get_killswitch_service` в
[VPN router](../../../backend/api/v1/vpn/router.py) создаёт
[services.vpn.event_publisher.EventPublisher](../../../backend/services/vpn/event_publisher.py).
Его `send_command_to_device` всегда возвращает `False`; этот же класс использует
[vpn_health](../../../backend/tasks/vpn_health.py). Это не рабочий
`backend.websocket.event_publisher` и не только неиспользуемая DI-функция с Noop.

**Evidence:** route→service→конкретный класс; отправки в transport в нём нет.
Дополнительно [KillSwitchService](../../../backend/services/vpn/killswitch_service.py)
и health monitor формируют lowercase `vpn_killswitch` / `vpn_reconnect`, тогда как
APK обычные команды принимает через `IncomingCommand`; нужен единый проверенный
wire contract, а не одна замена импорта.
**Fix:** настоящий publisher, адресуемая команда с ID/ACK, честный результат delivery,
интеграция Android handlers. **Regression:** route + реальный cross-worker Pub/Sub +
APK test double; затем owned VPN test device, reconnect после отсутствия handshake.
**Residual:** delivery ACK не доказывает tunnel health/iptables outcome.

### F32-12 — VPN kill switch может отрезать путь восстановления

**Root cause / файлы:** [CommandDispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt)
передаёт текущий management hostname; [KillSwitchManager](../../../android/app/src/main/kotlin/com/sphereplatform/agent/vpn/KillSwitchManager.kt)
строит IPv4 iptables rules с разрешением этого host и VPN endpoint. Обновления
набора signed fallback/discovery routes и DNS-адресов в этих правилах нет; IPv6
политика в этом менеджере не реализована.
**Evidence:** путь параметров и правила; блокировку живых удалённых устройств
не выполняли. **Fix:** явная management-plane политика, safe transactional update
правил, recovery после DNS/route change, согласованное IPv6 поведение и проверка
реального tunnel interface. **Regression:** отдельный network namespace/device:
VPN down, primary down, новый IP, только fallback, IPv6, reboot и disable rollback.
**Residual:** сначала доказать аварийный доступ, затем включать kill switch на fleet.

### F32-15 — PC-agent не имеет полного reconnect/result контракта

**Root cause / файлы:** [main.py](../../../pc-agent/agent/main.py) вызывает
`report_on_connect` один раз после sleep(1), а не после каждого authenticated
подключения. [client.py](../../../pc-agent/agent/client.py) выставляет `_connected`
после отправки auth, имеет volatile queue 1000; QueueFull отбрасывает сообщение,
ошибка send не создаёт durable receipt. Transport cleanup уже исправлялся;
не следует объявлять тот исправленный дефект снова открытым.
**Evidence:** текущий lifecycle; native PC restart/топология 32 instances в этом
срезе не принимались. **Fix:** authenticated lifecycle callback, snapshot topology
после reconnect, bounded команды и durable результаты там, где они управляют
запуском станций. **Regression:** задержка auth >1s, disconnect на result send,
смена списка instances offline, restart. **Residual:** автономному Android
не нужен PC-agent; этот пункт блокирует приёмку управления станциями, не APK OTA.

### F32-10 — метрики не дают достоверную картину fleet

**Root cause / файлы:** [metrics.py](../../../backend/metrics.py) определяет
`ws_connections_active`, `devices_online`, `task_queue_depth`, но вызывающих
обновлений этих трёх gauges в backend не найдено. Pool gauge обновляется отдельно,
его нельзя называть отсутствующим. Четыре workers без настроенного multiprocess
registry отдают worker-local metrics.
**Evidence:** 12 чтений `/metrics` показывают разные process start times,
WS/devices labeled samples отсутствуют. Значение queue=0 не доказывает отсутствие
работы при такой инструментализации. **Fix:** подключить реальные lifecycle counters,
корректное агрегирование gauges/workers и отдельные streaming metrics: viewers,
decoded frames, dropped frames, age/queue bytes, reconnect reasons; bounded cardinality.
**Regression:** два workers и известные device/viewer/task counts; recycle worker,
scrape после disconnect. **Residual:** structured logs полезны, но один request ID
не заменяет correlation `run/batch/task/command/device/session/stream_epoch`.

### F32-17 — monitoring stack не подключается к pilot по документации

**Root cause / файл:** [docker-compose.monitoring.yml](../../../infrastructure/monitoring/docker-compose.monitoring.yml)
в рекомендованном merge с корневым compose использует `./prometheus.yml`,
`./alert-rules.yml`, `./grafana/*` относительно корня, где этих файлов нет.
Фиксированная external network `sphere-platform_sphere-net` относится к старому
имени проекта; `container_name` глобальны. Порт Grafana 3000 конфликтует с frontend
в профилях, где опубликован тот же порт. В девяти pilot services monitoring отсутствует.
**Fix:** project-scoped compose overlay, проверяемые bind paths/ports/network,
scrape targets именно нового проекта. **Regression:** compose config в чистом
каталоге, coexistence двух проектов, actual target UP и тестовый alert.
**Residual:** включение dashboard с неверными метриками F32-10 не даёт наблюдаемость.

### F32-18 — backups и ограничение логов нужно привести к текущему запуску

**Root cause / файлы:** [backup-database.sh](../../../scripts/backup-database.sh)
жёстко задаёт старые `sphere-platform-postgres-1` / `sphere-platform-redis-1`;
`BGSAVE || true` и sleep(3) не подтверждают завершение нового snapshot. Скрипт
**не запускался**, старые контейнеры не трогались. В runtime у семи core containers
`json-file` с пустыми log options; explicit rotation есть у двух ingress services.

**Fix:** backup принимает проверенный project/service scope, подтверждает snapshot,
фиксирует состав данных и restore receipt; ротация Docker/application logs с
дисковым budget. До destructive fault drills — restore в отдельный проект:
PostgreSQL, нужные Redis данные, MinIO, OTA catalog/artifacts, ключи/конфигурация.
**Regression:** две установки рядом, невалидная цель отвергается, interrupted backup,
restore + чтение task/artifact и ограничение размера логов. **Residual:** disk full
сейчас не наблюдался; наличие dump без restore не считается восстановлением.

## Открытые условия приёмки

| Gate | Что уже есть | Что ещё нужно и чем закрывать |
| --- | --- | --- |
| **F32-19: harness/soak** | Native commands, DAG receipts, motion-aware multi-viewer helper; 1–8 devices в `scripts/pilot/android_soak.py` | Проверенный режим 32 с явным allowlist, per-device receipts, независимым watchdog, финальной API/PID/crash сверкой. `tests/load/protocols/video_streamer.py` формирует random NAL payload: он проверяет transport load, не настоящий WebCodecs decode. Нужны реальные APK→браузер и полный успешный 8h run. |
| **F32-20: WAN** | Signed discovery/cache, fallback logic; реальные отказы обеих сторон ранее пройдены на двух APK | Независимый второй ingress и независимый доступный config host; первичный provider и GitHub недоступны по отдельности/вместе. Не требовать переустановки или ручного IP. Второй URL через тот же провайдер не независимый резерв. Отдельно измерять path recovery и время повторной публикации tunnel route. |
| **F32-21: VPN runtime** | SQL IP leases и отдельные concurrency/reconciliation tests | Snapshot: encryption key/router credentials/server public key не настроены, router URL loopback, peers=0. Нужны свой provider, 2→8→32 peer handshake, DNS/MTU/UDP throughput и management recovery. Plain-control тест не объявлять VPN acceptance. |
| **F32-22: native capacity** | Два Android 9 boot/root capture/OTA/reconnect приняты в предыдущих bounded tests | 32 уникальных device identities; не клонировать зарегистрированные app data. CPU/RAM/GPU/decoder/network профили каждой станции, APK и browser. Длительная память с видео+tasks, capture start/stop, отсутствие ANR/crash и неожиданных PID changes. Другие Android/OEM/физические телефоны — отдельная матрица. |
| **F32-23: data/recovery** | SQL durable task intents, APK pending journal + compact ACK receipts, Redis reconnect fixes и tenant tests | Worker/SQL/Redis failure в разных точках admission/result/ACK, partial fleet reconnect, неизвестный commit outcome. Scheduler tick concurrency, PAUSED/cancel/resume и pinned script version. Retention task/step/log/artifact/ACK с query plans; restore и disk pressure. Non-owner runtime role/RLS для всех фоновых writers проверять отдельно до её rollout. |
| **F32-24: AI readiness** | Capture, DAG, remote input, server routing уже дают основу | Frame epoch/sequence/capture-age, latest-frame consumer, action ID/deadline/ACK, controller lease, stale-action rejection и safe release held input. Не реализовывать inference до приёмки транспорта. |

Общее ограничение: один Docker host, один PostgreSQL и один Redis не являются HA.
Для первого 32-device стенда не требуется срочно строить кластер. Требуются честный
режим деградации, сохранность SQL intent, ограниченные очереди и доказанное восстановление.
Внешний ingress не лечит падение единственного backend/хоста.

## Профиль нагрузки и будущий AI-контур

Текущие encoder defaults дают номинально **32 × 1.5Mbps = 48Mbps**, 64 → 96Mbps
для одного направления потока. Это арифметика конфигурации, **не измеренный трафик**:
ABR/изменения экрана, transport overhead, повторные передачи и несколько viewers
меняют результат. Сервер принимает и отдаёт видео; cross-worker Redis fanout добавляет
внутренний трафик. 32 × 1280 × 720 × 30 ≈ **885 млн pixel/s** декодирования при
полном движении, ещё без композиции. Пропускная способность сети не доказывает
достаточность GPU/browser.

Начальный профиль для эксперимента, не обещание производительности:

| Потребитель | Предлагаемый контракт | Что измерить |
| --- | --- | --- |
| Сетка 32 | Preview 360–540p, 5–10fps, ориентир 0.4–0.8Mbps; параметры видимы и подтверждены APK | Фактический bitrate/качество текста, decode/render age, CPU/GPU, очередь и память; ориентир 12.8–25.6Mbps на одну ногу до overhead |
| Открытый крупный экран | 720p, 15–30fps по требованию; один захват устройства с согласованным профилем | Время переключения, input ACK, влияние focus на остальные 31 плитку |
| Будущий AI | Около 2 observations/s/device: 64 observations/s на 32, 128 на 64; pending latest-frame slot, без очереди устаревших наблюдений | Capture age в момент inference/action, preprocessing и transfer, dropped obsolete frames; UI viewer count не должен определять доступность AI |

Наблюдение 2fps не означает автоматически низкую стоимость: если для него всегда
декодируется полный 30fps поток, работа уже выполнена. Выбор общего decode service,
кадрового endpoint или другого media transport делается после профилирования.
Не следует сейчас переносить весь проект на WebRTC или строить отдельную AI-платформу
без измерения существующего узкого места.

Для будущего управления необходимо отделить:

1. **Задание:** durable DAG, сохранённый результат и reconciliation.
2. **Наблюдение:** кадр с возрастом и epoch; старые кадры можно выбрасывать.
3. **Действие:** ordered bounded control, ID, deadline, accepted/completed/unknown,
   исключительное владение человеком/ботом и release удерживаемых кнопок при отказе.

Нельзя повторять движение «вперёд» после неизвестного исхода так же, как безопасный
GET. Нельзя отдавать две секунды накопленных команд после reconnect. Текущие
`touch_tap/touch_swipe` fire-and-forget ветки APK этого контракта не предоставляют.
Более общий план: [AI readiness](../../architecture/AI-READINESS.md); здесь уточнены
требования для 32/64 и свежести данных, интеграция модели не выполнена.

## Порядок исправлений и допуска

1. **Остановка и сохранность работы:** F32-01–05. Малые атомарные fixes с failing
   regression → fix → retest; общий lease/intent design согласовать в коде и схеме,
   не маскировать потерю работы переводом всех RUNNING в QUEUED.
2. **Экран и управление:** F32-06–08. Ограничить память/возраст кадров, внедрить
   применяемый preview profile и измерения. Проверить две реальные APK, затем 4/8/16.
3. **Ресурсы и наблюдение:** F32-09/10/17/18. Redis budget, достоверные метрики,
   project-scoped monitoring, лог-ротация, проверенный backup/restore.
4. **Приёмка 32:** F32-19/22/23. Отдельный контролируемый ramp 4→8→16→32 и конечный
   8h профиль с real browser decode, задачами и согласованными fault windows.
   Полную 8h baseline на двух APK после последних video fixes также довести до конца.
5. **Смежные режимы:** F32-11/12/20/21 до объявления WAN+VPN отказоустойчивым;
   F32-14 до fleet OTA, F32-15/16 до station automation/n8n. Во время основного
   load test держать версии фиксированными и не включать непринятые режимы.
6. **После 32:** F32-13 в части сетки 64, profiling 64, затем отдельная AI-интеграция
   F32-24. Косметика UI и game-specific плагины не опережают эти задачи.

### Матрица обязательного испытания

| Сценарий | Критерий и evidence |
| --- | --- |
| Старт парка 4/8/16/32 | Уникальные identity, правильная версия/route; все зарегистрировались самостоятельно; время подключения каждого устройства |
| 32 живые плитки + batch/pipeline | Safe Android UI motion, реальные decoded/rendered кадры каждого устройства, terminal task/step receipts в APK и API; статичный экран не считать frozen только из-за низкого FPS |
| Несколько viewers / focus / закрытие | Один viewer не вытесняет другой; после последнего освобождён capture; нет постоянно растущих queues/memory |
| Android-side outage / server-side outage / оба | Раздельно и совместно, с восстановлением в разном порядке; автоматический auth+command+fresh video без F5/ручного IP/переустановки |
| Worker crash / PostgreSQL unavailable / Redis restart | No blind replay; неопределённый исход явно виден; после recovery нет orphan RUNNING, двойных внешних действий и потерянных saved receipts |
| Slow network / decoder overload | Система выбрасывает устаревшее видео и восстанавливается с keyframe; input/result delivery измеряются отдельно от transport ping |
| Emergency stop | Подтверждена фактическая остановка всех принятых заданий; offline устройство остаётся cancelling/unknown, не ложно stopped |
| Конец 8h | Runner terminal status, independent API reconciliation, PID/process start + crash/ANR diff, final resource sample; running никогда не считается passed |

**Предлагаемые исходные бюджеты, пока не результаты:** после установления исправного
маршрута command+fresh video recovery p95 ≤30s и каждое устройство ≤90s; первый
кадр при уже online устройстве p95 ≤3s; при движении frame age p95 ≤500ms и p99 ≤1s.
LAN и реальный WAN измерять раздельно; синхронизацию часов и её погрешность сохранять.
Для управления фиксировать accepted и completed отдельно; начальный ориентир
accepted p95 ≤750ms на согласованном WAN-профиле, дальнейший AI budget уточнять
по настоящему control loop. Время возврата самого provider/публикации нового адреса
в эти 30s не прятать: это отдельная составляющая полной недоступности.

**Stop conditions:** новый Sphere crash/ANR, неожиданный PID change, потерянный
receipt, необъяснимый дубликат эффекта, orphan execution, OOM либо длительное
нарастание очереди. Сохранить последние evidence и остановить допуск новой работы;
не скрывать ошибку автоматическим перезапуском всего стенда. Для памяти важны
плато после прогрева и возврат после stop, а не один удачный snapshot.

## Что этот документ меняет

Это актуальный перечень работ перед 32-device тестом; он дополняет исторический
audit report, а не переименовывает прошлые failed runs в passed. В этом срезе
сохранены диагностические пробы и evidence, **production code fixes не внесены**.
Каждый пункт закрывается отдельным исправлением, regression и подходящей native
приёмкой. Процент «всё почти готово» или срок по числу коммитов не выводится:
основная неопределённость — video capacity конкретных станций/браузера и поведение
при отказах с параллельной работой.

### F32-25 — pipeline-worker без tenant context не видит очередь

**21 сентября · P0 / High / воспроизведено · source fix AUD-133, runtime gate OPEN.**

[AUD-133](PIPELINE-RLS.md) реализует контракт ниже и сохраняет regressions для
startup, heartbeat, recovery, cancellation и pool isolation. Описание причины
и первоначальной пробы ниже относится к состоянию до исправления.

**Root cause:** `PipelineExecutor._poll_and_dispatch`, recovery и cancellation
создают обычные `AsyncSessionLocal` без trusted tenant context. Policy требует
`app.current_org_id`. Под non-owner ролью запрос успешно возвращает пустую очередь;
ошибки SQL нет, admission не начинается. Owner/dev tests этого не показывают.

**Evidence:** [отдельная diagnostic probe](evidence/pipeline_rls_probe.py) создала
QUEUED run в случайной fixture organization, вызвала настоящий executor с реальной
non-owner/NOBYPASSRLS ролью и затем сверила запись через owner: статус остался QUEUED,
tasks executor пусты. **1 ожидаемый failure**, это не пройденный regression и не
часть обычного passing `tests/` набора. Сырые логи приватные; результат сохранён
рядом с [AUD-132 evidence](evidence/batch-recovery.json).

**Affected files:** `backend/services/orchestrator/pipeline_executor.py`,
`pipeline_recovery.py`, startup selection; другие unscoped background workers
требуют такого же отдельного анализа. Это ограничение source-приёмки AUD-131.

**Fix / regression:** ограниченный discovery ожидающей/recoverable работы и
отдельная tenant-bound session на каждом этапе claim/renew/reconcile/write;
проверить startup/restart/cancel под настоящей runtime ролью и pool reuse между
двумя tenants. Не отключать RLS и не выдавать BYPASSRLS для обхода проблемы.

**Residual:** AUD-132 реализует контракт для batch admission, AUD-133 — для
pipeline. Остальные workers требуют отдельной проверки. Pilot на старой
dev-конфигурации не подтверждает работоспособность production DB-role.
Полный migration/runtime-role canary обязателен до заявления о готовности.

**Продолжение F32-25, scheduler (source fix AUD-136):** на неизменённом `scheduler_engine.py`
базы `294bd15` реальная non-owner роль не отключает due schedule с уже достигнутым
`max_runs`: после `_tick` оно остаётся active. Причина — тот же unscoped startup
SELECT. [Одна failing probe и ограничения](evidence/scheduler-rls.json),
[исходник](evidence/scheduler_runtime_probe.py). Android-задания не создавались.
Последующий [AUD-136](SCHEDULER-RUNTIME.md) исправляет эту RLS-видимость,
атомарность firing, обработку недоступного presence и conflict/interval defects.
Семь regressions упали до fix, 86 связанных tests после прошли. Миграция,
worker grant и native rollout остаются gates; исходная failing probe сохранена.

**Task dispatcher также воспроизведён:** unscoped poll оставляет Task в QUEUED,
transport calls=0. После tenant binding под той же non-owner ролью тот же Task
становится ASSIGNED, transport double calls=1. [Evidence](evidence/dispatcher-rls.json),
[probe](evidence/dispatcher_runtime_probe.py). Это подтверждённый P0 доставки,
не Android/network тест. Последующий [AUD-135](TASK-DISPATCH-RLS.md) исправляет
dispatch/cancellation через bounded discovery и tenant-bound sessions, а также
регистрацию worker без Redis на старте. Три failing startup regressions до fix →
101 связанных passing tests, включая реальный SQL timeout, lost commit ACK,
две организации, два workers и 64 offline devices перед online. Source-only;
scheduler RLS исправлен последующим AUD-136; native/runtime-role acceptance открыта.

**Продолжение F32-25 — watchdog (source fix AUD-137):** реальная non-owner роль после
`_expire_stale_tasks` сохраняет двухчасовой QUEUED task без изменений при лимите
60 минут. Контрольный вызов под той же ролью с tenant binding переводит его в
TIMEOUT. [Evidence](evidence/watchdog-rls.json), [probe](evidence/watchdog_runtime_probe.py).
Один ожидаемый failure вне стандартного CI; никаких заданий APK/Redis effects.
Последующий [AUD-137](WATCHDOG-STOP-RECOVERY.md) реализует bounded discovery/scoped
обработку. До fix ещё два regressions подтвердили: timeout ASSIGNED/RUNNING
разрешал выдачу следующего DAG до физического результата. Теперь сохраняется stop
intent и execution fence; TIMEOUT delivered задачи требует terminal APK receipt.
Старая диагностическая проба относится к прежнему source; текущий контракт проверяют
22 новых tests в passing suite. Native stop/reconnect и legacy TIMEOUT reconciliation OPEN.


### F32-26 — задержка отмены внутри долгого sleep

Native canary `c42bb5b`, APK 1.2.8: отмена 10-секундного sleep завершается примерно
через 10 секунд после stop, хотя intent уже принят. При сетевых пробах задержка
stop → terminal достигала примерно 70 секунд (включая восстановление транспорта).
[Сценарии, точные latency samples и root cause](CANARY-20260921.md#найденное-ограничение-f32-26).
`DagRunner.executeNode(sleep)` ждёт полный delay без cancellation checkpoint;
последующий эффект не выполняется, SQL fence остаётся до terminal результата.
Нужен bounded cooperative wait и regression на latency/no-next-effect; fix открыт.
Нельзя ускорять UI фиктивным CANCELLED или отпускать устройство раньше APK.
