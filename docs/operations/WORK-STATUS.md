# Работы, требования пользователя и границы приёмки

**Проверенная установка:** UI `d70f55c6` / API `d720232e`.

**9 октября: разрешён и написан первый direct RTT canary.** Браузерный WebRTC,
серверное межпроцессное согласование и отдельный Android debug source set готовы
для испытания. По умолчанию отключён; Android JNI не входит в обычные сборки.
Видео/касания на рабочей установке остаются WS; живой direct RTT ещё не измерен.
[Scope, проверки и rollout gates](../audits/2026-10-09/DIRECT-PROBE-SOURCE.md).

**9 октября: UI d70f55c6 установлен на 3015 и выбранном публичном адресе.**
Повторная idle-потеря ACK отличается от неизвестного результата касания; held/terminal
unknown, остановка input и прежние deadlines сохранены. Исправлен контраст статуса
в светлой теме. 1950 frontend tests / 139 suites, types/build прошли.
Конечная браузерная проверка приняла только wording/контраст и показ транспорта;
idle timeout повторился, его причина и задержка остаются UNKNOWN/OPEN.
[Установка и проверка](../audits/2026-10-09/IDLE-CONTROL-UX-INSTALLED.md) ·
[Исходное воспроизведение и границы](../audits/2026-10-09/IDLE-CONTROL-RELAY-REVIEW.md) ·
[Исследование прямого транспорта](../design/BROWSER-DIRECT-TRANSPORT.md).

**9 октября: дополнительная проверка туннеля нашла и исправила Grafana.**
На публичном адресе большие JS давали parse errors; на3015 dashboard работал.
Адресный gzip static-assets установлен graceful reload без replacement46контейнеров.
Два повторных открытия дали реальные панели без новых console errors;
22страницы, deep-link/F5, JSON export и ELK worker проверены. PH011 получил6кадров,
но steady FPS/control не приняты. Product9/41 сохранён.
[Доказательства и границы](../audits/2026-10-09/PUBLIC-WEB-SUPPLEMENTAL-QA.md).

**Первоначальная доставка 9 октября, 15:53 UTC:** публичный UI синхронизирован с 3015.
На том срезе Tuna-host показывал UI86354350/API d720232e. Вход, каталог22сценария, builder и мониторинг
проверены; временный monitoring failure сохранён. Все46 контейнеров и API/WS/
bootstrap сохранены, новых images нет. Public stream/control/soak не приняты,
9/41 не меняется. [Receipt](../audits/2026-10-09/PUBLIC-WEB-DELIVERY.md).

Сверено **9 октября 2026 (UTC+5)**. Это действующий указатель статусов; машинный
источник — [STATUS-REGISTRY.json](STATUS-REGISTRY.json). Установка и runtime:
[CURRENT-STATE](CURRENT-STATE.md). Критерии эксплуатации: [READINESS](READINESS.md).
Предыдущая [подробная сверка чата и кода](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md)
сохранена как датированный срез. Она не переписывается при изменении этого списка.

## Что означают числа и насколько велика работа

**9 принято / 41 открыто из 50** — продуктовый план. Принятое означает только
scope доказательств конкретного пункта. В исходном аудите было шесть подтверждённых
дефектов; все шесть имеют записанную приёмку EP-001–006. Остаток включает расширение
возможностей, дизайн и будущие подсистемы. Новые дефекты могут возникать внутри
частично выполненного пункта: пример — clock regression рекордера и idle timeout.

**34 source-fixed / 7 незакрытых из 41** — отдельный старый веб-аудит. Три из семи
PARTIAL, четыре OPEN. Это не дополнительные семь независимых задач поверх 41.
«Два» в предыдущем сообщении означало два коммита, отдельного реестра из двух проблем нет.
Resource/Fleet32 admission имеет отдельные gates и также не складывается с продуктовым счётчиком.

Приоритет P1/P2 сохранён из baseline. Масштаб S/M/L/XL — инженерная оценка оставшегося
охвата, не срок и не severity: S — локальный фикс, M — отдельный workflow,
L — несколько слоёв/проверок, XL — новая подсистема или большой нагрузочный этап.
У принятых строк это оценка исходного объёма, а не оставшаяся работа.

## Сначала закрыть риски эксплуатации

