# Sphere: актуальное состояние и критерии приёмки

**Проверенная установка:** UI `369654a0` / API `369654a0`.

**10 октября — broadcast исправлен и установлен.** На обоих адресах UI/API369;
все4 exact-source CI success:3428 backend tests/252subtests,1966 frontend tests.
Изолированный PostgreSQL/Redis test подтвердил202, commit и admission. На рабочем
стенде ожидаемый404 после чтения presence проверен без запуска массовых действий.
APK, schema/OTA и45соседних контейнеров сохранены при каждой установке.
Idle control и direct transport остаются открытыми; probe выключен.
[Установка, проверки и остаток](../audits/2026-10-10/BROADCAST-INSTALLED-ACCEPTANCE.md).

Последнее сравнение: public idle heartbeat512мс, lastACK487мс; local ACK244мс
без fault в конечном срезе. Это не синхронный trace или причинная атрибуция.
[Наблюдения](../audits/2026-10-10/IDLE-LOCAL-PUBLIC-COMPARISON.md).
Close/phase/network diagnostics теперь доставлены, но новый native ICE canary
не проведён. [APK1.3 plan](../design/APK-1.3-COMPATIBILITY-AND-RELEASE.md) — NO-GO.
Product9/41,legacy7; limited observer21:09→12:41UTC и whole-PC writer UNKNOWN.

## Исторические срезы до последней установки

Следующие даты, source-only статусы и версии относятся к записанным тогда окнам.
Текущая установка и delivery receipt указаны выше.

**9 октября18:23UTC — API9ad установлен, direct pilot завершён без соединения.**
Две native попытки подтвердили загрузку JNI и публикацию авторизованного SDP answer,
но host ICE не открыл DataChannel: ноль RTT samples, причина UNKNOWN. PH011 вернули
прежний APK d8023bce /1.2.49-dev; probe endpoint отключён, allowlist пуст.
UI d70 сохранён,45соседних контейнеров/schema/OTA/публичные маршруты сохранены.
Обычный viewer получил13кадров без decode/render errors; idle timeout повторился.
Новая source коррекция закрытия сокета и фаз диагностики проверена локально,
на3015ещё не установлена. [Пилот, ресурсы и границы](../audits/2026-10-09/DIRECT-PROBE-PILOT.md).
Последующий source bounded ICE/DTLS snapshot сохраняет counters/unknown/age при
отказе:16focused frontend tests/types passed. Рабочий runtime не менялся;
[exact CI/delivery и network canary ещё требуются](../audits/2026-10-09/DIRECT-PROBE-NETWORK-SNAPSHOT.md).

**Предыдущая UI-only установка9октября — d70f55c6 на3015 и публичном адресе.**
Idle-only потеря подтверждения теперь имеет точную категорию и текст; при неизвестном
касании предупреждение и блокировка сохраняются. Статус читаем в светлой теме
на фоне видео. Frontend CI: 1950 tests / 139 suites, types/build, 26 pages / 73 assets.
45 соседних контейнеров, API/APK/schema/OTA сохранены. Конечная проверка wording/контраста
не закрывает повторившийся idle timeout или задержку.
[Installed receipt](../audits/2026-10-09/IDLE-CONTROL-UX-INSTALLED.md).

**9 октября — direct transport: исследование и отключённый source prototype:** подтверждён общий
APK video/input-receipt WebSocket и server relay. Public PH011 без касаний повторил
idle failure: actual ACK RTT518ms, heartbeat deadline age503ms. Причина задержки
не локализована. Предложен browser↔APK WebRTC prototype для video и input вместе,
с TURN fallback и обязательными ownership/network/resource gates.
Последующим запросом разрешена разработка RTT-only canary; межпроцессное SDP,
browser echo и отдельный Android debug source set написаны. AAR pinned; live RTT
и native cleanup ещё не приняты, рабочий media/control транспорт сохранён.
[Scope и source checks](../audits/2026-10-09/DIRECT-PROBE-SOURCE.md).
[План и первичные источники](../design/BROWSER-DIRECT-TRANSPORT.md) ·
[Source/test UI correction и фактическая canary](../audits/2026-10-09/IDLE-CONTROL-RELAY-REVIEW.md).

**9 октября16:21UTC — исправлена загрузка Grafana через публичный туннель.**
Дополнительная проверка воспроизвела parse errors двух больших JS, отсутствующие
на3015. Static-only gzip на gateway восстановил dashboard в двух открытиях;
все46контейнеров/API/WS/bootstrap сохранены. Пройдены22страницы, F5/query/export/worker;
PH011 read-only viewer отрисовал6кадров без decoder errors, steady FPS/control
не приняты. Прежняя отметка об открытии Grafana уточнена этим новым доказательством.
[Дополнительная QA и исправление](../audits/2026-10-09/PUBLIC-WEB-SUPPLEMENTAL-QA.md).

**9 октября, 15:53 UTC / 20:53 UTC+5 — новый веб подключён к действующему Tuna-туннелю.**
На этом историческом срезе публичный адрес начал обслуживать UI86354350, как и 3015; прежний публичный
frontend8fef5eb больше не выбирается для этого host. API d720232e, bootstrap/WS,
APK/OTA и все46 контейнеров сохранены; только Nginx graceful reload, без новой
сборки. В браузере приняты вход,22сценария, существующий граф3узла/2связи и
наблюдаемость; временный monitoring request failure сохранён, refresh восстановил
данные. Это не приёмка public stream/control или устранение idle/дискового риска.
[Доставка и ограничения](../audits/2026-10-09/PUBLIC-WEB-DELIVERY.md).

**9 октября — защита актуальных указателей runtime в документации.**
После установки таймингов найдены устаревшие current-claims API be803773 в
SCRIPT-STUDIO/READINESS и старый UI ec3f2267 в LOCAL-PILOT. Указатели исправлены;
десять входных документов и руководств теперь имеют единый проверяемый banner.
Checker отвергает старую API/UI пару, отсутствующий, дублирующийся или скрытый
ниже истории banner. 26 documentation regressions прошли; исторические версии
в датированных receipts сохранены. Это статическая согласованность конкретного
указателя, не семантическая аттестация всех документов или новая runtime установка.
[Правило обновления](../DOCUMENTATION.md) · [Действующий реестр](WORK-STATUS.md).

**Действующий реестр работ:** [WORK-STATUS](WORK-STATUS.md) / [машинный статус](STATUS-REGISTRY.json).
Source, установленный runtime и конечная приёмка разделены; старые snapshots ниже сохраняют свои даты.

**Обновлено:** 9 октября 2026, Asia/Yekaterinburg; даты отдельных runtime/CI срезов указаны ниже.<br />
**Область:** исходники и документация ветки PR #19, записанные runtime-наблюдения, Android APK и готовность следующего прогона.<br />
**Канонический документ текущего состояния:** этот файл. Исторические отчёты ниже сохраняют исходные даты и факты.

**9 октября15:17UTC /20:17UTC+5 — API d720232e установлен, UI86354350 сохранён.**
Bounded server timings доставлены из exact-source CI image;45other containers/schema/OTA/APK
сохранены. Все4 CI successful; backend3387passed/37skipped/233subtests, full hosted mypy.
PH011 idle failure снова воспроизведён: heartbeat510ms/tick15ms/lastACK RTT256ms/WS OPEN0B,
no held pointer/terminal. Все наблюдаемые server spans <25ms; queue/network/APK/native
причина OPEN. Графv1/3узла2связи/Undo0, queue0 сохранены; View/lab/temp tab закрыты.
Ни deadlines, ни replay не менялись.4workers/metric mmap1MiB в конечном срезе;
это не resource soak. Product9/41 и whole-PC writer UNKNOWN сохраняются.
[Доставка, измерения и ограничения](../audits/2026-10-09/CONTINUOUS-SERVER-TIMINGS-INSTALLED.md).

**Предыдущая UI-only установка9октября: 86354350/APIbe803773.**
Failure snapshot и доступная desktop/phone диагностика установлены; frontend exact-source
CI success, frontend1948tests/139suites. 45other containers/schema/OTA/APK сохранены.
На предыдущем UI0b321d49 PH011 idle failure снова подтверждён: heartbeat512ms,
tick15ms, last ACK RTT248ms, WS OPEN/0B, без касаний/terminal. Причина OPEN,
настройки deadline и replay не изменены. Graphv1/3узла/2связи/Undo0, queue0 сохранены.
[Установка, приёмка и границы](../audits/2026-10-09/STREAM-DIAGNOSTICS-INSTALLED-ACCEPTANCE.md).

**Предыдущая сверка9октября — чат, документы и код:** [актуальная карта всех 50 пунктов](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.md)
и [машинный ledger с SHA-256](../audits/2026-10-09/CHAT-CODE-RECONCILIATION.json).
Продуктовый объём остаётся **9 принято / 41 открыто**. Старый веб-аудит отдельно:
последний записанный срез **34 source-fixed / 7 незакрытых**, включая F32/F33/F39
PARTIAL; прежние восемь — более ранняя запись, а не остаток всего продукта.
Найден и воспроизведён дефект смешения Date.now/performance.now при записи
XPath → следующий input. Source **1577e01e** исправляет его; 76 focused и все
1938 frontend tests/139 suites, nonincremental TypeScript проходят. UI60be6ecd
установлен на3015 с APIbe803773; finite PH011 mixed recording принята ниже.
Normal continuous input уже подключён, recorded MOVE/tree/crop/pixel bundle
остаётся OPEN. Idle receipt failure и whole-PC writer UNKNOWN — приоритеты перед расширением
automation. Новое limited окно наблюдения за диском описано ниже.
[Clock regression и границы](../audits/2026-10-09/STUDIO-RECORDER-CLOCK-FIX.md).

**9 октября12:42UTC /17:42UTC+5 — limited disk/RAM observation возобновлено.**
721×120s до10Oct12:42UTC,16MiB;24known named files и RAM/process/Docker/WSL.
Complete samples, source SHA и PID/creation/command binding проверены.
VSS unavailable, USN/ETW не запущены; whole-PC writer UNKNOWN. Нет autostart,
прежний gap не покрыт. EP-033/047 и9/41 сохраняются.
[Срез и ограничения](../audits/2026-10-09/STORAGE-OBSERVER-RESTART.md).

**9 октября,02:28–02:34 UTC /07:28–07:34 UTC+5 — clock fix установлен.**
На3015 UI **60be6ecd** / API **be803773**. Все4 exact60be CI successful; frontend
1938tests/139suites, types/build,26pages/73assets. Only UI replaced,45other
containers/schema/OTA/APK сохранены. PH01110249: tap→planned XPath→tap→Back,
4строки без clock error; Back APK confirmed469мс. После Stop явный transfer
добавил4actions/2пауз, canonical9узлов/8связей; queue0. Undo восстановилv1/3узла/
2связи; View, lab/temp tab закрыты, чистая user tab refreshed. Save/Run не
выполнялись. Late-ACK-after-Stop live ordering не доказан, fixtures сохраняют
это покрытие. Long-chain overview слишком мелок; rich recorder/idle/ownership/
resources остаются OPEN,9/41 не меняется.
[Доставка, приёмка и границы](../audits/2026-10-09/STUDIO-CLOCK-INSTALLED-ACCEPTANCE.md).

**Предыдущая установка: 9 октября +05 / 8 октября21:43–21:51 UTC — responsive Studio/navigation.**
На3015 UI **ec3f2267** / API **be803773**. Reviewed UI заменён отдельно:
45other containers/schema/OTA/APK10249 сохранены. Frontend CI1936tests/
139suites, types/build,26pages/73assets passed. Все4 exact-source workflows
successful; backend3346passed/37skipped/229subtests, coverage80.72%.
Four compact panels сохраняют
queue/device state и прекращают скрытый ввод; desktop library доступна рядом
с laboratory. Реальный844×390 получил graph195px вместо112px;390×844 и
1440×900 проверены. Независимый node add/parameters/Undo не изменил published v1.
PH011 подтвердил Home3/Recents187/Back4/Menu82:4/4APK outcomes, порядок и очередь
сохранены при Actions→Device; запись не возобновилась. View выбран, тестовая
queue явно очищена, версия не опубликована и задание не запускалось.
Browser Back и общая кнопка вернули catalog main2132.5→2132.5px после commit.
Viewport reset. Continuous path/automatic XPath+PNG bundle и landscape overview
readability остаются OPEN; ledger9/41 не изменён.
[Установка, конечная приёмка и границы](../audits/2026-10-09/STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md) ·
[Компоновка](../audits/2026-10-09/STUDIO-RESPONSIVE-WORKSPACE.md) ·
[Контракт Back/scroll](../audits/2026-10-09/ROUTE-SCROLL-RESTORATION.md).

**9 октября +05 / 8 октября20:13–20:23 UTC — Studio outage retention установлен.**
Временный отказ capabilities скрывает/inert редактор, сохраняя same-identity
draft/queue/task/unknown guards; grants остаются запрещёнными. Stream/native
reads прекращаются, preparation до POST отменяется. Native PNG remount больше
не считается завершением прерванной Android-команды. Source regressions и
nonincremental TypeScript прошли; полный frontend1915/138suites. Portalled окно
запуска тоже приостанавливается, сохраняя pending/unknown/confirmed outcome
без скрытого redirect. Все4 exact-source CI successful; backend3346passed/
37skipped/229subtests. На3015 UI46ca2096/APIbe803773,45other containers/schema/
OTA/APK10249 сохранены. При72s API outage без F5 восстановились PH011/View,
тот же completed task с3отчётами/marks, PH011/priority8 в launch portal.
SQL read за конечное окно подтвердил1task; новые Android input не отправлялись.
Desktop1440/mobile390 проверены, viewport reset. Dirty queue/unknown POST/native
PNG abort доказаны fixtures; живой token refresh и idle failure не закрыты.
Ledger9accepted/41open.
[Контракт и доказательства](../audits/2026-10-09/STUDIO-PERMISSION-OUTAGE-RETENTION.md).

**8 октября,18:39–19:28 UTC /9 октября UTC+5 — API be803773 установлен.**
Failed viewer socket больше не выключает общий continuous listener. Backend
CI3346passed/37skipped/229subtests/80.71%; frontend1892/138suites, Android и
preview successful. Only API replaced;45other containers/schema/OTA/APK10249
сохранены. PH011 independent View подтвердил dragDOWN1/MOVE5/UP1 и wheel
deltaDOWN1/MOVE1/UP1, CANCEL0; receiver удалён, View выбран, viewport reset.
Idle native_receipt_timeout повторился: конечный успех не закрывает этот P1.
При transient capability failure потерялись laboratory/task UI state без F5;
это исторический trigger установленного выше state-retention fix. Ledger9accepted/41open.
[Установка, доказательства и ограничения](../audits/2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md).

**Storage window завершён09:01 UTC, не является работающим ночным наблюдателем.**
241/241samples за8h; свободное место C: уменьшилось6.48GiB, выделение Docker VHDX
и четырёх emulator VMDK неизменно. VSS недоступен; writer attribution UNKNOWN.
Рост внутри Docker guest не равен росту host VHDX. После09:01 есть monitoring gap;
новый collector/autostart не запускались. Incident OPEN.
[Полный разбор конечного окна](../audits/2026-10-08/STORAGE-WINDOW-COMPLETION.md).

**8 октября,18:08–18:18 UTC — UI36b160f9 установлен; API fault isolation подготовлен.**
Baseline5382fe4 пересоздаёт Workbench при token rotation, теряя запись/результаты
и unknown-POST guard. Source fix привязывает очистку к sessionVersion, сохраняя
token/frame/native-owner invalidation транспорта.6 новых baseline regressions
падали;93 focused tests/4suites и TypeScript прошли. Все4 CI successful:
frontend1892/138suites, backend3337passed/37skipped/229subtests. Reviewed UI
установлен,45 других контейнеров/schema/OTA сохранены. Saved-v1 canary
b50dd03f завершила3шага; View/queue0/graph3/2 сохранены. Реальный token refresh
пока не засвидетельствован; trigger прежнего runtime reset не записан.
[Доказательства и ограничения](../audits/2026-10-08/STUDIO-SESSION-REFRESH-STATE.md).
Видео работает, но API9610523 не подтверждает continuous capability. Source
regressions доказали, что failed viewer send выключает общий listener.
Fix изолирует только exact viewer и запрещает OPEN после failed binding;
27 runtime/158 related tests, Ruff/mypy passed. API установка ещё нужна;
реальный trigger отключения не доказан. SF26-05/06 и storage OPEN.
[Fault isolation](../audits/2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md).

**8 октября, 07:49–08:06 UTC — Studio UI `5382fe4` установлен на3015.**
API `9610523`, PH011 APK10249, schema и OTA сохранены;45 других контейнеров
не заменены. Запуск теперь ждёт known native release и завершения текущего
XPath/native capture; отказ до POST сообщает, что задания нет, неизвестный
POST не повторяется.237 local regressions/7suites и TypeScript прошли.
Все4 exact-source CI green: frontend1884/138suites, backend3337passed/37skipped/
229subtests, Android и preview. Две реальные saved-v1 canary выполнили3шага:
из native READY и во время root read. Сервер подтвердил cleanup/lock release
дерева за32ms до создания второго задания. Mobile390 без horizontal overflow;
View/queue0/graph3/2 сохранены, viewport override reset.
После простоя отдельно возник `native_receipt_timeout`; explicit recovery
вернул READY.60s direct service-only probe:240/240ACK, p95≈265ms/max≈462ms,
0touches, native RELEASE3. Он не объясняет browser idle failure.
Idle loss, global task/native lease, rich recording, root exit1 и storage OPEN;
ledger9accepted/41open. [Приёмка запуска](../audits/2026-10-08/STUDIO-TASK-INSTALLED-ACCEPTANCE.md) ·
[Приоритетный сбой простоя](../audits/2026-10-08/STUDIO-IDLE-RECEIPT-FOLLOWUP.md).

**8 октября, 07:10–07:15 UTC — Studio UI `a8945e4` установлен на3015.**
API `9610523`, PH011 APK10249 сохранены. Normal Studio Control теперь continuous
READY, независимо от callbacks записи: Android View подтвердил DOWN1/MOVE4/UP1/
CANCEL0. Start показал native-release preparation; записанный swipe дал1строку.
Home оставался pending после Stop и обновил исходную2-ю строку до confirmed
(ответ507ms); normal control вернулся в READY.201 local regressions, hosted
frontend1869/138suites, types/build/image admission passed.45 других контейнеров
и OTA сохранены. Graph3/2 без изменения, test queue/receiver удалены; desktop1440
и mobile390 проверены, viewport reset. Task-launch handoff, rich recording,
root exit1 и storage OPEN; ledger9accepted/41open.
[Установленная приёмка](../audits/2026-10-08/STUDIO-RECORDER-INSTALLED-ACCEPTANCE.md).

**8 октября, 06:53–06:55 UTC — UI/API `9610523` установлены на3015.**
XPath показывает этап отказа и snapshot ID, сохраняет возраст предыдущего дерева
и приостанавливает автоопрос. Реальная native-owner busy canary без касаний
показала502/native_input_busy; после RELEASE3 явный retry получил46узлов,
cleanup/lock release подтверждены, Control вернулся в READY.
Frontend1861/138suites; backend3335passed/37skipped/229subtests; full CI green.
45 других контейнеров сохранены каждым install, schema/OTA без изменения;
Compose model roundtrip проверен, UI17→2/API10→2 файлов. APK10249 толькоPH011.
Исторический root exit1, storage и host corruption OPEN; ledger9accepted/41open.
[Установленная приёмка и ограничения](../audits/2026-10-08/UI-INSPECTION-INSTALLED-ACCEPTANCE.md).

**8 октября, 07:27–07:31 UTC+5 — финальный UI `e88c4db` установлен на3015.**
API `2225f73` и PH011 APK10249 сохранены; frontend1848passed/137suites,
types/build/26packaged pages/73assets.45 других контейнеров и OTA неизменны.
Обычное управление автоматически включает живые жесты, отдельной кнопки нет.
Исправленный быстрый XPath→Control при pending root read показал drain, затем
вернулся в READY без recovery; повторный вход в XPath получил46узлов и highlight.
Независимый Android View после переходов: dragDOWN1/MOVE4/UP1/CANCEL0,
wheelDOWN1/MOVE1/UP1/CANCEL0; Home748ms вернул launcher и automatic READY.
Тестовый receiver удалён. Единственный прежний root read exit1 пока не объяснён;
finite успешный прогон не закрывает root/fleet fault soak. APK10249 толькоPH011,
normalOTA не продвигался. SF26-05OPEN, ledger9accepted/41open.
[Установленная приёмка, provenance и ограничения](../audits/2026-10-08/CONTROL-HANDOFF-INSTALLED-ACCEPTANCE.md).

### Предшествующие checkpoints автоматического управления

**8 октября, 07:01–07:15 UTC+5 — UI `29eecb8`, API `2225f73` установлены.**
Обычное «Управление» включает непрерывные жесты без отдельного переключателя.
PH011 APK10249 подтверждён независимым Android View: dragDOWN1/MOVE5/UP1/
CANCEL0, wheelDOWN1/MOVE1/UP1/CANCEL0. Home765ms вернул launcher и native READY.
XPath дождался release, получил46узлов и выделил launcher элемент без нажатия.
Один следующий auto read завершился root SHELL exit1; причина не установлена.
После явного возобновления несколько чтений успешны; это не закрывает ошибку.
Быстрый возврат в Control во время root read воспроизвёл native rejection;
source `e88c4db` удерживает gate до завершения запроса, его установка ещё требуется.
UI hosted1844/137, API3327passed/37skipped/229subtests;45 других контейнеров,
schema head и OTA сохранены. APK10249 толькоPH011; normalOTA не продвигался.
[Обратный переход и регрессии](../audits/2026-10-08/INSPECTION-RETURN-TO-CONTROL.md) ·
[Idle receipt recovery](../audits/2026-10-08/IDLE-RECEIPT-RECONCILIATION.md).
SF26-05OPEN, ledger9accepted/41open; storage и повторное Git повреждение OPEN.

**8 октября, 06:08–06:16 UTC+5 — автоматический UI установлен; Home follow-up открыт.**
Reviewed UI `bc86752` на3015, API `28104f8` и APK10249 PH011 сохранены.
Открытие видеопотока само включает native READY. Реальный браузер и Android View
подтвердили dragDOWN1/MOVE3/UP1/CANCEL0 и wheelDOWN1/MOVE1/UP1/CANCEL0.
Первый Home подтверждён824ms, launcher виден, но управление потребовало
восстановления. Второй Home773ms вернулся в READY автоматически. Первый случай
не считается безошибочной приёмкой. Source follow-up закрывает воспроизведённую
гонку старой periodic authorization и добавляет точный failure reason readback;
новая установка и проверка перехода ещё обязательны. Frontend CI1837/137,
types/build/packaged pages/image прошли;45 других контейнеров и OTA сохранены.
[Наблюдение, доказательства и следующие проверки](../audits/2026-10-08/CONTINUOUS-INPUT-HANDOFF-OBSERVATION.md).

**8 октября, 05:26–05:40 UTC+5 — непрерывные жесты PH011 установлены и проверены.**
Reviewed API/UI `28104f8` на3015; pilotAPK **1.2.49-dev/10249**, source `d8023bc`,
адресно установлен толькоPH011. Прямой live WebSocket и независимый Android View
подтвердили пять MOVE приUP0; браузерный drag дал дельтуDOWN1/MOVE5/UP1/CANCEL0.
Пользователь подтвердил работу. «Домой» подтверждено после known native release.
Полный CI: backend3319passed/37skipped/229subtests; frontend1825/137suites;
APK979passed/3skipped в каждом Dev/Enterprise. PH02510248, остальные APK сохранены;
normalOTA не продвигался. SF26-05OPEN, ledger9accepted/41open.
[Установленная приёмка и ограничения](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-ACCEPTANCE.md).

**Установленный UX source `bc86752`:** отдельный переключатель убран, обычное «Управление»
автоматически включает native gestures; Home/keyboard ждут RELEASE3, колесо
использует тот же owner. Переход Home имеет follow-up выше.
[Поведение и регрессии](../audits/2026-10-08/CONTINUOUS-INPUT-AUTOMATIC-UX.md).

### Историческая установленная приёмка до continuous canary

**8 октября, около04:10 UTC+5 — PH025: исправление static reconnect установлено и проверено.**
На3015 reviewed UI `fcdc547`; API `a41c4e6` сохранён. APK **1.2.48-dev /10248**,
source `c62ded6`, адресно установлен через recovery grants на **PH011 и PH025**:
terminal completion, новый heartbeat, version readback, grants auto-cleared.
Повторные входы дали локально6/12drawn, удалённо6/4drawn; второй одновременный
viewer PH025 получил3IDR. Во всех пяти случаях decode/render errors0/0.
При втором viewer physical captured88→88, encoded114→117: owned RAW refresh
решает отсутствие IDR без движения экрана. «Недавние» и «Домой» проверены
визуально; receipts600/480ms не являются input→picture latency.
Candidate full tests979passed/3skipped в каждой Dev/Enterprise; все пять
exact-source hosted CI source `c62ded6` successful. PH010 и остальной парк
не обновлялись, normal OTA channel не продвигался. Continuous input на3015
**выключен**, ledger9accepted/41open сохранён. Это конечная приёмка двух pilots,
не fleet soak, не доказательство20–30FPS или frame-exact жестов.
[Установка, доказательства и ограничения](../audits/2026-10-08/PH025-STATIC-RECONNECT-ACCEPTANCE.md) ·
[Acceptance JSON](../audits/2026-10-08/PH025-STATIC-RECONNECT-ACCEPTANCE.json).

### Исторические checkpoints до установленной приёмки

