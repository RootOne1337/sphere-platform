# Приоритеты оставшихся работ и следующий подтверждённый дефект

**Дата:** 6 октября 2026, Asia/Yekaterinburg. **Baseline reader:** `32c97b8`; **установленные API/UI:** `eb7a7c26` / `1c26ffc7` (UI 11:50 UTC).
**Приёмка:** 9 принято / 41 с открытыми критериями из исходных 50 работ.
Это пересортировка эксплуатационного порядка, а не изменение immutable baseline,
первоначальных P1/P2 или критериев приёмки. Пункты имеют разный размер: 41 не означает
41 маленький дефект или 41 коммит. Существующие частичные реализации сохраняются.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Исходные 50 требований](../2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json) ·
[Последний установленный мониторинг](../2026-10-05/ENTERPRISE-FLEET-COVERAGE.md).

## Конструктор по запросу пользователя: редизайн и лаборатория установлены

Поверх этапа A установлен [редизайн](STUDIO-REDESIGN.md) с каталогом, формами,
локальным ELK, читаемыми узлами и одним выбранным Android. В лаборатории есть
живая запись отправленных click/swipe/wheel, вставка свежего XPath и наблюдение
задания закреплённой версии; это частичная реализация EP-017/018/019, не их приёмка.
Исправлены pending-launch ownership, потеря полей через Undo и terminal telemetry.
Исторический редизайн: 1451 frontend tests / 125 suites, types/build и native показ прошли. Два канареечных
задания одной remote PH025 v1 start/sleep4000/end завершились с 3 успешными отчётами;
финальные UI-коррекции не создавали третьего задания. Счёт **9 / 41** не изменён.

