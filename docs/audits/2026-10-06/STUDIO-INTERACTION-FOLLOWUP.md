# Script Studio и управление Android: продолжение аудита

Дата: **6 октября 2026**, UTC. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Исходный baseline `bc9f4bb`; PNG source fix — **59fa314**. Установленный UI
**1c26ffc7**, API **eb7a7c26**. Live проверки ниже относятся к этим версиям.
Новые связи и selector queue ещё не установлены; host build/deploy gate закрыт.

**Датированное продолжение 7 октября:** repair завершён; UI b50d6ae установлен
на 3015. Свободная сборка/связи приняты на baseline 439f910, ordered recorder —
на 99af20d; b50d6ae добавляет принятый resize overview и сохранение ручного zoom.
[Latest runtime/browser/CI receipt](../2026-10-07/STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json) ·
[Resize](../2026-10-07/STUDIO-CANVAS-RESIZE.md).
**Позднейший срез 7 октября, 03:35 +05:** API 114775a получил live contract 1.0
для 32 действий: valid 200, missing coordinates 422, anonymous 401. 25 сценариев
сохранены, 14 online agents переподключились; APK не менялся.
[API delivery/acceptance](../2026-10-07/REVIEWED-BACKEND-DELIVERY.md).
CI exact source: frontend 1692/133, backend 3037 passed / 37 skipped и Android success.
Утверждения installed 1c26ffc7/закрытый host gate выше и в таблице ниже —
исторический срез 6 октября. Continuous/rich recorder остаются открытыми;
старые JSON receipts не переписываются как новые результаты.

Этот документ дополняет [основной аудит](../2026-10-05/ENTERPRISE-PRODUCT-AUDIT.md),
[исходный backlog](../2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json),
[доставленную запись команд](STUDIO-COMMAND-RECORDING.md) и
[инструкцию Studio](../../operations/SCRIPT-STUDIO.md).
Исторические JSON state не переписываются как будто все пункты завершены.
Общая приёмка остаётся **9 accepted / 41 open**; прежние восемь release gates
являются другим списком и не означают восемь оставшихся работ по всему продукту.

## Новые требования и фактическое состояние

| ID | Требование | EP / приоритет | Состояние этого среза |
| --- | --- | --- | --- |
| SF26-01 | Разорвать/перенести связь между шагами | EP-014,015 / P1 | Source fix, 38 scoped tests; новая UI приёмка ожидается |
| SF26-02 | Настроенные Android navigation actions в библиотеке | EP-016,018 / P1 | Source: шесть key_event presets, без live input |
| SF26-03 | Записывать Home/Back/Recents рядом с видео | EP-018 / P1 | Уже installed; Home повторно проверен PH010; остальные варианты не объявляются live-accepted |
| SF26-04 | XPath из inspector в ходе записи без перестановки шагов | EP-018 / P1 | Source selector review queue; отдельная пометка future action, не APK ACK |
| SF26-05 | Непрерывное управление до отпускания мыши | EP-017,020 / P1 | Подтверждён пробел всего input protocol; нужен APK injector и channel lifecycle |
| SF26-06 | Специальная запись: XPath, область, native crop, цвет pixel | EP-018,019,022 / P1 | Design/dependencies описаны ниже; реализации correlated evidence нет |
| SF26-07 | Исходный PNG без pixel loss | EP-022 / P1 | Конкретный файл PH011 принят по pixel evidence; это не закрытие всех artifacts |
| SF26-08 | Визуальные группы/subgraphs и высокоуровневые связи | EP-014,015,020 / P2 | Нужны semantic contract, versioned composition и debug boundaries |
| SF26-09 | Подключить выбранную группу целиком / 128 thumbnails | EP-031 / P2 | Отдельный bounded thumbnail subscription; не128 full-video sessions |
| SF26-10 | Синхронный клик/жест выбранной группы | EP-020,031 / P2 | Нужны target manifest, ownership, partial outcome и stop; не blind broadcast |
| SF26-11 | AI узлы/страница/чат и наблюдаемое исполнение | EP-046 / P2 | Будущий provider adapter, typed tool contracts и scoped evidence; provider не подключён |
| SF26-12 | Свободное добавление/drag-drop вместо обязательной вставки | EP-014,015 / P1 | Source free canvas: отдельный узел, явная вставка, draft/publish split;395 tests/17 suites, types passed; visual/runtime gate открыт |

[Свободная сборка, удаление, восстановление и приёмка](STUDIO-FREE-CANVAS.md)
добавлены по последнему уточнению пользователя. Installed UI не обновлён.

## Подтверждённые runtime наблюдения

### Связи

Во временном непубликованном Start→End документе работающего UI выделение
линии и Delete уже удаляли связь; Undo восстанавливал JSON. Не было явного
редактора связи и `onReconnect`, поэтому операция плохо обнаруживалась.
Новый source добавляет **Откуда / Когда / Куда / Разорвать связь**, расширяет
попадание в линию и сохраняет workbench при редактировании.
[Контракт, tests и browser acceptance](STUDIO-CONNECTION-EDITING.md).

### Navigation recording