1. **Диск и ОЗУ (EP-033/047):** limited observation возобновлено9Oct12:42UTC
   до10Oct12:42UTC: 721×120s/16MiB,24named files и RAM/Docker/WSL; complete
   samples и process epoch проверены. Прежний разрыв не покрыт, whole-PC writer
   UNKNOWN: VSS/USN/kernel evidence недоступны. Большой VHD не доказывает writer;
   reboot/deadline останавливают сбор, resource soak/retention ещё нужны.
   [Окно и границы](../audits/2026-10-09/STORAGE-OBSERVER-RESTART.md).
2. **Idle control (EP-020/029):** PH011 native_receipt_timeout повторился
   с heartbeat512ms/tick15ms/WS OPEN0B/lastACK RTT248ms. Снимок сохраняет
   доказательство, участок задержки server/APK/native/reverse path пока неизвестен.
   UI86354350 установил snapshot и доступную desktop/phone панель диагностики.
   Deadline/replay не менялись; необходимы корреляция, исправление и повторная canary.
   [Receipt и границы](../audits/2026-10-09/STREAM-DIAGNOSTICS-INSTALLED-ACCEPTANCE.md).
   Семь серверных timing spans установлены в API d720232e без ID/payload/per-MOVE logs.
   PH011 heartbeat510ms/lastACK RTT256ms повторился; наблюдаемые server spans <25ms.
   Queue/network/APK/native причина OPEN; диагностическая доставка не закрывает idle дефект.
   [Новый installed receipt](../audits/2026-10-09/CONTINUOUS-SERVER-TIMINGS-INSTALLED.md).
   [Границы и следующие проверки](CONTINUOUS-INPUT-TIMINGS.md).
3. **Общий владелец input (EP-017/020):** Redis lease для continuous viewer существует;
   согласование viewer/task/API/scheduler и неизвестных результатов во всех комбинациях не принято.
4. **Rich recorder (EP-018):** clock fix1577e01e сохранён в UI86354350;
   PH011 mixed tap/XPath/tap/Back и перенос в граф приняты в конечном scope.
   Следующий объём — trajectory/context/Unicode/IME; EP-018 остаётся OPEN/PARTIAL.

## Реестр продукта

Baseline [5 октября](../audits/2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json) намеренно
сохраняет первоначальное OPEN. Следующая таблица показывает действующий остаток.
Прогресс PARTIAL не равен ACCEPTED; никакая строка здесь не подтверждает Fleet32/500/1000.

