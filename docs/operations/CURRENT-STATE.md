# Sphere: актуальное состояние и критерии приёмки

**Обновлено:** 1 октября 2026, Asia/Yekaterinburg; даты отдельных runtime/CI срезов указаны ниже.<br />
**Область:** исходники и документация ветки PR #19, записанные runtime-наблюдения, Android APK и готовность следующего прогона.<br />
**Канонический документ текущего состояния:** этот файл. Исторические отчёты ниже сохраняют исходные даты и факты.

[Главная](../../README.md) · [Каталог документации](../README.md) · [Readiness](READINESS.md) · [Fleet32 gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

> [!IMPORTANT]
> **Текущий loopback runtime, 1 октября:** `3015 → UI 3022 / API 18080`, frontend/API **`b9a3f29`**. Compiled UI переключён в **15:44:19 UTC+5**, Next PID **21016** / relay PID **2080**, прежний Next 3021 / PID 45944 сохранён для rollback. В одиночном просмотре tap/swipe разрешён по последнему кадру текущего OPEN socket после 10 s без изменений; first-frame/error/reconnect gates сохраняются. Backend заменён отдельно в **16:01:53** после required CI, build/readiness подтверждены; database head, соседние containers, public UI, OTA catalog/artifacts и tunnels не менялись. [Static input contract](STATIC-STREAM-INPUT.md), [allowlisted runtime/OTA/capture/decode evidence](../audits/2026-10-01/PH010-PH025-PLANAR-CAPTURE-EVIDENCE.json). **Browser visual QA заблокирована политикой URL CUA**, обход не выполнялся; native decoded PNG не является browser screenshot или draw-FPS benchmark.

**Текущий APK canary:** `1.2.39-dev / 10239`, source **8a66afe**, planar=true /
GPU=false, 8464127 bytes, SHA256
`c9f4a5ef9652a2bb2b14765e4c91fa929d4e1b59e7645703be99ed64f8dcca07`.
Подписан прежним pilot key; обе configured debug flavors: **770 tests каждый,
769 passed / 1 skipped / 0 failures / 0 errors**, обе собраны. По одному адресному
OTA PH010 и remote PH025: completed / installed 10239 / recovered-after-restart,
свежие online versions подтверждены. Normal/global OTA и GitHub latest APK aliases
не продвигались, default planar/GPU flags false. Это canary, не production release.

**Новые реальные video measurements:** PH010 — **300 и 299 pictures / 10 s**
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
Source **`3148668`** завершил обязательные GitHub backend/frontend/security/
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

Повторная сверка в 02:19 UTC+5: на `96ea973` Frontend tests/types/build и
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
