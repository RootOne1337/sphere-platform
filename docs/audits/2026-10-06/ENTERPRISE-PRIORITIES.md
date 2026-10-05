# Приоритеты оставшихся работ и следующий подтверждённый дефект

**Дата:** 6 октября 2026, Asia/Yekaterinburg. **Исходники:** `32c97b8`.
**Приёмка:** 9 принято / 41 с открытыми критериями из исходных 50 работ.
Это пересортировка эксплуатационного порядка, а не изменение immutable baseline,
первоначальных P1/P2 или критериев приёмки. Пункты имеют разный размер: 41 не означает
41 маленький дефект или 41 коммит. Существующие частичные реализации сохраняются.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Исходные 50 требований](../2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json) ·
[Последний установленный мониторинг](../2026-10-05/ENTERPRISE-FLEET-COVERAGE.md).

## Почему не продолжать только добавлять метрики

Ограничения ресурсов, доставка обновлений и управляемость выбранного устройства
влияют на возможность обслуживать парк. Дополнительные графики не заменят эти
проверки. Поэтому EP-033/047 идут перед самостоятельным metrics producer EP-010.
Зависимость всего EP-033 от EP-032 в исходном плане остаётся: ограничить нынешний
single-device read можно отдельно, не дожидаясь общего журнала всех источников.

Нельзя объявлять заполнение Windows-диска диагностированным: предыдущие 241 срез
показали снижение свободного C: на 2,154 GiB при стабильном allocated Docker VHD.
Writer остаётся UNKNOWN. Новая проверка относится к heap одного запроса backend;
она не доказывает долговременную утечку, источники роста VHD или host commit.
Не запускаются новый бесконечный обход, массовое обновление APK, очистка истории
или перераспределение данных. Удаление старых логов/quota policy — отдельная часть.

## Подтверждённая проблема EP-033, часть A

Контракт исправления, budgets и открытые границы отдельно:
[ограниченное чтение логов](DEVICE-LOG-READ-BUDGET.md).

`get_device_logs` читает до трёх дневных файлов через `Path.read_text` и строит
общий список всех строк. Ограничение `lines` применяется после выделения памяти;
поиск также выполняется над полностью прочитанным архивом. Работа выполняется
синхронно в async HTTP handler, задерживая event loop.

[Изолированный воспроизводимый probe](../../../scripts/audit/probe_log_read_budget.py)
создал три временных файла по 8 MiB и запросил 1000 строк. Авторизация заменена
fixture; настоящие устройства, БД и Redis не используются. Временные файлы удалены.

Результат исходного reader: прочитано **25165824 bytes**,
Python tracemalloc peak **48271208 bytes** (примерно
46.04 MiB). Получено 1000 строк. Это Python
traced allocations за вызов, не полный RSS процесса и не замер ОС.
[Исходный receipt](evidence/log-read-budget/before.json).

Следующий контракт: конечный byte budget чтения и ответа; целые строки с явным
исключением слишком длинных строк; bounded admission без растущей очереди; файловый
I/O вне event loop; строгая дата/размер поиска; UI показывает границы tail/search и
частичность. Ошибка чтения не превращается в «логов нет». Не меняется tenant/RBAC.
Глобальная org/disk quota, независимый sweeper и forecast/drop counters остаются
открытыми. EP-033 целиком не принимается только по этому исправлению.

## Эксплуатационная безопасность и ресурсы

| ID | Исходный приоритет | Открытое требование |
|---|---|---|
| EP-033 | P1 | Byte-bounded backend log reads и global retention |
| EP-047 | P1 | Общая matrix500/1000 иresource leak gates |
| EP-041 | P1 | Release rollout receipts и каналы |
| EP-029 | P1 | Selected video end-to-end диагностика и управление |
| EP-031 | P1 | Thumbnail wall 128 вместо множества full video |
| EP-050 | P1 | Alert delivery иsynthetic Android SLI |

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
| EP-048 | P1 | Тесты всех меню/форм/ролей иvisual states |
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
Ни совпадение SHA, ни зелёный CI сами по себе не являются подтверждением этих gates.
Не делается неизвестный массовый rollout или нагрузочный тест на рабочем парке.

## Воспроизведение

```powershell
python -m scripts.audit.probe_log_read_budget --output .local-pilot/log-probe.json
```

Probe генерирует 24 MiB только во временной директории и удаляет её до сохранения
малого receipt. Проверяет content hash последних 1000 строк; не публикует их.
Для исправленного reader отдельный запуск `--expect-bounded` требует метаданные
budget и отсутствие whole-file read. Замер не используется как нагрузочный SLA.