| ID | Приоритет | Масштаб | Статус / прогресс | Работа |
| --- | --- | --- | --- | --- |
| EP-001 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Сохранять видимость колонок после F5 |
| EP-002 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Исправить canonical export визуального сценария |
| EP-003 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Открывать existing canonical script в builder |
| EP-004 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Нормализовать device_model в Fleet Matrix |
| EP-005 | P2 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Не показывать пустое количество узлов в pipeline picker |
| EP-006 | P1 | S | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | HTTP rejection не является delivered в legacy webhook |
| EP-007 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Встроенная Grafana должна открыть запрошенный dashboard |
| EP-008 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | Подключить реальные HTTP RPS и latency panels |
| EP-009 | P1 | M | ACCEPTED_RECORDED_SCOPE / ACCEPTED_FINITE | История CPU/RAM с корректным scope |
| EP-010 | P1 | L | OPEN / PARTIAL | Активные tunnels и fleet metric coverage |
| EP-011 | P1 | L | OPEN / PARTIAL | Версионировать все browser table/view preferences |
| EP-012 | P1 | M | OPEN / OPEN | Расширить registry typed columns и пресеты |
| EP-013 | P2 | M | OPEN / PARTIAL | Единые tokens, preferences и icon semantics |
| EP-014 | P1 | L | OPEN / PARTIAL | Studio canonical AST и отдельный layout |
| EP-015 | P1 | L | OPEN / PARTIAL | Studio source schema, drafts, conflict и undo |
| EP-016 | P1 | L | OPEN / PARTIAL | Studio каталог всех runtime actions |
| EP-017 | P1 | M | OPEN / PARTIAL | Live device picker и capability preflight в Studio |
| EP-018 | P1 | L | OPEN / PARTIAL | Запись Android input и selector candidates |
| EP-019 | P1 | L | OPEN / OPEN | Пошаговый trace и replay с frame correlation |
| EP-020 | P1 | L | OPEN / PARTIAL | Server/agent debug pause, step, cancel и safety |
| EP-021 | P1 | XL | OPEN / OPEN | Объединить automation workspace и references |
| EP-022 | P1 | M | OPEN / PARTIAL | Task detail: полные outcomes и artifacts |
| EP-023 | P2 | M | OPEN / OPEN | Schedules: timezone, missed fire и next run explain |
| EP-024 | P2 | M | OPEN / OPEN | Triggers: безопасная simulation и feedback loop limits |
| EP-025 | P1 | L | OPEN / OPEN | Webhook attempts/outbox и совместимость доставки |
| EP-026 | P2 | XL | OPEN / OPEN | Typed datasources и project manifest |
| EP-027 | P1 | M | OPEN / PARTIAL | Inspector tree, selectors, freshness и performance |
| EP-028 | P1 | M | OPEN / PARTIAL | Явный device/agent telemetry scope и inventory |
| EP-029 | P1 | L | OPEN / PARTIAL | Selected video end-to-end диагностика и управление |
| EP-030 | P2 | M | OPEN / PARTIAL | Original PNG и matching asset provenance |
| EP-031 | P1 | L | OPEN / OPEN | Thumbnail wall 128 вместо множества full video |
| EP-032 | P1 | L | OPEN / PARTIAL | Общие structured logs всех разрешённых sources |
| EP-033 | P1 | L | OPEN / PARTIAL | Byte-bounded backend log reads и global retention |
| EP-034 | P2 | M | OPEN / PARTIAL | Audit journal semantic outcome и redacted diff |
| EP-035 | P2 | M | OPEN / OPEN | Dashboard attention queue и actionable drilldown |
| EP-036 | P2 | M | OPEN / PARTIAL | Groups membership и bulk plan |
| EP-037 | P2 | M | OPEN / PARTIAL | Locations hierarchy UX и validation |
| EP-038 | P2 | M | OPEN / OPEN | Discovery capability-scoped onboarding |
| EP-039 | P2 | M | OPEN / PARTIAL | Users role preview, safety и access review |
| EP-040 | P2 | M | OPEN / PARTIAL | Configuration effective state и разделение policies |
| EP-041 | P1 | L | OPEN / PARTIAL | Release rollout receipts и каналы |
| EP-042 | P2 | XL | OPEN / OPEN | Generic resources вместо game domain assumptions |
| EP-043 | P2 | XL | OPEN / OPEN | Разделить account session и universal run |
| EP-044 | P1 | L | OPEN / PARTIAL | VPN assigned/applied/handshake/egress outcomes |
| EP-045 | P2 | XL | OPEN / DEFERRED_DESIGN | Versioned VPN provider adapters и rotation |
| EP-046 | P2 | XL | OPEN / DEFERRED_DESIGN | AI-ready schemas/runbooks и scoped artifacts |
| EP-047 | P1 | XL | OPEN / PARTIAL | Общая matrix500/1000 иresource leak gates |
| EP-048 | P1 | L | OPEN / PARTIAL | Тесты всех меню/форм/ролей иvisual states |
| EP-049 | P1 | L | OPEN / PARTIAL | Документация source/runtime/schema freshness |
| EP-050 | P1 | L | OPEN / OPEN | Alert delivery иsynthetic Android SLI |

## Дополнения из чата

### CHAT-01 · Возврат назад на прежнюю позицию

**ACCEPTED_FINITE** · EP-011, EP-015.

Browser Back и общая кнопка Back: каталог 2132.5 → 2132.5 px после route commit; память вкладки ограничена.

Остаётся: Нет обещания сохранения scroll после F5. Защита грязного черновика при browser Back/Forward остаётся открытой.

Доказательства: [ROUTE-SCROLL-RESTORATION](../audits/2026-10-09/ROUTE-SCROLL-RESTORATION.md).

### CHAT-02 · Свободные узлы и редактирование соединений

**ACCEPTED_FINITE** · EP-014, EP-015.

Detached add, palette drag/drop, явная вставка, разрыв/переназначение связи и Undo имеют конечную приёмку.

Остаётся: Semantic subgraphs/зоны orchestration/pipeline, полный conflict diff и все графы не приняты.

Доказательства: [STUDIO-INSTALLED-ACCEPTANCE](../audits/2026-10-07/STUDIO-INSTALLED-ACCEPTANCE.json), [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.json).

### CHAT-03 · Доступность библиотеки на телефоне и компоновка

**PARTIAL** · EP-013, EP-014, EP-048.

Четыре compact panels, desktop library рядом с laboratory; 390×844, 844×390 и 1440×900 проверены.

Остаётся: В landscape общий fit длинной вертикальной цепочки делает узлы слишком мелкими; полная visual/a11y matrix открыта.