Подтверждённый P1 [полных DAG в каталоге](STUDIO-REDESIGN.md#source-review-catalog-payload-retention-remains-open-p1)
получил установленный функциональный контракт: `GET /scripts/catalog`, persisted
version/hash/node_count и lazy detail закреплённой версии. Прямые известные writers
переведены на append-version publisher, старые in-place SQL-патчи прекращают работу.
Tenant backfill/reconcile обработал 25 версий / 22 сценария без изменения исходников,
указателей, дат или 445 заданий. Неизвестный внешний SQL writer пока не блокируется
DB-trigger, поэтому готовность других организаций требует собственных receipts.

[Доставка](SCRIPT-CATALOG-DELIVERY.md) · [Контракт](SCRIPT-CATALOG-METADATA-CONTRACT.md) ·
[Pinned evidence](SCRIPT-CATALOG-EVIDENCE.json) · [Инструкция](../../operations/SCRIPT-CATALOG.md).
Fixture 100 сценариев × 500 узлов: 85176 bytes catalog против 48889157 bytes legacy,
одна SQL-команда без DAG/hash materialization. Живой all-каталог: 22 строки /
14037 bytes против 34553 bytes. 171 source tests с shipped dependencies, final migration
test и 1506 frontend tests / 126 suites прошли; exact images собраны и установлены.
Native QA фиксируется в evidence отдельно от тестов. **P1 остаётся открытым по
производительности:** нужны p95/CPU/RSS/query buffers/browser heap и load/soak,
а не только payload. Это исправление не устанавливает причину host memory/storage роста.
Первая установка автоматически откатилась из-за эквивалентных Windows bind-path;
после проверки папок и прав повторная сохранила 44 соседа. Fleet-срезы 14/5 → 9/10 →
10/9 → 14/5 (контрольный GET 07:41:18 UTC) записаны, они не обещают отсутствие reconnect. APK/OTA/туннели не менялись,
новых Android команд не отправлялось. Счёт **9 / 41** остаётся прежним.

Все четыре source CI исторического UI `a670a3df` завершились success:
[receipt](evidence/studio-redesign/source-ci.json). Отдельный актуальный срез
подтвердил четыре успешных source workflow `eb7a7c26`: backend, frontend,
Android и Preview; он сохранён в [catalog evidence](SCRIPT-CATALOG-EVIDENCE.json).
Результат не переносится автоматически на последующий документационный head
и не доказывает hosted deployment.

Далее: EP-016 versioned schemas/capability preflight, EP-015 conflict diff и sidebar
dirty route blocker, EP-018 text/navigation/selector recording, durable launch
reconciliation, EP-019/020 agent-correlated trace/replay. Они не заменяют общие
resource, release и fleet load/soak gates. VPN-протоколы и проектные базы данных
остаются отдельными будущими этапами.

### Исторические результаты этапа A

Рабочий [Script Studio на 3015](http://127.0.0.1:3015/scripts/builder): граф ↔ JSON,
32 action templates, полный JSON параметров узла, bounded undo/draft/import/export,
серверная draft validation и запуск сохранённой версии с явным выбором устройств.
Реальный start/sleep 2000 ms/end canary сохранён, повторно открыт и выполнен только
на remote PH025: completed, 3/3 reports, v1/hash совпали. Exact API image 631 tests;
frontend 1353 tests / 122 suites, production build/types и native themes/390px layout
проверены. Счёт **9 / 41** сохраняется: EP-014…020 ещё имеют открытые критерии.

На момент этапа A впереди были EP-015 version-conflict diff и защита dirty navigation,
EP-016 versioned action schemas/limits/effects и APK preflight, EP-017 live picker,
EP-018 recorder и trace/replay/debug EP-019/020. Текущая частичная реализация указана
выше. Эти зависимости не заменяют resource/release gates ниже. Один sleep-canary не доказывает все runtime actions,
автономную миссию, uptime, исправление утечки или нагрузку 20–30/500/1000 устройств.
Offline inventory подтвердил 32 API/UI types и 33 Android handlers (`loop` не
публикуется); четыре неверно параметризованных known actions проходят только
структурную schema. Это конкретные основания EP-016, не live exception proof.
[Результат и все ограничения](SCRIPT-STUDIO-FOUNDATION.md) ·
[Инструкция](../../operations/SCRIPT-STUDIO.md) · [Pinned evidence](SCRIPT-STUDIO-EVIDENCE.json).

## Новый runtime дефект, выявленный установленным canary

[PH011 получила APK 1.2.46](ANDROID-CLEAR-INSTALLED.md) с сохранением данных.
Одно задание completed 25/25 подтвердило полную очистку и clear-first replacement
через последующие XPath asserts. Это следующий этап после исторического helper-only
proof; старый build receipt сохранён. Общий счёт **9 / 41** не изменён.

Screenshot action создаёт PNG в `/sdcard`, не ограничивает накопление и ждёт blind
300 ms. Node success не сопровождается server artifact: manifest пуст. Подтверждены
original PNG, hash match и адресный cleanup. Перед дальнейшим EP-016 делается
ограниченный срез EP-047/019: capture ACK, валидация PNG и локальные count/byte/age
budgets. Task upload/replay и причину host disk-growth этим не закрываем.

## Почему не продолжать только добавлять метрики

Следующий этап EP-018: [запись key/text и подтверждения APK](STUDIO-COMMAND-RECORDING.md).
Установленный UI теперь связывает AndroidNavigationBar с лабораторией: исходная отправка,
отдельный результат APK, блокировка pending/unknown при переносе, review/delete
и auth-session isolation. **1546 tests / 128 suites**, types/build и четыре source CI
прошли; Preview deploy skipped. UI-only установка сохранила API/APK/туннели и 45
соседних контейнеров. Через native browser записаны кнопки и текст, с явными
Settings prerequisites сохранена одна v1 и выполнено одно remote PH025 задание:
**10/10** успешных отчётов. Темы и 1280/390 px проверены; это не latency/FPS/soak.
[Pinned evidence](STUDIO-COMMAND-RECORDING-EVIDENCE.json) сохраняет точные revisions,
version/hash/task, native JPEG и отдельные source/runtime результаты.
EP-018 не закрыт: automatic selector candidates и prerequisites остаются впереди.
Дополнительно найден P1 в APK: `input_clear`/`clear_first` путают CUT 277 с CTRL_A;
[source fix и candidate 1.2.46](ANDROID-FOCUSED-TEXT-CLEAR.md) используют root chord
и ограниченный ACK прежней FIFO-сессии. По 855 passed / 1 assumption-skipped в
двух debug flavors, четыре source CI, signer/ZIP/DEX и native SDK28 helper прошли.
Исходное поле очистилось с курсором внутри; пустой повтор и follow-up input прошли.
APK **не установлен/не опубликован OTA**: полный installed-agent canary, другие
SDK/editors и rollout остаются впереди. Recorder по-прежнему не вызывает неявную
очистку. [Pinned evidence](ANDROID-FOCUSED-TEXT-CLEAR-EVIDENCE.json).
Пересоздание одного повреждённого generated class зафиксировано отдельно;
причина host corruption и writer неизвестны. Общий счёт 9 / 41 сохранён.

Ограничения ресурсов, доставка обновлений и управляемость выбранного устройства
влияют на возможность обслуживать парк. Дополнительные графики не заменят эти
проверки. Поэтому EP-033/047 идут перед самостоятельным metrics producer EP-010.
Зависимость всего EP-033 от EP-032 в исходном плане остаётся: ограничить нынешний
single-device read можно отдельно, не дожидаясь общего журнала всех источников.

Нельзя объявлять заполнение Windows-диска диагностированным: предыдущие 241 срез
показали снижение свободного C: на 2,154 GiB при стабильном allocated Docker VHD.
Writer остаётся UNKNOWN. Новая проверка относится к heap одного запроса backend;
она не доказывает долговременную утечку, источники роста VHD или host commit.
Не запускаются новый бесконечный обход, массовое обновление APK или очистка истории.
Небольшая адресная миграция 14 файлов логов описана отдельно с backup/hashes; она не
является массовым переносом host datasets. Удаление/quota policy — отдельная часть.

## Подтверждённая проблема EP-033, часть A

Контракт исправления, budgets и открытые границы отдельно:
[ограниченное чтение логов](DEVICE-LOG-READ-BUDGET.md).

Исторический `get_device_logs` в `32c97b8` читал до трёх дневных файлов через `Path.read_text` и строил
общий список всех строк. Ограничение `lines` применялось после выделения памяти;
поиск также выполнялся над полностью прочитанным архивом. Работа выполнялась
синхронно в async HTTP handler, задерживая event loop.

[Изолированный воспроизводимый probe](../../../scripts/audit/probe_log_read_budget.py)
создал три временных файла по 8 MiB и запросил 1000 строк. Авторизация заменена
fixture; настоящие устройства, БД и Redis не используются. Временные файлы удалены.

Результат исходного reader: прочитано **25165824 bytes**,
Python tracemalloc peak **48271208 bytes** (примерно
46.04 MiB). Получено 1000 строк. Это Python
traced allocations за вызов, не полный RSS процесса и не замер ОС.
[Исходный receipt](evidence/log-read-budget/before.json).

Установленный контракт `5405d465`: конечный byte budget чтения и ответа; целые строки с явным
исключением слишком длинных строк; bounded admission без растущей очереди; файловый
I/O вне event loop; строгая дата/размер поиска; UI показывает границы tail/search и
частичность. Ошибка чтения не превращается в «логов нет». Не меняется tenant/RBAC.
Storage-коммит `9889c9ac` добавил постоянный том и перенёс 14 файлов со сверкой SHA256;
две неудачные попытки и rollback описаны, поздний срез 11 online вместо 14 сохранён.
Global org/disk quota, независимый sweeper и forecast/drop counters остаются
открытыми. EP-033 целиком не принимается только по этому исправлению.

## EP-033, часть B: intake и writer установлены

[Ограниченный upload](DEVICE-LOG-UPLOAD-BUDGET.md) установлен в backend `76596c39`:
512 KiB инкрементального приёма, 60 s total ASGI deadline, четыре uploads на worker
с фиксированным writer executor. Oversize не буферизуется целиком; FS lifecycle
вынесен из event loop. Exact image прошёл 572 tests, mypy/Ruff/OpenAPI check.
14 исходных prefixes сохранены; 45 соседних контейнеров не заменены. Live declared
и chunked requests вернули 413, новые upload separators появились в пяти файлах.
Срез 14 online / 5 offline не доказывает непрерывную стабильность.
Следующие gates EP-033: общие квоты, независимая очистка, rotation/delete concurrency,
restore и leak/load acceptance. Общий счёт **9 / 41** не меняется; host writer неизвестен.

## Эксплуатационная безопасность и ресурсы

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-033 | P1 | Byte-bounded backend log reads и global retention |
| EP-047 | P1 | Общая matrix 500/1000 и resource leak gates |
| EP-041 | P1 | Release rollout receipts и каналы |
| EP-029 | P1 | Selected video end-to-end диагностика и управление |
| EP-031 | P1 | Thumbnail wall 128 вместо множества full video |
| EP-050 | P1 | Alert delivery и synthetic Android SLI |

## Достоверная диагностика и поиск инцидента

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-028 | P1 | Явный device/agent telemetry scope и inventory |
| EP-032 | P1 | Общие structured logs всех разрешённых sources |
| EP-022 | P1 | Task detail: полные outcomes и artifacts |
| EP-010 | P1 | Активные tunnels и fleet metric coverage |
| EP-044 | P1 | VPN assigned/applied/handshake/egress outcomes |
| EP-034 | P2 | Audit journal semantic outcome и redacted diff |

## Безопасное создание и отладка автоматизации

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-014 | P1 | Studio canonical AST и отдельный layout |
| EP-015 | P1 | Studio source schema, drafts, conflict и undo |
| EP-016 | P1 | Studio каталог всех runtime actions |
| EP-017 | P1 | Live device picker и capability preflight в Studio |
| EP-018 | P1 | Запись Android input и selector candidates |
| EP-019 | P1 | Пошаговый trace и replay с frame correlation |
| EP-020 | P1 | Server/agent debug pause, step, cancel и safety |
| EP-021 | P1 | Объединить automation workspace и references |
| EP-025 | P1 | Webhook attempts/outbox и совместимость доставки |
| EP-023 | P2 | Schedules: timezone, missed fire и next run explain |
| EP-024 | P2 | Triggers: безопасная simulation и feedback loop limits |

## Работа оператора с большим парком

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-011 | P1 | Версионировать все browser table/view preferences |
| EP-012 | P1 | Расширить registry typed columns и пресеты |
| EP-048 | P1 | Тесты всех меню/форм/ролей и visual states |
| EP-049 | P1 | Документация source/runtime/schema freshness |
| EP-035 | P2 | Dashboard attention queue и actionable drilldown |
| EP-040 | P2 | Configuration effective state и разделение policies |
| EP-039 | P2 | Users role preview, safety и access review |
| EP-036 | P2 | Groups membership и bulk plan |
| EP-037 | P2 | Locations hierarchy UX и validation |
| EP-038 | P2 | Discovery capability-scoped onboarding |
| EP-027 | P1 | Inspector tree, selectors, freshness и performance |
| EP-030 | P2 | Original PNG и matching asset provenance |
| EP-013 | P2 | Единые tokens, preferences и icon semantics |

## Расширение платформы после проверок основы

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-026 | P2 | Typed datasources и project manifest |
| EP-042 | P2 | Generic resources вместо game domain assumptions |
| EP-043 | P2 | Разделить account session и universal run |
| EP-045 | P2 | Versioned VPN provider adapters и rotation |
| EP-046 | P2 | AI-ready schemas/runbooks и scoped artifacts |

## Отдельные обязательные release gates

Восстановление после process/host reboot, обрыва сети и потери ответа; refresh и
OTA на удалённой сети; контроль signer/version/hash; отсутствие повторного
необратимого действия; backup/restore, migration и rollback; смешанный прогон
stream+script на реальном доступном парке. Эти условия могут быть важнее отдельной
UI-возможности и не сводятся к числу закрытых 50 продуктовых работ.

Новый UI остаётся на 3015, публичный 18080 имеет отдельную историю установки.
Current source CI ещё не all-green; совпадение SHA или будущий зелёный CI сами по
себе не являются подтверждением этих gates. Native frame/route diagnostics после
сохранения APK logs важнее расширения декоративных панелей; historical parser
warning не выдаётся за доказанную общую причину сетевых обрывов.
Не делается неизвестный массовый rollout или нагрузочный тест на рабочем парке.

## Воспроизведение

```powershell
python -m scripts.audit.probe_log_read_budget --output .local-pilot/log-probe.json
```

Probe генерирует 24 MiB только во временной директории и удаляет её до сохранения
малого receipt. Проверяет content hash последних 1000 строк; не публикует их.
Для исправленного reader отдельный запуск `--expect-bounded` требует метаданные
budget и отсутствие whole-file read. Замер не используется как нагрузочный SLA.