**8 октября, после03:40 UTC+5 — PH025: второй путь чёрного экрана доказан.**
Reviewed UI `fcdc547` установлен на3015;45 остальных контейнеров и OTA-каталог
сохранены. Первый вход11drawn, Android Recent32/Home49,0decode errors.
Но повторный вход на статичном экране дал8packets/244B,SPS/PPS4/4 и0pictures:
first-frame timeout снова воспроизведён. Реальный MediaCodec из рабочегоAPK10247
после одного RAW принял два sync requests, но дал0/0 новых pictures. Sourcefix
подаёт owned RAW на sync request с одним pending/4refresh/s и fences старых/
неопределённых callbacks; cached SPS/PPS идут раньше IDR. APK10248 ещё не
установлен; temporary scoped capture restart восстановил картинку, но вопрос
не закрыт. Default полные tests до ordering followup:978passed/3skipped в
каждой из двух variants. Continuous input на3015 всё ещё не включён.
[Причина и обязательная приёмка](../audits/2026-10-08/PH025-STATIC-RECONNECT.md).

**8 октября, после 02:54 UTC+5 — PH025: первая причина чёрного экрана воспроизведена.**
В настоящем браузере принудительный `prefer-hardware` отвергает AVC:
`OperationError`, 0 outputs/drawn. Те же 16 packets при `no-preference`
и software control дали 11 outputs/drawn без ошибок. Source теперь разрешает
браузеру выбрать поддерживаемый decoder; диагностика показывает bounded
причину отказа. Три red→green регрессии, leaf 42, полный frontend **1820 tests /
137 suites**, fresh route typegen и полный TypeScript прошли. Установка на
3015 и live приёмка ещё впереди; UI af9054e / API a41c4e6 / APK сохранены.
Static capture без VCL и continuous input остаются независимыми открытыми
условиями. [Причина, изменение и границы](../audits/2026-10-08/PH025-DECODER-RECOVERY.md) ·
[Evidence](../audits/2026-10-08/PH025-DECODER-RECOVERY-EVIDENCE.json).

**8 октября, после02:30 UTC+5 — scoped native receipt source:** добавлена
адресная transient пересылка подтверждений между APK и viewer workers.
Lua атомарно меняет readiness/known release и публикует exact scoped identity;
foreign/старые sockets и неизвестный исход не создают takeover/replay.
Raw receipt JSON сохраняет uptime9007199254740991 без округления Lua cjson.
34 новых cases, полный leaf130 cases прошёл в fake Lua и реальном Redis с
isolated audit keys; Ruff/mypy прошли. Socket metadata в этих тестах mock:
startup/subscriber/routes, настоящий auth/topology lifecycle и installed
browser→Android всё ещё открыты. UI/API/working APK не обновлялись; SF26-05 OPEN.
[Контракт и обязательная интеграция](../protocols/CONTINUOUS-INPUT-RECEIPTS.md) ·
[Evidence](../audits/2026-10-08/CONTINUOUS-INPUT-RECEIPTS-EVIDENCE.json).

**Browser sourcea979bc9 — все четыре exact hosted CI accepted:** Android,
frontend, backend и preview. Frontend1817passed/137suites плюс fresh types/build,
backend3268passed/37skipped/229subtests. Receipt source выше является следующим
изменением и требует нового exact-source CI; эти runs его не включают.

**8 октября, после02:03 UTC+5 — непрерывные жесты: browser source и реальная
Kotlin-проверка.** Доступность ADB восстановилась; на одном idle PH010 через
debug classpath проверены10 настоящих случаев Controller/Ownership/Pipe →
native → независимый View. Пять MOVE туда-сюда340→180→400→220→340 пришли
до UP; explicit CANCEL3 и следующий gesture, heartbeat hold1816ms,
EOF/generation/capture loss, duplicate/foreign owner и bounded burst прошли.
Receiver/classpath удалены, launcher и версия рабочего APK10247 сохранены.
Fake capture/generation этого driver не проверяют MediaProjection, реальный
WS dispatcher, сервер или новый JS-клиент. Browser controller/DOM adapter
проверены64 новыми cases; полный frontend **1817tests/137suites**, fresh route
typegen и полный non-incremental TypeScript прошли. Одна MOVE-точка и32 scalar
receipt records; loss/backpressure/unknown result не создают replay. Модуль ещё
не подключён к DeviceStream/routes. На3015 continuous режим **не включён**;
manual/DAG server exclusion, scoped transient receipts, actual frame/probe,
Recorder и local/remote end-to-end/soak остаются OPEN. Ledger9/41 сохранён.
[Полная граница приёмки](../audits/2026-10-08/CONTINUOUS-INPUT-POINTER.md) ·
[Evidence](../audits/2026-10-08/CONTINUOUS-INPUT-POINTER-EVIDENCE.json).

**Серверный source0a8cd9 принят всеми четырьмя exact-source CI:** Android,
frontend, backend и preview. Backend3268passed/37skipped/229subtests;
frontend1753tests/136suites плюс types/build. Эти runs не включают последующий
browser controller source; CI следующего commit проверяется отдельно.

**8 октября, после01:20 UTC+5 — continuous input server source:** отдельные
strict contracts, один Redis owner device между workers и scoped socket send
проверены96 новыми cases:44 protocol/52 lease-delivery. Те же96 прошли в
fakeredis Lua и настоящем Redis с isolated audit keys, без Android commands,
изменения application image/files или live routes. Общий retrying Redis pool
проверенно запрещён; dedicated pool8/250ms/Retry0, lease/auth1500ms,
delivery age500ms и envelope2048B. DOWN/MOVE/UP публикуются отдельно;
native STARTUP0 отличён от socket completion, known RELEASE3 — от uncertainty.
Замена socket, cancellation/timeout и late receipts не дают replay/takeover.
Ruff/mypy прошли; exact hosted CI source0a8cd9 принят, см. followup выше.
Routes/subscriptions/receipt delivery, actual permission cadence и server DAG
exclusion, browser pointermove/recorder и real APK acceptance ещё открыты.
На3015 установленный continuous режим **не включён**, ledger9/41 сохранён.
[Контракт и открытые условия](../protocols/CONTINUOUS-INPUT-SERVER.md) ·
[Evidence](../audits/2026-10-08/CONTINUOUS-INPUT-SERVER-EVIDENCE.json).

**Capture frame source3dc2456 — CI принят полностью:** Android push/PR,
frontend, backend и preview, пять exact-source successful runs. Backend:
3172passed/37skipped/229subtests плюс image/bootstrap/RLS/migrations checks;
frontend1753tests/136suites и fresh types/build. Дополнительно devDebug APK
с CANARY=true собран успешно; default snapshot сохранён побайтово до сборки.
Ни один новый APK не установлен, UI/API не обновлены. Mutable Gradle output
теперь flagged debug; exact hashes обоих preserved private snapshots указаны
в [отдельной CI/artifact приёмке](../audits/2026-10-08/VIDEO-CAPTURE-V2-CI.json).

**8 октября, после 00:11 UTC+5 — capture identity в видеопакете:** debug canary
получил фиксированный v2 header с UUID захвата. Сервер классифицирует H.264
после header, сохраняя исходные bytes; браузер связывает epoch с успешным
выводом текущего кодека. Same-size restart, поздний output и ошибочная
отрисовка не подтверждают текущую картинку. Default/release APK сохраняет v1.
Полные локальные проверки: frontend **1753 tests /136 suites**, fresh Next route
types и TypeScript; Android **966 passed /3 skipped,82 suites в каждой** из двух
debug variants, devDebug APK собран. Backend classifier/queue: **49 passed**,
Ruff/mypy; это leaf unit run, полный backend выполняется в hosted CI.
Ни новый APK, ни UI/API не установлены; на3015 input пока discrete. Multiworker
owner/scoped receipts и browser pointermove ещё обязательны, SF26-05 OPEN.
[Wire format и ограничения](../protocols/VIDEO-CAPTURE-V2.md) ·
[Точные результаты](../audits/2026-10-07/VIDEO-CAPTURE-V2-EVIDENCE.json).

**7 октября, 23:34 UTC+5 — storage observation gap:** прежние четыре
collector processes отсутствуют, последние complete samples около14:03UTC.
Старые status files ошибочно выглядят `running`; причина остановки неизвестна.
Восстановлен limited host/file observer PID29648 до8 октября07:13:38UTC+5,
пять Docker/LDPlayer files, RAM/process/WSL metadata,16MiB общий предел.
В текущем терминале нет administrator: новая VSS/USN/ETW attribution не
восстановлена. Сохранённые три ETL и старые reports оставлены для анализа.
Storage/RAM проблема не объявляется устранённой.
[Проверенный разрыв и восстановленное покрытие](../audits/2026-10-07/STORAGE-COLLECTOR-INTERRUPTION.md).

**7 октября, после 23:15 UTC+5 — continuous input APK source:** capture epoch,
синхронный admission, WS generation и общий arbiter с DAG/discrete mutations
подключены к dispatcher только при явном debug canary flag. FIFO handoff ждёт
execution marker старой root-очереди; неизвестное завершение запрещает нового
владельца. Обе Android debug variants: **958 passed / 3 skipped, 81 suites
в каждой**; сборка devDebug успешна, release с canary flag проверенно запрещён.
Новый APK не установлен; UI af9054e / API a41c4e6 сохранены. Реальная приёмка
Kotlin pipeline открыта: сейчас оба ADB inventories пусты. Server lease/scoped
receipts, epoch показанного кадра и browser pointermove ещё не подключены.
На 3015 жест пока отправляется после отпускания. Ledger **9/41** сохраняется.
[Контракт, тесты и оставшиеся условия](../audits/2026-10-07/CONTINUOUS-INPUT-APK-LIFECYCLE.md) ·
[Evidence](../audits/2026-10-07/CONTINUOUS-INPUT-APK-EVIDENCE.json).

APK lifecycle source c88c51b прошёл оба Android CI; frontend/backend runs были
superseded следующим docs commit. Exact docs head **0b96a3794e58bacc6a6c1dc072bbcdea938baffd**
с тем же Android/frontend/backend source затем прошёл Android, frontend,
backend и preview CI. Это предыдущий source, не CI нового v2 frame change.

**7 октября, continuous supervisor source:** добавлен один owner/worker,
bounded очередь 4 samples с coalescing MOVE и reserved terminal slot, строгий
private root pipe и отдельные STARTUP/INPUT/RELEASE receipts. Unknown cleanup
блокирует последующее подключение; активный owner нельзя заменить duplicate
open. Это ещё не подключено к CommandDispatcher/server/browser, installed
runtime сохраняется. Локально обе debug variants: **925 passed / 3 skipped,
77 suites в каждой**, включая 33 новых случая mailbox/supervisor/pipe.
Native source 1dccd05 и supervisor source 3cb9fe9 прошли оба Android CI и
frontend/backend CI. Последующее подключение APK описано выше; этот абзац
сохраняет границу предыдущего этапа.
[Контракт и оставшиеся условия](../audits/2026-10-07/CONTINUOUS-TOUCH-SUPERVISOR.md).

**7 октября, после18:47 UTC+5 — native continuous touch canary:** отдельный
Android helper через встроенный MotionEvent/InputManager принял пять MOVE до UP
в самом View. Проверены EOF, lease expiry, duplicate sequence, длительный
heartbeat hold, частичный пакет, bad magic и смена display geometry. Выявлена
и исправлена несовместимость бинарного stdio с LF→CRLF в root-канале; используется
bounded hex framing. Диагностический receiver/JAR удалены, display/launcher
восстановлены; рабочий APK1.2.47-dev/10247 на этом экземпляре не заменялся.
**Непрерывный режим в вебе ещё не включён:** UI af9054e/API a41c4e6 сохраняются,
browser→server→APK owner/queue/capability/recording остаются OPEN. Ledger9/41
не меняется. [Реальная native приёмка и ограничения](../audits/2026-10-07/CONTINUOUS-TOUCH-NATIVE-CANARY.md).

**7 октября, после18:14 UTC+5 — Studio navigation установлен на3015:** UI
**af9054e**, API **a41c4e6** сохранён. Собственный диалог перечисляет несохранённую
работу и защищает sidebar, общий поиск и explicit logout до начала их side effects.
Ожидающие/неизвестные команды лаборатории проверяются повторно перед выходом;
устаревшее подтверждение при смене владельца/сессии отменяется. Локально1733 tests /
135 suites и source types прошли; exact frontend CI37624946579 успешен, fresh
types/build/26pages/73assets. В установленном браузере приняты отмена, поиск,
mobile Escape и явный переход; desktop/mobile/short-height layout проверены.
Получение файла экспортом в IAB не подтверждено, browser Back/Forward SPA остаётся
вне полного route blocker. Другие45 containers, OTA/API/APK/SQL сохранены.
[Контракт и реальные screenshots](../audits/2026-10-07/STUDIO-NAVIGATION-PRESERVATION.md) ·
[Exact acceptance](../audits/2026-10-07/STUDIO-NAVIGATION-INSTALLED-ACCEPTANCE.json).

NTFS observer исправлен после stopped-error на всплеске4096 identities:
replacement реально работает с13:03:12 до19:53:12UTC,14 pure regressions/Ruff/mypy
прошли. Новые поля coverage показывают evictions/backlog; старый observation gap
не реконструирован. Host/VSS, ETW supervisor и VMDK observers продолжали работать;
две автоматические traces сохранены, writer analysis остаётся OPEN. Это конечные
окна без autostart. [Инструкция и текущие private reports](HOST-RESOURCES.md).
Общий audit ledger **9 accepted / 41 open** сохраняется; continuous gestures,
rich recording и correlated debugger остаются следующими работами Studio.

**7 октября, после16:40 UTC+5 — storage attribution и реальный сбор:**
в отдельном30s elevated окне C:−235 745 280B / VSS allocation+234 881 024B
(99,63%). Это механизм конкретного эпизода, не writer всего8h или всей истории.
Проверен drift ранее одобренного VSS max8GiB→19,06GiB; повторное применение
8GiB освободило16,304GiB на C: и удалило две inspected restore copies. Отдельные
~20GiB до этого освободил сам оператор удалением постороннего файла.
39 owned Docker images удалены с all46 epoch guards/rollback preservation,
guest reclaimed11,890GiB; host VHD length/allocation234 731 077 632B сохраняются.
Quota-changing actor неизвестен, offline compaction не выполнялась.

Вместо limited сейчас actual elevated host observer16:27→00:27 следующего дня,
VSS measured, RAM/commit/pools/процессы/Docker/WSL; отдельно bounded event-triggered
kernel supervisor, whole-C: NTFS journal reader и six-VMDK LDPlayer observation.
Пока running, RAM soak не принят.109 targeted tests /34 subtests, Ruff/mypy;
runtimeUI/APIa41c4e6 не заменены,
Android/SQL/сценарии не менялись. Ledger9/41 и host incident OPEN сохраняются.
[Текущий отчёт, screenshots и evidence](../audits/2026-10-07/HOST-STORAGE-VSS-CURRENT.md) ·
[Инструкция и private report locations](HOST-RESOURCES.md).

**7 октября, 16:02 UTC+5 — повторная потеря места подтверждена конечным окном:**
97/97 samples за 8h, C: free -9 144 741 888 B; Docker VHDX logical/allocated
234 731 077 632 B постоянны во всех срезах. Pagefile logical постоянен, allocation
и identity недостаточны для delta. Writer и storage/RAM leak остаются OPEN.
Диагностический source ecc8221 добавляет bounded read-only report и явный limited
host observer: RAM/commit/pools/process epochs/Docker/WSL без повышения прав,
VSS при отказе UNKNOWN. 67 targeted tests / 16 subtests, Ruff/mypy passed;
отдельный hosted CI ecc8221 ещё не выдаётся за завершённый.
Тогдашний limited collector15:56→23:56 superseded после18 samples;
текущее elevated наблюдение описано выше, finite RAM soak ещё не принят. Runtime UI/API a41c4e6,
SQL/APK и другие services не заменялись. У legacy PG/Redis/MinIO/n8n отмечен
logging drift: compose limits есть, работающие контейнеры старой конфигурации.
[Конечные measurements, inventory и ограничения](../audits/2026-10-07/HOST-STORAGE-FOLLOWUP.md) ·
[Evidence](../audits/2026-10-07/HOST-STORAGE-FOLLOWUP-EVIDENCE.json) ·
[Operator commands](HOST-RESOURCES.md). Общий ledger 9/41 сохраняется.

**7 октября, 07:59 +05 — UI/API a41c4e6 установлены на3015:** strict discrete
input admission отклоняет missing coordinates/coercion/malformed JSON без
остановки видео. Real PH010 canary получил пять отказов, затем video binary
messages и ping на том же WS; корректного Android input не отправлял.
Все14 online agents переподключились,25 сценариев и другие45containers сохранены;
SQL/OTA/APK не менялись. Browser подтвердил matched revisions, разрыв/Undo и
server parameter verification. Exact source CI: **3097 passed /37 skipped /
193 subtests**, coverage**80.43%**; frontend**1695/133**, types/build/26pages/73assets;
Android success. [Доставка, границы и screenshot](../audits/2026-10-07/VIEWER-INPUT-DELIVERY.md) ·
[Exact acceptance](../audits/2026-10-07/VIEWER-INPUT-INSTALLED-ACCEPTANCE.json).
Notice React-tested; отдельный browser malformed-input notice canary открыт.
8h bounded disk observer начат03:02Z; причина storage/RAM growth ещё не установлена.
Continuous injector/rich recorder/ledger9/41 не закрываются этой регрессией.

**7 октября, 03:35 +05 — обновлён API 114775a на 3015:** установлен тот же
production image, который прошёл полный hosted CI. Live contract 1.0 содержит
32 действия; корректный draft принят, tap без координат отклонён 422, без auth 401.
В настоящем Script Studio UI b50d6ae виден server parameter verification.
Все 25 сценариев сохранены; task detail отвечает; 14/19 устройств вернулись
в online с новыми heartbeat/connected_since. Другие 45 контейнеров, SQL head,
OTA и APK сохранены; миграций и новых запусков сценариев не было.
Backend exact-source CI **3050 passed / 37 skipped / 112 subtests**, coverage
**80.41%**, все 6 jobs success; frontend и Android того же source — success.
**51 local delivery tests** проверяют archive/installer/rollback boundaries.
[Доставка и подробная приёмка](../audits/2026-10-07/REVIEWED-BACKEND-DELIVERY.md) ·
[Image/runtime/browser evidence](../audits/2026-10-07/BACKEND-CONTRACT-INSTALLED-ACCEPTANCE.json).
Это pilot с реальной авторизацией, не VPS production-role/fleet soak admission.

**7 октября — установленный UI b50d6ae на 3015:** обзор графа теперь
следует за размером холста, а ручной pan/zoom сохраняется. Без дополнительного
«Весь граф» проверены переходы 1920→1280 и 390 px, оба направления ELK,
JSON roundtrip и реальные structural validate ответы старого API.
Заголовок читаем; новые шаги не скрывают End.
[Exact installed/browser/CI evidence](../audits/2026-10-07/STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json) ·
[Resize и границы](../audits/2026-10-07/STUDIO-CANVAS-RESIZE.md) ·
[Header](../audits/2026-10-07/STUDIO-RESPONSIVE-HEADER.md) ·
[Node placement](../audits/2026-10-07/STUDIO-NODE-OCCLUSION.md).

Все три CI exact source b50d6ae успешны: frontend **1692 tests / 133 suites**,
fresh types/build, 26 pages / 73 assets image admission; 22 archive/installer
methods и 18 HTTP cases. Backend **3037 passed / 37 skipped**, 55 subtests,
coverage 80.36%; Android workflow success. Runs: frontend 37535540138,
backend 37535540188, Android 37535540323, attempt 1.
Это результаты установленного UI SHA; последующие delivery-tools/docs HEAD
проверяется отдельно. Старый backend 439f910 attempt 1 имел один 20 s
PowerShell fixture timeout; attempt 2 отменён новым push. Причина старого
timeout не установлена, ограничения теста не ослаблялись.

Windows completed repair, Healthy/OK и Git fsck подтверждены. Предыдущая
установка UI сохраняла API **eb7a7c26**; последующий API rollout **114775a**
описан выше. APK не обновлялся.
[Postboot handoff](../audits/2026-10-07/POSTBOOT-RECOVERY.md).
API validate теперь подтверждает структуру/Lua safety и action-parameter contract;
выполнение Android и capabilities конкретного APK проверяются отдельно.
Причины расхода диска/RAM и повреждений файлов не установлены. Ledger
**9 accepted / 41 open** сохраняется; continuous input, rich recorder и fleet
acceptance не закрываются приёмкой графа.

**Доставка backend завершена в пределах описанного canary:** bounded archive,
source/run/attempt, independent CI config ID и full workflow success проверены;
установщик сохраняет конфигурацию и SQL и допускает только backend image delta.
Continuous DOWN/MOVE/UP остаётся следующим P1: нужен APK injector и lifecycle
touch sequence, а не только pointermove в браузере.
[Контракт доставки и оставшиеся gates](../audits/2026-10-07/REVIEWED-BACKEND-DELIVERY.md).

Ниже — исторические срезы до postboot handoff; версии/runtime gates относятся
к указанному моменту, не отменяют актуальное состояние выше.

**7 октября — полный CI sourcece6e377 success:** backend3015passed/37skipped,
frontend1686/133 с26pages/73assets, Android variants и signed smoke прошли.
[Exact baseline](../audits/2026-10-07/STUDIO-CI-BASELINE.json). Это source admission,
не установка на3015 и не результат следующего изменения упаковки.

**7 октября — source delivery без локального rebuild:** frontend CI упаковывает
проверенный standalone output в unprivileged Linux/amd64 image, проверяет actual
image pages/assets и сохраняет bounded Docker-save archive с SHA/run/attempt
receipt на3дня. Read-only admission проверяет archive/config/source/CI binding.
**18local archive/installer methods**, Ruff/Node/YAML checks passed.
Hosted image source99af20d принят: **26pages/73assets**,115MiB gzip,
artifact11438406747, image/config/source admission success.
[Exact image receipt](../audits/2026-10-07/REVIEWED-WEB-IMAGE-EVIDENCE.json) ·
[Доставка и host gate](../audits/2026-10-07/REVIEWED-WEB-DELIVERY.md).
Исторический read-only preflight до reboot не выполнял apply. После completed
repair UI-only99af20d install подтверждён отдельным linked postboot receipt.

**6 октября,18:54 UTC — frontend sourcee7f3ffb полностью проверен:**1686/133,
18 HTTP contract tests, fresh types/build и **standalone26pages/73assets passed**.
Root200 содержит проверенный Next Flight redirect на/dashboard; warning missing
root manifest отсутствует. [Exact receipt](../audits/2026-10-06/FRONTEND-STANDALONE-EVIDENCE.json).
Это hosted artifact admission, не browser hydration/visual/runtime acceptance.
Fresh backend/Android workflow этого head ещё выполнялся на момент receipt;
последний полный backend/Android source517d73b приведён ниже. После docs-only
коммита результаты остаются привязаны к проверенному SHA, не к новому HEAD.
Installed UI/API/APK сохранены; host repair gate и **9 accepted/41open** не изменены.

**6 октября — полный hosted CI Studio source517d73b принят:** backend
**3015 passed /37 skipped**, coverage80.35%; lint/mypy/security/bootstrap/RLS/
Alembic success. Frontend **1686 tests /133 suites**, types/build/standalone
entry check success; Android all-variant tests/signed smoke build success.
Preview guard success, **deploy skipped**. [Dated receipt](../audits/2026-10-06/STUDIO-SOURCE-CI-20261006.json).
Пять первоначальных backend failures устранены исправлением publication fixtures;
новая PostgreSQL historical read/rejected update/rollback регрессия прошла.
Это не installed/runtime acceptance и не CI следующего head.

**Следующий source5000bc9 — admission упакованного frontend:** удалён второй
root redirect, добавлен standalone HTTP probe страниц и их client assets.
**10 local HTTP tests passed**, source-only types passed; стандартные local types
ссылаются на старый generated validator удалённой page и не приняты.
Fresh head44af412 прошёл1686/133, types/build; первый HTTP probe потребовал
только307/308 и отказал на штатном Next root200. Ожидание исправлено: exact
meta/RSC redirect to/dashboard,18 local cases passed. Subsequent e7f3ffb hosted
probe accepted отдельно, см. верхний receipt.
[Основание, failed run и границы](../audits/2026-10-06/FRONTEND-STANDALONE-ADMISSION.md).
[Continuous input audit](../audits/2026-10-06/CONTINUOUS-INPUT-INTEGRATION.md):
scrcpy5.0 исследован на pinned commit, direct binary protocol/version/reset
constraints описаны; upstream не встроен, DOWN/MOVE/UP пока не включены.
Последний host read: **Warning /Full Repair Needed**, свободно41 028 304 896B.
UI1c26ffc7/APIeb7a7c26/APK сохранены; новый local Next/Android/Docker build и deploy
не выполнялись. Общая приёмка **9 accepted /41 open** остаётся прежней.

**6 октября, 23:16 UTC+5 — свободная сборка Studio в исходниках:** отдельный узел
по умолчанию, palette drag/drop с pan/zoom, явная вставка в цепочку,
редактируемые разорванные ветки, сохранение расположения при правке параметров.
Удаление шага, выбор entry, защита входа и Undo/Redo в режиме графа;
незавершённый документ блокируется перед check/save. **395 tests /17 suites**
и TypeScript passed. [Контракт и визуальная приёмка](../audits/2026-10-06/STUDIO-FREE-CANVAS.md).
Baseline **a9d8b85**: frontend/Android CI success, backend lint/mypy/security/bootstrap/RLS
success; полный backend test job завершился5 failures /3006 passed /37 skipped:
catalog publication fixtures содержали sleep без ms. Исправление fixture и
historical-read/rollback регрессия доставлены в6a61c03; guard не ослаблен.
Это не положительный CI free-canvas head.
**Не установлено:** UI1c26ffc7/APIeb7a7c26/APK сохранены; C: repair gate закрыт.
Общий реестр9/41 не меняется; нового source browser acceptance нет. Повторно
просмотрен installed baseline1280×720; source palette сделана компактнее по его
результату. Снимок и точный scope находятся в linked free-canvas документе.