Доказательства: [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md).

### CHAT-04 · Палец мышью: MOVE поступает до отпускания

**ACCEPTED_FINITE** · EP-029, EP-020.

Обычное управление PH011 APK10249: DOWN1/MOVE5/UP1; wheel DOWN1/MOVE1/UP1, capability и owner согласуются автоматически.

Остаётся: Это не подтверждение всего парка/всех APK, нулевой задержки или исправления повторного idle native_receipt_timeout.

Доказательства: [CONTINUOUS-VIEWER-FAULT-ISOLATION](../audits/2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md), [CONTINUOUS-INPUT-AUTOMATIC-UX](../audits/2026-10-08/CONTINUOUS-INPUT-AUTOMATIC-UX.md).

### CHAT-05 · Запись Home, Back, Recents, Menu

**ACCEPTED_FINITE** · EP-018.

PH011: четыре APK confirmed outcome в порядке записи, очередь сохранена при переключении панелей, late ACK после Stop обновляет исходную строку.

Остаётся: Подтверждение этих четырёх кнопок не закрывает весь rich recorder или все типы input.

Доказательства: [STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.json), [STUDIO-RECORDER-INSTALLED-ACCEPTANCE](../audits/2026-10-08/STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md).

### CHAT-06 · Запись непрерывной траектории жеста

**OPEN** · EP-018, EP-019.

Рекордер сохраняет завершённые дискретные swipe endpoints. recordingMode выбирает discrete transport.

Остаётся: Долговечная MOVE trajectory, нормализация времени/геометрии, лимиты, отмена и точное воспроизведение ещё не приняты.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-07 · Смешанная запись XPath → tap → системная кнопка

**ACCEPTED_FINITE** · EP-018.

UI60be6ecd/APIbe803773: PH01110249 tap → planned XPath → tap → APK-confirmed Back,4 строки; явный перенос6actions с2паузами,9узлов/8связей; Undo восстановилv1/3узла/2связи. Все4CI success, frontend1938tests/139suites.

Остаётся: Finite PH011 не подтверждает все устройства/rotation/clock changes/replay; MOVE/context bundle отдельно OPEN (CHAT-06/08), EP-018 остаётся OPEN/PARTIAL.

Доказательства: [STUDIO-CLOCK-INSTALLED-ACCEPTANCE](../audits/2026-10-09/STUDIO-CLOCK-INSTALLED-ACCEPTANCE.md), [STUDIO-RECORDER-CLOCK-FIX](../audits/2026-10-09/STUDIO-RECORDER-CLOCK-FIX.md).

### CHAT-08 · Запись контекста: XPath, зона, crop, цвет пикселя

**OPEN** · EP-018, EP-019, EP-027, EP-030.

Можно явно добавить выбранный XPath-кандидат; отдельный native PNG работает в принятом scope.

Остаётся: Автоматического pre-action tree/crop/pixel bundle со связанными кадром, командой и snapshot IDs нет. Нужны freshness, quotas, TTL и экспорт.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-09 · Исходный PNG

**ACCEPTED_FINITE** · EP-030.

Отдельный native capture: original Android → server → browser bytes/hash chain; пользователь разрешил считать screenshot рабочим.

Остаётся: Сравнение двух присланных файлов приостановлено пользователем. Matching assets/provenance и workflow artifacts остаются открытыми.

Доказательства: [DEVICE-CONTROL-AND-NATIVE-CAPTURE](../audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).

### CHAT-10 · Веб обновляется при изменении данных

**PARTIAL** · EP-010, EP-050.

Fleet WS пакетно invalidates REST queries; скрытые вкладки/reconnect согласуются отдельно. Prometheus/fleet metrics обновляются polling 15 s.

Остаётся: Не каждая метрика имеет push producer; events connected не доказывает исправность Android или freshness каждого показателя.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-11 · 128 устройств: thumbnails, Connect all, синхронизатор

**OPEN** · EP-031, EP-047.

Текущая /stream wall использует full DeviceStream; grid до 64.

Остаётся: 128 thumbnails по 5/10 s, shared capture/budgets и Connect all/synchronized input с partial outcome/Stop требуют отдельной реализации и приёмки.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-12 · Наблюдение заполнения всего ПК без ручного угадывания

**OPEN** · EP-033, EP-047.

Новое limited окно9Oct12:42→10Oct12:42UTC,721×120s/16MiB. Complete samples,
process creation/command/source identity проверены. Прежний разрыв не покрыт.

