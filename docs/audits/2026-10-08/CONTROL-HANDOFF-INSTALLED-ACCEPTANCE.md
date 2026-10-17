# Обычное управление, навигация и XPath: установленная приёмка

8 октября 2026, Asia/Yekaterinburg. Один pilot PH011, APK10249; конечные
проверки не являются admission всего парка. Канонический статус:
[CURRENT-STATE](../../operations/CURRENT-STATE.md).

## Подтверждённая проверка UI `29eecb8` / API `2225f73`

Reviewed UI стартовал02:01:01UTC, API01:44:42UTC8October. Автоматическое обычное
«Управление» открыло native READY без отдельного переключателя жестов.
Независимый Android View измерен до/после настоящего CUA drag:
DOWN2/MOVE4/UP2/CANCEL0 → DOWN3/MOVE9/UP3/CANCEL0.
ДельтаDOWN1/MOVE5/UP1/CANCEL0; последний MOVE9566751ms native uptime,
terminal9566753ms. Это MOVE до отпускания, не visual input→picture latency.
Wheel затем дал DOWN1/MOVE1/UP1/CANCEL0 и194ms от начала до terminal.

Home с receiver на переднем плане подтверждён765ms, launcher проверен
независимым dumpsys, новая capability/STARTUP вернула READY автоматически.
Ответ SHELL не является задержкой отображения кадра. XPath сначала показал
ожидание release, затем46узлов960×540 rotation0. Выбор launcher значка показал
рамку/XPath/все возвращённые атрибуты и не запустил приложение.

Один следующий auto read завершился root SHELL exit1. Auto polling остановился,
старый валидный snapshot сохранился. Два отдельных read-only stage probes
wm/dump/cat/wm/cleanup прошли; после явного возобновления несколько auto reads
успешны. Причина exit1 не установлена. Уникальные временные XML удалены,
полное дерево и сырые owner/receipt/auth данные не публикуются.

Быстрый XPath→Control при незавершённом read воспроизвёл отдельный
`native_input_rejected_or_unknown` без отправки касания. Source `e88c4db`
устраняет этот overlap, его установка и повторная приёмка фиксируются отдельно.
[Причина и regression](INSPECTION-RETURN-TO-CONTROL.md).

## Provenance и ограничения

UI `29eecb8`: hosted CI37715096698,1844passed/137suites, TypeScript/build,
26packaged pages/73assets. Config image SHA-256:
`9fc276c1753229fba357e6ecf9ad0d5dfe944579488b9e47be298d54ca0c86e0`.
API `2225f73`: CI37712824712,3327passed/37skipped/229subtests, lint/types/
security/RLS/bootstrap/Redis acceptance. Config image SHA-256:
`9992849d1f265aa7f27386c254a7dd7ddad2206194d68f295f7cf6de1909673d`.
Loaded OCI manifest и config digests различаются штатно и проверены installer.
Миграции не запускались; SQLhead `20261006_script_catalog_metadata` сохранён.
45 остальных контейнеров и OTA catalog сохранены каждым installer.

APK10249 source `d8023bc`, SHA-256
`6b177bcbac3bb319597630f34f88956bc79a6e0e3261508c2fe09708b393b013`;
candidate979passed/3skipped в каждом Dev/Enterprise. ТолькоPH011 обновлён;
PH02510248, normalOTA не продвигался. Default/release continuous flagfalse.
Rich trajectory/XPath/crop recording, remote/fleet fault qualification,
correlated playback, real idle-loss recovery canary и soak остаются OPEN.
Idle recovery имеет одну попытку только после native RELEASE3; неизвестное
касание не повторяется. Не заявлены zero latency/frame-exact input/20–30FPS.
SF26-05OPEN, product ledger9accepted/41open. Storage и повторное повреждение
Git остаются самостоятельными открытыми incident.

## Финальная установка и повторение ошибки на `e88c4db`

Reviewed UI source `e88c4db8633d8288d7bbea58da773eb52d5f0e8f` стартовал
02:27:14.403216UTC. CI37717225465:1848passed/137suites, TypeScript/build,
26pages/73assets. Archive120852437B; config digest
`88b0b84fd311e298c9410f250d5e6362bcb1fd7740e4fa6c7f7dd3e6e04b36a5`,
loaded OCI manifest
`d9326840eb36dedc3cfdf73f8a7f63628aa7b7ce4cd3333481770e2bb55be502`.
Installer подтвердил45 других неизменённых контейнеров, API и OTA SHA-256
`5d5dcb5521277b51f366ea5370a2f7df5fd62696de0d5b7b86a56b443b03af10`.
ResourceFindings пуст; localhost3015 healthy. Backend/Android/migration/workflow
sources между `2225f73` и `e88c4db` не отличаются; UI обновлён отдельно.

Реальный браузер после reload показал правильный source и native READY.
Первый XPath entry дождался release и получил46узлов. Затем те же два быстрых
действия «Обновить дерево»→«Управление» показали drain/read-only, после ответа
автоматически вернули READY без recovery. Повторный refresh→Control→XPath
сохранил ожидание и получил свежий46-node snapshot; highlight и атрибуты
launcher значка работают, нажатие Android не отправлялось. Конечный успешный
прогон не устанавливает причину прежнего root exit1 и не заменяет fault soak.

После переходов независимый receiver снова подтвердил CUA drag:
DOWN1/MOVE4/UP1/CANCEL0,145ms до terminal, последний MOVE за9ms до UP.
WheelDOWN1/MOVE1/UP1/CANCEL0,186ms. Home748ms вернул launcher и automatic READY.
Эти durations не являются input→picture latency. Перед удалением fixture
выбран «Просмотр» и получен native closed. Собственный receiver package удалён,
`pm path` пуст, launcher и основной APK10249 проверены независимо; app data
основного агента сохранены. Веб оставлен в обычном «Управлении».

Private bounded evidence: `inspection-final-native-before.json`,
`inspection-final-native-drag.json`, `inspection-final-native-wheel.json`,
`inspection-web-install.json`, `inspection-return-before.png` и итоговый
`control-final-e88c4db.png` в `.local-pilot/continuous-live-20261008`.
[Sanitized acceptance](CONTROL-HANDOFF-INSTALLED-ACCEPTANCE.json).