**6 октября, 22:52 UTC+5 — следующий source P1 Script Studio:** общий контракт
параметров **1.0 / 32 опубликованных действия**, error paths без input values,
check/create/update guard до записи версии, требования и optional fields в форме.
141 Python/ASGI/schema tests прошли также с shipped FastAPI/Pydantic/SQLAlchemy;
374 frontend tests /16 suites, TypeScript, scoped Ruff и mirror check прошли.
Предыдущий head **de969f9** завершил backend/frontend/Android CI success,
Preview success с deploy skipped; это не CI нового source кандидата.
Локальный full backend mypy не принят: global Python содержит повреждённый
SQLAlchemy source, отдельная pinned среда сообщает отсутствие Requests stubs.
Сам pure validator прошёл isolated mypy; полный CI остаётся обязательным.
**Не установлено:** UI1c26ffc7/APIeb7a7c26/APK сохранены; C: Warning/Full Repair
Needed. Общая приёмка9/41 не меняется. Следующие gates — APK capabilities,
continuous pointer и correlated recording/replay. [Результат и границы](../audits/2026-10-06/STUDIO-ACTION-PARAMETERS.md).

**6 октября, 22:13 UTC+5 — Studio interaction source fixes:** явный editor
связи, перенос её конца, delete-only transition и шесть Android key presets.
Selector из XPath inspector теперь проходит ту же ordered review queue, что
click/key/text, с меткой **В план · не выполнялся**: не выдаётся за APK ACK и
не переставляет граф до переноса записи. **234 tests / 11 suites passed**,
strengthened selector bounds10/10 и TypeScript passed. Home на installed PH010
записан с реальным439ms ACK и экспортирован в key_event3; это не frame latency.
Новые source fixes **не установлены**: C: repair gate закрыт. UI1c26ffc7/APIeb7a7c26,
APK/OTA/туннели сохранены, общий9/41 не изменён. Continuous DOWN/MOVE/UP,
rich XPath/native crop/pixel recorder, correlated replay, subgraphs, group input
и AI workspace разложены по требованиям, зависимости и приёмке.
[Follow-up и приоритеты](../audits/2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md) ·
[Связи](../audits/2026-10-06/STUDIO-CONNECTION-EDITING.md).

**6 октября, 21:58 UTC+5 — проверен конкретный PNG пользователя с PH011:** файл
`sphere-414ce0e9-…-dc4f98b956364287bb5157d9bee5450f.png` — 960×540, 236 486B,
RGBA8; pHYs/eXIf нет, DPI не записан. Native server trace подтвердил10/10 RPC
и cleanup. Независимые native PNG/RAW совпали по всем518 400pixels;
весь участок пользовательского PNG ниже status bar (495 360pixels) совпал
побайтово с Android. Для этого файла деградация pixels не подтверждена.
Source candidate отделяет video frame export от original PNG и добавляет
native1:1 preview без изменения downloads. **49/3 scoped tests и TypeScript
passed**; установка/визуальная приёмка этих кнопок ещё не выполнены из-за C:
`Warning / Full Repair Needed`. UI/API/APK сохранены. Остальные PNG/устройства,
rich recorder, task artifact delivery и долгосрочный storage writer не закрыты.
[Проверка и границы](../audits/2026-10-06/NATIVE-PNG-PIXEL-VERIFICATION.md) ·
[Pixel evidence](../audits/2026-10-06/NATIVE-PNG-PIXEL-EVIDENCE.json).

