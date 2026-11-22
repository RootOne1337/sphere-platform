# Сверка запросов, аудитов и реализации Sphere

Дата: **9 октября 2026**, Asia/Yekaterinburg. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Это актуальная карта работ поверх замороженных аудитов с указанием границ доказательств.

## Состояние и область проверки

Продуктовый план: **50 пунктов, 9 приняты в записанном объёме, 41 открыт**.
Это не процент полной готовности к production. Старый веб-аудит отдельно имеет
**34 исправленных в исходниках / 7 незакрытых**: F32/F33/F39 PARTIAL;
F34/F36/F40/F41 OPEN. Число 8 относилось к более раннему состоянию другого списка.
SF26 детализирует запросы Studio и не добавляет независимые пункты к 50 работам.

Браузер в этом этапе показывает **UI ec3f2267 / API be803773** на 3015.
APK 10249 относится к ранее принятой проверке PH011; сейчас Android не опрашивался.
Исправление смешанных часов recorder в 1577e01e ещё не установлено.
Исходники, установленная версия и конечная живая проверка разделены ниже.

Проверено:

1. Требования чата: телефонная вёрстка, Back и позиция прокрутки, граф и связи,
   recorder, XPath и исходные изображения, управление и наблюдаемость,
   универсальные ресурсы, VPN adapters, будущие AI и прямой медиаканал.
2. Все 50 исходных критериев приёмки, зависимости и ссылки на код. Сопоставлены
   последующие receipts продукта, HTTP, ресурсов, responsive Studio, простоя
   управления и завершённого наблюдения за диском.
3. Пути web → backend → APK для часов записи, проверки параметров, запуска
   continuous runtime и Redis, источника hierarchy, преобразования координат,
   polling/events, ограничений логов и нынешней видеоматрицы.
4. Текущий builder визуально прочитан без изменений: viewport 648×884,
   main 648×820, ширина документа 648, версия 1, 3 узла и 2 связи. Не выполнялись
   Save, Run, Android input, навигация или изменение пользовательского графа.
5. Два новых компонентных случая упали до исправления. После правки проходят
   76 проверок записи в 3 наборах, все 1938 frontend tests в 139 наборах и TypeScript.

Это не заявление о построчном ревью всего проекта. В областях без новой живой
приёмки сохранён OPEN и указаны исходные критерии. Старые номера строк baseline
не выдаются за актуальные: JSON содержит текущие пути и SHA-256 файлов.

## Подтверждённые нестыковки

### RCN-01: XPath и Android input используют разные часы

DeviceStream и AndroidNavigationBar используют performance.now; Workbench
передавал Date.now при добавлении selector. Следующий клик после XPath мог
остановить запись из-за нарушения порядка времени. Другое календарное время
искажало паузы. Исправление в исходниках: 1577e01e.

Новые тесты проверяют tap → XPath → tap → Back submitted → Stop → поздний ACK.
XPath остаётся явно выбранным будущим действием, а не Android ACK.
Защиты pending/unknown и принадлежность позднего ответа исходной строке сохранены.
[Доказательство, тест и состояние доставки](STUDIO-RECORDER-CLOCK-FIX.md).

### RCN-02: разные списки и исторические статусы

Baseline 5 октября содержит 50 OPEN; первый пакет показывает 5/45, второй 7/43,
ресурсная приёмка — 9/41. Это записи разных моментов. Актуальная карта наследует
приёмку только из закреплённых receipts; исходные JSON не переписываются.

Старый веб-аудит содержит 41 finding и имеет отдельный последний срез 34/7.
Последующие частичные улучшения не закрывают оставшиеся семь автоматически.
Нужен отдельный receipt полного оставшегося объёма каждого пункта.

### RCN-03: обычный живой жест не является непрерывной записью

websocket.startup запускает ContinuousRuntime с Redis ContinuousLeaseStore.
Старое описание модуля «future/no startup» исправлено: путь уже подключён.
Наличие Redis lease не доказывает единого арбитра viewer, task, API и второго оператора.

Обычный Control передаёт native MOVE до UP на совместимом тестовом APK.
recordingMode сохраняет дискретные конечные точки свайпа и длительность,
без траектории MOVE. Поэтому SF26-05/06 нельзя закрыть одной успешной
проверкой обычного перетаскивания.

### RCN-04: проверка параметров не проверяет установленный APK

ScriptValidationResponse содержит action_parameters_verified=true и
device_execution_verified=false. Ответ action contract отдельно содержит
installed_apk_capabilities_verified=false. Наличие 32 форм не доказывает
исполнение 32 действий на каждом установленном APK.

Нужны свежие target/action/display/root сведения и ясная семантика результата.
Подготовка одного viewer перед task не заменяет арбитраж всех источников управления.

### RCN-05: реальный источник hierarchy

AdbActionExecutor вызывает Android uiautomator dump через root и обрабатывает XML/XPath.
Backend ограничивает XML 128 KiB, количество nodes 4096 и depth 64.
В проверенном пути нет основания называть inspector установленным сервером
Appium UiAutomator2. Разные движки имеют разные возможности; новое название
не расширяет доступные Android nodes.

Автоматический связанный набор tree/native crop/pixel пока отсутствует.
Выбор элемента по видео и дереву и явный selector plan уже реализованы.

### RCN-06: нынешняя видеоматрица не является thumbnail wall

stream/page.tsx импортирует DeviceStream; размеры сетки доходят до 64.
Запрошены 128 thumbnail с интервалом 5/10 секунд и один качественный selected stream.
Нужны отдельные capture/subscription/cache, TTL, ограничения concurrency и bytes.
Кнопка Connect all поверх нынешнего full-video пути не закрывает EP-031/F34.