На локальном PH010, device `5df4805e-fe64-4d39-960c-19ceab206cd6`, APK1.2.45-dev,
включена запись в installed Studio. Home появился как **Ожидает APK**, затем
**Подтверждено APK**, observed ACK **439 ms**. После Stop и явной вставки
JSON содержал `key_event:3` между Start и End. Новый script/task не публиковался,
чужие данные Android не менялись; launcher уже был открыт.

Это функциональный canary одной команды, а не p95 или input-to-frame latency,
FPS, fleet soak либо универсальная поддержка каждой клавиши/версии APK.
Home/Back/Recents работают через существующий HTTP APK observer; click/swipe
через WS по-прежнему имеют только transport-submitted receipt.

### PNG

Проверен именно filename, указанный пользователем, на PH011: **960×540,
236 486 B**, RGBA8, без pHYs/eXIf. Server trace по snapshot ID подтвердил
native capture, **10/10 RPC**, **6714 ms**, cleanup. Независимый PNG и RAW
совпали по всем518 400pixels. Все495 360pixels пользовательского файла ниже
status bar тоже совпали;126 изменившихся pixels находятся только в верхней строке.
[Полная проверка и границы](NATIVE-PNG-PIXEL-VERIFICATION.md) ·
[Receipt](NATIVE-PNG-PIXEL-EVIDENCE.json).

В source есть native1:1 preview, original download без byte mutation и
разделение video frame export. Это не native crop/pixel sampler в recorder.
Текущая задержка native root capture не позволяет незаметно выполнять его
перед каждым кликом и одновременно обещать мгновенную интерактивность.

## Selector queue: исправление порядка и честные outcomes

Прежний callback `onInsertSelector` сразу изменял DAG, тогда как record buffer
click/key/text переносился позднее. Клик→XPath мог превратиться в XPath→клик.
Source fix использует общий bounded review buffer:

1. В inspector **Добавить XPath в очередь записи** добавляет `tap_element`
   в текущую позицию timeline, в recording и stopped режимах.
2. Статус **В план · не выполнялся** отличается от WS submission и APK ACK.
   Выбор inspector не нажимает элемент Android и не запускает task.
3. Device/snapshot/node membership, geometry, rotation, XPath syntax/length,
   timestamp order и общий лимит200 проверяются до добавления.
4. При остановке запись можно просмотреть, удалить отдельный planned step и
   явно перенести всю очередь. Pending/unknown команды сохраняют прежний guard.
5. В DAG входит только исполняемый `tap_element` selector. Snapshot ID/node ID/
   rotation остаются временным review context; private attributes не копируются.
   Это ещё не durable artifact manifest или доказательство устойчивости XPath.

[Recording model](../../../frontend/src/features/scripts/studio/recording.ts) ·
[Workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx) ·
[Model acceptance](../../../frontend/__tests__/scripts/studio-selector-recording.test.ts) ·
[UI acceptance](../../../frontend/__tests__/scripts/studio-workbench.test.tsx).

## Следующий P1: continuous pointer protocol

6 октября pinned upstream исследован отдельно:
[scrcpy5.0, точный commit, control-only adapter и отказные случаи](CONTINUOUS-INPUT-INTEGRATION.md).
Это design/source audit, не поставленный continuous mode.

До нового injector сделан отдельный source P1
[общего контракта параметров 32 опубликованных действий](STUDIO-ACTION-PARAMETERS.md).
Он блокирует malformed новые publications и раскрывает требования/optional fields
в NodeInspector; не меняет motion protocol, APK или installed runtime. Доставка и
capability preflight остаются открытыми. У continuous pointer прежние критерии ниже.

Текущий browser pointerdown лишь начинает локальный drag; pointerup отправляет
один click/swipe. Backend принимает только `click/swipe/keyevent/text`; APK
исполняет конечный `input swipe`. Непрерывного DOWN/MOVE/UP сейчас нет.
[Browser input](../../../frontend/components/sphere/DeviceStream.tsx) ·
[WS contract](../../../backend/api/ws/stream/router.py) ·
[APK executor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt).