Остаётся: Whole-PC writer UNKNOWN: VSS unavailable, USN/ETW не запущены.
Нет reboot autostart; после deadline нужны bounded restart/health,
resource soak/retention и RAM acceptance.

Доказательства: [STORAGE-OBSERVER-RESTART](../audits/2026-10-09/STORAGE-OBSERVER-RESTART.json), [STORAGE-WINDOW-COMPLETION](../audits/2026-10-08/STORAGE-WINDOW-COMPLETION.json).

### CHAT-13 · Единая автоматизация и универсальные ресурсы

**OPEN** · EP-021, EP-026, EP-042, EP-043.

Сценарии, задания, orchestration и pipeline доступны как отдельные текущие сущности.

Остаётся: Общий workspace/references, универсальные project resources/connectors и semantic composition ещё не приняты.

Доказательства: [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-14 · Подключаемые VPN providers и AI

**DEFERRED_DESIGN** · EP-045, EP-046.

Требования и границы будущего этапа записаны; интеграция не объявлена установленной.

Остаётся: Нужны отдельные contracts/versioning/secrets/ownership/deadlines/rollback и подтверждённые результаты, прежде чем давать управление.

Доказательства: [AI-READINESS](../architecture/AI-READINESS.md), [CHAT-CODE-RECONCILIATION](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md).

### CHAT-15 · Прямой browser ↔ Android transport

**PARTIAL** · EP-029, EP-020, EP-047.

Исследование текущего WS пути и первичных источников выполнено. Предложен prototype:
browser WebRTC ↔ Android libwebrtc, direct video и input/ACK, coturn fallback;
Pion/SFU/overlay рассмотрены по ролям, а не добавлены обязательным media hop.

Последующим запросом пользователя разрешена разработка. Написан RTT-only canary:
Maven AAR pinned, authenticated generation-bound signaling, allowlist устройств,
WebRTC echo без media/input. Он отключён и не установлен в рабочее окружение.
Остаётся: полный native provenance/SBOM, live RTT/cleanup, media/control ownership,
current-path attribution, TURN/network matrix и production gate. Draft latency targets
не являются достигнутым SLA. [Исходники и проверки](../audits/2026-10-09/DIRECT-PROBE-SOURCE.md).

Доказательства: [Исследование и порядок внедрения](../design/BROWSER-DIRECT-TRANSPORT.md),
[Фактический relay path и idle canary](../audits/2026-10-09/IDLE-CONTROL-RELAY-REVIEW.md).

## Когда переходить к прямому browser ↔ Android media

Проработать архитектуру можно отдельным следующим этапом, **не ожидая завершения
всех будущих 41 возможностей**. До выбора решения нужны versioned offer/input
contract, auth/ownership boundaries, измеримый текущий transport baseline и
resource accounting; сетевой план должен различать same-PC, LAN и Internet/NAT.
Требование «прямое соединение» не означает гарантию direct path в любой сети:
исследование должно предусмотреть явный relay fallback и его ограничения.

До production pilot необходимы закрытые idle/control-owner риски, session/auth/
geometry fences, подтверждённые capture/encoder/browser budgets и отдельные
прогоны direct/relay/reconnect/revocation/version compatibility с rollback.
Технология предложена для прототипа в [отдельном исследовании](../design/BROWSER-DIRECT-TRANSPORT.md);
Android artifact выбран для изолированного RTT canary; рабочий WebRTC, VPN и AI
этим этапом не установлены. Live media/control приёмка остаётся впереди.
В новом transport APK execution сценариев и server task receipts должны сохранять
свою независимую семантику. Устойчивые online badges — полезное наблюдение,
но не измерение uptime, input-to-frame latency или terminal outcome.

## Как закрывать работу без потери истории

- Не менять frozen baseline/старый JSON receipt. Добавить датированное evidence.
- В STATUS-REGISTRY обновить acceptedScope/remaining, source/test/install/live
  границы; для полного EP closure проверить **все** исходные acceptanceCriteria.
- Частичный пользовательский workflow закрывать в CHAT-ID с указанным scope;
  родительский EP остаётся OPEN, пока его остальные критерии не выполнены.
- Сослаться из current-state/readiness на новую запись. Старые installs и CI
  остаются историей своих SHA. После изменения запустить checker из DOCUMENTATION.
- Не переносить successful CI одного SHA, закрытие user workflow или финальный
  readback на другой source, весь парк либо непрерывный SLA.