### RCN-07: real-time UI сочетает события и REST polling

useFleetEvents принимает WebSocket события и пакетно инвалидирует query roots.
Активные queries перечитываются через REST; неактивные помечаются stale.
Панели Prometheus, ресурсов и fleet coverage обновляются каждые 15 секунд;
health — 30, VPN peers — 30, pool — 60. Focus/reconnect отдельно сверяют данные.

Значок событий не доказывает свежесть каждой метрики, кадра или Android.
Это не передача всех значений всех панелей только через push.

### RCN-08: атрибуция диска хоста имеет текущий разрыв наблюдения

Приняты ресурсы cgroup backend, а не все Windows процессы и диск.
Observer завершил 241/241 срез 8 октября в 09:01 UTC и не работает бесконечно.
Allocations VHD и четырёх VMDK были постоянны во всём окне; guest рос внутри
прежнего allocation, free C: падал примерно на 6.48 GiB. Writer всей потери
UNKNOWN, VSS в том окне недоступен.

На 22:46:42 UTC 8 октября среди видимых командных строк нет текущего процесса
host_storage_watch/disk_writer_watch/ntfs_growth_watch/collect_storage_allocation.
Один замер свободного места 50802831360 B не является трендом или атрибуцией.
Завершённое окно не восстанавливает следующую потерю после deadline.
[Неизменяемый receipt и ограничения](../2026-10-08/STORAGE-WINDOW-COMPLETION.md).

### RCN-09: ограничения логов устройства не равны общим квотам

Logs router имеет read/upload budget и ротацию по устройству. Writer прямо
отделяет global quotas и cross-worker lock от нынешней реализации.
Org/global sweeper, expiry отключённых источников, disk forecast, backup/restore
и нагрузочные проверки ещё нужны. Per-device limit не закрывает ресурсные gates.

## Актуальный объём SF26

Критические связи проверенного кода:

| Связь | Веб | Backend / APK |
| --- | --- | --- |
| Запись и время | [Workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx), [queue/export](../../../frontend/src/features/scripts/studio/recording.ts), [clock contract](../../../frontend/src/features/stream/controlObservation.ts) | APK ACK сохраняет исходную submitted строку; XPath — будущий шаг |
| Жесты | [DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx) | [startup](../../../backend/websocket/startup.py) → [runtime](../../../backend/websocket/continuous_runtime.py) → [Redis authority](../../../backend/websocket/continuous_lease.py) |
| Параметры действий | [Builder](../../../frontend/app/(dashboard)/scripts/builder/page.tsx) | [response semantics](../../../backend/schemas/script.py), [contract 1.0](../../../backend/schemas/action_contract.v1.json), [DagRunner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt) |
| XPath и координаты | [SingleDeviceStream](../../../frontend/src/features/stream/SingleDeviceStream.tsx) | [bounded XML parser](../../../backend/services/ui_hierarchy.py), [APK source/transform](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt) |
| Актуальность данных | [WS invalidation](../../../frontend/lib/hooks/useFleetEvents.ts), [cadence](../../../frontend/lib/queryPollIntervals.ts) | Событие инвалидирует query, а значения панели перечитываются через REST |
| Массовый обзор | [Нынешняя stream matrix](../../../frontend/app/(dashboard)/stream/page.tsx) | Отдельный thumbnail capture contract ещё не принят |
| Логи | [Log API writer/read](../../../backend/api/v1/logs/router.py) | Per-device bounds не заменяют общий sweeper и quota |
| Доступность модалок | [UserDialogs](../../../frontend/src/features/users/UserDialogs.tsx) | Fixture warning не переносится автоматически в production finding |

### Состояние требований SF26

| ID | Реализация и открытые границы |
| --- | --- |
| SF26-01 | Reconnect/remove/Undo приняты в конечной проверке; EP-014/015 OPEN |
| SF26-02 | Шесть key presets создают action и не отправляют Android input |
| SF26-03 | Home/Recents/Back/Menu: 4/4 APK-confirmed на PH011 в ec3f2267; это не весь парк |
| SF26-04 | Explicit future XPath есть; clock fix 1577e01e ещё не установлен |
| SF26-05 | Normal Control подключён; idle/global arbitration/recorded MOVE OPEN |
| SF26-06 | Automatic tree/crop/pixel bundle не реализован |
| SF26-07 | Конкретные PNG приняты; artifact/matcher scope OPEN, спор отложен |
| SF26-08 | Subgraphs и высокоуровневая семантическая композиция — design OPEN |
| SF26-09 | 128 thumbnail и group subscription OPEN |
| SF26-10 | Group synchronizer, manifest, partial outcomes и stop OPEN |
| SF26-11 | AI provider, chat и typed tools отложены |
| SF26-12 | Detached node, drag/drop и explicit insertion приняты; composition OPEN |

## Порядок работ и критерии перехода

| Порядок | Работа | Admission |
| --- | --- | --- |
| 1 | Часы recorder | CI точной ревизии, reviewed artifact, установка 3015, mixed-input browser проверка |
| 2 | Разрыв наблюдения за диском | Один bounded observer; sample health/deadline/budget/privilege, writer/VSS/allocated metadata |
| 3 | Idle receipt failure | Ограниченные browser → Redis → APK → native timings; idle/hidden/restart/fault, без повторения неизвестного input |
| 4 | Владение input | Viewer/task/API concurrency, known release, cancel/late outcome/fence, target identity |
| 5 | Расширенная запись | Versioned path, pre-action bundle, freshness/ambiguity, quota/TTL/redaction, review/export |
| 6 | Trace/replay/debug | Command/frame/snapshot/attempt IDs, replay наблюдений, ясные pause/step/cancel effects |
| 7 | Thumbnail wall | 128 tiles раз в 5/10 секунд, shared capture/budgets, один selected stream, teardown |
| 8 | Platform workspace | Used-by graph, universal resources, role/theme/mobile matrix, versioned providers |