Готовый первичный reference — **scrcpy**, Genymobile, Apache-2.0: отдельный
control channel, MotionEvent injection, shell/app_process privilege. Собственный
H.264 канал Sphere можно сохранить; замена всей бизнес-логики не требуется.
Client/server scrcpy protocol зависит от одинаковой версии; перед интеграцией
нужны pinned revision, лицензия и compatibility matrix, а не произвольный latest.
[Architecture](https://github.com/Genymobile/scrcpy/blob/master/doc/develop.md) ·
[Controller source](https://github.com/Genymobile/scrcpy/blob/master/server/src/main/java/com/genymobile/scrcpy/control/Controller.java).
Scrcpy не установлен/не встроен этим срезом; его код не копировался.

Требования перед включением:

- Agent capability negotiation: старые APK продолжают существующий discrete
  mode; UI не обещает continuous input без подтверждённого injector.
- Один owner/lease на device и touch sequence; pointer ID, downTime, monotonic
  eventTime, display/rotation/session epoch. Replayed/foreign events отклоняются.
- Bounded queue и MOVE coalescing; UP/CANCEL имеют приоритет и не исчезают при
  backpressure. Нельзя эмулировать held touch серией самостоятельных swipes.
- Pointercancel, focus loss, socket close, lease expiry, APK death и смена
  геометрии завершают touch. Reconnect не восстанавливает старый DOWN.
- Recorder хранит path как новый поддержанный action либо отдельный trace;
  не превращает кривую линию в якобы точный straight swipe без предупреждения.
- Замерять input submit→inject ACK и input→первый изменившийся rendered frame
  отдельно. APK ACK не является визуальным результатом.

Приёмка: held drag на локальном и удалённом canary, движение до mouseup,
поворот, exit viewport, disconnect на held DOWN, reordered/duplicate frames,
конкурирующий controller, weak emulator5/10Hz. CPU/RAM/queue depth и latency
отмечаются вместе с display Hz/FPS; искусственное дублирование кадров не считается
ростом capture rate. Проверка не меняет лимит FPS всего парка автоматически.

## P1 special recorder: коррелированные observations

Специальный режим должен явно отделять **исполняемое действие** от **наблюдений**:

| Часть | Обязательный контекст |
| --- | --- |
| Touch | display coordinates, normalized/ref coordinates, path, duration, command ID |
| UI tree | snapshot ID, requested/completed times, rotation, full attributes, selector candidates |
| Original pixels | source PNG hash, capture/display dimensions, timestamps, crop rectangle и source coordinates |
| Pixel probe | RGBA, source hash, точные integer x/y, declared color space/unknown |
| Outcome | submission, APK dispatch, observed postcondition, task/run/node/attempt IDs |

Не брать pixels из H.264 decoded frame для original эталона. Crop делать от
полного native PNG без resize/JPEG; полный source hash и координаты оставлять
рядом. Элемент, дерево и картинка могут относиться к разным моментам: record
должен показывать skew и invalidation, а не объявлять их одним кадром.

Нужны versioned manifest, event/capture ordering, sampling budgets, interrupt
policy, auth/tenant scoping, explicit export и retention. Text/resource IDs/
screenshots могут содержать private content; rich evidence opt-in и отделяется
от operational logs. Ограничения bytes/files/TTL и cleanup receipts обязательны
до массового включения — это связано с текущим disk-growth incident.

Server task artifact transport/lifecycle остаётся открытым EP-022; local APK
cache8files/5MiB/30min не означает server delivery. Наличие PNG не является
подтверждением cloud artifact или работоспособности каждой detector strategy.
[APK screenshot cache](ANDROID-SCREENSHOT-CACHE.md).

## Composition, fleet input и AI: отдельные границы

Canvas group — визуальная зона; subgraph — исполняемая composition с входами,
выходами, pinned version и parameter contract. Task/schedule/orchestration не
следует превращать в декоративные nodes без backend semantics. Первым этапом
нужны schema/compiler/lifecycle и сохранение JSON round-trip; далее debug scope,
cancel propagation и deterministic resume. Существующие вкладки можно связать
общим workspace, сохраняя их authority и идентичность ресурсов.

Fleet synchronizer требует явного target manifest, совместимой geometry,
capability/freshness и отдельного ownership. Partial failure показывает итог
каждой машины; автоматического повтора неизвестного действия нет. Подключение
128 thumbnails имеет отдельные budgets и cadence; full-video остаётся у выбранной
машины. Группа не является разрешением управлять скрытыми/чужими устройствами.

AI integration должна использовать те же typed tools, RBAC, pinned versions,
receipts и bounded artifacts. Chat может показывать публичные пояснения решений,
вызовы инструментов и подтверждённые результаты по выбранному run/device.
Provider secrets, бесконечные raw logs и неподтверждённый «успех» в transcript
не допускаются. Плагины/providers обновляются через versioned adapter, без
переписывания базового DAG или привязки к одной игре. AI/VPN redesign в этом
срезе не внедрён.

## Проверки, доставка и порядок работ

**234 tests / 11 suites passed**, затем strengthened selector bound case
**10/10 passed**; TypeScript прошёл с1GiB heap. Проверены reconnect/duplicate
outlets/legacy branch, permissions/pending edit/Undo/workbench, selector ordering,
limits/foreign context/no fake ACK, native screenshot lifecycle, navigation и DAG.
Ранее одиночные tests выявили ошибки test harness: structuredClone в jsdom,
React empty style attribute и static mock UUID; они исправлены без подавления
production errors. Последний общий scoped прогон не содержит React warnings.

Это bounded source regression, не production build, hosted rollout, новая
визуальная приёмка или тест500–1000машин. C: остаётся **Warning / Full Repair
Needed**; postboot repair acceptance и независимый backup не подтверждены.
[Host incident и acceptance](HOST-FILESYSTEM-INCIDENT.md).

Порядок: host acceptance → immutable build/deploy и browser matrix новых
source fixes → continuous injector/channel → rich observations/artifact transport
→ correlated debugger → composition/fleet sync → AI/provider workspace.
Ни новая версия APK, ни весь парк, ни туннели этим срезом не обновлялись.