**Критическое ограничение хоста — 6 октября, 20:23 UTC+5:** Git objects
восстановлены, fsck exit0; **C: NTFS всё ещё `Warning / Full Repair Needed`**.
Elevated Scan подтвердил offline defects в двух директориях. Verified local
recovery copy11files/16 450 263B включает source/config/PostgreSQL, но лежит на
том же SSD и не является backup личных файлов/всех volumes. Запрос **`chkdsk C: /f`
при следующей загрузке** подтверждён BootExecute; перезагрузка и repair ещё не
выполнены. Нездоровый/неизвестный volume теперь блокируется resource guard.
37 scoped CLI tests passed; тяжёлые builds и runtime deployment не выполнялись.
RAM около11,4GiB Windows Scan host освободилась после завершения проверки;
это не закрывает долгосрочную утечку. VSS max current19,1ГБ расходится с прежним
verified8GiB, причина неизвестна. **Разработку с heavy builds на C: не возобновлять
до postboot acceptance.** Старые APK/UI/API версии ниже остаются установленными.
[Incident, queue и acceptance](../audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

[Главная](../../README.md) · [Каталог документации](../README.md) · [Readiness](READINESS.md) · [Fleet32 gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

**6 октября, 19:48 UTC+5 — APK 1.2.47 установлен только на локальный PH011:**
Source **3493eb6 / 10247** устранил blind screenshot wait и неограниченное
накопление новых PNG в `/sdcard`: подтверждённый FIFO root ACK, проверка PNG и
private cache **8 файлов / до 5 MiB каждый / 30 min при следующем capture**.
Оригинальные пиксели не перекодируются. Одно обновление **1.2.46 → 1.2.47**
сохранило UID, preferences и identity; только PH011. Один saved-version task
**b1d67f65-f7b9-4859-906a-77513017acfc** завершился **14/14**, сделал 10 снимков;
остались последние **8 / 1 880 304 B**, первые два удалены. Последний original
**960×540 PNG** совпал с Android по SHA256; native browser проверил реальные reports.
Локальные полные Dev/Enterprise suites: по **869 passed / 3 skipped** из 872;
Ubuntu CI JUnit четырёх вариантов: по **871 passed / 1 skipped**, обе filesystem
symlink ветки исполнены. Все четыре source workflow **3493eb6** success,
Preview deploy skipped. Общий счёт **9 / 41** сохраняется.
**Task artifact delivery остаётся открытой**: server manifest пуст; output честно
указывает local cache и `server_artifact_available=false`. PNG evidence получен
адресно через ADB, это не server upload. Remote APK/OTA, UI **1c26ffc7**, API
**eb7a7c26** и туннели этим этапом не обновлялись. Далее — EP-016 action schemas /
capability preflight и отдельный task artifact transport/lifecycle.
[Контракт и установленная проверка](../audits/2026-10-06/ANDROID-SCREENSHOT-CACHE.md) ·
[Pinned evidence](../audits/2026-10-06/ANDROID-SCREENSHOT-CACHE-EVIDENCE.json).

**Повторный host incident 6 октября, 19:28 UTC+5:** пять loose Git объектов
оказались повреждены, включая blobs текущего frontend и двух JPEG evidence.
Сохранены raw backups, восстановлены только эти пять объектов из GitHub с проверкой
исходного SHA-1; последующий Git fsck и pinned evidence validator прошли.
Новое Ntfs55 **11:15:49 UTC / record 220639** относится к индексу вне проекта,
в WindowsApps/Deleted. Это повторяемое повреждение данных с **неустановленной
причиной**; source regeneration не является ремонтом C:, а успешные тесты не
доказывают исправность SSD/RAM. Disk-growth writer также остаётся UNKNOWN.
[Доказательства и границы восстановления](../audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

**Историческая установка 6 октября, 18:48 UTC+5 — APK 1.2.46 только на локальном PH011:**
Адресное обновление 1.2.44 → 1.2.46 / 10246 сохранило UID, четыре preference файла
до старта и device ID. Backup private; остальные 18 версий, API/UI, OTA и туннели
сохранены. Один сохранённый DAG v1, одно задание, **25/25 success**: standalone
`input_clear`, пустой повтор и `type_text.clear_first:true` проверены отдельными
XPath asserts; итоговый текст точно `replacement-native`. Native browser подтвердил
результат. Remote rollout и другие SDK/editors остаются открытыми.
Выявлен следующий дефект: screenshot создал local PNG в `/sdcard`, но manifest
задания пуст; автоматической доставки нет. Файл вручную сохранён без перекодирования
и удалён адресно. Код имеет неограниченное накопление PNG и 300 ms blind wait;
это не доказанная причина роста Windows C: или Docker VHD. Следующий срез — capture
ACK/PNG validity и bounded local retention. Общий счёт **9 / 41** сохраняется.
[Установка и новый дефект](../audits/2026-10-06/ANDROID-CLEAR-INSTALLED.md) ·
[Pinned evidence](../audits/2026-10-06/ANDROID-CLEAR-INSTALLED-EVIDENCE.json).

**Исторический срез сборки 6 октября, 17:43 UTC+5 — исправление APK очистки текста собрано, не установлено:**
Source **`6a9f570f`**, candidate **1.2.46-dev / 10246**. Вместо ошибочного CUT 277
используется root Ctrl+A/Delete с отпусканием клавиш и отдельным ограниченным ACK
в прежней FIFO root-сессии. Unknown outcome не повторяет очистку и не вводит замену;
`field_verified=false` отделяет dispatch ACK от результата произвольного editor.
По **855 passed / 1 assumption-skipped** в Dev/Enterprise (одинаковые cases),
45 focused входят в эти наборы. Подпись pilot совпала с baseline; ZIP/DEX checks прошли.
Все четыре source CI `6a9f570f` success; Android signed release smoke использовал
одноразовый CI key, Preview deploy skipped. Это не CI последующего docs head.
Реальный локальный SDK28 helper из временного candidate APK полностью очистил
тестовую строку с курсором внутри, выдержал пустой повтор и обычный follow-up input.
Сохранены два original PNG и receipts. Установленный локальный Agent **1.2.44-dev**
не заменён; remote PH025 **1.2.45-dev** также остаётся старым. Полный canary нового
AdbActionExecutor через установленный APK, другие SDK/editors и rollout ещё нужны.
UI **`1c26ffc7`** / API **`eb7a7c26`**, OTA/туннели этим этапом не обновлялись.
Первый Enterprise run остановился на одном повреждённом generated `.class`;
пересоздан только этот 1753-byte output и повторён полный suite. Причина неизвестна,
это не ремонт NTFS или установление disk-growth writer. Счёт **9 / 41** сохраняется.
[Результат и границы](../audits/2026-10-06/ANDROID-FOCUSED-TEXT-CLEAR.md) ·
[Pinned evidence](../audits/2026-10-06/ANDROID-FOCUSED-TEXT-CLEAR-EVIDENCE.json) ·
[Host incident](../audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

**6 октября, 12:15 UTC+5 — отдельный инцидент файловой системы рабочего ПК:**
Windows System/Ntfs55 подтвердил повреждение структуры C: и индекса старого
исключённого контекста сборки. Текущий `git fsck --no-dangling` прошёл; это не
проверка всего тома и не доказательство причины заполнения диска. Автономный ремонт,
перезагрузка и удаление повреждённой папки не выполнялись. Используются проверенные
Git-архивы и ресурсные ворота. [Receipt и границы](../audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

**6 октября, 16:50 UTC+5 — запись текста и Android-кнопок установлена в Script Studio:**
UI **`1c26ffc7`** на [3015/scripts/builder](http://127.0.0.1:3015/scripts/builder),
image `sha256:9c408135c5bcee80814886361e4ec15934e94e407cb4509d9ada4b90209331ae`.
API остаётся **`eb7a7c26`**. Изменён только UI; сохранены 45 соседних контейнеров,
APK/OTA/туннели. Recorder различает WS submission и HTTP APK confirmation,
фиксирует время отправки и блокирует перенос pending/unknown результатов.
**1546 tests / 128 suites**, TypeScript, финальные builder checks 67/2 и immutable
production build прошли. Четыре source CI `1c26ffc7` success, Preview deploy skipped.
Это не CI последующего документационного head или hosted deployment.
Через native browser на remote PH025 / APK 1.2.45-dev записаны Home, клик и текст;
явно добавлена подготовка Settings, сохранена одна v1, выполнено одно задание:
**completed, 10/10 успешных APK reports**, version/hash совпали. Операторский ACK
2,2–3,7 s не является замером input-to-frame, FPS или p95. Конечные срезы — 14 online /
5 offline из 19, presence доступен; SLA/zero downtime не заявляются.
Обе темы и 1280/390 px проверены, 5 native JPEG, captured console warnings/errors 0;
viewport восстановлен. В header остаётся MISMATCH из-за разных Git UI/API revisions;
это не самостоятельная проверка совместимости. Не закрыты selector/prerequisites,
Unicode/IME, frame-correlated replay, load/soak и storage writer. Найден отдельный
P1 APK на момент этого recorder этапа: `input_clear`/`clear_first` путают CUT 277
с SELECT_ALL; recorder вводит `clear_first:false`. Source fix/candidate 1.2.46
зафиксирован выше; установленный старый APK ещё не получил handler.
Общий счёт **9 / 41** сохраняется.
[Доставка и native проверка](../audits/2026-10-06/STUDIO-COMMAND-RECORDING.md) ·
[Pinned evidence](../audits/2026-10-06/STUDIO-COMMAND-RECORDING-EVIDENCE.json) ·
[Инструкция](SCRIPT-STUDIO.md) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 12:35 UTC+5 — metadata-only каталог в API и UI:**
Обе рабочие сборки на [3015/scripts](http://127.0.0.1:3015/scripts) —
**`eb7a7c26`**. API image
`sha256:559b6bf58e39ed080244d2708a2189856b086dc3c89bf281f62cf42d5f2b28f3`,
UI image `sha256:63159a43a6dde21edc4950b0dd33aa99e01e04ad06e6643d7bf572fba087b1b6`.
Первый запрос каталога получает только persisted version/hash/node_count;
исходник загружается после явного открытия DAG и проверяется по выбранному receipt.
Tenant/session cache, отмена запроса и недоступность метаданных имеют отдельные
контракты; legacy API и остальные consumers сохраняются.
Additive migration и tenant backfill подготовили **25 версий / 22 сценария**,
reconcile завершился без расхождений. Source aggregate SHA256 до/после совпал;
версии, указатели, даты и **445 заданий** сохранились. Повторный проход не изменил
ни одной строки. Живой all-каталог: **14037 bytes**, legacy: **34553 bytes**;
это конечный ответ данного tenant, а не измерение fleet p95 или browser heap.
В PostgreSQL fixture 100 сценариев × 500 узлов: **85176 вместо 48889157 bytes**,
одна SQL-команда без передачи DAG. **171 source tests**, отдельный final migration
test и **1506 frontend tests / 126 suites** прошли с shipped backend dependencies;
exact API image: 596 agent/status, 37 catalog и 35 resource tests, mypy/Ruff/OpenAPI
и packaged maintenance probes прошли. Наборы частично пересекаются, их нельзя
складывать как число уникальных проверок. Native QA установленного source:
реальные состояния 19/3/22, поиск, выбранный DAG и история, запуск без отправки,
переход в редактор, темы/F5 preferences, 1280/724/390 px без расширения документа,
9 JPEG и 0 captured console warnings/errors. Heap/network/frame timing не измерялись.
Первая установка откатила приложения из-за сравнения двух записей одного Windows
bind-path; подтверждено совпадение папок и прав, сравнение нормализовано, повторная
установка завершилась. Additive schema не откатывалась. Сохранены **44 соседних
контейнера**. Срезы UTC: до 07:34:38 — **14 online / 5 offline**; после API 07:34:49 —
**9 / 10**; после UI 07:35:02 — **10 / 9**; контрольный GET 07:41:18 — **14 / 5**,
presence доступен, API ready. Это конечные наблюдения во время reconnect,
не zero downtime/SLA. APK/OTA/туннели сохранены, новых Android
команд или заданий этот этап не создавал.
Все четыре source workflow **`eb7a7c26`** — backend, frontend, Android и Preview —
завершились success. Это source CI, не доказательство hosted deploy или результата
последующего документационного head; receipts входят в pinned evidence.
**9 принято / 41 открыто**: функциональный контракт metadata-only установлен,
но p95/CPU/RSS/query-buffer/browser-heap и load/soak gates остаются открытыми.
Host storage writer по-прежнему UNKNOWN; NTFS-инцидент рассматривается отдельно.
[Доставка и ограничения](../audits/2026-10-06/SCRIPT-CATALOG-DELIVERY.md) ·
[Pinned evidence](../audits/2026-10-06/SCRIPT-CATALOG-EVIDENCE.json) ·
[Инструкция каталога](SCRIPT-CATALOG.md) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 07:00 UTC+5 — редизайн сценариев и лаборатория устройства:**
UI **`a670a3df`**, образ `sha256:e803fc55dc05c1271762d3dca911d1f354e2a42665e8cb0cd917fff20e631c69`,
API **`c2b91e32`** на [3015/scripts](http://127.0.0.1:3015/scripts).
Каталог с сохраняемым видом/плотностью/детализацией, группированная библиотека 32
действий, прямоугольные узлы, явные переходы, формы параметров и локальный ELK worker.
Один выбранный Android: H.264, запись отправленных click/swipe/wheel в памяти,
явная вставка свежего XPath и наблюдение задания закреплённой версии.
Исправлены потеря неприменённых полей через Undo, потеря pending-launch receipt при
закрытии устройства, масштаб графа после смены панелей и устаревшие итоговые счётчики.
Детали выполнения используют общие темы и фиксируют длительность по `finished_at`.
**1451 frontend tests / 125 suites**, TypeScript и immutable production build прошли.
Два native-browser canary на remote PH025 выполнили одну v1 start/sleep4000/end:
по три успешных отчёта, sleep4002 ms, неизменный hash. Их source UI — `6a427df` и
`4ab8cc1`; финальная UI-коррекция проверена тестами и показом этих результатов,
третье задание для неё не создавалось. Native QA: обе темы, 1440/724/390 px, реальные
версии/диалоги/поток/XPath и F5 preferences; каждый скриншот имеет свою ревизию.
45 соседних контейнеров сохранены; конечные срезы 02:00:12/02:00:20 UTC — 14 online /
5 offline из 19, presence доступен. APK/OTA/туннели и API не заменялись.
Это не SLA, проверка всех действий, frame-exact replay или load/soak 20–30/1000 машин.
Все четыре source workflow `a670a3df` завершились success; backend job сообщил
2844 passed / 30 skipped / 1 warning. [Pinned CI](../audits/2026-10-06/evidence/studio-redesign/source-ci.json)
отдельно от установленного API и проверок последующих документационных head.
У preview прошёл guard, deploy skipped по условию включения; это не hosted deploy.
**9 принято / 41 открыто**. Следующие важные контракты — metadata-only каталог (P1:
нынешний список загружает полные DAG), capability preflight, durable reconciliation,
полный recorder/trace/replay и общие resource/release gates. Host writer неизвестен.
Два повреждённых Git tree объекта восстановлены с точными исходными SHA-1;
`git fsck --full --no-dangling` прошёл, история не переписана. Причина повреждения
не установлена и не связывается доказательно с расходом Windows-диска.
[Результат и ограничения](../audits/2026-10-06/STUDIO-REDESIGN.md) ·
[Pinned evidence](../audits/2026-10-06/STUDIO-REDESIGN-EVIDENCE.json) ·
[Инструкция](SCRIPT-STUDIO.md) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md) ·
[Следующий контракт каталога](../audits/2026-10-06/SCRIPT-CATALOG-METADATA-CONTRACT.md).

**Историческая установка 6 октября, 02:35 UTC+5 — Script Studio, этап A:**
API **`c2b91e32`**, UI **`952b5e2f`** на [3015/scripts/builder](http://127.0.0.1:3015/scripts/builder).
Граф ↔ JSON, каталог 32 действий и все JSON-параметры узла, import/export,
bounded undo/redo и явный local draft; серверная проверка draft без создания
script/version/task или Android command. Scope — structure/routes/Lua safety,
не runtime validation всех полей, selectors и capabilities APK.
Через настоящий браузер создан и повторно открыт canary, выбран только remote
PH025 / APK 1.2.45-dev: start → sleep 2000 ms → end, **completed, 3/3 reports**,
v1 и SHA256 совпали. Export/import дал тот же DAG/hash; task для сценария один.
В exact API image **631 tests passed**; frontend **1353 / 122 suites**, Node24
production build/types, packaged mypy/scoped Ruff/OpenAPI прошли. Native browser
проверил обе темы и ширины 1280/390 px; нулевая высота mobile canvas исправлена.
При каждом переключении сохранены 45 соседних контейнеров и постоянный logs volume.
API restart дал временный presence 0/19, затем 14/5; последняя UI-установка 14/5.
Это конечные срезы, не zero downtime или SLA. API/UI разные revisions вследствие
двух frontend-only fixes; backend tree тот же. APK/OTA/туннели сохранены.
Source CI snapshot (точное время в evidence): frontend/Android и backend
lint/security/bootstrap/RLS прошли; backend Tests — 1 failed / 2842 passed / 30 skipped
в sleep-based проверке heartbeat. Test-only follow-up `2dbe82e`: 47 реальных
PostgreSQL/Redis recovery/admission tests прошли, normal/delayed renewal проверены;
source CI `2dbe82e` завершился успешно: **2844 passed / 30 skipped / 0 failed**,
coverage 80,20%; backend/frontend/Android/preview guard прошли. Последующий docs
head имеет отдельный CI; runtime images от этих test/docs изменений не меняются.
**9 принято / 41 открыто**. Recorder, conflict diff, versioned capability schema,
trace/replay/debug и общие resource/release/load gates ещё открыты.
[Результат и acceptance](../audits/2026-10-06/SCRIPT-STUDIO-FOUNDATION.md) ·
[Evidence](../audits/2026-10-06/SCRIPT-STUDIO-EVIDENCE.json) ·
[Инструкция Studio](SCRIPT-STUDIO.md) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 01:37 UTC+5 — ограничен приём загружаемых APK-журналов:**
Установленный API `76596c39`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Body больше 512 KiB отвергается до полного buffering; total ASGI intake deadline 60 s.
Четыре uploads на worker включают приём и filesystem writer; весь FS lifecycle
в отдельном executor. 8 MiB fixture: declared oversize 0 receive, unknown length
9 вместо 128 chunks; Python traced peak около 8 MiB → 0,506 MiB для unknown case.
Это не общий RSS limit или установленная причина расхода Windows C:.
В packaged image прошли 537 device/status/WS/VPN cases, включая 35 новых upload,
и 35 resource cases: **572 passed**; mypy/scoped Ruff/OpenAPI check прошли.
Сохранены 14 original-byte prefixes / 3614902 bytes и 45 соседних контейнеров.
В 01:42 UTC+5 после переключения подтверждены новые uploads в пяти файлах;
живые declared/chunked oversize POST вернули 413, PH025 GET — 1000 строк.
В браузере проверены непустой журнал, поиск, refresh и границы данных.
Online 14 / offline 5 из 19 — конечный срез, не SLA; UI/APK/OTA/туннели сохранены.
Source CI пока не принят целиком; последующий docs head проверяется отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: общие квоты, независимая очистка,
rotation/delete concurrency, backup/restore и leak/load gates остаются.
[Контракт и результат](../audits/2026-10-06/DEVICE-LOG-UPLOAD-BUDGET.md) · [Pinned evidence](../audits/2026-10-06/DEVICE-LOG-UPLOAD-EVIDENCE.json) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 00:55 UTC+5 — ограниченное чтение и постоянное хранение логов:**
API `9889c9ac`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Предел чтения — 2 MiB, JSON-массива строк — 512 KiB; четыре операции на worker
без растущей очереди. Файловый I/O вынесен из event loop. На одинаковом архиве
24 MiB совпали последние 1000 строк; Python traced peak снизился с 46,04 до 0,447 MiB.
Это не замер RSS и не установленная причина расхода Windows-диска.
14 файлов / 902996 bytes перенесены в постоянный том; исходные байты проверены
после rollback и пересоздания контейнера. Сохранены 45 соседних контейнеров.
Проверки образов: 502 + 35 тестов reader, затем 26 тестов final storage image;
23 Compose-проверки, 1307 frontend-тестов / 121 suite, build/types и scoped lint прошли.
В живом браузере проверены ширины 1440/390 px, обе темы, поиск и обновление;
настоящий GET для PH025 вернул 483 строки. Срезы online 14→9 и 14→11 сохранены;
устранение reconnects и непрерывная стабильность ещё не подтверждены.
Полный CI не прошёл: GitHub не выделил runner для backend Tests и Security.
Android CI storage-source прошёл; CI последующего docs-коммита учитывается отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: квоты, независимая очистка, upload budget,
backup/restore и проверки утечек/нагрузки ещё впереди.
[Результат и ограничения](../audits/2026-10-06/DEVICE-LOG-READ-BUDGET.md) · [Доказательства](../audits/2026-10-06/DEVICE-LOG-READ-EVIDENCE.json) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Исторический срез 6 октября, 00:00 UTC+5 — tenant-сводка EP-010 Stage B:**
API `7fef9c53`, веб `9ad0a69e` на [3015/monitoring](http://127.0.0.1:3015/monitoring).
Шесть отдельных источников: активный парк, связь, VPN-отчёт Android, назначения,
сохранённые handshakes и неподключённые проверки публичного транспорта.
Живое окно 19:00 UTC: 19 устройств, 14 online + 5 unknown; 14 VPN inactive + 5 unknown.
Первая установка выявила text/binary Redis mismatch; отдельный фикс и регрессия
подтвердили исправление. 476 + 35 exact-image tests, 1298 frontend tests, Node24
build/types, scoped Ruff и OpenAPI прошли. Сохранены 45 соседей; APK/OTA не менялись.
CI исходников API `7fef9c53`: backend 2754 passed / 30 skipped; frontend, Android
и остальные gates прошли. CI последующего docs-коммита проверяется отдельно.
**9 принято / 41 открыто**, EP-010 OPEN: независимый producer, транспортные probes
и нагрузочный прогон ещё не приняты. [Доказательства и ограничения](../audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE.md) ·
[Pinned receipts](../audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE-EVIDENCE.json).

**Историческая установка foundation — 5 октября, 21:11 UTC+5:** API `d656b579`,
UI `cb5b3f91` сохранён. VPN-отчёт Android имеет независимое серверное время и
владельца сеанса; атомарная запись защищена от запоздавшего старого подключения.
После 120 с отчёт не считается свежим. Живое окно16:20 UTC:14 свежих false и5
unknown при14 online/5 offline из19. Это не проверка VPN-трафика или SLA.
Exact image444+35 tests; source CI backend2722 passed/30 skipped, frontend и
Android прошли. Сохранены 45 соседей. **9 принято/41 открыто**, EP-010 ещё OPEN.
[Результат, ограничения и следующие критерии](../audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md) · [Pinned evidence](../audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json).

**Историческая установка Stage A — 5 октября, 20:31 UTC+5:** backend `66714f26`,
UI `cb5b3f91` сохранён. Список peers и pool counts теперь одинаково исключают
устаревший/future handshake, неназначенные и непривязанные peers; добавлено время
SQL-среза. Exact image: 99 VPN + 27 resource tests, mypy 231/Ruff прошли; сохранены
45 соседних контейнеров. Живой текущий VPN-каталог пуст: нули не доказывают работу
VPN на Android. Последующее окно 6×3 с: 14 online из 19, без утверждения SLA.
**9 принято / 41 открыто**: весь EP-010 ещё открыт.
[События, polling и оставшиеся источники](../audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-NEXT.md) · [Image/runtime evidence](../audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json).

**Историческое уточнение 20:43 UTC+5 — CI и схема Stage A:** source `66714f26`: backend test step
2685 passed /30 skipped, coverage 79.70%; bootstrap/lint/security/RLS прошли.
Workflow остановлен следующим шагом проверки устаревшего OpenAPI. Frontend и
Android CI этого source прошли. Схема синхронизирована отдельным docs-коммитом
`ffdcd36`; exact-image exporter `--check` прошёл. На момент этого среза полный CI нового head ещё не
был принят; успешный CI `d656b579` записан выше. Этот docs-only коммит не меняет установленные API/UI revisions.

**5 октября, 19:55 UTC+5 — EP-009 принят на живом 3015:** API/UI **`cb5b3f91`**,
gateway config **`993d9eac`** сохранён. Реальная история CPU в использованных ядрах
и памяти в GiB cgroup контейнера: окна 1/6/24 h, сбор/обновление 15 с, среднее CPU за 1 минуту.
Лимит памяти 2 GiB подтверждён; CPU quota не подменяется нулём. Host/RSS сюда не
смешиваются. 1275 frontend tests/120 suites, production Node24 build/types и 27
tests в exact API image, mypy 231/Ruff, promtool и живые queries прошли. Браузер
1600/390 px, обе темы и автоматическое обновление проверены. При замене каждого
API/UI сохранены 45 соседей; Prometheus reload без replacement всех 46.
Сохранена временная потеря 14→12→13 online; последующее конечное окно 6×3с:
14 online /5 offline из19. Это не непрерывный SLA или устранение утечки.
**9 закрыто / 41 открыто из 50**; следующий EP-010, host leak attribution, Studio
и stream+script load/soak открыты.
[Приёмка и screenshots](../audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md) ·
[Pinned evidence](../audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-EVIDENCE.json) · [Живой monitoring](http://127.0.0.1:3015/monitoring).

**Исторический срез: 5 октября, 19:03 UTC+5 — HTTP-метрики и исправление маршрута review UI приняты на 3015:**
UI **`7c985feb`**, API **`51ccaa36`**, gateway config **`993d9eac`**;
read-only preflight **`00ed391f`**. Реальные RPS/p95/4xx/5xx, история 1/6/24 h,
top-30 маршрутов с поиском и деталями установлены и проверены HTTP/браузером.
p95 — histogram estimate до заголовков ответа; это не stream/input latency.
Empty/stale/error/partial не подменяются нулём. Встроенная Grafana повторно
проверена с Viewer/query и отзывом собственной сессии после logout.
**118 suites /1235 frontend tests**, затем **99 тематических tests** на финальном
UI, types/changed-file lint/build и **14 gateway preflight tests** прошли.
Браузер: 1600/390 px, две темы, поиск/детали; кнопка обновления40×40 px.
Guard сохранил одну неудачную UI-установку/rollback. Логи доказали неправильный
upstream192.168.0.1 при пропавшем DNS alias; теперь UI зарезервирован172.30.0.3
в отдельном internal subnet. Replacement canary: 23 probes,200/502, конечный200;
gateway не перезапускался. Zero downtime не заявляется. При установке сохранены
остальные44 контейнера; API/APK/DB/tunnels/public18080 не менялись этим пакетом.
Срез19:00:36 UTC+5:14 online /5 offline из19; это не fleet/Android SLA.
**8 закрыто /42 открыто из50**. Следующие приоритеты: EP-009 CPU/RAM history,
EP-010 tunnel/fleet coverage; Studio/recording/trace и load/soak открыты.
[Приёмка и реальные screenshots](../audits/2026-10-05/ENTERPRISE-HTTP-METRICS.md) ·
[Pinned evidence](../audits/2026-10-05/ENTERPRISE-HTTP-METRICS-EVIDENCE.json) ·
[HTTP contract](HTTP-METRICS.md) · [Review gateway](REVIEW-GATEWAY.md) ·
[Живой monitoring](http://127.0.0.1:3015/monitoring).

**Ресурсы, конечный срез12:58 UTC+5:** recorder COMPLETE,241/241 samples за8 h.
C:−2,154GiB; Docker VHD allocated234731077632 B стабилен, exact VSS allocated0
во всех241 срезах; pagefile logical стабилен. Available physical RAM−5,39GiB,
Windows commit+6,06GiB; эти показатели не смешиваются. Writer UNDETERMINED,
RAM leak acceptance OPEN; окно включало сборки/перезапуск API и не является idle
контрольным опытом. Сборщик завершён, новые бесконечные обходы не запущены.
[Отчёт](../audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md) ·
[Конечные доказательства](../audits/2026-10-05/HOST-STORAGE-NIGHT-FINAL-EVIDENCE.json).

**Исторический срез: 5 октября, 08:19 UTC+5 — второй пакет продуктового аудита принят на 3015:**
API **`51ccaa36`**, review UI **`6b7de0cc`**, network topology **`52403b4`**.
EP-006: 403 больше не записывается как delivered; 429/5xx имеют конечный retry,
коррелируемые результаты и стабильный HMAC/delivery ID. Реальный loopback HTTP
canary выполнен внутри установленного backend: пять случаев, receiver закрыт.
EP-007: Grafana получила постоянный private proxy IP вне dynamic pool; браузер
показывает `sphere-collection` с реальными графиками. Viewer/query/read-only
границы проверены; logout немедленно отзывает ещё действующую ticket cookie.
**116 suites / 1196 frontend tests**, TypeScript/build, **70 целевых API tests
в production image**, mypy229/Ruff/OpenAPI прошли. Внедрение включало guard
rollback и пять backend recreations; парк восстановился до14 online/5 offline
к03:19:27 UTC. Это конечная приёмка, не zero downtime или многодневный SLA.
Публичный UI18080, APK, DB и туннели сохранены. **7 закрыто / 43 открыто из50**;
RPS/p95/resource history, Studio/recording/trace и load/soak остаются открытыми.
Source CI конечного документа проверяется отдельно; старый Codecov upload failure
сохранён. Storage recorder ещё RUNNING до12:58 UTC+5; дисковая/RAM проблема не закрыта.
[Изменения, установка и границы](../audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP.md) ·
[Доказательства](../audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP-EVIDENCE.json) ·
[Живой monitoring](http://127.0.0.1:3015/monitoring).

**Исторические ресурсы06:50 UTC /11:50 UTC+5:** recorder207 срезов, C: net−2,16GiB за6h52m;
Docker VHD allocated не вырос, exact VSS0 во всех207 срезах. Максимальный
двухминутный drop1,77GiB в06:22 UTC пока writer UNDETERMINED. Это новое окно,
не прежний VSS growth; host RAM/commit тоже сохранены отдельно. Recorder RUNNING
до07:58 UTC, причина и RAM leak acceptance OPEN.
[Промежуточные доказательства и пределы](../audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md).

**Исторический срез: 5 октября, 07:33 UTC+5 — первый пакет на 3015:**
UI **`6ff6bc2`**, API **`c1a6e79a`**. Исправлены EP-001…EP-005: F5 preferences,
canonical export/import графа, модель устройства в реестре/picker/потоках,
реальное число шагов в orchestration picker. Live-запись выявила и закрыла отдельный
cache-дефект каталога после POST/PUT. **116 suites / 1185 frontend tests**, TypeScript,
production build, DAG validator и browser/API приёмка прошли. Существующий граф открыт;
owned canary создан/сохранён, серверный canonical readback получен, затем canary
архивирован с version precondition. Android команды не запускались.
Только review UI обновлён: остальные 45 контейнеров сохранили identity/image/StartedAt;
APK/API/Tuna сохранены. На срезе 14 online из 19. Публичный UI18080 не обновлялся.
EP-006 webhook, EP-007 Grafana и остальные 44 работы исходного плана открыты;
длительная стабильность и полное выполнение автоматизации этим пакетом не приняты.
[Журнал исправлений и границы приёмки](../audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION.md).

**5 октября — исходный продуктовый аудит, без изменения приложения на этапе аудита:**
проверены 22 раздела меню в установленном UI/API `c1a6e79a`, исходники `c3937a1`.
Шесть подтверждённых дефектов: сброс колонок после F5, несовместимые экспорт и импорт
графа сценария, поле модели устройства, пустое число узлов в выборе сценария
и неверная отметка HTTP 403 как доставки legacy webhook.
Grafana показывает Welcome вместо dashboard; причина пока OPEN.
План из 50 работ различает дефекты, ограничения возможностей, дизайн и будущие адаптеры.
Каталог включает 32 типа действий, 178 HTTP operations, 161 schema и 672 объявления
элементов управления; это не утверждение об исполнении всех действий.
Исправления приложения и новая установка на этом этапе не выполнялись.
[Аудит, доказательства и критерии](../audits/2026-10-05/ENTERPRISE-PRODUCT-AUDIT.md) ·
[План с зависимостями](../audits/2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json).

**Исторический запуск окна, 5 октября04:58 UTC+5:** source `02b5084`, hidden elevated8h recorder
с точными C:/VSS/allocated named-file/RAM/commit/pool counters; Docker каждые16min.
241 samples/120s,16MiB report budget, без полных directory walks и service/device
mutations. Первый native sample/PID/hash проверены, итоговая приёмка RUNNING;
due примерно12:58 UTC+5.67 volumes/46 container epochs сохранены после адресного
cache prune:795→768 records, guest+1,068GiB. Windows VHD остаётся218,61GiB.
68 diagnostic tests и Ruff pilot scope passed. API ready;14 online /2×10245,
12×10244; installed API/UI c1a6e79. Историческая причина и long RAM soak OPEN.
[Полный контракт и evidence](../audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md).

**Последний этап ресурсов, 5 октября / 21:42 UTC 4 октября:** 51 старый owned image
удалён после проверки tags/commit/container references; все 46 identities/epochs
сохранены. Внутри Docker освобождено 10,938 GiB, images 237→186; VHDX остаётся
218,61 GiB. API/UI `c1a6e79`, 14 online10244 на срезе после очистки.
Exact VSS и finite ETW подтверждают отдельные writers; краткий free-drop совпал
с обновлением AdGuard. Полная историческая атрибуция / RAM soak / compaction OPEN.
Recorder `1402612`, bounded projection `9a9256f`, 8 Windows cases passed.
[Writer evidence и пределы](../audits/2026-10-05/DISK-WRITER-ATTRIBUTION.md).

**Android R09:** `ae90715` исправляет disk quota/rotation/startup и bounded queue;
`e75d365` — source-кандидат 1.2.45-dev /10245, 1680 passed /2 skipped.
Artifact `bdfebea` собран23:14 UTC и опубликован `android-canary/dev`.
PH010 local/PH025 remote адресно обновлены23:18 UTC через scoped root recovery:
completed receipts, fresh heartbeat и native installed SHA совпали; quota6→5,
каждый≤2MiB.2 online10245 /12 online10244; normal/android-dev10209 не менялся.
11 коротких срезов сохраняют14 IDs/epochs, API ready и46 containers.
**SOURCE_FIXED / STARTUP_CANARY_VERIFIED / LONG_RETENTION_SOAK_OPEN**;
normal/stable promotion и live saturation ещё не приняты. Source `bdfebea`: все4 CI success.
[Контракт и проверки](../audits/2026-10-05/APK-LOG-RETENTION.md).

**Продолжение22:52 UTC:** net C: free −2,033GiB с21:38 UTC, exact VSS allocation
+1,969GiB. Новый short trace: Docker VHD writes /VSS +224MiB. Две persistent copies,
allocation17,205GiB /max19,057GiB до изменения.
Source `c89594a`, read-only image plan: 14 tests, actual0 candidates /46 containers.
[VSS evidence и конкретный вариант8GiB](../audits/2026-10-05/VSS-RETENTION-REVIEW.md).
**22:58 UTC после одобрения:** max8GiB принят, обе прежние copies удалены Windows;
free C: вырос на17,205GiB до58,976GiB. 22:59 UTC API ready/14 online10244;
все46 container identities/epochs сохранены. VHD не сжимался, VSS не отключался.

**Исторический ресурсный срез, 5 октября / 20:15 UTC 4 октября:** системное окно
COMPLETE — 31 срез, все 62 native queries успешны. Allocated VSS вырос 13,9 → 14,1 ГБ
по округлённому display; free C: -264,719 MiB за 30 минут. Рост VSS подтверждён,
но предыдущие -6,459 GiB не атрибутированы целиком; writer UNDETERMINED. Короткие
disk/RAM продолжения завершены, восьмичасовые окна прерваны после перезапуска.
C: free 34,670 GiB, available RAM 19,018 GiB. 48 diagnostic cases и CI сборщика
`a305076` прошли; runtime `c1a6e79`, APK10244 и R09 log retention OPEN сохранены.
[Наблюдения, RAM и пределы](../audits/2026-10-05/HOST-DISK-GROWTH.md).

**Дополнительный срез диска, 4 октября / 17:50 UTC:** рабочая папка — 7,996 GiB,
отслеживаемые файлы — 22,08 MiB; shared Docker VHD — 218,61 GiB вне workspace.
Обход проверил метаданные 5 038 969 доступных файлов C:. Штатная очистка download
caches npm/pip дала наблюдаемые +4,726 GiB; C: free 41,431 GiB при guard.
Все 46 container identities/image/start сохранены; API c1a6e79, 14 online10244.
Никаких рестартов / Android команд. Оставшиеся Next caches 0,819 GiB не удалены:
автоматическая проверка отклонила действие. VHD compaction и причина отдельного
доочисточного снижения free space остаются открыты.
[Измерения и доказательства](../audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP.md).

> [!IMPORTANT]
> **Предыдущая установка: API / UI c1a6e79**, [веб на 3015](http://127.0.0.1:3015/devices).
> **4 октября 2026, после перезагрузки ПК в 16:39 UTC.** Исправлен повторный
> запуск npm ci при изменении SHA; переиспользование зависимостей доказано двумя сборками.
> Адресно очищены 8,21 GiB старых кэшей Next, 19 контекстов и 53 неиспользуемых
> образа проекта. Новый API принял ротацию логов 20m × 5. Диск, физическая память
> и Windows commit измерены отдельно; VHD не сжимался, длительная утечка ОЗУ не доказана.
> **113 наборов / 1122 frontend-теста, 186 API-проверок, 18 проверок допуска сборки;
> mypy: 229 файлов; OpenAPI: 178 операций / 140 путей; все четыре CI прошли.**
> RPC trace сохраняет этап, прогресс и исход команды; ошибка Redis cleanup больше
> не заменяет полученный результат. Local PNG 200, remote 504 и отдельный recovery
> PNG 200 за 3,817 с сохранены вместе. Первое окно связи FAILED: 11→14 / смена epochs;
> второе сохранило 14 online и даты подключений. Это конечная проверка, не длительный SLA.
> APK 10244, Tuna и OTA сохранены; пять offline вне приёмки. **34 исправлено в коде /
> 7 незакрытых.** [Измерения и открытые критерии](../audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md).
> Визуальная приёмка: OPEN_URL_POLICY_BLOCKED.

> [!IMPORTANT]
> **Предыдущая установка: API / UI 9716348**, [review 3015](http://127.0.0.1:3015/devices).
> **4 октября 2026, 10:06 UTC+5:** исходный PNG доступен из обзора и под одиночным видео;
> Android/server/browser SHA-256, без ресайза/перекодирования. PH025/PH010 actual PNG
> 960×540 прошли полное декодирование. Сохранение H.264-кадра подписано отдельно.
> Добавлен manual Android profile; 7 native reads, проверенные bounded TS-парсеры.
> Wheel и key/text controls покрыты тестами; live keyboard/wheel result OPEN.
> **113 suites / 1117 frontend; 140 API cases; mypy229, schema178/140, CI4 passed.**
> Последние 7 срезов: 14 online10244, epochs после API restart сохранены; это не soak/SLA.
> Первый remote PNG504 и семь simultaneous code1005 disconnects сохранены; причина OPEN.
> APK/Tuna/OTA не менялись. 5 offline вне приёмки; **34 source-fixed / 7 незакрытых**.
> [Контракт, исходные файлы, тайминги и пределы](../audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md). Browser visual OPEN_URL_POLICY_BLOCKED.

> [!IMPORTANT]
> **Историческая установка этапа XPath: API 9274e50 / UI 84750e3**, [review 3015](http://127.0.0.1:3015/devices).
> **4 октября 2026, 05:55 UTC+5:** исправлен пользовательский отказ XPath:
> вход в режим сам читает дерево после текущего кадра, клик во время загрузки
> сохраняется. Подсветка, все возвращённые атрибуты, XPath/JSON и список узлов;
> автообновление через 5 с после ответа, только в видимом инспекторе, при ошибке — пауза.
> **5 воспроизведённых отказов → 8 интеграционных pointer cases; 110 наборов /
> 1043 frontend-теста; 108 API/XML/PostgreSQL/Redis проверок** прошли в образах.
> На API получены настоящие деревья: PH010 — 45, удалённый PH025 — 49 узлов,
> 960×540, cleanup подтверждён. APK 1.2.44-dev / 10244 в этом этапе не менялся.
> Используется root UI Automator; полный встроенный сервер UIAutomator2 не добавлен.
> После замены UI: 7 срезов сохранили 14 online и даты соединений; API/Tuna/OTA
> и 15 соседей сохранены. Прежний API gate **FAILED (14→13, PH015)** остаётся в evidence;
> последующее восстановление не доказывает непрерывную стабильность. Это не soak/SLA.
> **34 source-fixed / 7 незакрытых, включая 3 PARTIAL.** F35 visual и nonroot path,
> Matrix preview, качество/задержка, другие формы, durable outcomes и нагрузка OPEN.
> CI каждого source и пределы браузерной приёмки записаны отдельно.
> [Контракт и доказательства](../audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md) · Browser: OPEN_URL_POLICY_BLOCKED.

> [!IMPORTANT]
> **Предыдущая установка: API 37bb436 / UI 922f479**, review [3015](http://127.0.0.1:3015/devices).
> Проверено **4 октября 2026, 02:04 UTC+5**. F39: группы и локации используют проверенные сервером
> права записи и удаления; открытые формы и Enter учитывают полученный отзыв доступа.
> **16 воспроизведённых отказов → 107 наборов / 1013 тестов** в собранном веб-образе;
> **89 PostgreSQL/Redis проверок** прошли также в неизменённом API-образе.
> CI исходников 922f479: Preview — success; Frontend — success; Android — success; Backend — success. Время отдельной проверки CI записано в evidence.
> После замены только UI семь срезов сохранили **14 online APK 10244**, heartbeat <60 с
> и прежние даты соединений. **15 соседних сервисов, API, Tuna и OTA сохранены.**
> Каталоги API: одна группа и ноль локаций; метаданные до/после совпадают.
> Живые записи/удаления, reboot и VPN команды не отправлялись; APK не обновлялся.
> Предыдущий N10 сохраняет неудачное первое окно и восстановление;
> причина его повторных SSL/Socket переподключений остаётся неизвестной.
> **33 source-fixed / 8 незакрытых, включая три PARTIAL.** Остальные формы, member
> lifecycle, JPEG Matrix, XPath, FPS/latency, browser/soak и OTA reconciliation открыты.
> [Контракт и evidence](../audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS.md) · Browser: OPEN_URL_POLICY_BLOCKED.

> [!IMPORTANT]
> **Предыдущая проверка видео и backend: 3 октября 2026, 15:53 UTC.** API **37415e3** установлен;
> UI **77fca37** и APK **1.2.44-dev / 10244** сохранены. На удалённой PH025 и
> локальной PH010 получено по **599 H.264 кадров за 20  с: 29,95 кадра/с**.
> Это доставка до WebSocket-получателя; отрисовка браузера и задержка ввода ещё не приняты.
> **N09:** после потери кадра очередь отбрасывает зависимую цепочку и запрашивает
> новый ключевой кадр; срок хранения проверяется также при выдаче из очереди.
> **230 WebSocket-тестов + 41 тест PostgreSQL/Redis; 271 passed в собранном образе.**
> GitHub CI исходников прошёл. Семь срезов: **14 online на 10244**, heartbeat <60  с,
> новые даты подключения сохраняются. 15 соседних сервисов, Tuna и OTA сохранены.
> Два отката из-за формы/порядка mounts разобраны в отчёте; mounts эквивалентны.
> [Отчёт и доказательства](../audits/2026-10-03/STREAM-REFERENCE-RECOVERY.md). F36: качество, браузер, задержка и soak OPEN.
> Исходный аудит: **33 исправлено / 8 OPEN**; stable/normal OTA promotion OPEN.
> Визуальная проверка браузера: OPEN_URL_POLICY_BLOCKED.

> [!IMPORTANT]
> **Предыдущая проверка APK: 3 октября 2026, 15:01 UTC (20:01 UTC+5).**
> **Все 14 доступных устройств работают с 1.2.44-dev / 10244**;
> пять офлайн-устройств остаются вне этой приёмки.
> Исправлен отказ `ota_signer_unavailable` в guard 10241. На удалённой PH028
> адресное OTA 43→44 подтверждено квитанцией, новым heartbeat и SHA установленного
> файла. Остальные 13 устройств получили разовую установку через root APK;
> данные и идентификаторы сохранены.
> 12 контрольных срезов сохранили весь cohort и серверные даты подключения;
> heartbeat моложе 60 секунд. Все 16 прежних контейнеров сохранены.
> APK source **ad34c12**: **831 passed / 1 skipped** на каждый Android flavor;
> его backend/frontend/Android CI прошли. UI **77fca37** / API **facba9a**:
> [3015/updates](http://127.0.0.1:3015/updates). Canary 44 опубликован в managed
> каталоге; normal android/dev остаётся 10209.
> Stable/normal promotion, verified manifest, measured FPS/input latency и soak
> остаются OPEN. **33 source-fixed / 8 OPEN**, F32/F33 PARTIAL.
> Browser visual: OPEN_URL_POLICY_BLOCKED.
> [Native/rollout report](../audits/2026-10-03/OTA-SIGNER-COMPATIBILITY.md) · [ABR proof](../audits/2026-10-03/STREAM-BITRATE-RECOVERY.md).

> [!IMPORTANT]
> **Предыдущий OTA/API/UI readback, 3 октября 2026,03:17:58 UTC:**
> [3015/updates](http://127.0.0.1:3015/updates), UI **77fca37** / API **facba9a**.
> APK **1.2.41-dev/10241** опубликован в canary и адресно установлен на 14 целях;
> для каждой exact terminal receipt +новый heartbeat. Все14 online на 10241,
> пять offline вне приёмки. 12 finite срезов03:14:44–03:16:35 UTC сохранили
> cohort/connected_since, heartbeat <30 s. Это короткая проверка после обновления.
> Backend strict publication/duplicate 409 и APK identity guard добавлены;
> веб проверяет поля/receipt и выполняет read-only reconciliation неизвестного исхода.
> **104 suites /946 frontend tests**, 130 cases в immutable API image,
> 818 passed / 1 skip на каждый Android flavor. Full backend 2381 passed/16 skipped;
> facba9a остановился на staleOpenAPI; repair **5bb36ca прошёл backend,
> frontend и Android CI**, включая schema check. Новый docs head имеет свои checks. Новый guard 10241 требует live next-upgrade canary.
> Login/API/Prometheus/Grafana/events WS прошли;13 соседних сервисов сохранены.
> Normal android/dev10209, production signer/stable/general manifest/bulk,
> browser/soak и stream+scripts20–30-device gates OPEN. **33 source-fixed/8 OPEN**,
> F32/F33 PARTIAL. [Новый отчёт](../audits/2026-10-03/OTA-RELEASE-IDENTITY.md) ·
> [Контракт](OTA-PUBLICATION-AND-APK-CHECKS.md).

> [!IMPORTANT]
> **Предыдущий live OTA readback10240,3 октября2026:** [3015/updates](http://127.0.0.1:3015/updates).
> Проверено и адресно обновлено **11 устройств до1.2.40-dev/10240**;
> exact install receipts и новый heartbeat получены для каждого.
> **Все14 online теперь10240**,5offline вне приёмки.12 конечных срезов
> 02:20:43–02:23:29UTC: тот же cohort, heartbeat<30s;
> отдельные connected_since до/после не изменились. Это не длительный soak.
> APK package/signer проверены по exact installed-file hashes; данные не очищались.
> Normal android/dev всё ещё10209; general manifest/bulk workflow и stable release OPEN.
> Source **6d5f280 CI passed**: frontend/Android/backend, **2351 passed/16skipped**.
> UI **a2c4f02**,API **8cd5cf0**; новый docs head имеет собственный CI.
> [Полный rollout/receipts](../audits/2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).

> [!IMPORTANT]
> **Предыдущая версия UI/API, F32; fleet readback,3 октября2026.**
> [3015/vpn](http://127.0.0.1:3015/vpn), UI **a2c4f02** / API **8cd5cf0**.
> VPN controls: explicit targets/action, owned preflight, подтверждение и
> результаты по устройствам; unknown не replay. No-op kill-switch честно
> сообщает unsupported. N06 deferred provider initialization исправлен и принят
> live422/404. **103 suites / 916 frontend tests в Node24**, **159 backend cases
> в immutable API image**, mypy225 / OpenAPI175 operations passed.
> Login/API/Prometheus/Grafana/events WS прошли22:59UTC2октября;
> **13 постоянных соседних сервисов** сохранены. Finite online14→11→12;
> стабильность этим этапом не принята. Сверка01:53UTC3октября:19 устройств,
> online14, **только3 на1.2.40-dev;11 online на старых APK**.
> [Отчёт/receipts](../audits/2026-10-03/VPN-CONTROL-OUTCOMES.md) ·
> [Контракт](VPN-CONTROL-OUTCOMES.md). **33 source-fixed / 8 OPEN**;
> F32/F33 PARTIAL, browser/rollout/combined fleet acceptance OPEN.

> [!IMPORTANT]
> **Предыдущий review: 3 октября 2026, 03:06 UTC+5.**
> [3015/locations](http://127.0.0.1:3015/locations), UI **8e0aeb5** / API **db6be05**.
> F26: география, nullable clear, owned detail и иерархия установлены;
> циклы и устаревшие записи/удаления отклоняются атомарно. **102 suites / 893
> frontend tests**, **40 PostgreSQL cases**, включая **30 в новом production
> image**. Собственный live API canary создан, проверен и удалён, без команд
> Android. Login/API/Prometheus/Grafana/events WS passed; шесть конечных срезов
> 22:07–22:09 UTC: **14 online / 5 offline**. Это не SLA/FPS/soak.
> **13 постоянных соседних контейнеров** сохранили ID/image/starttime.
> [F26 evidence](../audits/2026-10-03/LOCATION-HIERARCHY.md) ·
> [Контракт](LOCATION-HIERARCHY.md). **33 source-fixed / 8 OPEN**;
> visual/keyboard/mobile, public rollout и combined fleet acceptance OPEN.

> [!IMPORTANT]
> **Предыдущий review,3 октября02:33 UTC+5:** [3015/orchestration](http://127.0.0.1:3015/orchestration), UI **5b20955** / API **cc28e9b**. F28: полный owned detail, JSON editor, explicit activation и timestamp conditions; nonterminal runs защищают runtime definition.101 suites/867 frontend tests;120 related PostgreSQL cases,35 cases также в новом production image. Собственный live pipeline v1→v2→inactive; stale409/invalid422,0 runs/Android commands. Login/API/Prometheus/Grafana/events WS passed. Initial12online/7offline; затем шесть срезов21:16:59–21:19:29UTC показали14online/5offline. Это конечное наблюдение, не SLA/FPS/soak.13 соседних работающих контейнеров сохранили ID/image/starttime. [F28 evidence](../audits/2026-10-03/PIPELINE-DEFINITION-WORKFLOW.md) · [Контракт](PIPELINE-DEFINITIONS.md). Browser visual/keyboard/mobile и production rollout OPEN. Исторические срезы ниже сохранены по датам.

> [!IMPORTANT]
> **Работающий review,2 октября23:45 UTC+5:** [3015/scripts](http://127.0.0.1:3015/scripts), UI **c989eaa** / API **d2846ef**. F27 source/test/API исправлен: доступный архив, выбранный immutable DAG/hash/diff, conditional rollback/archive и показанная версия для Run. Реальный собственный сценарий v1→v2→новая v3→архив; stale mutations/admissions409.100 suites/846 frontend tests,25 actual PostgreSQL cases также в production image passed.43 соседних контейнера сохранены; финальный срез19/online14/offline5. Browser visual, production rollout и длительная приёмка OPEN. [F27 evidence](../audits/2026-10-02/SCRIPT-VERSION-WORKFLOW.md) · [Операторский контракт](SCRIPT-VERSIONS.md).

> [!IMPORTANT]
> **Работающий review,2 октября18:13 UTC+5:** [3015/updates](http://127.0.0.1:3015/updates), Docker UI **d61ab49** / API **8267b94**. F33 PARTIAL: адресное OTA, current-socket wake, same-ID redispatch и conditional revoke установлены. Remote PH013 обновился10230→10240; live send, completed/restart receipt и новый heartbeat подтверждены.99 suites/825 frontend tests;310 transport/API regressions и5 actual PostgreSQL/RLS/Redis cases (также внутри production image) passed. Каталог19/online14/offline5,3online10240.43 соседних контейнера сохранены. [F33 evidence](../audits/2026-10-02/OTA-ADDRESSED-DELIVERY.md) · [Операторский контракт](OTA-ADDRESSED-UPDATES.md). Bulk rollout, verified artifact manifest и browser visual OPEN.

**Исторический проверенный documentation CI:**a408b31 — [frontend37012373103](https://github.com/RootOne1337/sphere-platform/actions/runs/37012373103), [backend37012373085](https://github.com/RootOne1337/sphere-platform/actions/runs/37012373085), [Android37012373076](https://github.com/RootOne1337/sphere-platform/actions/runs/37012373076), success; backend2248 passed/16 skipped. Core d2846ef frontend/Android passed; backend2268 passed/2 failed/16 skipped из-за старой MagicMock request fixture. Test-only correction **da7cf58**:8 batch unit passed; новый documentation head требует отдельного CI. [F27 CI details](../audits/2026-10-02/SCRIPT-VERSION-WORKFLOW.md).

> [!IMPORTANT]
> **Предыдущий review, 2 октября17:12 UTC+5:** [3015/audit](http://127.0.0.1:3015/audit), Docker UI **67b6bef** / API **39baa13**. F37: поиск всего журнала организации, диапазон UTC и bounded CSV5000 с отменой/проверкой receipt установлены. Event за page1 и actual truncated CSV подтверждены на5386 событиях. Login/API/Prometheus/Grafana/events WS/compiled artifact passed;43 остальных containers сохранены.19 устройств,14online/5offline после backend replacement — конечный срез. [Audit investigation / receipts и ограничения](../audits/2026-10-02/AUDIT-INVESTIGATION.md).

> [!IMPORTANT]
> **Предыдущий review, 2 октября16:18 UTC+5:** [3015/users](http://127.0.0.1:3015/users), Docker UI **e2362eb** / API **933164e**. F38: native form, точные ошибки полей, адресные подтверждения ролей/отключения и проверка ответа установлены. Login/API, Prometheus/Grafana/events WS и compiled artifact passed;44 остальных containers сохранены. Каталог19, online14/offline5 — конечный срез. [User access / receipts и ограничения](../audits/2026-10-02/USER-ACCESS.md). N04/N05 finite API proofs сохранены в [предыдущем отчёте](../audits/2026-10-02/GROUP-HIERARCHY-AND-AUDIT.md).

> [!IMPORTANT]
> **Предыдущий review, 2 октября 05:08 UTC+5:** [3015](http://127.0.0.1:3015/) теперь в отдельном Docker project. UI **d4364e5**, API **5fcf18a**. Login, static asset/build stamp, Prometheus, Grafana session/health и events WS проверены до и после restart обоих review контейнеров. Все 14 прежних контейнеров сохранили IDs/images/StartedAt. Native UI3030/relay3015 исчезли; причина не доказана. [Runtime и Android canary](../audits/2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md).

> [!IMPORTANT]
> **Историческая native установка 2 октября 2026, 01:28:45 UTC+5:** `3015 → standalone UI3030/API18080`, frontend и backend **5fcf18a**. Readiness/build SHA, owned listeners и авторизованный API проверены. Предыдущий Next7416/UI3029 и backend image8d64ca4 сохранены; заменён только owned relay и backend. Это проверочный веб [3015/tasks](http://127.0.0.1:3015/tasks); public frontend не заменён. [Журнал](../audits/2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Точные receipts](../audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN-EVIDENCE.json).

**Исторический F28 source/test срез: 32 source findings исправлено полностью**, включая все5 P1; **9 исходных остаются открытыми**, включая F33 PARTIAL. Совокупный frontend — **101 suites/867 tests**, **285 новых regressions** сверх582. F27:25 actual PostgreSQL tests/production image,80 script unit tests/1 skipped, Types/mypy224/Ruff0.15.2, immutable production builds и OpenAPI174 operations/137 paths passed. Browser visual, Android artifact upload N01, legacy RPC errors N03, durable audit outbox и 20–30-device acceptance OPEN. [Script contract](SCRIPT-VERSIONS.md) · [F27 receipts](../audits/2026-10-02/SCRIPT-VERSION-WORKFLOW-EVIDENCE.json). Старые срезы ниже сохранены со своими датами.

**Исторический published verification5d27624 полностью прошёл CI:** [backend37000707994](https://github.com/RootOne1337/sphere-platform/actions/runs/37000707994), [frontend37000707943](https://github.com/RootOne1337/sphere-platform/actions/runs/37000707943), [Android37000707995](https://github.com/RootOne1337/sphere-platform/actions/runs/37000707995). Source67b6bef frontend37004977091 success; backend37004977150/Android37004977161 выполнялись на срезе документа. Новый docs head требует своих checks. Предыдущие groups/null/cycles/audit rollback и user422/404/400,23 HTTP/49 RBAC proofs сохраняются с собственными датами. [User contract](USER-ACCESS.md) · [F37 live/read limits](../audits/2026-10-02/AUDIT-INVESTIGATION.md).

**GitHub CI application source5fcf18a:** [backend run36921814744](https://github.com/RootOne1337/sphere-platform/actions/runs/36921814744)
выполнил **2165 tests / 16 skipped**, coverage78%; job затем упал на stale generated
OpenAPI. Экспорт исправлен до **171 HTTP operations / 134 paths**, local `--check`
passed. Redis/Alembic следующие шаги этого run не были приняты. Verification head **77e96a4** отдельно завершился success по backend/frontend/Android; [полные jobs](https://github.com/RootOne1337/sphere-platform/actions/runs/36924906048) прошли после обновления OpenAPI. Frontend и Android
CI того же source passed; новый verification head имеет собственные checks.

**Открытый follow-up N01:** APK DAG screenshot сохраняет Android-local path без
загрузки в storage. Read configuration на pilot пока выключена; наличие файла
Android не изображается как серверный snapshot. Полный Android→storage→browser
путь ещё не принят. Конечный variable-only pinned rerun подтверждён на remote PH025/10240: оба задания completed/success; после изменения latest v2 APK повторно исполнил v1. Это не приёмка произвольных скриптов или всего парка. Свежая визуальная проверка Sphere
остаётся `OPEN_URL_POLICY_BLOCKED`, запрет не обходился.

**Live API срез 01:30:49 UTC+5:** login passed, owned task manifest200,
unknown task rerun404; каталог19, reported online14/offline5. Версии APK смешаны;
10240 не установлен повсеместно. APK/OTA/tunnels этим batch не изменялись.
Моментальный срез не является новым результатом soak/FPS/latency. Предыдущие
исправления каталогов/навигации/settings остаются в исходниках; [F13 proof](../audits/2026-10-02/ORCHESTRATION-CATALOG-PAGING.md).

**Предыдущая установка 2 октября, 00:36 UTC+5:** UI7f30d9d/3029, API8d64ca4;
89 suites / 705 tests. Это исторический срез, заменён текущей установкой выше.

**Предыдущая установка 1 октября:** UI 8f615c6 на 3023 / relay3015 установлен
в 17:28:52, backend 8d64ca4 — в 18:04:04. На срезе 22:19 прежние 3015/3023
не слушали порт; причина завершения этих процессов этим batch не установлена.
[Исторический cross-layer audit и OTA evidence](../audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY.md).

**Текущий APK canary:** **1.2.40-dev / 10240**, source **68155c1**, planar=true /
GPU=false, **8465471 bytes**, SHA256
`c612fba1e4a537ab1a0d9951e520bbd4063c3548308a4ebc31b72b59fa735a70`.
Прежний pilot signer/package подтверждён. Обе configured debug flavors: **783 tests
каждый, 782 passed / 1 skipped / 0 failures / 0 errors**, обе собраны. По одному
адресному OTA на PH010 и remote PH025: completed / installed 10240 /
recovered_after_process_restart=true; свежие online versions подтверждены.
Normal/global OTA и GitHub latest aliases не продвигались; default flags false.
Это debug canary, не production release и не обновление всего парка.

**Исправленные cross-layer дефекты:** [web diagnostics ownership/freshness](../audits/2026-10-01/STREAM-DIAGNOSTIC-OWNERSHIP.md),
[terminal heartbeat cleanup/fencing](../audits/2026-10-01/PIPELINE-TERMINAL-HEARTBEAT.md),
[codec callback ownership/output release](../audits/2026-10-01/ENCODER-CALLBACK-OWNERSHIP.md).
Каждый имеет before/after regression proof. Ни один не объявляется единственной
причиной низкого FPS удалённых устройств.

**Последний finite native video trial, 10240:** PH010 **299 pictures / 10 s**,
first picture **0.860 s**, native 960×540/~60 Hz. PH025 first picture **9.844 s**,
**4 pictures в startup-окне 3..13 s**, затем **21 в 13..23 s**, display **5 Hz**.
Post-encoding heartbeat около 25 s: local capture 60 / render 30 / encode 29,
remote capture 4 / render 5 / encode 5; recorded input drops / WS rejects / encoder errors
0. На 40 s тот же snapshot уже старше 18–20 s, поэтому нули не относятся ко всему
trial. Remote arrival gaps 3–5 s близки producer PTS gaps; upstream timestamp
rejections пока не учтены raw counters, loss целых pictures не исключён.
[Allowlisted evidence](../audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY-EVIDENCE.json).
Browser draw FPS, quality и input-to-visible latency не измерены; текущая browser
review blocked URL policy. Предыдущий PyAV decode 462/462 и CPU snapshot относятся
к 10239 и сохранены ниже, не повторялись на 10240.

**Code acceptance 8d64ca4:** [Backend 36864314898](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314898)
success, **2140 passed / 15 skipped**; OpenAPI, RLS, Alembic, lint/types, security,
production bootstrap, metrics replacement, Redis pressure/restart passed.
[Frontend 36864314913](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314913)
и [Android 36864314903](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314903)
success. Frontend локально **73 suites / 582 tests**, isolated compile passed;
source tree установленной UI 8f615c6 и APK 68155c1 совпадает с соответствующим tree
8d64ca4. Preview guard success / deployment skipped. Failed pipeline race и
промежуточный RLS test-hook failure сохранены в audit, runtime policy не ослаблена.

**Recovery после API rollout:** **18:05:42** — 19 records / 13 online / 6 offline,
PH010/PH025 online 10240, launcher и not_streaming. PH028/10232 кратко потерял WS
(code 1005) и восстановил heartbeat в 18:05:46. Три GET-only среза
**18:10:41 / 18:10:51 / 18:11:01** — **14 online / 5 offline**, прежний online set.
Это finite recovery evidence, не uptime SLA или подтверждение всех ожидаемых 23.
Закрыты только собственные viewers; global stop отсутствует.

### Предыдущий срез 1 октября: b9a3f29 / APK10239

> [!IMPORTANT]
> **Исторический loopback runtime, 1 октября:** `3015 → UI 3022 / API 18080`, frontend/API **`b9a3f29`**. Compiled UI переключён в **15:44:19 UTC+5**, Next PID **21016** / relay PID **2080**, прежний Next 3021 / PID 45944 сохранён для rollback. В одиночном просмотре tap/swipe разрешён по последнему кадру текущего OPEN socket после 10 s без изменений; first-frame/error/reconnect gates сохраняются. Backend заменён отдельно в **16:01:53** после required CI, build/readiness подтверждены; database head, соседние containers, public UI, OTA catalog/artifacts и tunnels не менялись. [Static input contract](STATIC-STREAM-INPUT.md), [allowlisted runtime/OTA/capture/decode evidence](../audits/2026-10-01/PH010-PH025-PLANAR-CAPTURE-EVIDENCE.json). **Browser visual QA заблокирована политикой URL CUA**, обход не выполнялся; native decoded PNG не является browser screenshot или draw-FPS benchmark.

**Предыдущий APK canary:** `1.2.39-dev / 10239`, source **8a66afe**, planar=true /
GPU=false, 8464127 bytes, SHA256
`c9f4a5ef9652a2bb2b14765e4c91fa929d4e1b59e7645703be99ed64f8dcca07`.
Подписан прежним pilot key; обе configured debug flavors: **770 tests каждый,
769 passed / 1 skipped / 0 failures / 0 errors**, обе собраны. По одному адресному
OTA PH010 и remote PH025: completed / installed 10239 / recovered-after-restart,
свежие online versions подтверждены. Normal/global OTA и GitHub latest APK aliases
не продвигались, default planar/GPU flags false. Это canary, не production release.

**Предыдущие реальные video measurements:** PH010 — **300 и 299 pictures / 10 s**
в независимых native capture/wire trials. PyAV 19.0.0 декодировал **462 pictures**
без ошибок, все native **960×540**. [Методика и собственный decoded sample](CODEC-INPUT-CANARY.md).
PH025 — **19 и 17 pictures / 10 s**; его дисплей всё ещё сообщает **5 Hz**.
Remote 3..13 s measurement windows включают startup. Arrival gaps 3–4 s близки
producer PTS gaps: это сужает диагноз, но не изолирует capture/codec input/loss
целых pictures. Не измерены browser draw FPS и абсолютная input-to-visible latency.
Local APK CPU sample ~80% одного ядра, включая pattern + RGBA conversion, codec12%;
плавный finite PH010 stream не доказывает лёгкий runtime для десятков viewers.

**Code acceptance b9a3f29:** [Backend 36850795071](https://github.com/RootOne1337/sphere-platform/actions/runs/36850795071)
success, **2135 passed / 15 skipped / 0 failures / 0 errors**, OpenAPI check,
Redis pressure/restart, production-image bootstrap, lint/types, configured security,
RLS и Alembic single-head passed. [Frontend 36850795102](https://github.com/RootOne1337/sphere-platform/actions/runs/36850795102)
и [Android 36850795212](https://github.com/RootOne1337/sphere-platform/actions/runs/36850795212)
success. Frontend local **73 suites / 576 tests**, types/targeted legacy lint и
isolated compile passed. Preview guard success / deployment skipped: это не
публичный production deployment. Ранее Backend 8a66afe остановился только на stale
generated OpenAPI после успешных tests; schema regenerated в **3639a97**, failed
run сохраняется как counterexample.

**Диагностика после backend rollout:** `encoder_input_drops_total` реально дошёл
от PH025 до API. В конечном 33 s trial три API reads ещё содержали один ранний
heartbeat, encoded=0, хотя viewer позже получил 49 pictures. Нулевой early input
drop counter не закрывает late-drop gate; post-encoding heartbeat остаётся нужен.
Датированный final readback в evidence: **19 records / 14 online / 5 offline**,
PH010/PH025 online10239, not_streaming, launcher resumed; закрыт только собственный
viewer, global stop отсутствует. Это конечный readback, не обещание uptime всех23.

### Предыдущие runtime/validation slices

UI c547f5d был переключён в 04:19:15: `3015 → UI 3021 / API 18080`, API85c8014,
Next45944 / relay28872. Android Back/Home/Recents/Menu подтверждены source tests;
прежний Next3020 сохранён для rollback. Этот UI/API slice заменён текущим выше.

Предыдущий UI `4c79ef6` с независимыми receive/draw FPS compiled и переключён в
01:52:06 UTC+5. В 03:35 обнаружено отсутствие прежних Next/relay listeners и
старого UI 3019; backend/API/tunnels работали, причина исчезновения процессов не
установлена. В 03:35:34 восстановлена та же pinned compile: Next PID 28988 /
relay PID 7156. Это исторический restore, не текущий ingress после 04:19 switch.

Историческая browser acceptance **30 сентября, 22:21–22:29 UTC+5** относится
к UI `3132afc` на `3015 → UI 3018 / API 18080`: WEB/API stamp, live events,
PostgreSQL details и hide/restore selection. Тогда старые Next PID были сохранены;
1 октября они уже отсутствовали. Backend `85c8014` переключён 30 сентября
**21:37**, healthy/readback **21:37:59**. Семь конечных срезов **21:40:40–21:41:40**
показывали 14 новых sessions/fresh heartbeat; отдельный срез **22:29:40** —
14 online / 5 offline / 0 connecting. Это конечные проверки, не uptime SLA,
не новая stream/scripts/OTA acceptance. Ниже сохранены версии и даты прежних этапов.

## История диагноза и предыдущих проверок

**Уточнение диагноза, 1 октября 05:32 UTC+5:** standalone native control на PH010
с тем же Google AVC и 960×540 сравнил графический Surface input с прямым planar
YUV. Surface: **8 pictures / 1.2 s (6.67/s)**, input-to-output callback 418–488 ms;
planar: **36 / 1.2 s (30/s)**, 1.29–2.46 ms. Переключение Surface CBR → VBR и
AVC → VP8 не ускорило input. Во всех окончательных controls drain завершён,
inflight = 0. Это уточняет прежний CPU вывод: ограничение проявляется в graphics
input path, а не в чистом AVC encode синтетического YUV. Реальный RGBA conversion,
capture/wire/browser FPS, читаемость и remote input latency ещё не приняты.
Новый APK этим probe не устанавливался; normal OTA и default capture не менялись.
[Методика, ограничения и следующий canary](CODEC-INPUT-CANARY.md),
[allowlisted evidence](../audits/2026-10-01/PH010-CODEC-INPUT-EVIDENCE.json).

**Новый сравнительный срез 1 октября:** одинаковый GPU APK 1.2.36 на local
PH010 (~60 Hz display) дал 65 pictures / 20 s, remote PH025 (5 Hz) — 44/20 s.
Оба ниже acceptance: host FPS limit не единственная причина. Source 1.2.37
установлена на PH010 и локализовала Surface swap wait 277–306 ms: 68 pictures /
20 s, selected `OMX.google.h264.encoder`, capture 1280×720 при source 960×540.
Source 1.2.38 устраняет upscale только в GPU canary и связывает live input с
capture geometry; она собрана, подписана pilot key и установлена адресным OTA
на PH010 и PH025. PH010: **113 pictures / 20 s (5.65/s)**, Surface swap mean
**169.62–180.10 ms** в пяти motion windows. Штатный Android screenrecord без
Sphere video transport дал **47 frames / 7.845044 s (5.991 FPS)**; отдельный
трёхсекундный control — 18 encoded frames при отрисовке сцены около 60 FPS.
Это отделяет низкую частоту Android capture/encoding path от сетевого тракта
для локального control, но не исключает remote network latency.
На PH025 reported code 10238 подтверждён, display mode остаётся **5 Hz**.
52-second viewer получил 81 packets / 470417 bytes; GPU startup и native
960×540 codec format подтверждены. Motion launch вернул execution_read_timeout,
поэтому motion FPS/input acceptance не присваивается. В stage windows есть
GL draw max 3064.61 ms и texture read max 1126.49 ms; это конкретные Android
pauses, не изолированный codec CPU benchmark. Unknown launch не повторялся;
последующий read-only snapshot — online / not_streaming, private canary не resumed.
[Allowlisted evidence](../audits/2026-10-01/PH010-PH025-NATIVE-SIZE-EVIDENCE.json).
[Workload, ограничения и command RTT](VIDEO-CADENCE-CANARY.md#сравнение-той-же-gpu-сборки-и-измерение-стадий-1-октября).

**Native codec CPU control, 04:52 UTC+5:** PH010 / 10238, одна finite private
motion Activity с подтверждённым foreground, native 960×540 / target 30 / 1.5 Mbit/s.
В десяти последовательных секундных окнах получено **63 pictures / 10 s (6.3/s)**;
selected codec — `OMX.google.h264.encoder`. Три bounded `top` snapshots показывают
`media.codec` **92/96/100% одного ядра** при двух logical CPUs (total basis 200%),
APK **8%**, включая отрисовку private canary в том же процессе; temporary su
permission broadcast самого observer также расходует CPU.
Surface swap means **154.67–160.91 ms**, texture/draw means ниже 1 ms.
Это согласуется с узким местом Android software encoding/consumer path, но не
является профилем каждого codec thread, доказательством universal CPU budget или
отсутствия remote network delay. Spans arrival/PTS **9.781/9.778 s** не показывают
рост backlog в этом окне и не измеряют абсолютную latency. Собственный viewer
закрыт; позже подтверждены launcher и `not_streaming`, global stop не отправлялся.
[Allowlisted CPU/wire evidence](../audits/2026-10-01/PH010-CODEC-CPU-EVIDENCE.json).

**Validation source `2bed596`:** настроенный APK `1.2.38-dev/10238`, SHA256
`15c2392be0d8c6e845a84234302d1ccde4b04ed41d3f8b97c38fd76f73c00381`,
8459015 bytes, прежний pilot package/certificate. Обе configured debug flavors:
746 tests, 745 passed / 1 skipped / 0 failures / 0 errors; dev debug compiled.
GitHub Backend run 36784890226, Frontend 36784890290, Android 36784890424 —
success этого source; preview guard passed, deploy skipped. Source/default,
configured artifact, installed version и acceptance остаются разными gates.

**Fleet observation 03:44:07 UTC+5:** 19 records, 14 online / 5 offline;
у online есть версии 1.2.22/30/32/34/36/38. Следующий PH025 update подтвердил
10238 отдельно. Следовательно, утверждение «весь парк на новейшем APK» неверно;
массовая OTA и latest aliases этим этапом не изменены. Presence и этот конечный
срез не заменяют длительный soak, 23 ожидаемых устройства или video acceptance.

**Operator follow-up:** владелец подтвердил LDPlayer limit 5 FPS и выбрал 10.
Read-only PH025 check **04:00:55 UTC+5** всё ещё сообщает mode 5 Hz, APK 10238
online; restart/application нового host limit не подтверждены. Новый целевой
профиль 10 FPS не принимается как прежнее требование 20–30 source pictures/s.
Encoder target 30 не устраняет source limit. Владелец также подтвердил отсутствие
Android Back/Home/Recents navigation в активной карточке. Source `c547f5d` добавляет
эти кнопки и Menu через acknowledged SHELL, без новой APK. Первое frame/current
WS gate, pending lock, abort/late callback и unknown без автоповтора покрыты
регрессиями; в той версии pointer input на stale video был заблокированным
(исправлено для single-device в b9a3f29, см. актуальный блок выше). Native
PH025 / 10238: подтверждён foreground finite private Activity, одна Back-команда
дала successful receipt за **1672 ms**, read-only dump подтвердил возврат launcher.
Это не native acceptance всех клавиш и не browser input-to-visible measurement.

**Навигация / source и runtime `c547f5d`:** 73 frontend suites / **567 tests passed**,
types/targeted ESLint passed, isolated production compile passed. GitHub frontend
tests/types/build success; Android/backend jobs на момент UI switch ещё шли.
Предыдущий Android source `2bed596` уже прошёл все обязательные jobs. Локальная
компиляция/current listeners и CI source — разные доказательства.

**Read-only input controls, 04:21 UTC+5:** по два full API round trip на command/
device: PH010 `true` 437/250 ms, `input` без аргументов 500/500 ms; PH025 `true`
1125/203 ms, `input` 391/390 ms. Последняя команда печатает usage, не вводит событие;
ни Activity, ни viewer этим control не запускались. Установленный `/system/bin/input`
на обоих устройствах запускает Java через `app_process`/`input.jar`; startup имеет
стоимость, но эти измерения **не** локализуют весь latency в нём. Изменчивость даже
`true` требует разделить доставку, очередь, Android выполнение и receipt. Двух
samples недостаточно для p95/SLO; 1672 ms Back не объявляется постоянным ping.
Остаются отдельные Android capture/encoding и input-to-visible latency gates.

**Redis CI counterexample / source `eda41c7`:** navigation frontend/Android CI
`c547f5d` прошли, backend test-suite step прошёл, но последующий isolated AOF/write
probe получил `OOMKilled` при 2 GiB. Source ceiling повышен до 3 GiB при прежних
512 MiB dataset/eviction/persistence. 8 Compose regressions и unchanged native
workload на том же immutable Redis 7.2.16 config прошли локально. GitHub Linux
[run 36791986031](https://github.com/RootOne1337/sphere-platform/actions/runs/36791986031)
тоже прошёл: **2145 tests / 0 failures / 0 errors / 15 skipped**, unchanged
Redis AOF/BGSAVE/write/restart probe successful, kernel peak **1599836160 B**,
6532 keys и marker сохранились, own container удалён, `OOMKilled=false`.
Frontend/Android CI этого code head тоже success. Installed pilot Redis остаётся 1536 MiB, не
перезапускался/не resized. Это отдельный memory risk; его связь с текущим video/
input latency не установлена. [Срез и границы](REDIS-MEMORY.md#новый-counterexample-1-октября-2026),
[allowlisted evidence](../audits/2026-10-01/REDIS-AOF-HEADROOM-EVIDENCE.json).

### Одиночный поток: картинка подтверждена, плавность остаётся открытой, 1 октября

Оператор подтвердил картинку на `3015`, но сообщил слайд-шоу в «Карточке
устройства», примерно PH025. Требование — 20–30 FPS при движении на слабом
Android emulator (reported 2 CPU / 2 GB / 540p). Наличие H.264 не заменяет FPS
acceptance. В **01:08:48–01:09:24 UTC+5** finite wire canary PH025
(installed **1.2.34-dev**) получил **26 pictures / 28 packets / 395258 bytes**;
capture/render/encoder=26, local queue accepted=28 и viewer получил те же bytes,
rejected/errors/encoded FPS drops=0. Короткая шторка возвращена, pixels не
сохранялись, закрыт только собственный viewer. Это packet-delivery evidence,
не continuous-motion или browser draw benchmark. Недостаток кадров начинается
до encoder в этом срезе; Cloudflare/Tuna packet loss им не доказан.

Отдельный source defect исправлен: FPS gate перенесён с encoded H.264 output
на raw ImageReader frames перед CPU copy/encoder submission. Два regressions
failed до fix и проходят после. Новый optional raw skip counter отделён от
legacy encoded drops; older APK без поля остаётся unknown. Оба Android debug
flavors — **722 tests каждый: 721 passed / 1 skipped**, dev debug compiled;
backend targeted **40 passed**, frontend **71 suites / 537 passed**, TS/targeted
lint passed. 20–30 FPS этими тестами не удостоверены. Backend CI `a907736`
остановился на generated OpenAPI: optional counter отсутствовал в schema.
Экспорт воспроизвёл stale check; schema обновлена, локальный `--check` проходит.
Frontend и Android CI этого source success. Следующий head проверяется отдельно.

**Адресное OTA PH025:** настроенный APK **1.2.35-dev / 10235**, source
`a907736`, SHA256 `a8b92f1f3e00859378f1ea45da87ed08c4906dfe300b32cac5ae07aa4981628f`,
подписан прежним pilot key. Один grant вернул **completed** в **01:27:44 UTC+5**
с installed code 10235 и recovery-after-process-restart. Свежий JSON readback
**01:39:53**: PH025 online, 1.2.35, heartbeat 01:39:47, not_streaming после
закрытия нашего viewer. Опубликован только `android-canary`, global channel,
GitHub APK/config aliases и остальные устройства не заменялись.
Последующий короткий motion probe получил 20 picture packets / 22 packets /
251168 bytes. Его telemetry snapshot был stale и не доказывает совпадение
всех стадий. Оператор после обновления вновь подтвердил слайд-шоу на PH025.

**Browser FPS source:** независимые last-second receive/draw counters,
монотонное окно, idle decay до zero, reset при новой session и bounded 1024
events с явным lower-bound marker. SPS/PPS и invalid packets не считаются
pictures; failed render не считается draw. Пять новых tests и полный frontend
**71 suites / 542 passed**, TypeScript/targeted lint passed. Это fixtures,
не native GPU/WebCodecs benchmark. UI `4c79ef6` реально переключён на 3015
в 01:52:06, но browser/native FPS acceptance остаётся открытой. Все обязательные
GitHub backend/frontend/Android jobs source `4c79ef6` success; preview deploy skipped.

**GPU follow-up:** source 1.2.36 содержит opt-in debug SurfaceTexture/EGL bridge,
default false, без CPU Bitmap copy; startup fallback только до создания первого
VirtualDisplay. Native resource ownership, producer timestamp gate и stop
проверяются отдельно. Четыре resource tests failed на encoder baseline `4c79ef6`,
после fix проходят; targeted streaming suite passed. Полные debug flavors:
**735 tests каждый, 734 passed / 1 skipped / 0 failures / 0 errors**, dev APK
compiled, 4m. Configured GPU APK установлен на PH025; native performance gate
не прошёл (подробности и display comparison ниже). Finite 30-second motion activity существует только в debug
source set, private/без recents, с auto finish. Контракт и источники:
[GPU/video canary](VIDEO-CADENCE-CANARY.md).
Подробности, невалидный первый motion probe, неизменённые network queues и
открытый reference-loss risk: [APK/video audit, VIDEO-I04/I05](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md).


**GPU native canary, 1 октября 02:29:44–02:30:36 UTC+5:** настроенный debug
APK `1.2.36-dev / 10236`, source `5118525`, SHA256
`301097dc1382a966df29ff3a793fcc5e896478cd02de1d9f6743b7426ff52108`,
8451575 bytes, прежний package и pilot signer. Один адресный OTA grant PH025
подтвердил completed + online 10236; global android channel/aliases не менялись.
GPU startup marker найден, CPU fallback marker отсутствует. Private debug
activity запущена один раз с `am start -W`, Status: ok; auto-return 30 s.
За 52 s viewer получил 67 packets / 460618 bytes, в выбранных 20 s движения —
44 picture packets (2.2/s в среднем). Секундные окна включают интервалы без кадров;
≥20 FPS gate **failed**, читаемость/browser draw не проверены. Это не доказательство
loss-free всей цепочки: приёмка по GPU marker и wire metadata, один heartbeat
snapshot capture=43 / rendered=42 / encoded=42 / WS accepted=46, rejected/errors=0,
FPS stages=3. Поздние API samples повторяют тот же snapshot с age 3–12 s.

**Ключевое различие источников, read-only `dumpsys display`:** PH010/011
(локальные по оператору) сообщают 960×540, ~60 Hz; PH022/025 (удалённые)
960×540, **единственный mode 5 Hz**, vsync deadline 201 ms. PH023 offline,
её capability не получена. Это platform-reported capability, не measured
animation FPS; тем не менее настоящий 20–30 unique pictures/s source при таком
режиме не подтверждён. LDPlayer имеет отдельный FPS limit многооконности;
его фактическая host setting требует проверки оператора. Host settings/APK
не пытаются обходить незадокументированными properties, новые картинки не
генерируются дублированием. Нужно изменить лимит на **одном** canary, повторить
capability readback и тот же motion test; default GPU/mass rollout остаются закрыты.

`gfxinfo` накопленного процесса: 59 frames, 39 janky (66.10%), p50 200 ms,
p90 2950 ms, p99 4100 ms. Это не изолированная статистика только activity.
`cpuinfo` показывает исторический accounting window, 23% iowait и load 7.26;
не трактуется как live CPU Windows/причина stalls. Дополнительные многосекундные
паузы остаются не локализованы. MediaCodec dump пуст — codec implementation
не установлена. Wire timestamp сейчас callback wall clock, не producer PTS;
разделение capture/encode/queue latency требует отдельной instrumentation.

[Sanitized evidence](../audits/2026-10-01/PH025-GPU-CANARY-EVIDENCE.json) содержит
artifact facts, все секундные окна, dated heartbeat samples и comparison;
без video pixels, credentials, root logs и signed grant. Source `5118525`
завершил обязательные GitHub backend/frontend/Android jobs success; preview
deploy skipped. Android configured build повторно выполнил по 735 tests обеих
flavors (734 passed / 1 skipped), compile и artifact checks прошли. Эти тесты
не меняют неуспешный native performance gate.

### Видеопоток: ownership ввода — source follow-up, 1 октября

Четыре pointer regressions failed на `356bd35`: ложный swipe при смене размеров
кадра и управление gesture другим pointer. `DeviceStream` сохраняет pointer ID
и geometry, отменяет gesture при resize/stale/reconnect/config reset и не
переносит held input в восстановленную session. Lost capture прекращает gesture;
обычные same-size кадры не мешают input. Полный frontend **71 suites / 536 tests
passed**; TypeScript и targeted ESLint passed (legacy config warning сохранён).
Подробности и границы fixtures:
[APK/video audit, VIDEO-I03](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md).
Source **`3d082c1`** compiled из isolated Git archive, production frontend CI
tests/types/standalone build success. Обычный Next output для local start
использован только в private archive, repository config не менялся. В **00:24**
восстановлен `3015` с UI `3019`, Next PID `26200`, relay PID `37264`;
backend/APK/tunnels не заменены. API acceptance **00:26:04** и blocked visual
gate описаны выше. API ответы не выдаются за проверку gestures/picture в браузере.
Source **`3d082c1`**: все обязательные GitHub backend/frontend/security/Android
jobs success; preview deploy skipped. 250 относительных documentation targets
проверены, missing 0; diff whitespace check clean.
Native dimensions, Android-side mapping и отдельный fleet snapshot mode не
закрыты этим browser fix.

### Android root availability — source follow-up, 30 сентября

На `e3dc143` три regressions воспроизвели IOException ещё при construction
компонента команд без `su`. Root process теперь создаётся только по явному
privileged action; startup и unused close не запрашивают root. Missing root
не превращается в успешное действие. Добавлены проверки idempotent close,
следующей explicit action, dead session и ошибки получения stdin.
Input outcome unknown по-прежнему не replayed. Подробнее:
[APK/video audit, APK-I04](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md#apk-i04--p1--отсутствие-root-не-должно-срывать-запуск-агента).
Полная local проверка 3m 33s: dev/enterprise debug **719 tests каждый,
718 passed / 1 skipped / 0 failures / 0 errors**, `assembleDevDebug` completed.
Установленные APK не заменены; startup/root-grant и постоянные stdout/stderr
session требуют отдельных device/process gates.
Source **`356bd35`** завершил обязательные GitHub backend/frontend/security/
Android jobs success; preview deploy skipped. Timestamp CI observation —
1 октября, source commit создан 30 сентября 23:56 UTC+5.

### UI hierarchy — source integrity/ownership fix, 30 сентября

Новый source follow-up удаляет общий `/sdcard/sphere_ui_dump.xml` и глобальный
`killall uiautomator`. Dump сериализован, пишет private per-request cache file,
читает до EOF через bounded runner и удаляет файл в finally. XML проходит
DTD/external entity rejection и SAX depth/node preflight перед DOM; один
validated DOM используется всеми XPath candidates одного poll.
Полные dev и enterprise debug suites: **713 tests каждый, 712 passed / 1 skipped,
0 failures / 0 errors**; dev debug compile completed. Подробнее:
[APK/video audit](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md).
Real Android root descendants/SELinux/private path cleanup остаются canary gate;
новая APK не установлена, hierarchy API и визуальный tree/outline ещё не включены.
Source **`e3dc143`**: все обязательные GitHub backend/frontend/security/Android
jobs success; preview deploy skipped. CI не заменяет перечисленные device gates.

### Android process runner — source fix, 30 сентября, 23:12 UTC+5

После source audit добавлен bounded concurrent stdout/stderr runner для shell,
execution/read deadline и cancellation cleanup напрямую принадлежащего процесса.
Oversize output не возвращается как успешный усечённый результат; неопределённый
исход останавливает DAG без retry/fallback даже при `fail_on_error=false`.
Command/stderr больше не включаются в ошибки shell общего журнала.
Два новых pipe tests failed на baseline, после fix command suite passed.
Полные dev/enterprise debug suites: **702 tests в каждом, 701 passed / 1 skipped,
0 failures / 0 errors**; `assembleDevDebug` completed. Это local compiled source,
не production-signed/настроенный OTA артефакт; установленный парк не обновлялся.
Android `su` descendants и root timeout cleanup ещё требуют device canary.
Source **`3148678`** завершил обязательные GitHub backend/frontend/security/
Android jobs success; preview deploy skipped. Этот CI относится к shell fix,
а не к последующему hierarchy follow-up и не заменяет device acceptance.
Продуктовый контракт single-device continuous/native-aspect video, fleet snapshot
previews и inspect-only XPath зафиксирован в
[APK/video audit](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md).
Остальные geometry/profile/hierarchy/log gates не закрыты этим shell fix.

### Service inspector — сохранение выбора через потерю API, 30 сентября, 22:21–22:29 UTC+5

Source follow-up исправляет подтверждённую UX ошибку: выбранная проверка
сервиса терялась, когда ошибка API или пустой результат фильтра размонтировали
inspector. Явный выбор теперь хранится в странице. Во время ошибки cached
HEALTHY и details по-прежнему скрыты; после восстановления используется только
новый ответ. Если выбранного ID нет в свежем списке, показывается существующая
проверка, без старых деталей отсутствующего сервиса. Выбор сохраняется в пределах
открытой страницы, не между logout/tenant или полной навигацией.

Два page-level regressions **failed на baseline**, после исправления **70
monitoring tests passed**, полный frontend **71 suites / 528 Jest tests**,
отдельный Node relay test passed; TypeScript и targeted ESLint passed (legacy
config warning сохранён). Ошибка API
воспроизведена через настоящий React Query lifecycle в тесте, без остановки
живого backend. GitHub frontend tests/types/production standalone build source
`3132afc` success. Isolated Git archive compile exit 0, loopback Next `3018`
и guarded switch собственного relay `3015 → UI 3018 / API 18080` приняты.
Browser выбрал PostgreSQL, скрыл inspector через пустой фильтр и восстановил
PostgreSQL после очистки: новые probe timings, pool 10 / checked out 1, ошибок
console в просмотренном интервале нет. Live API outage этим browser опытом не
симулировался; его gate покрыт page-level regression. Фактический viewport
647×884; это не повторная desktop-width приёмка. Старые Next PID/start dates
сохранены, backend/APK/туннели не перезапускались. Login/auth-me через `3015`
подтверждён; отдельный finite fleet readback 22:29:40 — 19 total / 14 online /
5 offline / 0 connecting. Private receipts:
`.local-pilot/observability-20260930/3132afc-preview-switch-receipt.json`.

Все обязательные GitHub jobs code source **`3132afc`** завершились success:
backend **2124 passed / 15 skipped / 5 warnings**, **695.96 s**; packaged
bootstrap, Ruff/mypy, security, RLS и Alembic single head; frontend **71 suites /
528 Jest tests**, отдельный Node relay test, types и production standalone build.
Android unit/signed smoke прошёл с CI signer; это не новая production-signed или
установленная APK. Preview deploy skipped. Этот результат относится к code source,
а CI последующих documentation-only commits учитывается отдельно.

### Android inspection / video modes — отдельный source-аудит 30 сентября

Новый [аудит APK, видео и UI-инспекции](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md)
связывает actual code paths, текущие limits и следующий план приёмки. Найдены
root process output/read budget и dump ownership gaps (source follow-ups выше); nominal log retention
не гарантирует лимит одной записи или счётчик потерь. Grid/detail используют
один H.264 тракт, demand profiles ещё не реализованы. XPath в DAG есть; protected
hierarchy endpoint и визуальный tree/overlay отсутствуют. Готовые OpenATX/Appium/
AndroidX решения изучены по официальным источникам, лицензии отмечены; чужой
код не добавлен и обязательный PC Agent/host ADB не введён. Это открытые задачи,
не принятый новый APK и не доказанная причина исторических обрывов видео.

### Dependency advisory — source/runtime follow-up 30 сентября, 21:11–21:44 UTC+5

Повторный security job docs source `60d9698` сообщил CVE-2026-101918 в
PyJWT 2.14.0. Закреплена 2.15.1, pinned baseline воспроизвёл raw RecursionError;
после исправления 79 auth/WS/service tests, dependency-aware types, Ruff/pip
check и полный requirements audit passed. Cache warnings audit сохранены.
Подробные primary sources, область воздействия и границы source/runtime — в
[dependency follow-up](../audits/2026-09-30/PYJWT-ADVISORY-FOLLOW-UP.md).
Source **`85c8014`** прошёл обязательные GitHub jobs: Linux backend **2124
passed / 15 Windows-only skipped / 5 warnings**, **703.21 s**, coverage
**77.87%**; frontend **71 suites / 526 Jest tests**, отдельный Node transport
test, types/build; security, Ruff/mypy 219, RLS, Alembic single head, packaged
image bootstrap и Android smoke/unit success. Preview deploy skipped — это
не установленная или production-signed APK.

Exact image **`sha256:b2a0d4bec434c127f522fec5ec8eb3a9c5cc35682b40759acf6c1ee6880e4ccd`**
прошёл fresh packaged PG/Redis application lifecycle и две multiprocess серии
по **160 known requests**: четыре workers, child replacement, no duplicates,
graceful master cleanup/fresh registry. Дополнительный recycle loop в этом
dependency проходе не запускался; `scrape_max_ms: 0` fixture не является новым
замером latency. Более ранние ресурсные измерения ниже сохраняют свои source.

Сверка installed packages выявила **два**, а не одно изменение: PyJWT
2.14.0 → **2.15.1** и cryptography 50.0.1 → **50.0.2**, разрешённое существующим
`cryptography>=42.0.0`. [Официальный changelog](https://cryptography.io/en/latest/changelog/#v50-0-2)
описывает обновление wheel OpenSSL до 4.0.3. Подтверждён именно проверенный
immutable image; полный dependency lock/reproducible resolution остаётся
отдельной задачей. Из environment изменился только SPHERE_BUILD_SHA.

Backend-only rollout в 21:37:50 сохранил DB head `20260921_watchdog_stop`,
neighbour IDs/images/StartedAt и OTA/APK hashes. В работающем контейнере
подтверждена PyJWT 2.15.1. Обычный login/auth-me и access token, выданный до
переключения, работают; браузерная сессия и Grafana продолжают работать.
Private receipts: `.local-pilot/jwt-20260930-live-rollout/`.

**Результат восстановления не сглажен:** первая минутная проверка
21:38:10–21:39:10 закончилась failure критерия непрерывности: online
14 → 11 → 14 → 12. В первоначальном readback все 14 session dates уже были
новее запуска API: объяснение этого среза исключительно старым presence cache
не подтверждено. Следующая ограниченная read-only проверка потребовала
`connected_since >= backend StartedAt` и heartbeat младше 45 s: семь срезов
21:40:40–21:41:40 подтвердили 14 новых sessions / 14 fresh heartbeat при scope
19. Первый failure receipt сохранён отдельно. Это восстановление после
перезапуска, не доказанная непрерывность или причина старых сетевых обрывов.

В записанном backend log interval: 21 agent connects / 7 disconnects, 26
`ota_recovery_receipt_unrecognized` от трёх устройств (17 failed: 8 timeout,
9 download_origin_rejected; 9 completed), две send warnings. Raw RecursionError,
InvalidSignatureError и traceback в этом журнале не найдены; это не гарантия
отсутствия всех ошибок. Старые OTA receipts не превращены в ACK и команды
обновления не повторялись. Контекст и следующий отдельный gate —
[remote connection / OTA audit](../audits/2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md).
Это не доказанная причина Android stream/OTA нестабильности.

### Service probe inspector — принятый UI/API rollout 30 сентября, 20:49–21:05 UTC+5

Карточки сервисов теперь раскрывают ограниченный контракт `details`: SELECT 1 /
размер и занятость пула отвечающего API-процесса; Redis PING / память из INFO
memory; filesystem / свободно/объём/занято. Uptime подписан как возраст
API-процесса, а не uptime PostgreSQL/Redis. Время отсутствует отдельно от нуля;
нулевой timing ошибки/timeout не показывается как успешная быстрая проверка.
Произвольные error strings и nested values не выводятся: могут содержать
credentials. Unknown/negative/non-finite поля не превращаются в ноль.

Найдена отдельная ошибка производителя: HealthService читал `connected_clients`
из INFO memory и при отсутствии поля возвращал 0; отсутствующий `used_memory`
тоже становился 0. Source перестал генерировать эти значения. Правильное число
клиентов уже берётся через INFO clients в существующей общей Redis card.
Backend и frontend `4024ccf` приняты в local pilot: Redis probe возвращает
PING/настоящую память без ложного clients поля; отдельная общая Redis card
показывает клиентов из INFO clients. Browser подтвердил pool 10 / checked out 1,
disk free/total/usage и обновление probe timings. Выбор сервиса сохраняется при
обычном refresh; после полной потери API и восстановления inspector вернулся
к первому сервису. Сохранение выбора через outage остаётся отдельной UX задачей.

Доказательства: три новых UI tests failed на прежнем компоненте; после исправления
**19 targeted UI tests passed**, TypeScript/targeted ESLint passed (legacy warning).
Два новых Redis tests failed на producer baseline; после исправления **73 monitoring
tests passed / 1 warning**, Ruff и dependency-aware mypy **219 modules clean**.
Полный GitHub CI source `4024ccf`: frontend **71 suites / 526 Jest tests**,
отдельный Node transport test, types/build success; backend **2120 passed / 15
Windows-only skipped / 5 warnings**, 667.69 s, coverage **77.87%**. Lint, security,
RLS, Alembic Single Head, packaged image bootstrap и Android smoke/unit job
success; preview deploy skipped. Это не production signer или установленная APK.

Exact pilot image **`sha256:438bdd9d82e4e15a95dd815089a7217ccc15b75409add8e00b06bc0a37cc9c7e`**:
fresh PG/Redis application-process lifecycle passed. Две серии по 4 child
replacements / 164 known requests каждая: четыре workers, no duplicate samples,
graceful master cleanup, fresh registry после container restart; max scrape
**5.10 ms**. Это ограниченная fixture, не high-load/soak.

Rollout заменил только backend image; env diff только SPHERE_BUILD_SHA. Readiness
ready, DB head `20260921_watchdog_stop` до/после, neighbour IDs/images/StartedAt и
OTA/APK hashes совпали. Private receipts:
`.local-pilot/probes-20260930-live-rollout/` и
`.local-pilot/observability-20260930/4024ccf-preview-switch-receipt.json`.
Текущий маршрут `3015 → UI 3017 / API 18080`; старые Next 3014/3016 сохранены.

Перед rollout было 14 online; первый post-rollout срез 21:03:54 — 11. Baseline
14 устройств восстановился с session timestamps и свежими heartbeat к 21:04:49;
семь срезов до 21:05:49 сохранили 14 / 5 при scope 19. Live scrape: 4 workers,
16 mmap files / 1 MiB, 236 samples, без дублей. Console errors в просмотренной
вкладке не зарегистрированы. Браузерная проверка выполнена при фактическом viewport
647×884; запрошенный override 1440×900 не применился, поэтому desktop-width QA
этим опытом не считается пройденной. Скриншоты и raw telemetry остаются приватными.

### Исторический UI rollout и dashboard provisioning — 30 сентября, 18:55–20:23 UTC+5

Frontend **`b650c03`** собран из committed Git archive; isolated production
compile exit 0. Владелец запустил Next на `127.0.0.1:3016`, после проверки
ownership переключён только принадлежащий preview relay:
`3015 → UI 3016 / API 18080`. Прежний Next `3014` сохранён. Private receipt:
`.local-pilot/observability-20260930/b650c03-preview-switch-receipt.json`.
Существующие operator credentials подходят: login через `3015` вернул 200.
Пароль не менялся; direct `3016` не является полным UI/API ingress.

GitHub Backend/Frontend/Android checks source `b650c03` завершились success;
preview deploy skipped. Frontend: **71 suites / 523 Jest tests**, отдельный
Node transport test, types/build passed. Local monitoring: **19 targeted
passed**, TypeScript и targeted ESLint passed; legacy eslintrc warning остаётся.

Browser подтвердил **WEB b650c03a / API 1ac06acb**, подключённые события,
обновляемый Prometheus срез и 10-секундное API обновление. Network card
показывает измеренную сумму TX+RX и скорость по двум срезам отдельно от
неизвестного числа туннелей. Устаревшее утверждение о worker-local counters
убрано: coverage warning относится к отсутствующим панелям RPS/p95/CPU/fleet.
Разные WEB/API SHA обозначают provenance, не отказ сервиса.

**Отдельный подтверждённый дефект Grafana:** новый dashboard JSON был виден
в Docker bind mount, но Grafana продолжала отдавать старую сохранённую панель.
Provider теперь использует `updateIntervalSeconds: 30`: polling вместо
filesystem watch, события которого могут не доходить через Docker bind mount.
Основание — [официальный provisioning contract Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/).
Один guarded restart собственного Grafana выполнен в **19:04 UTC+5**;
image/auth не изменились, соседние контейнеры сохранили ID/image/start time,
Grafana healthy. Browser iframe в **20:23** подтвердил новый текст и реальные
графики. Basic auth не включался, права bridge не расширялись. Private receipt:
`.local-pilot/observability-20260930/dashboard-provisioning-restart-receipt.json`.
Будущая смена dashboard файла без restart ещё не проверялась отдельной мутацией.

Actual browser screenshots сохранены приватно:
`.local-pilot/metrics-20260930-live-network-b650c03.png` (19:14) и
`.local-pilot/metrics-20260930-live-grafana-b650c03.png` (20:23).
Карточки сервисов пока не раскрывают имеющиеся API probe `details`: следующий
UI gap, не отсутствующий ответ backend. Resource budget, длительный fleet soak,
OTA и 20–30-device stream + scripts gates остаются открытыми.

### Pilot rollout и реальные данные — 30 сентября, 18:09–18:33 UTC+5

После завершения исполняемых GitHub checks source **`1ac06ac`** пересоздан
только service `backend` проекта `sphere-pilot-20260911`, без build/dependencies
при переключении. Развёрнут проверенный image
**`sha256:69da2cd08f09e151f0fd126a4ae2a001f2bb468f44a8735ff919d97a1194cc3a`**.
Revision label/env и API build stamp совпали; контейнер healthy, readiness 200.
Alembic head **`20260921_watchdog_stop`** совпал до/после: миграция не требовалась.
Соседние container IDs/images/start times, OTA-каталог и hashes APK не изменились.
Из environment поменялся только `SPHERE_BUILD_SHA`. Старые `sphere-platform`
и `sphere-tunnel` не изменялись. Private rollout receipt:
`.local-pilot/metrics-20260930-live-rollout/applied.json`.

**Проверки принятого backend source:** GitHub Backend/Frontend/Android checks
успешны; deploy job skipped. Linux backend suite — **2118 passed / 15 skipped /
5 warnings**, **579.94 s**, coverage **77.80%**. Skips — Windows-only проверки,
не пропущенные отказы Linux. Dependency-aware mypy — **219 files clean**, Ruff,
security medium/high gate, RLS, Alembic single head и packaged bootstrap прошли.
Windows full suite source `dac2319` — 2123 passed до добавления десяти lifecycle
tests; это отдельный результат, не запуск Windows suite на конечном head.
Exact image canary: две серии по 16 replacements, **176 known requests** каждая,
четыре workers, totals без дублирования, cleanup/restart; max scrape **22.71 ms**
при параллельной PG/Redis probe. Fresh packaged PostgreSQL/Redis lifecycle passed.
Длинный load/soak этими проверками не выполнен.

**Живой API и браузер:** monitoring metrics/nodes без авторизации теперь получают
**401**; авторизованный ответ содержит `observedAt`, реальные resource counters
и четыре probes (API/PostgreSQL/Redis/disk) с `details`. В `3015/monitoring`
видны RAM backend cgroup **546.5 MiB / 2 GiB**, Redis HEALTHY и TX/RX counters;
сетевая скорость появляется только после двух валидных срезов. Это значения
backend-контейнера, не всей Windows-станции и не Android. Load average не CPU %.
В live registry — **4 workers, 16 mmap files / 1 048 576 bytes**, один owner
directory, duplicate samples нет. Включён **128 MiB tmpfs**. Общие RPS/p95 панели,
exporters, Loki, tracing и tunnel/Android SLO этим rollout не добавлялись.

**Парк:** фактический pre-rollout snapshot содержал **12 online**, хотя срез
17:26 показывал 14. После переключения все 14 устройств операторского baseline
восстановились. Семь API-срезов **18:22:21–18:23:21 UTC+5** показывают 14 online /
5 offline, presence доступен, даты сессии и свежие heartbeat возвращаются.
Browser в 18:33 подтвердил online filter **14 из 14**, scope **19**, длительность
текущей сессии и версии Android-агента. Это наблюдение конечных срезов, не
доказательство непрерывной связи между ними или устранения причин прошлых
обрывов. Версии APK смешаны; remote OTA, video и автономные scripts этим
read-only follow-up заново не принимались.

**Найден и исправлен отдельный отказ preview:** прежний relay завершился при
`Unhandled 'error' event` / `read ECONNRESET` на Socket во время восстановления
соединений. Next `ea7f9cf` продолжал работать. Новый
[`preview_relay.cjs`](../../scripts/pilot/preview_relay.cjs) обрабатывает ошибки
HTTP/upgraded sockets, закрывает только ошибочную связь и отвечает 502 при
недоступном upstream, без повторения команд. Он слушает только loopback и
использует прежние `3014` UI / `18080` API. Relay заменён после проверки,
что прежний процесс завершён; Next владельца не остановлен. На Windows
транспортный test прошёл для client/upstream RST с данными в полёте, unavailable
API и запрета replay. Исходный редкий crash синтетически не воспроизведён:
основание исправления — actual stderr, passing test подтверждает заявленные
сценарии, а не универсальную безотказность. Linux gate добавлен в frontend CI.

**Расхождения UI до переключения в 18:55:** `WEB ea7f9cf7` и `API 1ac06acb` имеют разные SHA,
поэтому header показывает MISMATCH; это provenance, не измерение API health.
В этой старшей frontend-сборке ещё есть устаревшее предупреждение о worker-local
counters и неоднозначное «Не измеряется» над известными TX/RX (относится к числу
туннелей). Эти labels исправлены rollout `b650c03` выше; сам факт backend
aggregation не означает готовность всех графиков. Growth counters внутри
срока master, capacity alerts/maintenance, длительная fleet stability и финальный
20–30-device stream + scripts acceptance остаются открытыми.

Сырые receipts, operational identity, credentials и полные журналы остаются в
private `.local-pilot`. Новые screenshots показывают фактический browser runtime.

### Проверка graceful worker replacement — 30 сентября

CI source `c2bf178` прошёл lint, security, frontend и RLS, но packaged-image
canary остановился на `ConnectionResetError` во время намеренного SIGTERM
worker. Сохранённый CI receipt первой серии подтвердил totals **176**, четыре
workers и cleanup; вторая серия прервалась при polling `/identity`. Такой reset
не доказывает поломку production API и не считается успешной приёмкой.

Canary теперь допускает сетевую ошибку только при чтении `/identity`/`/metrics`
в пределах исходного **20 s** deadline замены. HTTP errors не скрываются;
запросы `/canary/*`, для которых проверяются точные totals, не повторяются.
После правки два локальных прогона с **64 replacements / 224 requests** каждый
прошли, max scrape **15.79 ms**. Это исторический срез до rollout; успешный CI
и переключение backend `1ac06ac` записаны в разделе выше.

### Dependency-aware type gate — source dac2319, 30 сентября

Полный mypy **2.3.1** с установленными backend dependencies теперь проходит
**219 source files**, включая `check_untyped_defs`. Исправлены типы SQLAlchemy
predicate/sort expressions, ASGI Message и Pydantic response boundaries;
nullable script/device ID проверяются до записи регистрации/фарм-задачи.
Три новых PostgreSQL regression tests воспроизвели ошибки на исходной версии;
после исправления **372 tests passed / 1 deprecation warning** в затронутых
device/WS/VPN/orchestration сценариях. Общий suite завершился:
**2123 passed / 5 warnings**, **596.50 s**, exit **0**, без load/soak и coverage.

CI lint теперь устанавливает backend dependencies и выполняет `pip check`,
поэтому отсутствующие импорты больше не превращают эти границы в `Any`.
Версии инструментов закреплены: Ruff **0.15.2**, mypy **2.3.1**.
Это source validation; live backend/3015/APK на этом этапе не переключались.
Структурный protocol VPN command publisher сохраняет прежнее поведение:
существующий stub возвращает `False`, реальная доставка kill-switch не
объявляется реализованной этой правкой.

### Ресурсный lifecycle метрик — source canary 30 сентября

На прежнем packaged image `e3b4fe7` повторены два независимых прогона с
**64** заменами workers каждый. После каждого сохранены точные HTTP totals,
четыре live workers и отсутствие duplicate samples. Registry вырос с
**18 files / 1 179 648 bytes** до **146 files / 9 568 256 bytes**; прирост
**128 KiB на worker replacement**. Максимальный scrape — **21.62 ms** в
изолированной fixture с 1 CPU / 384 MiB. Это измерение конечной synthetic
нагрузки, не production performance SLA.

Новый entrypoint маркирует private registry владельцем/master PID. `on_exit`
проверяет путь, marker, владельца и отсутствие live children, затем удаляет
только свой каталог. Неподтверждённый/чужой каталог сохраняется. Production/full
Compose ограничивает `/tmp/sphere-metrics` отдельным **128 MiB tmpfs**;
SIGKILL остатки исчезают при остановке контейнера. Пока master работает,
counter/histogram files сохраняются: tmpfs **не** делает рост бесконечно безопасным.
При заполнении нужны controlled maintenance/capacity alerts; многосуточный
высоконагруженный budget ещё не принят.

**188 monitoring/deployment tests passed / 1 warning** для нового lifecycle.
Source **`aac52c2`** принят в packaged image
**`sha256:db4b2e125151b4440c1c3c43141178decdf0f8c125b2be5a86da34db942b5ed9`**:
две серии по 64 replacements, **224** known requests на серию, max scrape
**15.45 ms**, сохранение totals/live gauges и zero start нового master.
Отдельный secondary master подтвердил cleanup после graceful shutdown **без**
остановки контейнера; соседний active master и operator data сохранились.
После SIGKILL directory остался и исчез после container restart, как заявлено.
Actual image mypy **219 files passed**; packaged PostgreSQL/Redis runtime probe
прошёл с exit 0 и ownership-checked cleanup. Private receipts:
`.local-pilot/metrics-20260930-lifecycle-{image,runtime}-evidence`.

Live preflight: DB Alembic head **`20260921_watchdog_stop`** совпал с source;
schema migration для этой версии не требуется. Pilot backend по-прежнему
`40357ca`, без нового metrics tmpfs. В browser на `3015` **17:26 UTC+5**
подтверждены **19 / 14 online / 5 offline** и реальные heartbeat; начало сессии,
scope counts/as-of и build endpoint старым API не возвращаются. Это объясняет
пустые данные нового интерфейса, а не доказывает их live rollout.
Свежий CI прежнего remote head
`59ba4c7` завершил исполняемые checks success, deploy skipped.

CI source `a99da81` выявил Bandit B108 на fixed namespace `/tmp/sphere-metrics`.
Это не создание предсказуемого tempfile: entrypoint использует private mktemp,
cleanup проверяет owner/permissions/marker. Добавлено только line-specific
`nosec B108` с объяснением, global rule не отключён. Локальный configured
`bandit -ll` gate passed (30 low findings остаются вне этого medium/high gate),
Ruff и dependency-aware mypy clean. Этот CI failure не объявлялся passed;
в момент его обнаружения backend не переключался.

### Multiprocess метрики — изолированная image acceptance 30 сентября

Source **`e3b4fe7`** собран из Git archive в production Linux-образ
**`sha256:638d609659232a9fcf8b2f4969e481b0ae1c39eba9afd4d40353c5b53593dd15`**.
В контейнере без сети и host ports проверен настоящий Gunicorn: отдельное
keepalive соединение с каждым worker подтвердило **32 × 4 = 128** requests.
После SIGTERM child hook удалил live gauges, новый worker появился, а totals
сохранились; ещё 32 requests дали **160**. После рестарта master сценарий
повторён: новый private registry начал с нуля. Дублирующихся samples нет.
Pool gauges **40/4** в этом canary заданы синтетической HTTP fixture: они
доказывают агрегацию, **не** количество connections живого PostgreSQL.

Свежая packaged PostgreSQL/Redis установка с миграциями, login/enrollment,
реальным app lifespan, audit/visibility и повтором в новом процессе прошла
отдельный runtime probe. Bootstrap image checks также passed. В обоих canary
backend source из checkout не монтировался; mounted только test adapters.
Созданные контейнеры удалены с проверкой ownership. Private evidence —
`.local-pilot/metrics-20260930-final-{image,runtime}-evidence`.

Per-device snapshots остаются в diagnostics API; production Prometheus
использует bounded fleet families. HTTP templates сохраняют параметры `{id}`,
не создают серии из произвольных URL/method и учитывают необработанные 500.
Два новых ASGI regressions воспроизвели failures на baseline. Первый полный
suite выявил четыре несовместимых UUID labels; нормализация восстановлена,
audit invariants не ослаблены. После этого **194** monitoring/stream/deployment/
audit-path tests passed. Повторный общий suite окончательного source завершился
**2120 passed / 5 warnings**, **608.15 s**, exit **0** (`tests`, без load/soak).
Coverage в этом локальном запуске не измерялось; coverage gate нового CI —
отдельная проверка. Deprecation warnings не скрыты.

Ruff **0.15.2** и targeted mypy нового кода passed; API docs `--check` passed.
Полный mypy **1.8.0** дал 17 errors в 9 неизменённых файлах, а **2.3.1** с
установленными backend dependencies — 14 errors в 8 неизменённых файлах.
Полностью чистый dependency-aware type gate не заявляется. CI последнего
remote doc head **`4dff726`** завершил все исполняемые checks success, deploy
skipped; это не результат нового source. CI lint устанавливает mypy/ruff без
backend dependencies и не заменяет этот локальный dependency-aware check.

Backend `40357ca`, APK и туннели на этом этапе сохраняют прежний runtime.
В браузере **16:42–16:45 UTC+5** `3015` подтвердил frontend `ea7f9cf`, подключённые
events, обновляемую историю **241 point**, iframe Grafana и **0 console errors**
в новой вкладке. Backend metadata endpoint отсутствует, legacy monitoring
payload отвергается; карточки не становятся здоровыми нулями. Resource retention
при долгом worker recycling ещё требует отдельной приёмки; см.
[multiprocess contract](OBSERVABILITY.md#multiprocess-contract--исходники-30-сентября-2026).

### Принята локальная сборка ea7f9cf — 30 сентября, 15:54–15:56 UTC+5

Владелец выполнил guarded updater в своей PowerShell-сессии. Receipt **15:54:12**
и readback портов: Next **5552 / 3014**, прежний relay **31892 / 3015**.
В браузере виден **`WEB ea7f9cf7`**, события подключены; Grafana открылась,
показала панели и больше не зарегистрировала OpenFeature error. В сохранённом
console остаются два исторических errors предыдущей сборки, новых после
переключения на этом canary нет. Это ограниченный browser smoke, не гарантия
отсутствия ошибок во всех страницах/сценариях.

Независимый HTTP canary прошёл через **работающий Next**, без импорта handlers
из checkout: history **200 / 241 points**, anonymous **401**, session **200**,
Grafana user **200 / isGrafanaAdmin=false**, dashboard **200 / canEdit=false**,
OFREP **200 / 378 flags**, graph query **200 / 1 frame**. История в браузере
обновлялась без кнопки refresh: **15:54:51 → 15:55:06 → 15:56:06 → 15:56:36**.
На новом source повторена mobile-проверка: document width/scrollWidth **390/390**,
iframe **350 px**; затем обычный viewport восстановлен. Сырые receipts и
desktop/mobile screenshots остаются в private pilot evidence.

**Живой адрес:** `http://127.0.0.1:3015/monitoring`; `/devices` использует тот же
реальный API. OFREP rollout gate закрыт для этого локального preview. Это не
публичный rollout и не приёмка Android OTA/автономного DAG/20–30 stream sessions.
Старый monitoring contract и multi-worker aggregation остаются P1; следующие
этапы и частоты обновления описаны в [runbook](OBSERVABILITY.md).

### Живой веб, встроенная Grafana и следующий фикс — 30 сентября, 15:39–15:49 UTC+5

Владелец выполнил подготовленный launcher после отказа автоматического запуска.
Readback подтвердил `3015` relay PID **31892**, Next `3014` PID **44804**,
source **`ab0724dbc148466d3ff3eea5c924c6447e3c3856`**. Production build этого
source завершился с exit 0, 33 application routes. Старый `3012` не заменён.
Адрес актуальной живой проверки: `http://127.0.0.1:3015/monitoring`.

В браузере подтверждены `События: подключены`, настоящий каталог **19 / 14
online / 5 offline**, версия WEB, история Prometheus **241 точка** и обновление
срезов без ручного refresh: **15:40:30 → 15:40:45 → 15:41:16 → 15:45:01**.
Встроенная Grafana показывает реальные панели; повторное открытие после
перехода в реестр успешно. На ширине 390 px document/main имеют ширину 390,
iframe 350, горизонтального document overflow нет. Screenshot и исходные
receipts сохранены приватно. Сквозной hidden-tab recovery проверен unit
regressions; этот browser receipt не выдаётся за тест реального сна компьютера.

Найдена отдельная ошибка загрузки feature flags Grafana: native OFREP endpoint
отвечает 200, а текущий `ab0724d` bridge отклоняет этот POST с **405**. Это
объясняет console initialization error; сами графики доступны. Source fix
разрешает только bulk read для namespace `default`, body до 16 KiB, с фиксированным
серверным контекстом. Browser identity не пересылается, записи запрещены.
Direct handler canary: flags **200 / 378**, graph query 200, Viewer
`canEdit=false`, dashboard write **405**, anonymous history **401**.
Полный frontend **71 suites / 523 tests passed**, TypeScript и targeted ESLint
passed; до патча regression дал 7 failures с 405. Это source/canary приёмка
следующего фикса, **не** заявление, что он уже работает на `3015`.

Архивный production build **`ea7f9cf7a457b551610e22f0cfa5bf1d8d7110d1`**
завершился с exit 0: 33 application routes, build ID
`N052OkmjfrKz_g01iCqwC`. Source config сохранён; только local artifact отключает
`output: standalone`. Сохраняются legacy lint warnings других страниц.
GitHub этого source: Frontend tests/types/build, security, lint, RLS,
production-image bootstrap и guard success; Backend Tests и Android ещё
in progress, deploy skipped. Полностью зелёный PR не заявляется.

При попытке обновить только operator-owned Next `44804` проверка процесса
остановила script **до остановки/запуска**: Windows из сессии ассистента
возвращает `CommandLine=null`, хотя PID портов и CreationDate совпадают с
launch receipt. Проверка владельца не ослаблена; подготовленный updater должен
выполняться в той же PowerShell security context, что и первоначальный запуск.
В этом срезе receipt ещё отсутствовал; последующее успешное переключение
владельцем и проверка `ea7f9cf` зафиксированы в разделе выше.

Карточки старого deployed monitoring API остаются недоступными: payload не
имеет времени/источника измерения. Новый веб не подменяет это здоровыми нулями.
P1 backend rollout и multi-worker aggregation ниже остаются открыты.

### Канал событий и актуальность веб-данных — 30 сентября, 15:33 UTC+5

Через действующий proxy `3012` выполнен отдельный read-only WS canary:
авторизованный `snapshot`, затем три `pong` за 20 s, задержки **21.0 / 5.2 /
2.7 ms**. Тот же API-срез: **19 / 14 online / 0 busy / 0 connecting /
5 offline**. Это проверка доступности канала, не длительный soak и не
приёмка стримов всего парка. Сырые receipts и credentials остаются приватными.

В исходниках исправляются конкретные пробелы: проигнорированный reconnect
snapshot без REST reconciliation, отсутствие обновления Dashboard и смежных
таблиц по task events, отсутствие watchdog молча сломанного WS, пересоздание
канала при изменении callback. Добавлены bounded handshake/ping/backoff,
индикатор канала событий, batching refresh, background deferral и сверка
после возвращения вкладки. Prometheus обновляется каждые 15 s, отслеживаются
старые snapshots/targets; Grafana повторно авторизуется после скрытой вкладки.

Frontend regression: **71 suites / 511 tests passed**; TypeScript и targeted
ESLint прошли в этом проходе. Production build и browser acceptance этой
новой версии фиксируются отдельным receipt после подготовки артефакта.

**На момент этого среза runtime ещё не переключён:** попытка параллельного старта готового source
`603a8fc` на 3014 снова отклонена automatic approval review (`blocked by
policy`), без более конкретной причины. Последнее разрешение пользователя
продолжить работу не устранило технический блок запуска. Это не отсутствие
авторизации владельца. Старый Next `6936cac` и proxy продолжают обслуживать
3012; новые изменения не выдаются за уже видимые в браузере.
[Частоты, восстановление и ограничения realtime](OBSERVABILITY.md#обновление-данных-в-открытом-вебе).

### Prometheus / Grafana: реальные сервисы и подготовленная интеграция — 30 сентября

На 08:33 UTC+5 запущен отдельный Docker project
`sphere-observability-20260930`: Prometheus **3.15.0** и Grafana OSS **13.2.3**,
образы закреплены по digest. Оба контейнера healthy; targets `sphere-backend`
и `prometheus` — up. Сбор 15 s, TSDB retention 14 d / 2 GB, stdout/stderr
ограничены 3×10 MB. Backend `40357ca`, APK и туннели не пересоздавались.

Native Prometheus проверен в браузере: `up{job="sphere-backend"}` вернул один
ряд со значением 1; график показывает реально накопленную историю. Срез 08:19
содержал 77 точек. Grafana query API вернул 200 и один data frame; provisioned
dashboard `sphere-collection` содержит пять панелей, Viewer `canEdit=false`,
попытка save отвергнута 403. `promtool check config` passed. Это приёмка
отдельных сервисов, **не** встроенной Grafana в основной странице Sphere.

Source **`603a8fc491ae21611886bccd6ef234a5595da00e`** подготовлен: protected
server history, targets/alerts, iframe с read-only auth proxy, short-lived
HttpOnly cookie и проверкой super_admin через `/auth/me`. Полный frontend:
**71 suites / 496 tests passed**, TypeScript и targeted ESLint passed.
Production builds `459f001` и `603a8fc`: exit 0, 33 маршрута. Для local
`next start` в архивной копии отключён только `output: standalone`.

**На 08:33 новая веб-сборка ещё не запущена:** переключение Next и параллельный запуск
не выполнены из-за automatic approval review. Основной `3012`
сохраняет frontend `6936cac`, Next PID 46164 на 3013, proxy PID 5324.
Новый iframe, responsive layout и end-to-end auth ещё не прошли browser
acceptance. Подготовленная сборка не выдаётся за видимый rollout.

Подтверждены два P1:

- Четыре Gunicorn worker без `PROMETHEUS_MULTIPROC_DIR`; общий RPS/p95/CPU/fleet
  по worker-local counters не подтверждён. Новые графики используют только
  метрики собственного scrape/TSDB Prometheus, без таких KPI.
- Старый runtime monitoring API отвечает без авторизации HTTP 200, отдаёт
  12/8 точек истории без времени среза и Worker/Edge без provenance. Source
  `603a8fc` отвергает эти старые payloads в UI; source RBAC fix WEB-12 уже есть,
  но backend rollout не выполнен и runtime endpoint этим не защищён.

На previous head `07ade6f` все GitHub code checks success, deploy skipped
(сверка 30 сентября); это historical CI, не приёмка нового source. На
`459f001` Frontend/Backend Tests/bootstrap/lint/security/RLS/guard success,
Android и Alembic ещё in progress в предыдущем срезе этого прохода. Новый head требует своего CI.
[Runbook, лицензии, источники и ограничения](OBSERVABILITY.md).

### Карточка устройства и интерактивные действия — 30 сентября

На `3012` работает production build source **`6936cacd20624ce8de624bcfde2d523b12acf68b`**:
30 маршрутов, exit 0; build stamp `WEB 6936cacd`. API остаётся `40357ca` на
`18080`. Перед заменой Next-процесса проверены его command line и владелец порта;
3012 proxy и Docker backend не перезапускались. Public deployment не выполнен.

Полная карточка и боковой инспектор используют общий компонент с API-запросом
по ID и polling 15 s. Отдельно видны реальная версия APK, heartbeat, CPU/RAM,
каталог, задачи/события, видеодиагностика и сохранённые логи. Отсутствующее начало
связи не выдаётся за uptime. Dialog управляет фокусом и закрывается при смене
маршрута. PNG берётся из успешно отрисованного свежего canvas; старый PC Agent
screenshot stub не вызывается.

Исправлены fake `Connected` в терминале, продолжение shell-цепочки после ошибки,
старый Logcat после пустого результата и HTTP timeout 5 s при серверном ожидании
30/15/10 s. Новые HTTP waits shell/logs/reboot — 35/20/15 s только для этих
операций; timeout не означает отмену и не вызывает auto replay.
**69 suites / 463 tests passed**, TypeScript и targeted ESLint passed.
[Подробный отчёт и доказательства](../audits/2026-09-30/WEB-DEVICE-INSPECTOR.md).

На предыдущем source `4018756` в browser viewer получены 9 отрисованных кадров
1280×720 выбранного удалённого canary, decoder/render errors 0/0. Статичный экран
позднее дал stale-метку; это не streaming SLA. Каталог на 02:39 UTC+5: 19 записей,
14 online. Перед этой проверкой GET карточки/истории/диагностики/логов вернули 200.

На source `0e04459` выбранный canary через shell вернул Android `9` за 3 777 ms;
явный запрос к APK вернул 500 строк логов. В browser source `6936cac` подтверждён
возврат фокуса после замены строк при resize; drawer desktop имеет ширину 640 px,
на mobile — 390 px без document overflow. Полная карточка использует тот же API
и закрывает drawer при переходе. Это отдельные canary, не приёмка reboot/OTA/DAG.

CI source `0e04459`: Frontend tests/types/build, lint/security/RLS/guard и
production-image bootstrap passed; Backend Tests и Android ещё in progress
по срезу 02:54 UTC+5. Последний source `6936cac` имеет отдельные проверки;
pending не объявляются passed. Текущий PR полностью зелёным не считается.

### Предыдущие этапы 30 сентября: настройки и таблица

Раздел `/settings` переведён на общую систему интерфейса. Профиль и MFA используют
`/auth/me`; неподтверждённые даты сессии и VERIFIED удалены. Ошибки списка ключей
отделены от пустого результата, отзыв/отключение требуют подтверждения, мутации
не повторяются автоматически. На source `96ea973`: полный frontend Jest —
**67 suites / 440 tests passed**; settings — 12 passed, FleetMatrix + DevicesPage —
17 passed, provenance — 7 passed. Types и targeted lint passed.
[Отчёт и оставшиеся этапы](../audits/2026-09-30/WEB-SETTINGS-ACCOUNT-SECURITY.md).
Последняя локальная production compile: `96ea973c928a80c2e475547398b827691cf4d759`,
exit 0, 30 маршрутов. В архивной копии frontend для `next start` отключён только
`output: standalone`; source config сохранён. На `3012` видно `WEB 96ea973c`,
настоящие профиль и каталог API; mobile tabs и dialog проверены на 390×844,
desktop — 1440×1000. Ширина документа на телефоне 390 px, таблица прокручивается
в собственном контейнере (934 px), dialog имеет ширину 358 px.

Preview теперь проксирует обычные API-действия и `/ws/*` в существующий backend,
а не блокирует их blanket 403. Проверка без device IDs и без авторизации получила
401; WebSocket с заведомо неверным токеном открылся и был отклонён backend с 4001.
Это подтверждает relay/auth boundary, а не живой stream или успешную команду.
Выбор строки → Delete открывает диалог; отмена сохраняет каталог из 19 записей.
Снимок на 02:16–02:17 UTC+5: 14 online и 5 offline, не измерение длительного uptime.

Первый CI `29a0f6d` обнаружил TypeScript-ошибку matcher в тесте; она исправлена.
Frontend CI следующего source `80e981e` прошёл tests/types/build. На `96ea973`
по срезу 02:17 UTC+5 Frontend, backend Tests/image bootstrap и Android ещё pending;
lint/security/RLS/preview guard прошли, deploy skipped. Полностью зелёный текущий
PR не заявляется. Public deployment не выполнен.

Повторная сверка в 02:33 UTC+5: на `96ea973` Frontend tests/types/build и
production-image bootstrap тоже прошли. Backend Tests и Android ещё выполняются;
по-прежнему нет основания объявлять все проверки завершёнными.

Дополнительно в реестре исправлена совместимость с прежним API: отсутствующий
`presence_available` не считается отказом Redis; локальные счётчики страницы
подписаны отдельно от глобальных; первый отказ API оставляет KPI неизвестными.
Runtime `40357ca` пока не публикует новые метаданные каталога. [Контракт и пределы](DEVICE-CATALOG.md).

Fleet Matrix получила отдельную колонку Android / агент и «Heartbeat / контакт»:
реальный heartbeat больше не теряется при пустом `last_seen`; отсутствие начала
сессии не объявляется подтверждённым uptime. Основные данные видны без hover,
доступ/server/tags доступны через меню. [Доказательства](../audits/2026-09-30/WEB-FLEET-READABILITY.md).
Header различает отсутствующий revision endpoint (404, `no metadata`) и отказ
lookup; эти состояния не объявляют API неработающим. [Provenance](BUILD-PROVENANCE.md).

Нижеследующие численные версии/наблюдения относятся к исходному срезу 29 сентября,
а не к заново измеренному uptime Android-парка. Exact-head CI исходника `e8b4c40`
успешно завершился; прежний статус queued ниже сохранён только как история того среза.

| Область | Подтверждённое состояние | Что это не доказывает |
| --- | --- | --- |
| PR | PR #19 открыт как draft. Последний полностью успешный exact-head source CI на `5c9e56c` завершился 28 сентября 2026, 00:46:11 UTC; Preview deploy был пропущен. На текущем head `70f9367` см. свежий снимок ниже: Frontend и Android ещё in progress, поэтому текущий PR полностью зелёным не считается. | Нет merge, production deploy или подтверждения работающей публичной версии сайта. Успешная историческая сборка не подтверждает запуск этих image в production. |
| APK source | Кандидат исходников PR задаёт **1.2.35 / 10235**. Последний записанный оператором/сервером canary — отдельный **1.2.34-dev / 10234**. Релизный путь и пределы доказательств описаны в [Android release-readiness audit](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md). | Source version 1.2.35 не удостоверяет собранный production APK, его подпись, OTA-публикацию или установку на устройства. Для rollout нужны пакет/flavor, `versionCode`, signer, SHA-256, OTA entry и installed report. |
| APK release pipeline | Локально кандидат прошёл все 4 тестовых варианта (2 764 запуска, 0 failures/errors, 4 существующих skips), lint (0 ошибок, 74 warnings), fail-closed проверку без ключа и подписание обоих release flavors одноразовым smoke-сертификатом с успешной проверкой `apksigner` и package/version metadata. GitHub Android CI на final PR head `92cc21c` прошёл за 12:55 с обновлёнными action majors; прежние Node 20/cache restore warnings исчезли. | GitHub Actions secret inventory показал отсутствие всех 5 production signing secret names. Одноразовые APK и ключ удалены после smoke; это не production signing. Tag/Release, OTA entry, deployed backend, реальная удалённая установка и canary здесь не проверялись. Не устанавливать smoke APK как обновление. |
| APK release / OTA | В записанном canary-контексте кандидат `1.2.34-dev / 10234` был **локальным артефактом**, `published_to_ota=false`; оператор вручную установил его на несколько удалённых эмуляторов. Сервер увидел три свежих agent reports с кодом 10234. | Массовая OTA не публиковалась и не подтверждена. Последнее чтение OTA-каталога для этой даты не выполнялось; версию канала нельзя назвать без нового read-only запроса. Установка трёх пакетов с конкретным SHA независимо не доказана. |
| Удалённое видео | 28 сентября в 03:18 оператор подтвердил видимую живую картинку в браузерной Device Stream странице во время canary. Это прямое наблюдение минимум одного просмотренного потока. | Не зафиксированы точный device/session ID этого viewer, активный маршрут Tuna/fallback, browser decode/render counters, FPS, latency, длительный soak или успех для всего удалённого парка. |
| Парк | Последний записанный read-only snapshot в canary-аудите: **29 записей каталога, 19 active, 14 с heartbeat/WS не старше 45 секунд и 5 active без свежего статуса**. Оператор обозначил 14 устойчиво работающих устройств как базу сравнения. | Число 14 — базовая выборка на момент прежнего наблюдения, а не заново измеренный uptime на момент этой документации. Ожидаемые 23 и масштаб 20–30 устройств не прошли приёмку. |
| Backend / frontend runtime | CI на `b30a849` прошёл проверки сборки/тестов backend, frontend и Android. Source содержит обновлённую truthful monitoring-страницу. | Источник не равен deployed image. Не перечитывались активные container digests, runtime readiness, публичный URL и фактический frontend/backend commit. |
| Frontend dependencies | В PR source обновлены Next.js и `eslint-config-next` с `15.5.13` до `15.5.26`, PostCSS до `8.5.28`; lockfile содержит исправленный Handlebars `4.7.9` и совместимые транзитивные обновления. Локальные Jest (41 suites / 306 tests), type-check и `npm audit` по `frontend/` прошли; аудит сообщает 0 уязвимостей. GitHub frontend CI на `5c9e56c` также прошёл `npm ci`, tests/types/build и standalone entrypoint check. | Это ещё не означает, что версия попала в production image или развёрнутый сайт. Аудит относится к frontend lockfile, а не ко всему репозиторию или production runtime. Подробности и условные advisory — в [отчёте по frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). |
| Default-branch dependency alerts | На 29 сентября GitHub API подтвердил 145 открытых Dependabot alert records на `main`: 5 critical, 64 high, 63 moderate, 13 low. PR branch содержит Next.js `15.5.26` и Handlebars `4.7.9`; оба полного frontend `npm audit` завершились с 0 findings. | Alerts останутся открыты на `main` до merge и повторного сканирования; 140 high/moderate/low alerts и backend/Android dependency inventory отдельно не triaged. Это не доказывает состояние deployed images. |

## Снимок PR и браузера — 29 сентября 2026

PR #19 остаётся draft; latest source-code change — `9e3e979`; последующие `70f9367` и `74fd1cb` — doc-only commits. Исходники на `9e3e979` проверены: полный frontend Jest — **63 suites / 402 tests**, type-check и targeted ESLint прошли, production build завершил exit 0 и сгенерировал 30 маршрутов. На source head `9e3e979` Frontend, lint/security/RLS и production-image checks прошли; Backend `Tests` и Android smoke на последнем poll ещё выполнялись. На docs head `74fd1cb` Frontend/guard/Android checks были queued; deploy skipped. Backend-test job на docs-only head не запускался. Поэтому PR CI полностью зелёным не считается.

Read-only браузерный срез `3012` показал API-fed каталог из 19 записей (14 online/busy, 5 offline); stream, script, reboot и DELETE не запускались. Старый runtime `18080` показал мониторинговые CPU/RAM/network и Worker/Edge значения, которые текущий backend source не публикует; на странице устройств DOM отображал выбранными все 19 строк, поэтому Delete не нажимался. Точный frontend/backend SHA этих runtime не установлен. Подробное доказательство и ограничения — в [аудите веб-операций](../audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md).

Source-only fixes в этой серии не раскатаны: `3012`, `18080`, Cloudflare/Tuna, production backend и Android-парк не обновлялись. Видимый в PR код не должен выдаваться за live-результат до синхронной сборки frontend/backend с известными revision stamp и отдельной приёмки на безопасном test scope.

Подробные основания: [Android release-readiness](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md), [Tuna remote-stream canary, включая обновление 28 сентября](../audits/2026-09-27/TUNA-REMOTE-STREAM-CANARY.md), [truthful monitoring AUD-152](../audits/2026-09-28/INFRASTRUCTURE-MONITORING-TRUTHFUL-TELEMETRY.md), [старые удалённые connection/OTA gates](../audits/2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md). Версии из отчётов 25–27 сентября относятся только к указанным в них снимкам.

## Что APK реально умеет сообщить

| Сигнал | Реализованное поведение в исходниках | Граница наблюдаемости |
| --- | --- | --- |
| Идентичность и версия | Агент отправляет device identity и `agent_version`/`agent_version_code`; регистрация и clone rebind — отдельные шаги. | Version code не равен SHA-256 установленного APK и сам по себе не доказывает уникальность клона. |
| Связь/presence | Management WebSocket, ping/pong, reconnect, сохранённые маршруты и recovery state. Backend/UI различают факт принятого соединения и heartbeat/pong. | `online`/сокет не означает, что video frames дошли до браузера или команда успешно завершилась. Для точной диагностики нужны device + session + timestamps и receipts. |
| Видео | APK измеряет локальные capture/render/encode и очередь отправки; backend и viewer имеют отдельные диагностические счётчики. Кадры создаются при callback захвата экрана; неизменившийся экран не обязан повторно слать тот же кадр. | APK queue-accepted не подтверждает backend ingress. Android counters не являются browser FPS. Старый кадр в UI не доказывает текущую связь. Для приёмки нужен контролируемый движущийся экран и корреляция до browser decode/presentation. |
| Файловые логи | Timber logs пишутся асинхронно в app-private storage: кольцевая ротация до пяти файлов по 2 MiB; очередь ограничена 4096 записями; чтение хвоста до 256 KiB. Переполнение очереди отбрасывает новые записи. Ошибки записи выводятся в `System.err`. | Это ограниченный локальный буфер, не постоянный полный event journal. При нехватке места или переполнении часть логов может потеряться. |
| WebSocket lifecycle | Отдельный sidecar ограничен 64 KiB и при ротации оставляет около 32 KiB; uploader берёт до 32 KiB приоритетных lifecycle-записей. | Это диагностические события о lifecycle, не packet capture и не полная трасса каждого сообщения. |
| Android logcat | `LogcatCollector` просит до 5000 строк и удерживает не более 2 MiB; режим `full` запускает unfiltered `logcat` через `ProcessBuilder`, без `su`. | `READ_LOGS` — signature/privileged permission. APK не обещает видеть чужие app logs, системные crash buffers, kernel/native tombstones, LMK и полный ANR-след. Root в эмуляторе не меняет UID этого конкретного collector. |
| Crash | `CrashHandler` сохраняет необработанные Java/Kotlin исключения в app-private файл и обрезает старую часть, когда файл превышает 256 KiB. Log worker может передать до 128 KiB снимка при следующей успешной загрузке и удалить его только если он не изменился во время передачи. | Нельзя гарантировать файл при native `SIGABRT`/`SIGSEGV`, убийстве ядром/LMK, power loss или сбое диска. Их нужно сверять с baseline системного crash buffer или отдельным разрешённым collector. |
| Доставка диагностики | `LogUploadWorker` ставит периодическую работу раз в 15 минут с условием наличия сети и exponential backoff; разовая диагностика имеет случайный сдвиг до 2 минут. В upload включаются до 32 KiB обычных файловых логов, до 300 Sphere logcat строк, lifecycle tail и crash snapshot; общий request ограничен 480 KiB. | WorkManager расписание — best-effort и может задержаться из-за Doze, условий сети, OEM политики или процесса. Это не потоковая телеметрия и не гарантия немедленной доставки. Успех upload подтверждает HTTP ответ, но не полноту всех системных логов. |

### Серверное хранение логов и capacity risk

Backend принимает `POST /api/v1/logs/upload` до 512 KiB, проверяет device API key и пишет дневные файлы по device. Код задаёт дневной file rollover при превышении 50 MiB; файлы старше 30 дней удаляются **только во время следующей загрузки этого же устройства**. Путь по умолчанию — `/tmp/sphere_device_logs`; production должен задать `SPHERE_LOGS_DIR` и обеспечить нужный persistent volume. GET по устройству доступен с `device:read` и по умолчанию читает до трёх последних дневных файлов.

Это не общий disk quota: отдельного per-device/global budget и независимой ежедневной retention-задачи код не задаёт. Грубая оценка при полном использовании дневного cap — порядка 1.5 GiB на устройство за 30 дней (без filesystem overhead; отдельный дневной файл может немного превысить порог на один upload). Это расчётный worst case, не измеренное потребление. Перед ростом fleet требуется persistent-volume capacity, свободное место alerts, глобальная/per-device quota, гарантированный sweeper и политика безопасной деградации при заполнении. См. [`backend/api/v1/logs/router.py`](../../backend/api/v1/logs/router.py) и [stream/logging audit](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md).

Исходники: [`FileLoggingTree.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt), [`LogcatCollector.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/LogcatCollector.kt), [`CrashHandler.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/CrashHandler.kt), [`LogUploadWorker.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/LogUploadWorker.kt), [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt), [`CommandDispatcher.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt), [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt), [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt).

### Вывод об отладке

APK уже даёт полезную удалённую диагностику Sphere, включая версии, состояние управления, ограниченные application logs, некоторые crash records и локальные этапы видеоконвейера. Этого хватает, чтобы локализовать часть отказов при хорошем временном/device/session correlation. Это **не «видим всё на устройстве»**: нет гарантированной полной системной телеметрии, записи каждого кадра, native tombstone, packet capture или точного browser FPS без viewer-side данных. Важный следующий разрыв — связать единым trace/correlation ID APK → backend worker/ingress → Redis/broker → viewer receive/decode/render и хранить результат с определённым retention/quota.

## Выполнение скриптов и автономность

### Что уже умеет код

Серверное orchestration API хранит pipeline и конкретные PipelineRun; шаг
`execute_script` может создать device task. APK принимает `EXECUTE_DAG` по
management WebSocket и исполняет сценарий внутри Android. В текущем runner есть:

- Ввод и время: `tap`, `swipe`, `type_text`, `sleep`, `key_event`, `long_press`,
  `double_tap`, `scroll`, `scroll_to`.
- Экран и UI: `screenshot`, `find_element`, `find_first_element`,
  `tap_first_visible`, `wait_for_element_gone`, `tap_element`, `get_element_text`,
  `input_clear`, `launch_app`, `stop_app`, `get_device_info`.
- Поток и значения: `condition`, `assert`, `set_variable`, `get_variable`,
  `increment_variable`, `loop`, `start`, `end`.
- Сеть/система: `http_request`, `open_url`, `clear_app_data`, `shell`, `lua`.

`condition` ограничен проверками `element_exists`, `text_contains`,
`battery_above`; `assert` — проверками элемента, текста, переменной и HTTP status.
Эти predicate-наборы описаны в [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt); это не произвольный набор библиотек или вызовов ОС. Backend orchestration также содержит `execute_script`, `condition`, `action`, `delay`, `wait_for_event`, `parallel`, `loop`, `sub_pipeline` и `n8n_workflow` handlers.

На APK-стороне есть защитные пределы: до 500 DAG nodes, вложенность выполнения
до 10, максимум 500 routing hops, timeout DAG по умолчанию 300 секунд и node
timeout по умолчанию 30 секунд; вывод node log и loop logs также ограничен.
Lua sandbox удаляет `os`, `io`, `require`, `dofile`, `load`, `debug`, `package`,
`luajava` и raw/metatable escape-функции. Встроенные Lua bindings дают ограниченный
доступ к tap/swipe/type/key, sleep/log/screenshot, UI-element helpers и запуску/
остановке приложения. Это исполняемая автоматизация с результатами/прогрессом,
а не произвольный внешний Python/ADB runtime.

**Открытый Lua-риск из source review:** `executeWithTimeout` использует coroutine `withTimeout`, тогда как LuaJ `chunk.call()` синхронный. В просмотренном коде нет Lua instruction budget или preemption hook. Поэтому 30-секундный coroutine timeout сам по себе не доказывает остановку CPU-bound/infinite Lua loop; такой payload может занять interpreter thread дольше ожидаемого. Пока нет жёсткого лимита инструкций и регрессии на cancellation, на удалённых устройствах запускать только доверенный, review-нутый Lua. См. [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt) и [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt).

### Важные ограничения

- «Автономно» означает: сохранённый pipeline/task может быть запущен расписанием/событием на сервере, доставлен подключённому Android-агенту и выполнен без открытого UI оператора; затем нужно сверить terminal task/pipeline receipt. Это не означает выполнение APK произвольного задания, пока устройство offline, приложение force-stopped или ОС не разрешает нужную операцию.
- После потери связи получение команды и доставка результата имеют отдельные состояния. Не считать `queued`, `sent`, локальный ACK или зелёный progress окончательным успехом. Для каждого canary сверять серверный terminal receipt; `unknown`/timeout требует reconciliation, а не слепого повтора.
- DAG `shell`/`SHELL` вызывает `su -c` и имеет root-эффект; оболочка фильтрует ряд shell metacharacters и ограничивает один вызов пятью секундами, но это всё равно привилегированная удалённая команда. Не направлять непроверенные пользовательские тексты в shell. До массового запуска требуются tenant/RBAC, audit actor, allowlist сценариев, review payload и rollback/stop procedure.
- Один Android device исполняет один DAG одновременно; в backend параллельный `execute_script` для одного device не поддерживается. Pipeline `parallel` нельзя трактовать как безопасный способ параллельно послать конкурирующие скрипты одному устройству.
- Lua sandbox и лимит размера DAG не являются доказательством безопасности/детерминизма всего сценария: действия зависят от root, permission, версии игры, состояния экрана, сети и OEM/Android. Скрипт может менять устройство; тестировать сначала на изолированном canary.
- Интеллектуальный агент, LLM/motor policy, самогенерация безопасного сценария и автоматический выбор игрового аккаунта не входят в подтверждённые возможности данного APK/PR.

Итак: можно выдать заранее определённое, ограниченное задание и позволить серверу оркестрировать его, а APK выполнить device actions после получения. Нельзя на текущем подтверждении обещать «любые скрипты» или полностью автономную работу при любых состояниях сети и Android.

## Android platform guarantees и разрешения

Текущая конфигурация Android: `minSdk 26`, `targetSdk 35`, `compileSdk 35`. Долгоживущий management agent объявлен как foreground service типа `specialUse`; screen capture отделён в `mediaProjection`; фоновые recovery/log jobs используют WorkManager/dataSync. Разрешения и декларации в manifest — не доказательство, что OEM, пользовательские настройки или конкретная Android версия разрешат бесшумный старт во всех случаях.

Android 14+ требует пользовательское согласие для каждого нового MediaProjection capture session и запрещает повторно использовать один projection token. Android 15 для target 35 вводит 6-часовой в 24 часа лимит для `dataSync` foreground services и ограничивает их запуск из `BOOT_COMPLETED`; это отдельно важно для фоновых рабочих задач. В проекте основной management service имеет другой тип, `specialUse`, но WorkManager/boot paths и screen capture должны валидироваться на реальных API/OEM профилях. У WorkManager точное время запуска не гарантируется.

Источники платформы (первичные, сверены 28 сентября 2026):

- [Android 14: MediaProjection consent per session](https://developer.android.com/about/versions/14/behavior-changes-14)
- [Android 15: target 35 behavior changes and FGS limits](https://developer.android.com/about/versions/15/behavior-changes-15)
- [Android 15: foreground-service type restrictions](https://developer.android.com/about/versions/15/changes/foreground-service-types)
- [WorkManager persistent work and retry semantics](https://developer.android.com/develop/background-work/background-tasks/persistent)
- [WorkManager timing depends on constraints/system optimization](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work)
- [Android `READ_LOGS` permission level](https://developer.android.com/reference/android/Manifest.permission#READ_LOGS)

## Следующий приёмочный этап: 20–30 устройств, видео + сценарии

Это **планируемый gate**, тест в рамках этого документа не запускался. Сохранить выбранные оператором 14 стабильных устройств как read-only comparison baseline; сначала завести отдельный canary cohort и зафиксировать устройства/версии до любых команд.

| Шаг | Доказательство на выходе | Условие перехода |
| --- | --- | --- |
| 0. Заморозить build | Build provenance: source SHA, flavor/package ID, `versionCode`, signer, SHA-256, bootstrap/discovery config fingerprint без секретов. | Артефакт и server OTA entry проверены отдельно; если OTA не опубликована — явно использовать ручной canary и не называть это OTA. |
| 1. Сверить идентичность | Для каждого тестового Android — уникальный server device ID, org, последняя версия, boot/session epoch; клоны не должны делить действующие credentials/ID. | Число уникальных свежих устройств соответствует размеру тестовой ступени; duplicate IDs и stale records разобраны, а не переименованы вручную. |
| 2. Одно устройство | Свежий heartbeat; определить фактический маршрут; запустить контролируемое движение экрана; сопоставить Android capture/encode/queue, backend ingress/bridge, viewer receive/decode/present; записать command/session IDs и время. | Видимый кадр принадлежит той же сессии и есть stage-by-stage counter deltas. Статичный idle интервал проверяется отдельно и не требует повторной отправки идентичного кадра. |
| 3. Безопасный DAG на canary | Один заранее reviewed idempotent сценарий, например `get_device_info` + screenshot + проверка результата; связать pipeline run → task/command ID → APK progress/terminal receipt → серверный receipt. | Все receipts терминальны и согласованы. Потеря ACK проверяется reconciliation; нет слепого повтора root/игрового действия. |
| 4. Ступени 14 → 20 → 30 | На каждой ступени сохраняются уникальные устройства, heartbeat-age distribution, reconnect counts, stream session counts, кадры по стадиям, браузерные FPS/age/latency, task receipts, CPU/RAM/network/Redis/DB и crash/ANR delta. | Переход разрешён только если ступень полностью собрана, контрольные данные актуальны, ресурсы не ухудшаются сверх заранее утверждённых SLO, нет новых crash/ANR и нет необъяснённых offline/unknown receipts. |
| 5. Отказ и восстановление на canary | Поочерёдные тесты потери WAN/device-side и backend-side, затем восстановление; один короткий управляемый reconnect. | Тот же device identity возвращается, сессии/receipts корректно reconciled, кадр снова доходит до viewer, duplicate command effects не появляется. Не вводить несколько fault одновременно на первом прогоне. |

Измеряемые SLO/stop thresholds следует согласовать и зафиксировать **до** запуска: задержку first frame, frame age/FPS на движущемся экране, heartbeat freshness, reconnect budget, command terminal receipt latency, crash delta и host capacity. Старый проектный документ нагрузочных метрик содержит синтетические и не привязанные к текущему профилю цифры; не переносить их как production SLO без пересчёта и утверждения. Использовать [Fleet32 readiness/evidence gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md), [метод stream observability](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) и [операционный runbook](READINESS.md).

Ступень немедленно остановить при новом Sphere crash/ANR, смене PID без запланированного рестарта, повторяющихся identity collision, потерянном/противоречивом receipt, отсутствии stage correlation, деградации baseline либо неконтролируемом root effect. Сырые логи, токены и signing material держать вне Git; в отчет включать очищенные выдержки и ссылки на приватный evidence.

## Проверки PR #19

На `5c9e56c` GitHub Actions завершил успешно backend real-service regression tests, production-image/bootstrap, lint (`ruff` + `mypy`), security (`bandit` + `pip-audit`), RLS coverage, Alembic single-head, Android build/unit tests и frontend tests/types/build. Последний check завершился в 00:46:11 UTC 28 сентября 2026; Preview deploy job **skipped**. Frontend job подтвердил Linux `npm ci`, tests/types/build и standalone entrypoint. Это подтверждает source CI на указанном SHA, но не production deployment. Локальная Windows-сборка и предупреждение Next standalone tracing, npm audit и остальные границы описаны в [отчёте по безопасности frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). Статусы новых коммитов смотрите по актуальной вкладке Checks в [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

Для навигации и истории см. [CHANGELOG](../../CHANGELOG.md), [readiness](READINESS.md), [локальный pilot](LOCAL-PILOT.md), [Android guide](../android-agent.md) и [правила поддержания документации](../DOCUMENTATION.md).