Наблюдение за ресурсами можно вести одновременно с разработкой, если сам
collector ограничен по размеру и времени и не выдаёт завершённый job за running.
Не нужно бесконечно ждать следующей потери места перед возвращением к Studio.
Измерение причин, очистка и компакция — разные действия и receipts.

## Отложенные идеи из чата

Direct browser ↔ APK media, WebRTC/Pion/NAT/TURN пользователь отложил до отдельного
анализа. В этом этапе нет нового P2P протокола, обещания нулевой задержки или
изменения транспорта. Будущие Amnezia/proxy adapters и AI не подключаются
скрыто под видом UI исправления.

Сначала нужны versioned contracts, deployment/update/rollback и наблюдаемость
эффектов, затем отдельные этапы приёмки.

## Матрица 50 пунктов

ACCEPTED_RECORDED_SCOPE наследует конечный receipt только этого пункта.
PARTIAL означает часть реализации без полной приёмки. DEFERRED_DESIGN остаётся
OPEN в общем счётчике. Code ссылки ведут на текущие файлы; SHA-256 и baseline
dependencies сохранены в JSON. Критерии ниже — требования, а не автоматически
пройденные проверки.


### EP-001: Сохранять видимость колонок после F5

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: Видимость колонок сохраняется; конечная приёмка EP-001 записана отдельно.

Дальше: Общие table preferences относятся к EP-011, не автоматически к EP-001.

Критерии исходного плана:

- Изменить набор колонок → F5 → тот же набор.
- Миграция старой/повреждённой local schema без потери темы.
- Недоступный storage не ломает каталог.

Код: [frontend/src/features/devices/FleetMatrix.tsx](../../../frontend/src/features/devices/FleetMatrix.tsx).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-002: Исправить canonical export визуального сценария

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: Canonical array/action DAG совместим с сервером; связи и Undo используют тот же формат.

Дальше: Новые action/version regressions должны сохранять этот контракт.

Критерии исходного плана:

- POST canonical fixture принимается сервером.
- Lowercase action, links/retry/timeout сохранены.
- Неверный граф не публикуется и не запускается.

Код: [frontend/lib/dag/export.ts](../../../frontend/lib/dag/export.ts) · [backend/schemas/dag.py](../../../backend/schemas/dag.py) · [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-003: Открывать existing canonical script в builder

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: Сохранённые canonical версии открываются; текущий browser canary показывает v1, 3 узла/2 связи.

Дальше: Это не roundtrip всех будущих action или legacy документов.

Критерии исходного плана:

- Сохранённый canonical graph открывается.
- Roundtrip не теряет поля/ветви/версию.
- Load failure по-прежнему блокирует запись.

Код: [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-004: Нормализовать device_model в Fleet Matrix

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: Модель нормализована для registry/picker; отсутствие данных имеет fallback.

Дальше: Полный inventory и колонки относятся к EP-012/028.

Критерии исходного плана:

- API model отображается в registry и picker одинаково.
- Пустое/legacy поле отображается с честным fallback.
- Поиск/сортировка используют тот же canonical field.

Код: [frontend/src/features/devices/FleetMatrix.tsx](../../../frontend/src/features/devices/FleetMatrix.tsx) · [frontend/lib/hooks/useDevices.ts](../../../frontend/lib/hooks/useDevices.ts).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-005: Не показывать пустое количество узлов в pipeline picker

**Принят записанный объём · P2 · ACCEPTED_FINITE**

Факт и границы: Canonical current_version count принят; unknown count не считается нулём.

Дальше: Pipeline/schedule UX и semantic references — отдельные работы.

Критерии исходного плана:

- Count canonical current_version одинаков в scripts/pipeline/schedule.
- Unknown count обозначен явно, не пустой строкой/нулём.
- Старая форма ответа не ломает выбор версии.

Код: [frontend/app/(dashboard)/orchestration/page.tsx](../../../frontend/app/(dashboard)/orchestration/page.tsx).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-006: HTTP rejection не является delivered в legacy webhook

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: HTTP outcomes исправлены; loopback receipts204/403/429/503 и bounded retry приняты.

Дальше: Durable outbox/DLQ/replay требуют EP-025.

Критерии исходного плана:

- 2xx success, 403 rejected, 429 rate limited и 5xx retry различаются.
- Не повторять terminal rejection бесконечно.
- Новый результат отражён в delivery logs/receipts; n8n compatibility проверена.

Код: [backend/services/webhook_service.py](../../../backend/services/webhook_service.py) · [backend/services/task_service.py](../../../backend/services/task_service.py) · [backend/services/batch_service.py](../../../backend/services/batch_service.py).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-007: Встроенная Grafana должна открыть запрошенный dashboard

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: Grafana proxy/dashboard/Viewer query и отзыв собственной сессии подтверждены.

Дальше: Новые панели/mobile themes/synthetic Android SLI не приняты автоматически.

Критерии исходного плана:

- Получены dashboard и реальные панели, не Welcome.
- Request/redirect/auth/org/UID цепочка установлена.
- Истечение/отзыв Sphere session не даёт обхода RBAC.

Код: [frontend/lib/server/observability.ts](../../../frontend/lib/server/observability.ts).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-008: Подключить реальные HTTP RPS и latency panels

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: HTTP RPS/p95 подключены с window/unit/scope, empty/stale/error states.

Дальше: HTTP до заголовков не измеряет жест→экран или APK execution.

Критерии исходного плана:

- RPS/p95 отображают unit/window/scope.
- Empty/stale/error/partial vector различаются.
- Endpoint/error drilldown и bounded query allowlist.

Код: [frontend/lib/server/observability.ts](../../../frontend/lib/server/observability.ts) · [backend/metrics.py](../../../backend/metrics.py).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-HTTP-METRICS-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-009: История CPU/RAM с корректным scope

**Принят записанный объём · P1 · ACCEPTED_FINITE**

Факт и границы: История cgroup CPU/RAM подключена; код задаёт cadence15s.

Дальше: Windows disk/RAM, process RSS и fleet soak вне этой приёмки.

Критерии исходного плана:

- История источник/единица/интервал указаны.
- Process, cgroup и host не смешаны.
- Unknown memory/CPU не рисуется нулём.

Код: [backend/api/v1/monitoring/router.py](../../../backend/api/v1/monitoring/router.py).

[Записанная приёмка](../../../docs/audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-EVIDENCE.json); это не новая live проверка всех исходных критериев.


### EP-010: Активные tunnels и fleet metric coverage

**Открыт · P1 · PARTIAL**

Факт и границы: Tenant fleet coverage и VPN observations реализованы; StageA/B receipts сохранены.

Дальше: Independent producer/transport probes/active tunnel semantics/load ещё не приняты.

Критерии исходного плана:

- Assignment/Android applied/heartbeat имеют отдельные counts.
- Collector semantics не умножают gauge по workers.
- Tenant scope и source freshness видны.

Код: [backend/api/v1/monitoring/router.py](../../../backend/api/v1/monitoring/router.py) · [backend/metrics.py](../../../backend/metrics.py).


### EP-011: Версионировать все browser table/view preferences

**Открыт · P1 · PARTIAL**

Факт и границы: Column visibility/theme persistence и Back tab-memory scroll restoration есть.

Дальше: Общий registry order/width/pin/sort и cross-tab migration не принят; F5 scroll не обещан.

Критерии исходного плана:

- View, columns/order/width/pin/sort/density/page size persist.
- Shareable фильтры в URL, private prefs без secrets.
- Reset одной таблицы и cross-tab migration.

Код: [frontend/src/features/devices/FleetMatrix.tsx](../../../frontend/src/features/devices/FleetMatrix.tsx) · [frontend/src/shared/store/useUIStore.ts](../../../frontend/src/shared/store/useUIStore.ts).


### EP-012: Расширить registry typed columns и пресеты

**Открыт · P1 · OPEN**

Факт и границы: Базовый Fleet Matrix существует; модель исправлена.

Дальше: Typed column registry, provenance/unknown, presets и 1000 rows layout/pagination остаются.

Критерии исходного плана:

- Пресеты Operations/Connection/Versions/Resources.
- Каждое поле имеет provenance и unknown.
- 1000 rows server pagination, sticky identity, no page overflow.

Код: [frontend/src/features/devices/FleetMatrix.tsx](../../../frontend/src/features/devices/FleetMatrix.tsx) · [backend/schemas/devices.py](../../../backend/schemas/devices.py).


### EP-013: Единые tokens, preferences и icon semantics

**Открыт · P2 · PARTIAL**

Факт и границы: Theme tokens/AppearanceDrawer/Lucide и responsive Studio существуют.

Дальше: Полная 4 themes/5 accents/3 density matrix и единый redesign страниц не приняты.

Критерии исходного плана:

- Старая theme/density мигрирует без reset.
- Named icons/focus/reduced motion/zoom и единые units.
- 4 темы/5 акцентов/3 density проходят визуальную матрицу.

Код: [frontend/src/features/preferences/AppearanceDrawer.tsx](../../../frontend/src/features/preferences/AppearanceDrawer.tsx) · [frontend/src/shared/store/themeStore.ts](../../../frontend/src/shared/store/themeStore.ts).


### EP-014: Studio canonical AST и отдельный layout

**Открыт · P1 · PARTIAL**

Факт и границы: React Flow/ELK, отдельные узлы/drag/drop/explicit insertion/reconnect/remove/Undo реализованы и конечные canaries приняты.

Дальше: Versioned composition/subgraphs и unsupported action roundtrip остаются.

Критерии исходного плана:

- Semantic AST versioned, canvas metadata отдельно.
- Visual/source switch без semantic drift.
- Unsupported action сохраняется read-only либо блокирует Run.

Код: [frontend/lib/dag/export.ts](../../../frontend/lib/dag/export.ts) · [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx).


### EP-015: Studio source schema, drafts, conflict и undo

**Открыт · P1 · PARTIAL**

Факт и границы: Draft/source/undo/outage retention и pending/unknown guards реализованы.

Дальше: Полный conflict diff и dirty draft browser Back/Forward protection не приняты.

Критерии исходного плана:

- Dirty parse error не теряет текст.
- Draft autosave не публикует / не запускает.
- Concurrent version conflict с diff и undo/redo.

Код: [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx) · [backend/services/script_service.py](../../../backend/services/script_service.py).


### EP-016: Studio каталог всех runtime actions

**Открыт · P1 · PARTIAL**

Факт и границы: 32 action forms/contract1.0 есть в web/backend; APK содержит исполнителей.

Дальше: Parameter validation не проверяет installed APK; action-specific live matrix всего парка не принята.

Критерии исходного плана:

- Capability/action schema содержит поля/limits/effects/result.
- Неизвестные версии/permissions блокируют конкретный action.
- Нет promises arbitrary host code.

Код: [backend/schemas/dag.py](../../../backend/schemas/dag.py) · [android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt).


### EP-017: Live device picker и capability preflight в Studio

**Открыт · P1 · PARTIAL**

Факт и границы: Лаборатория выбирает один Android и version-pinned task с viewer-local handoff.

Дальше: Полный свежий action/capability preflight и competing input admission не приняты.

Критерии исходного плана:

- Target identity/version/display/root/input видны.
- Offline edit разрешён, Run/Record по свежему preflight.
- Смена target не переносит старый coordinate transform.

Код: [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx).


### EP-018: Запись Android input и selector candidates

**Открыт · P1 · PARTIAL**

Факт и границы: Click/swipe endpoints, explicit XPath plan и key/text ACK есть; queue200. Clock defect исправлен source1577e01e.

Дальше: Новая доставка pending; MOVE recording/Unicode/IME/automatic tree-crop-pixel bundle отсутствуют.

Критерии исходного плана:

- Tap/drag/text/wheel нормализуются с receipts.
- Ambiguity и fallback coordinates видимы.
- Secrets redacted, bounded buffer, Stop освобождает subscriptions.

Код: [frontend/app/(dashboard)/scripts/builder/page.tsx](../../../frontend/app/(dashboard)/scripts/builder/page.tsx) · [backend/services/ui_hierarchy.py](../../../backend/services/ui_hierarchy.py).


### EP-019: Пошаговый trace и replay с frame correlation

**Открыт · P1 · OPEN**

Факт и границы: Task logs/marks показывают завершённый шаг, но не correlated frame trace.

Дальше: Нужны command/frame/snapshot/attempt IDs, side-effect-free replay и artifact quotas/TTL.

Критерии исходного плана:

- Replay trace не запускает Android actions.
- Каждый step связан с command/frame/snapshot/attempt.
- Unknown/failed/cancelled различаются; TTL/quota artifacts.

Код: [frontend/app/(dashboard)/tasks/page.tsx](../../../frontend/app/(dashboard)/tasks/page.tsx) · [backend/schemas/dag.py](../../../backend/schemas/dag.py).


### EP-020: Server/agent debug pause, step, cancel и safety

**Открыт · P1 · PARTIAL**

Факт и границы: Viewer-local release/read handoff, APK ownership и Redis continuous lease используются.

Дальше: Global viewer/task/API arbitration и debugger acceptance не завершены; idle timeoutP1.

Критерии исходного плана:

- Pause/step настоящий protocol, либо явно unavailable.
- Late result не возрождает cancelled run.
- Retry non-idempotent input зависит от outcome.

Код: [android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt).


### EP-021: Объединить automation workspace и references

**Открыт · P1 · OPEN**

Факт и границы: Сценарии/tasks/schedules/pipelines/triggers существуют отдельно с некоторыми deep links.

Дальше: Definition→version→run→task→device→trace, used-by graph/glossary остаются.

Критерии исходного плана:

- Origin → version → run → task → device → trace deep links.
- Existing URLs сохранены.
- Used-by/dependency graph и glossary без неоднозначных sessions.

Код: [frontend/app/(dashboard)/orchestration/page.tsx](../../../frontend/app/(dashboard)/orchestration/page.tsx) · [frontend/app/(dashboard)/event-triggers/page.tsx](../../../frontend/app/(dashboard)/event-triggers/page.tsx).


### EP-022: Task detail: полные outcomes и artifacts

**Открыт · P1 · PARTIAL**

Факт и границы: Task detail показывает version/outcomes/logs/доступные screenshots; missing server file обозначается.

Дальше: Полный origin/attempt/deadline/artifact manifest и rerun plan не закрыты.

Критерии исходного плана:

- Pinned hash, attempts, deadline, ACK/result раздельно.
- Parent pipeline/trigger/schedule отображён.
- Rerun preview выдаёт новый task, а не меняет history.

Код: [frontend/app/(dashboard)/tasks/[id]/page.tsx](../../../frontend/app/(dashboard)/tasks/[id]/page.tsx).


### EP-023: Schedules: timezone, missed fire и next run explain

**Открыт · P2 · OPEN**

Факт и границы: Расписания/pipeline forms имеют имеющийся API и предыдущие regressions.

Дальше: Полный DST/missed/duplicate fire/history/conflict acceptance ещё нужен.

Критерии исходного плана:

- Cron/UTC/local/DST policy показаны.
- Next/missed/duplicate fire outcomes и execution history.
- Отмена/enable version conflicts без double fire.

Код: [frontend/app/(dashboard)/orchestration/page.tsx](../../../frontend/app/(dashboard)/orchestration/page.tsx).


### EP-024: Triggers: безопасная simulation и feedback loop limits

**Открыт · P2 · OPEN**

Факт и границы: Event triggers/delivery и catalog/read evidence существуют.

Дальше: Dry match без Run, cooldown/dedup/rate/recursion budgets и origin trace остаются.

Критерии исходного плана:

- Test match без pipeline Run.
- Cooldown/dedup/rate limits explain.
- Event origin и recursion budget предотвратят бесконечную петлю.

Код: [frontend/app/(dashboard)/event-triggers/page.tsx](../../../frontend/app/(dashboard)/event-triggers/page.tsx).


### EP-025: Webhook attempts/outbox и совместимость доставки

**Открыт · P1 · OPEN**

Факт и границы: Legacy HTTP outcome исправлен EP-006; n8n имеет отдельный service.

Дальше: Operator attempts/outbox/DLQ/replay и duplicate policy требуют отдельной приёмки.

Критерии исходного плана:

- Delivery ID/outcome/retry deadline/last error доступны.
- Подпись и payload сохраняют совместимость.
- DLQ/replay bounded и не дублируют irreversible effects.

Код: [backend/services/n8n_webhook_service.py](../../../backend/services/n8n_webhook_service.py) · [frontend/app/(dashboard)/webhooks/page.tsx](../../../frontend/app/(dashboard)/webhooks/page.tsx).


### EP-026: Typed datasources и project manifest

**Открыт · P2 · OPEN**

Факт и границы: Pipeline settings schema есть; generic datasource/resource manifest не принят.

Дальше: Versioned connector contract, plan/diff/conflicts, secret refs/write effects нужны.

Критерии исходного плана:

- Import plan diff/conflicts/dependencies до применения.
- Secrets по refs, credentials tenant scoped.
- Connector write effects/rollback отдельно от workflow definitions.

Код: [backend/schemas/pipeline_settings.py](../../../backend/schemas/pipeline_settings.py).


### EP-027: Inspector tree, selectors, freshness и performance

**Открыт · P1 · PARTIAL**

Факт и границы: Video/tree selection, raw attributes, bounded snapshot/refresh реализованы. APK вызывает root uiautomator dump.

Дальше: Это не Appium UiAutomator2 server; performance/freshness/matcher/automatic bundle ещё открыты.

Критерии исходного плана:

- Video selection/tree selection синхронны.
- Ancestors/attributes/duplicates/export/selector candidates.
- Singleflight/cancel obsolete, stale marked, no hidden polling.

Код: [backend/services/ui_hierarchy.py](../../../backend/services/ui_hierarchy.py) · [android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt).


### EP-028: Явный device/agent telemetry scope и inventory

**Открыт · P1 · PARTIAL**

Факт и границы: DeviceStatusProvider/профиль отдают доступную Android telemetry.

Дальше: Полный inventory, deviceRAM против agentRSS/PSS, observed_at/provenance/network identity не принят.

Критерии исходного плана:

- Device RAM и agent PSS/RSS отдельно.
- Source/error/observed_at validity не заменяется0.
- Version/display/storage/network/capabilities structured.

Код: [android/app/src/main/kotlin/com/sphereplatform/agent/providers/DeviceStatusProvider.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/providers/DeviceStatusProvider.kt).


### EP-029: Selected video end-to-end диагностика и управление

**Открыт · P1 · PARTIAL**

Факт и границы: Normal continuous Control принят PH011APK10249; отдельный idle receipt failure повторился.

Дальше: Нет fleet input-to-pictureSLO; нужны bounded correlated timing и idle loss fix.

Критерии исходного плана:

- Capture/encode/relay/decode/render FPS + drops/bitrate.
- Home/Back/Recents/text/wheel и transform при rotation.
- Input ACK/result/frame timings без ложного cross-clock one-way claim.

Код: [frontend/src/features/stream/SingleDeviceStream.tsx](../../../frontend/src/features/stream/SingleDeviceStream.tsx).


### EP-030: Original PNG и matching asset provenance

**Открыт · P2 · PARTIAL**

Факт и границы: Original PNG имеет finite pixel/hash receipts; пользователь отложил спор.

Дальше: Matching asset provenance/region/rotation и workflow artifactsOPEN; DPI/вес сами не доказывают pixel loss.

Критерии исходного плана:

- Pixel dimensions/hash/MIME/capture source проверены.
- Screenshot не перекодируется из H264.
- Asset version/region/scale/rotation для future matcher.

Код: [android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt).


### EP-031: Thumbnail wall 128 вместо множества full video

**Открыт · P1 · OPEN**

Факт и границы: stream/page.tsx импортирует DeviceStream; GRID_SIZES до 64, это full-video matrix.

Дальше: Thumbnail wall128, cadence5/10s, shared capture/budgets/teardown не реализован.

Критерии исходного плана:

- Интервалы5/10s и128tile, shared capture/stagger.
- TTL/cache/bytes/concurrency budgets.
- Selected stream отдельно, teardown при filter/hidden/unmount.

Код: [frontend/app/(dashboard)/stream/page.tsx](../../../frontend/app/(dashboard)/stream/page.tsx).


### EP-032: Общие structured logs всех разрешённых sources

**Открыт · P1 · PARTIAL**

Факт и границы: Различение log sources и bounded device read реализованы.

Дальше: Общий server cursor devices/groups/run/correlation без client fanout и полный export не приняты.

Критерии исходного плана:

- All devices / groups / run / correlation server query.
- Source / severity / time / build / sequence schema.
- Bounded cursor/export, без 1000 client fanout.

Код: [backend/api/v1/logs/router.py](../../../backend/api/v1/logs/router.py) · [frontend/app/(dashboard)/logs/page.tsx](../../../frontend/app/(dashboard)/logs/page.tsx).


### EP-033: Byte-bounded backend log reads и global retention

**Открыт · P1 · PARTIAL**

Факт и границы: Byte-bounded read/upload реализованы; router отделяет global quota/cross-worker lock от writer.

Дальше: Org/global sweeper/quotas/offline expiry/backup/restore/load остаются.

Критерии исходного плана:

- Tail/filter byte budget и bounded concurrency.
- Org/global quotas и independent retention sweeper.
- Offline sources expire; disk forecast/drop counters.

Код: [backend/api/v1/logs/router.py](../../../backend/api/v1/logs/router.py).


### EP-034: Audit journal semantic outcome и redacted diff

**Открыт · P2 · PARTIAL**

Факт и границы: Audit journal/investigation имеют предыдущие исправления.

Дальше: Полный redacted diff, actor/effect/result correlation и cursor export не закрыты.

Критерии исходного плана:

- Actor/effect/result/receipt correlations.
- Before/after diff без secrets.
- Server filters/cursor и bounded export всего scope.

Код: [frontend/app/(dashboard)/audit/page.tsx](../../../frontend/app/(dashboard)/audit/page.tsx).


### EP-035: Dashboard attention queue и actionable drilldown

**Открыт · P2 · OPEN**

Факт и границы: Dashboard содержит текущие агрегаты/drilldowns.

Дальше: Actionable attention queue с reason/version/affected scope и total/page acceptance нужна.

Критерии исходного плана:

- Reasons affected scope/version/reconnect/task outcomes.
- Link открывает конкретный filter/detail.
- Data coverage и query total/page semantics видны.

Код: [frontend/app/(dashboard)/dashboard/page.tsx](../../../frontend/app/(dashboard)/dashboard/page.tsx).


### EP-036: Groups membership и bulk plan

**Открыт · P2 · PARTIAL**

Факт и границы: Group workflow/permissions/hierarchy имеют предыдущие исправления.

Дальше: Membership preview/owner/change evidence/bulk partial outcome UX ещё нужны.

Критерии исходного плана:

- Membership preview и affected target count.
- Notes/owner/last changed и audit links.
- Bulk partial outcome и filter scope понятны.

Код: [frontend/app/(dashboard)/groups/page.tsx](../../../frontend/app/(dashboard)/groups/page.tsx).


### EP-037: Locations hierarchy UX и validation

**Открыт · P2 · PARTIAL**

Факт и границы: Location hierarchy/forms имеют отдельные regressions.

Дальше: Полная create/edit/error/focus/mobile matrix и membership explain не приняты.

Критерии исходного плана:

- Parent tree/breadcrumb/cycle validation.
- Address/coordinates source/multiple membership explain.
- Create/edit failures удерживают поля и focus.

Код: [frontend/app/(dashboard)/locations/page.tsx](../../../frontend/app/(dashboard)/locations/page.tsx).


### EP-038: Discovery capability-scoped onboarding

**Открыт · P2 · OPEN**

Факт и границы: Discovery использует текущий agent/onboarding API; будущий PC-agent не установлен.

Дальше: Android onboarding без обязательного PC-agent, budgets/progress/cancel/dedup/receipts нужны.

Критерии исходного плана:

- Android onboarding не требует PC Agent.
- Agent-scoped subnet/ports/budgets/progress/cancel.
- Dedup results/registration receipts, permission explain.

Код: [frontend/app/(dashboard)/discovery/page.tsx](../../../frontend/app/(dashboard)/discovery/page.tsx).


### EP-039: Users role preview, safety и access review

**Открыт · P2 · PARTIAL**

Факт и границы: Role-aware Users и описания UserDialogs есть; Jest сохраняет Radix warnings.

Дальше: Fixture warning не доказывает production defect; полная role/revision/revocation/a11y matrix нужна.

Критерии исходного плана:

- Permissions preview и role revision conflict.
- Last admin/self disable policy + server enforcement.
- Revoked session и tenant tests.

Код: [frontend/app/(dashboard)/users/page.tsx](../../../frontend/app/(dashboard)/users/page.tsx).


### EP-040: Configuration effective state и разделение policies

**Открыт · P2 · PARTIAL**

Факт и границы: Settings/pipeline settings имеют текущие permission scopes.

Дальше: Effective/applied generations, policy composition, secret lifecycle и unknown/conflict save states не приняты целиком.

Критерии исходного плана:

- Workspace tabs с независимыми permission scopes.
- Pending/effective/applied config generations.
- Secret lifecycle и errors без ложного save success.

Код: [frontend/app/(dashboard)/settings/page.tsx](../../../frontend/app/(dashboard)/settings/page.tsx) · [frontend/app/(dashboard)/pipeline-settings/page.tsx](../../../frontend/app/(dashboard)/pipeline-settings/page.tsx).


### EP-041: Release rollout receipts и каналы

**Открыт · P1 · PARTIAL**

Факт и границы: Addressed OTA/release identity имеют finite receipts; pilot10249 не означает весь парк.

Дальше: Stable promotion, normal/dev compatibility, rollout/rollback и mixed-fleet soak остаются.

Критерии исходного плана:

- Offered/downloaded/verified/installed/unknown по target.
- Platform/flavor/code/signer/hash preflight.
- Recovery/rollback constraints видны; нет скрытого массового обновления.

Код: [frontend/app/(dashboard)/updates/page.tsx](../../../frontend/app/(dashboard)/updates/page.tsx).


### EP-042: Generic resources вместо game domain assumptions

**Открыт · P2 · OPEN**

Факт и границы: GameAccount/game-specific history остаются в backend.

Дальше: ResourceType/Record/Lease/SecretRef/Connector с migration/legacy adapter/rollback нужны.

Критерии исходного плана:

- Versioned ResourceType/Record/Lease/SecretRef/Connector.
- Legacy adapters/migration/rollback сохраняют history.
- Никакого удаления game models в UI fix phase.

Код: [backend/models/game_account.py](../../../backend/models/game_account.py) · [backend/schemas/pipeline_settings.py](../../../backend/schemas/pipeline_settings.py).


### EP-043: Разделить account session и universal run

**Открыт · P2 · OPEN**

Факт и границы: Sessions связаны с domain model; workflowRun/account session не унифицированы.

Дальше: Ясный naming/lease context/history adapter и independent CanonicalRun нужны.

Критерии исходного плана:

- Названия, relations и lease context однозначны.
- Исторические sessions доступны через adapter.
- CanonicalRun/Task не зависят от одной игры.

Код: [frontend/app/(dashboard)/sessions/page.tsx](../../../frontend/app/(dashboard)/sessions/page.tsx).


### EP-044: VPN assigned/applied/handshake/egress outcomes

**Открыт · P1 · PARTIAL**

Факт и границы: Provision outcomes/assignment/Android VPN observation разделены.

Дальше: Actual applied/handshake/egress и partial/unknown recovery требуют live targets.

Критерии исходного плана:

- Provision receipt иactual Android state раздельны.
- Unknown не превращается в successбез проверки.
- Control transport и egress VPN разделены.

Код: [frontend/app/(dashboard)/vpn/page.tsx](../../../frontend/app/(dashboard)/vpn/page.tsx).


### EP-045: Versioned VPN provider adapters и rotation

**Открыт · P2 · DEFERRED_DESIGN**

Факт и границы: Amnezia/WireGuard/proxy adapters/script rotation остаются проектированием.

Дальше: Versioned import/apply/status/rotate/upgrade/rollback, secret refs исохранность control нужны.

Критерии исходного плана:

- Validate/import/apply/status/rotate/upgrade/rollback contract.
- Config / binary / capability versions и secret refs.
- Manual/script/schedule один API, recovery control сохраняется.

Код: [frontend/app/(dashboard)/vpn/page.tsx](../../../frontend/app/(dashboard)/vpn/page.tsx).


### EP-046: AI-ready schemas/runbooks и scoped artifacts

**Открыт · P2 · DEFERRED_DESIGN**

Факт и границы: API/schemas/runbooks есть; AI provider/chat/tool runner не установлен.

Дальше: Scoped tools, draft→validate→test→publish, effects/TTL/budgets/provenance нужны.

Критерии исходного плана:

- Natural language → draft → validate → test → publish.
- API schemas / examples / reason codes / recovery instructions.
- Observations не дают privileges, budgets / TTL / RBAC обязательны.

Код: [backend/schemas/dag.py](../../../backend/schemas/dag.py).


### EP-047: Общая matrix500/1000 иresource leak gates

**Открыт · P1 · PARTIAL**

Факт и границы: Observer завершён 8 октября 09: 01UTC; VHD/VMDK allocations постоянны, freeC падал; writerUNKNOWN.

Дальше: Сейчас нет новых writer measurements; нужен bounded collector health/deadline/coverage и 500/1000/128/1 load matrix.

Критерии исходного плана:

- 1000 registry / 128 thumbnails / 1 selected video measured.
- Нет роста decoder / URL / log / report buffers после teardown.
- VHD/guest/RAM/provenance отдельные readings.

Код: [frontend/src/features/devices/FleetMatrix.tsx](../../../frontend/src/features/devices/FleetMatrix.tsx) · [backend/api/v1/logs/router.py](../../../backend/api/v1/logs/router.py).


### EP-048: Тесты всех меню/форм/ролей иvisual states

**Открыт · P1 · PARTIAL**

Факт и границы: Finite desktop/portrait/landscape Studio принят ec3f2267; после clock fix1938 tests проходят.

Дальше: Все страницы/модалки/роли/темы/zoom/reduced-motion не приняты; landscape chain fit мелкий.

Критерии исходного плана:

- Loading/empty/error/offline/forbidden/partial/conflict.
- Keyboard / zoom / mobile / reduced motion / 4 themes.
- Actual write receipt + repeat validation после deploy.

Код: [frontend/src/features/preferences/AppearanceDrawer.tsx](../../../frontend/src/features/preferences/AppearanceDrawer.tsx) · [frontend/app/(dashboard)/orchestration/page.tsx](../../../frontend/app/(dashboard)/orchestration/page.tsx).


### EP-049: Документация source/runtime/schema freshness

**Открыт · P1 · PARTIAL**

Факт и границы: Source/installed UI/API/schema/evidenceSHA разделены; старые pointers/comments исправляются.

Дальше: Effective ledger и admission каждой новойдоставки нужны; CI старого SHA не переносится.

Критерии исходного плана:

- Installed SHA/manifest/capability visible с датой.
- Docs генерацияв pinned runtime, с проверенной версией генератора.
- Evidence immutable; новый результат отдельнымclosure receipt.
- Default-branch dependency alerts сопоставлены с PR lock и installed SBOM; другие 142 alerts пока не приняты.

Код: [scripts/export_api_docs.py](../../../scripts/export_api_docs.py) · [docs/operations/CURRENT-STATE.md](../../../docs/operations/CURRENT-STATE.md).


### EP-050: Alert delivery иsynthetic Android SLI

**Открыт · P1 · OPEN**

Факт и границы: Collection/HTTP/resources и events есть; synthetic Android SLI не принят.

Дальше: Alert→affected scope→runbook→recovery и bounded Android synthetic нужны.

Критерии исходного плана:

- Scrape/HTTP/stream/script/OTA разные SLI.
- Alert→affected scope→runbook→observed recovery.
- Synthetic target bounded с разрешёнными effects.

Код: [backend/api/v1/monitoring/router.py](../../../backend/api/v1/monitoring/router.py).


## Машинная сверка и границы

[Актуальный ledger и SHA-256 source/evidence](CHAT-CODE-RECONCILIATION.json).
Все 50 ID уникальны; 9 accepted / 41 open выведены из закреплённых receipts;
legacy 7 unclosed — из отдельного среза. Original criteria/dependencies сохранены.
Ни один OPEN не закрыт этим документом.

Radix warnings в Users fixtures сохраняются, но UserDialogs уже содержит
DialogDescription/aria-describedby: сообщение само не доказывает production defect.
Доступность всех модальных окон остаётся EP-048.

Новая доставка исходников требует нового CI/install/live receipt.
Не переносить screenshot/CI ec3f2267 на другую ревизию.
