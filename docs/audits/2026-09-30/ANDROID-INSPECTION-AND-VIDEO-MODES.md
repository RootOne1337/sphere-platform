# Android: наблюдаемость, два режима видео и UI-инспекция

**Дата проверки:** 30 сентября 2026, Asia/Yekaterinburg.<br />
**Source follow-up:** 1 октября 2026; browser gesture ownership, raw FPS gate и PH025 wire canary.<br />
**Source baseline:** `f092a16`; frontend selection follow-up `3132afc`.<br />
**Статус:** аудит, source fixes и план приёмки; 1 октября APK 1.2.36-dev установлен
адресным OTA на PH025. GPU bridge подтверждён; удалённые PH022/025 сообщают
единственный display mode 5 Hz, локальные PH010/011 — 60 Hz. Плавность и
чёткость одиночного потока не приняты. [Finite evidence](../2026-10-01/PH025-GPU-CANARY-EVIDENCE.json).

**Android source follow-up:** APK-I01 исправлен в `3148668`: concurrent bounded
process runner и запрет продолжения DAG при неопределённом результате shell;
обязательные GitHub jobs success. APK-I02 исправлен в `e3dc143`: private serialized
dump и validation; обязательные GitHub jobs success. APK-I04 follow-up устраняет eager root spawn при создании
компонента команд. Исходные наблюдения ниже сохранены как baseline. CI и device
acceptance отмечаются раздельно; остальные устройства этим canary не заменены.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Device inspector](WEB-DEVICE-INSPECTOR.md) ·
[Stream stage audit](../2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) ·
[OTA / remote gates](../2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md) ·
[GPU/video canary](../../operations/VIDEO-CADENCE-CANARY.md) ·
[Каталог](../../README.md) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Вывод и границы проверки

Рабочий транспорт уже передаёт H.264, а веб декодирует его через WebCodecs и
рисует canvas. Скрипты умеют искать UI-элементы, включая XPath. Это не означает,
что реализованы отдельный экономичный fleet-профиль, гарантированная плавность
при 20–30 потоках, полноценный UIAutomator2 server или визуальное дерево с
выделением элементов. Эти возможности требуют отдельных контрактов и приёмки.

Подтверждение remote video в предыдущих опытах сохраняется. Оно не доказывает
доставку обновления каждому APK или отсутствие последующих обрывов. Историческая
browser acceptance: API `85c8014`, UI `3132afc` на `3015 → UI 3018 / API 18080`;
срез 22:29:40 — 14 online / 5 offline / 0 connecting. Ранее конечная
проверка восстановления 21:40:40–21:41:40 показывала 14 online / 5 offline.
Точные условия и первый неуспешный
post-restart замер находятся в CURRENT-STATE; здесь они не заменены SLA.

**1 октября, 00:24–00:26 UTC+5:** preview восстановлен после отсутствующих старых
PID/listeners. Исторический ingress `3015 → UI 3019 / API 18080`, UI `3d082c1`,
API `85c8014`. Проверены source archive/compile, login/auth-me, service probes
и protected observability JSON; fleet 19 total / 14 online / 5 offline /
0 connecting. CUA отклонил `getTab` для `3015/login` по URL policy. Обход не
производился; новый screenshot/visual/rotation canary не подтверждены.

Требование продукта сохраняется: Android APK + сервер + браузер. Обязательный
PC Agent, внешний ADB на станции владельца или ручная установка каждого клона
не добавляются. Название существующего класса `AdbActionExecutor` не означает
сетевой ADB: этот путь выполняет локальные Android root-команды через `su`.

## Что есть в исходниках

| Область | Проверенный код | Наблюдаемая возможность / ограничение |
| --- | --- | --- |
| Android capture/encoder | [StreamingManagerImpl](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt), [H264Encoder](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/H264Encoder.kt) | MediaProjection → Surface → MediaCodec; defaults 30 FPS, 1.5 Mbit/s, keyframe interval 1 s. Это configuration targets, не измеренный FPS/канал |
| Размер видео | [VirtualDisplayManager](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/VirtualDisplayManager.kt) | 1280×720 landscape / 720×1280 portrait на старте. Смена ориентации во время сессии требует отдельной проверки |
| Ограничение кадров | [FrameThrottle](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/FrameThrottle.kt) | Целевой предел 30; не контракт отдельных grid/detail demand profiles |
| Viewer и диагностика | [DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx), [decoder](../../../frontend/lib/h264-decoder.ts) | receive/decode/draw counters, queue/errors, fresh-frame gate для клика и PNG; опциональные APK stage counters |
| Fleet | [MultiStreamGrid](../../../frontend/src/features/devices/MultiStreamGrid.tsx), [stream page](../../../frontend/app/(dashboard)/stream/page.tsx) | Явный start/stop, bounded список потоков, тот же DeviceStream. Мелкая плитка сама по себе не уменьшает Android capture/encoder нагрузку |
| Backend stream | [WS router](../../../backend/api/ws/stream/router.py), [REST router](../../../backend/api/v1/streaming/router.py) | Tenant/RBAC, viewer lifecycle, owner-worker command publication. Принятие команд/локальной очереди не доказывает draw в браузере |
| XPath в сценарии | [AdbActionExecutor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt), [DagRunner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt) | `uiautomator dump`, XML/XPath 1.0 и center по bounds, root-dependent. Нет protected hierarchy API и дерева/overlay в основном вебе |
| Диагностические файлы | [FileLoggingTree](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt) | Очередь до 4096 записей, nominal 5×2 MiB rolling files, отдельный bounded WS lifecycle sidecar |
| Получение logcat | [LogcatCollector](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/LogcatCollector.kt) | Concurrent stdout reader и bounded tail. Полнота системного журнала зависит от Android UID privileges |
| Доставка логов | [LogUploadWorker](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/LogUploadWorker.kt) | Periodic 15 min, immediate jitter до 2 min, pending crash upload, общий UTF-8 budget 480 KiB; WorkManager не гарантирует точное время |

Полный журнал всех действий, каждого кадра, native tombstones, packet capture и
состояния всей станции не подтверждён. Статус online — heartbeat, а не факт
успешного видео, задания или OTA. FPS capture, encoder и browser draw различаются.

## Найденные разрывы и порядок исправления

### VIDEO-I04 · P1 · FPS gate на закодированных reference pictures

**Baseline `0a09355`:** `StreamingManagerImpl.onFrameReady` применял
`FrameThrottle` к неключевым H.264 access units по времени вызова callback.
MediaCodec может выдавать разные source pictures близко друг к другу. Такой
drop не равен пропуску сырого изображения: slice с NAL type 1 может быть
reference picture, используемой последующими pictures. Сохранение SPS/PPS/IDR
само по себе не делает произвольный drop остальных slices безопасным.
Это следует из codec semantics и приоритета сохранения reference pictures
в [RFC 6184, §7.3](https://www.rfc-editor.org/rfc/rfc6184#section-7.3).
Sphere использует WebSocket, а не RTP; здесь RFC служит источником H.264
dependency semantics, не описанием реализованного transport protocol.

**Исправление исходников:** FPS gate перенесён в raw ImageReader callback,
перед доступом к pixels/Bitmap copy/encoder Surface submission. Skipped image
всегда закрывается через `finally`. Закодированные access units передаются
в WS queue в исходном порядке без FPS filtering. Bounded WS/network queues
сохраняются; это не обещание доставки при congestion и не замена GOP recovery.

`capture_throttle_drops_total` — optional v2 extension для raw skips;
`frame_throttle_drops_total` сохраняет прежнее значение encoded FPS loss.
Старый APK без нового поля показывает unknown/«—», а не zero. Backend валидирует
границы counter, сохраняет его в diagnostic snapshot и отдельном Prometheus
gauge `sphere_stream_capture_throttle_drops_session`; отсутствующий optional
counter удаляет прежний gauge, в том числе при downgrade. Heartbeat и web
показывают обе стадии отдельно.

**Доказательство в fixtures:** два regressions failed до fix: callback burst
терял два encoded reference slices, а raw capture сверх лимита всё равно
копировался и подавался в encoder. После fix проходят оба и stopped-output
gate. Пять NAL units (SPS/PPS/IDR/reference/reference) доходят в прежнем порядке;
raw skip закрывает image без bitmap copy и Surface lock. Это unit boundary
test с fake native resources, не запуск OMX decoder на LDPlayer.
Полные dev и enterprise debug suites: **722 tests каждый, 721 passed /
1 skipped / 0 failures / 0 errors**, dev debug compile. Backend targeted
**40 passed** (один существующий FastAPI deprecation warning), frontend
**71 suites / 537 passed**, TypeScript и targeted ESLint passed; legacy ESLint
config warning сохранён. Configured candidate, installed version и remote
performance acceptance учитываются отдельно.

### VIDEO-I05 · P1 acceptance · PH025 и границы motion probe, 1 октября

Пользователь подтвердил картинку в браузере, но сообщил, что одиночный поток
в карточке остаётся слайд-шоу. Требование: примерно 20–30 FPS на движущемся
экране; reported hardware — 2 CPU / 2 GB, display 540p. Это operator evidence,
не измерение частоты браузерного draw. CUA URL policy продолжает блокировать
наш visual QA; никакого обхода или нового browser screenshot не было.

Два JSON-среза **00:47:18 / 00:47:38 UTC+5**: 19 total / 14 online,
все online APK сообщили not_streaming. Эти срезы не оценивают активный FPS.
Затем отдельный authenticated viewer подключён к **auto-ph-025**, installed
**1.2.34-dev**, через backend loopback 18080. Android ingress/туннель не менялись.
За **01:01:54–01:02:30** получено 8 packets, из них 6 pictures;
APK snapshot: capture=6, rendered=6, encoded=6, local WS accepted=8,
rejected=0, encoded FPS drops=0. Неподвижный экран не был motion benchmark.

Первый compound shell motion probe не доказал движение: metacharacters
запрещены существующим shell boundary, helper не сохранил полный API error.
Его 12 pictures и пустой output не считаются successful motion acceptance.
Никакой shell validation для этого теста не ослаблялась.

Исправленный probe **01:08:48–01:09:24 UTC+5** использовал отдельные команды
`cmd statusbar expand-notifications` и `cmd statusbar collapse`, с возвратом
шторки; API вернул completed output без error. Apps/accounts/settings не
менялись. Received **28 packets / 395258 bytes, 26 picture packets**;
APK snapshot: **capture=26, rendered=26, encoded=26, WS accepted=28 /
395258 bytes**, rejected=0, capture/render/encoder errors=0 и encoded FPS
drops=0. Пятьсекундные окна pictures: **3, 5, 3, 5, 10, 0, 0**.
В этом конечном срезе каждый произведённый encoded picture дошёл до нашего
viewer. Недостаток непрерывных кадров нельзя приписать потерям этих packets
в Cloudflare/Tuna или исправленному VIDEO-I04: его drop counter здесь zero.

Всего считались headers/NAL types/bytes; pixels и видеозапись не сохранялись.
Закрывался только наш viewer; global STOP не отправлялся, teardown решает
server viewer ownership. Один отсутствующий Prometheus queue-drop series не
подменяет end-to-end receipt; вывод основан на согласованных session counters.

**Открыто:** короткая шторка не является 30-second continuous-motion workload,
полный FPS нельзя считать как 26/35 и сравнивать с target во время движения.
Нужны continuous motion, timestamps по кадрам и capture/render/encoder/wire/
browser draw rates на одном session/device/profile. Source FPS fix в исходном
прогоне на удалённый APK ещё не установлен. Фиксированный 720p capture и CPU
ImageReader→Bitmap→Canvas bridge требуют отдельного performance benchmark.
Следующий scope — готовые Android MediaProjection/MediaCodec Surface tools,
GPU bridge с проверяемым fallback, codec caps и атомарный geometry/input
contract; не произвольное подключение нового PC Agent и не CSS-only resize.

**Адресный canary после fix:** configured APK 1.2.35-dev / 10235 source
`a907736`, прежние package/signer, signed discovery v27. Managed artifact hash
проверен перед единственным PH025 grant. Receipt **01:27:44 UTC+5** completed,
installed_version_code=10235, recovered_after_process_restart=true. Readback
**01:39:53** подтвердил свежий online heartbeat с новой версией. Global
android channel и GitHub manifests не менялись. Следующий short motion probe
получил 20 pictures / 22 packets / 251168 bytes; оба telemetry samples остались
со старым heartbeat, поэтому end-to-end stage equality здесь не утверждается.
Пользователь снова увидел slideshow на PH025 после canary. Это не FPS acceptance.

**Browser FPS follow-up:** decoder считает validated picture access units и
успешные canvas callbacks за последнюю monotonic секунду отдельно. Idle окна
затухают до zero, новую session нельзя смешать с предыдущей; bounded 1024
timestamps показывают lower bound при насыщении. Пять новых regressions,
полный frontend 71 suites / 542 tests, TS/targeted lint passed. Fake codec
tests не заменяют настоящий browser draw; visual QA остаётся blocked.

**CI integrity:** backend `a907736` failed generated schema check после
optional counter. Reproduction failed до regeneration, после `--check`
passed; endpoint catalog не изменился. Frontend/Android CI source success.
Full backend tests на failed run не запускались; последующий head отдельно.
Source `4c79ef6` завершил все обязательные backend/frontend/Android jobs success,
preview deploy skipped. Его compiled UI запущен на 3015 → UI 3020 / API 18080
в **01:52:06**, source/process/API proof отдельно от blocked visual acceptance.

**GPU source follow-up:** opt-in debug SurfaceTexture/EGL bridge подаёт raw
producer texture в encoder Surface без CPU RGBA readback/Bitmap copy. Все GL
resources принадлежат одному thread; stop не уничтожает codec во время swap.
Counter gate закрывается до reset и не учитывает duplicate producer timestamps.
Четыре новые encoder resource regressions failed на `4c79ef6`: configure/start
failure, codec stop exception и repeated stop оставляли owned resources.
После исправления проходят вместе с raw gate/GL startup/fallback/owner-order
fixtures. Native EGL, реальный FPS и читаемость fixtures не удостоверяют.
Default path остаётся CPU, новый configured GPU APK и device acceptance
учитываются по [отдельным gates](../../operations/VIDEO-CADENCE-CANARY.md).


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

[Sanitized evidence](../2026-10-01/PH025-GPU-CANARY-EVIDENCE.json) содержит
artifact facts, все секундные окна, dated heartbeat samples и comparison;
без video pixels, credentials, root logs и signed grant. Source `5118525`
завершил обязательные GitHub backend/frontend/Android jobs success; preview
deploy skipped. Android configured build повторно выполнил по 735 tests обеих
flavors (734 passed / 1 skipped), compile и artifact checks прошли. Эти тесты
не меняют неуспешный native performance gate.

**Дополнительный source risk:** backend `VideoStreamQueue` при congestion
удаляет non-IDR frames без проверки reference dependency. Transport limits
нужно сохранять, а reference loss завершать whole chain recovery до fresh
IDR, не продолжать произвольными delta frames. В текущем PH025 probe такой
drop не установлен; это отдельная gate перед overload/mass acceptance.

### APK-I01 · P1 · stdout/stderr и пределы root-команд

**Source follow-up:** [BoundedProcessRunner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/BoundedProcessRunner.kt)
читает stdout/stderr одновременно, сохраняет не более 256 KiB / 1 KiB для shell
и дочитывает лишние байты, чтобы не заполнить pipe. Mutex ограничивает один
runner call двумя активными readers; в idle reader threads нет. Один monotonic
deadline 5 s охватывает execution и output EOF, cancellation закрывает streams
и напрямую принадлежащий process. Cleanup grace проверяет reader/process exit;
это не доказанное завершение всех descendants Android `su` daemon.

Полный exit с кодом !=0 остаётся явной ошибкой с exit code, без command/stderr
в общем журнале. Timeout/read failure и oversize stdout — incomplete outcome:
DAG не повторяет команду и не идёт в fallback даже при `fail_on_error=false`.
Cancellation также не превращается в пустой успешный output. Spawn failure
отделён от ошибки после spawn. На исходном коде два pipe regressions failed;
после исправления проходят с теми же ограниченными pipes. Дополнительно проверены
1 MiB в каждом stream при retained budgets 1024/128 bytes, частичные UTF-8 reads,
nonzero exit, read failure, cancellation и EOF deadline после process exit.

Production artifact и remote root cleanup требуют отдельной проверки;
Windows/JVM pipes не равны поведению каждой Android `su` реализации.
Local full validation: dev и enterprise debug **702 tests каждый: 701 passed /
1 skipped / 0 failures / 0 errors**; dev debug APK compiled. Это unconfigured
debug verification artifact, не новая версия для ручной установки или OTA.

**Source finding, не доказанная причина старого black screen.** В `shellExec`
сначала вызывается `waitFor(5 s)`, потом читается stdout и stderr. Команда с
большим выводом может заполнить pipe до своего завершения. Кроме того,
`readText().take(256 * 1024)` сначала создаёт полную строку; это ограничивает
возвращаемый текст, но не объём чтения/аллокации. `stderr.readText().take(1024)`
имеет то же свойство. Обработка output после wait не покрыта общим read deadline.

Android [Process reference](https://developer.android.com/reference/java/lang/Process)
прямо описывает риск блокировки при несвоевременном чтении ограниченных pipes.
Наличие пятсекундного timeout не делает большой вывод успешно доставленным.
На удалённые устройства для воспроизведения не отправлялись большие команды.

**Следующий fix:** один process runner с concurrent drain двух streams,
bounded UTF-8 retained output, полным execution/read deadline, cleanup/join
reader на timeout/cancellation и проверкой exit code. Использовать существующий
bounded-drain опыт LogcatCollector, сохранив shell validation и root boundary.
Fixture обязана проверять большой stdout, большой stderr, ненулевой exit,
медленную выдачу, EOF, cancellation и отсутствие живого child/reader после timeout.

### APK-I02 · P1 · целостность и конкуренция hierarchy dump

**Source follow-up после `3148668`:** общий `/sdcard` path и `killall` удалены.
Mutex охватывает создание private cache file, process output, parsing и unlink.
Каждый dump получает свой путь, shell-quoted без operator input; процесс читает
оба pipes concurrent с execution/read deadline 4 s и retained stdout 512 KiB.
Oversize/incomplete output не используется для поиска первого элемента.

[UiHierarchyXml](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/UiHierarchyXml.kt)
отвергает DTD/entity declarations и external resolution. SAX preflight проверяет
полный XML, depth ≤64 / element count ≤10,000 до построения DOM; обход DOM также
ограничивает полное количество узлов. DOM и XML существуют только в одном poll,
все XPath candidates этого poll используют один document. Персистентный snapshot
cache и публичный hierarchy endpoint не добавлены.

Fixtures: partial 7-byte reads, разные private paths, invalid suffix с valid
first node, oversize output, concurrent ownership, cancellation/unlink. Android
XML parser через Robolectric API 28: Unicode/predefined entity, DTD/internal/
external entity rejection, byte budget, root, node и depth limits, включая
15,000 вложенных nodes. Полные dev/enterprise debug suites: **713 tests каждый,
712 passed / 1 skipped / 0 failures / 0 errors**, debug compile completed.

**Оставшийся gate:** runner завершает directly owned `su` process, но descendants,
SELinux/root utility доступ к private cache path и inode cleanup после timeout
нужно принять на реальном device. Retained XML 512 KiB — не hard limit записи
нативной утилитой во временный файл. Глобальный kill не возвращается как обход.
Этот source fix ещё не подтверждает визуальный XPath-inspector или installed APK.

**Source finding.** `dumpUiXml` использует общий `/sdcard/sphere_ui_dump.xml`,
глобальный `killall uiautomator`, wait до чтения и один `Reader.read(buf)` на
512×1024 **символов**. Single read не гарантирует EOF, а символы не равны
байтам. Проверка подстроки `<hierarchy` не доказывает целостность XML. Это
непригодный готовый контракт для одновременных script и inspector запросов.

**Следующий fix:** serialized ownership одной inspection сессии, private
уникальный dump path, byte/count/depth budgets, явные truncated/timeout/invalid
статусы, scoped child cleanup вместо общей команды kill. DOM factory сейчас
создаётся без явной политики DTD/external entities; до приёма XML от удалённого
API должны быть запрещены DTD/external resolution. Существующий dump локальный;
удалённая XXE эксплуатация этим аудитом не продемонстрирована.

**Приёмка:** fixture с частичными чтениями, XML выше лимита, неполным XML,
DTD, двумя конкурентными запросами, отменой; live canary на launcher/SystemUI
и отдельной app с семантическими узлами. Повтор root-действия после timeout
не разрешается без reconciliation.

### APK-I03 · P2 · потери логов и жёсткие бюджеты

**Source finding.** `queue.offer(entry)` не проверяет отказ; writer disk errors
идут в stderr. Общая telemetry не сообщает число потерянных записей. Сообщение
и stack trace перед enqueue не имеют собственного byte budget. Rotation проверяет
текущий размер до append, поэтому одна большая запись может превысить 2 MiB;
4096 строк не являются фиксированным memory budget. Nominal retention не следует
называть жёстким пределом 10 MiB или хранением всех действий за неделю.

**Следующий fix:** лимит одной записи в байтах, dropped/queue/write-error
counters без log recursion, severity-aware bounded retention, disk pressure
test и crash/lifecycle priority. Сохранять UTC timestamp/offset, monotonic
duration и upload watermark для различения нового события и повторённого хвоста.
Нужны реальные quota/retention правила на backend и проверяемая cleanup job;
еженедельная очистка здесь не объявляется реализованной.

### APK-I04 · P1 · отсутствие root не должно срывать запуск агента

**Воспроизведённый source finding на `e3dc143`.** Конструктор singleton
`AdbActionExecutor` вызывает `Runtime.exec("su")` до первой команды. Компонент
инжектируется в `SphereAgentService` и `CommandDispatcher`. Если binary `su`
отсутствует, constructor выбрасывает IOException; root-dependent input становится
ненужным prerequisite для создания service dependency. Это не доказанная причина
LDPlayer cold-start/remote disconnect: там root может быть доступен.

Три regressions с отсутствующим `su` failed до fix: construction, close без
действий и failure только при явной privileged action. Follow-up откладывает
spawn до root-команды; unused close не запускает process. Cleanup и смена session
сериализованы одним lock; ссылки на failed pipe инвалидируются независимо от
`Process.isAlive`. Неопределённое delivery не replayed, следующая явная команда
может открыть новую session. Недоступный root остаётся ошибкой requested action,
а не фиктивной успешной root capability. Инициализация не добавляет idle processes
или reader threads.

Local full validation APK-I04: dev/enterprise debug **719 tests каждый:
718 passed / 1 skipped / 0 failures / 0 errors**, `assembleDevDebug` completed,
3m 33s. Шесть lifecycle/availability tests и прежние unknown-delivery/DAG
regressions проходят. Это source compile, не production APK, OTA или реальная
проверка root grant на телефоне.

**Оставшиеся ограничения:** persistent input session пока не дренирует свои
stdout/stderr, в отличие от bounded one-shot runner APK-I01/I02. Например,
многословные `monkey` commands могут заполнить pipe; это отдельный lifecycle fix,
который нельзя считать закрытым lazy spawn. `su` spawn/grant и synchronous stdin
write не имеют доказанного общего deadline; отсутствие prompt/blocking требует
root/non-root canary. Успешный flush означает доставку в pipe, не исполнение
Android action. Close ждёт directly owned process до 250 ms после записи exit;
это не общий timeout close и не подтверждённое завершение descendants.

### VIDEO-I01 · P1 перед mass test · разные режимы имеют общий capture demand

**Source finding.** MultiStreamGrid и detail используют одинаковый viewer;
новый viewer lifecycle не несёт профиль FPS/resolution/bitrate. Нет arbitration
качества между несколькими зрителями одного device. Нельзя считать fleet grid
экономичной только потому, что canvas занимает мало места на странице.

**План контракта:** `overview` и `interactive` как явные запросы backend,
aggregation demand по device и viewer lease. Один capture ownership, debounced
смена профиля, установленный effective profile с причиной и временем. Для
overview исследовать небольшой поток либо выборочные изображения; для detail —
непрерывный H.264 и быстрый input feedback. Переключение не должно сбрасывать
игровое состояние или переиспользовать запрещённый projection token.

FPS/разрешение/битрейт подобрать на canary, а не объявить обещанными значениями.
Входные скриншоты будущего AI — отдельный consumer contract; не направлять в
браузер все AI кадры и не привязывать работу automation к открытой вкладке.

### VIDEO-I03 · P1 · gesture ownership и смена геометрии кадра

**Baseline `356bd35`, 1 октября.** Pointer gesture хранит только x/y. Если между
down и up приходит кадр 720×1280 вместо 1280×720, endpoint получает ложный swipe,
составленный из двух координатных пространств. Второй pointer может заменить
start, завершить или отменить чужой gesture. Четыре regressions failed до fix;
обычный gesture и обновление кадров того же размера проходят на baseline.

Source follow-up `DeviceStream` закрепляет pointer ID и frame width/height.
Смена canvas dimensions, stale state, decoder reset/configuration, reconnect,
server control error и unmount отменяют старый gesture. Up/cancel/lost capture
другого pointer не исполняют input и не отнимают ownership. Новое движение
можно начать после fresh frame. Не отправляется дополнительная команда, retry
или APK update; существующий coordinate wire contract сохраняется.

Полный frontend: **71 suites / 536 tests passed**, TypeScript и targeted ESLint
passed с прежним eslintrc deprecation warning. Восемь новых scenarios: dimension
change, pointer release/replace/cancel ownership, normal same-size frames, lost
capture, stale→fresh и reconnect→fresh. Resize и multitouch проверены React/WS
fixtures; реальная rotation/system input требуют отдельного canary. Это не
переход на native capture и не защита от Android-side geometry/session mismatch.

### VIDEO-I02 · P1 acceptance · static screen, stage correlation и плавность

В существующем viewer 10 s без draw переводит состояние в stale. Это не
доказательство offline: статичный экран и broken capture нужно различать по
независимым heartbeat, capture health, encoder output, relay ingress и draw.
Локальная WS queue accepted не означает server received. Между узлами нет
подтверждённой сквозной frame correlation, поэтому точная network/delivery
latency не выводится из их абсолютных timestamps без clock bounds.

**Приёмка:** static screen и движущийся экран отдельно; время до первого draw,
browser draw FPS/jank, decoder queue, memory, encoded bytes, drops/recovery,
input roundtrip. Сначала один remote canary, затем bounded 2/4/14/20–30 views
с фактическими версиями APK и именованным ingress. Предел 64 tiles — UI capacity,
не доказанный throughput. Потери ACK, idle, tab hidden/resume, reconnect и второй
viewer проверять отдельно от happy path. Running не считается passed.

### UI-I01 · P2 feature · визуальный инспектор отсутствует

Не добавлять кнопку, которая обещает готовый UIAutomator2, пока нет endpoint и
APK capability. Нужны capability state, snapshot ID, device/session ID,
observed_at, display size/rotation/insets, package/window, nodes с bounds,
truncation/count/depth, permission/timeout/unsupported причины. Запрос только
по действию оператора; ограниченный refresh при открытом inspector, без постоянного
dump на каждом APK heartbeat.

Frontend: дерево, поиск resource-id/text/class, выбор node, hover/highlight,
копирование XPath. Bounds переводятся из физического display в видео, затем
через contain/cover/letterboxing в canvas. Highlight не является кликом;
исполнение click требует отдельного RBAC и свежего snapshot. При смене rotation,
session/device, просроченном snapshot или неподтверждённом display mapping overlay
и input блокируются. Sensitive/password text не сохраняется в общем журнале.

**Ограничение Android:** custom rendered app может не публиковать отдельные
семантические узлы для своих игровых кнопок. Android
[AccessibilityNodeProvider](https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeProvider)
описывает предоставление virtual hierarchy самим view. Вывод: XPath не может
гарантировать все игровые элементы без этой структуры. Отсутствие узла нужно
показать честно; CV/OCR относятся к отдельному будущему пути.

## Готовые решения: что исследовано, что интегрировать

| Решение | Вывод для Sphere | Лицензия / происхождение |
| --- | --- | --- |
| [OpenATX uiautomator2](https://github.com/openatx/uiautomator2) | Готовые UI inspection/XPath patterns; Python wrapper использует device HTTP service, стандартный bootstrap описан через ADB. Сам wrapper не становится Android-only интеграцией автоматически | [MIT, © 2017 openatx](https://github.com/openatx/uiautomator2/blob/master/LICENSE) |
| [OpenATX device server jar](https://github.com/openatx/android-uiautomator-server-jar) | Кандидат внутреннего on-device engine: upstream описывает `app_process` запуск и JSON-RPC. Возможный локальный root bootstrap из APK — инженерная гипотеза, пока не принято на LDPlayer/Android/OEM. Loopback-only, не публичный RPC | [MIT, © 2015 xiaocong](https://github.com/openatx/android-uiautomator-server-jar/blob/master/LICENSE) |
| [Appium UiAutomator2 driver](https://github.com/appium/appium-uiautomator2-driver) | Полезен как reference/test harness. Официальный driver содержит host ADB и port forwarding; не вводить его как обязательный workstation dependency | [Apache-2.0, JS Foundation and contributors](https://github.com/appium/appium-uiautomator2-driver/blob/master/LICENSE) |
| [AndroidX UI Automator](https://developer.android.com/training/testing/other-components/ui-automator) | Официальные test/inspection API и wait/stability/multi-window contracts; test library не заменяет permission/bootstrap/lifecycle архитектуру агента | Google AndroidX; перед bundling проверить выбранный Maven artifact и notices |

Исходники этих библиотек не скопированы в Sphere в этом проходе. Перед reuse
зафиксировать upstream commit/release, SHA256 artifact, transitive licenses и
copyright notices. Если engine требует root/shell privilege, normal non-root
phone получает отдельную Accessibility capability или явный unsupported, а не
обещание одинаковых возможностей. Внешняя workstation dependency не добавляется.

Решение по видео пока сохранить существующий MediaCodec/WebCodecs тракт,
сначала измерить и устранить конкретные дефекты. Менять весь transport на
WebRTC/MJPEG/VNC без A/B и измерения не требуется: это отдельное решение после
профилей, backpressure и latency evidence, с оценкой TURN/relay cost и ingress.

## Следующие атомарные этапы

### Уточнённый продуктовый контракт — запрос владельца 30 сентября

| Режим | Что должен видеть оператор | Что не считается выполнением |
| --- | --- | --- |
| Одна выбранная машинка / fullscreen | Непрерывный H.264 видеопоток с реальными пропорциями захвата; native размер, либо явно обозначенное масштабирование с сохранением пропорций. Веб масштабирует изображение через contain; пиксельные размеры и mapping доступны | Периодическое обновление screenshot, fixed 16:9 независимо от экрана, target 30 FPS без измеренного draw |
| Большой парк / 64+ окон | Ограниченные по частоте и размеру snapshot previews с независимыми presence/freshness сигналами; без 64 полноценных decoder loops по умолчанию | Старый MultiStreamGrid с тем же видеопотоком, только уменьшенный CSS; обещание 64+ throughput по числу tiles |
| XPath inspection | Явный режим выбора узла, outline и подробная структурированная карточка рядом: все доступные безопасные attributes, bounds, ancestry, XPath, snapshot/device/session/time/source. Клик в этом режиме выбирает узел и не отправляет tap в Android | Пустая кнопка, придуманные nodes, XPath для игровых pixels без семантического дерева, вызов actions от hover |
| Debug automation, следующий этап | Коррелированные run/node/action events и overlay найденного UI/CV/pixel target с состоянием результата; отдельное включение и ограниченный retention | Объявление debug playback по логам, не связанным со snapshot/frame/session; постоянно включённая запись всех кадров |

Native dimensions и одинаковые пропорции — разные критерии. Изменение размера
capture требует одновременного input mapping contract: нельзя убрать fixed 720p
и продолжить масштабировать taps через старые 1280/720 constants. Device rotation,
Android 14 app-window sharing, insets и codec-supported geometry получают отдельные
gates; `onCapturedContentResize` не заменяется повторным использованием consent token.
Основание: [официальный MediaProjection guide](https://developer.android.com/media/grow/media-projection).

Первоначальный source `VirtualDisplayManager.createConfig` принудительно выбирал
16:9/9:16; default CPU path сохраняет этот legacy contract.
Например, экран 1920×1200 имеет ratio 1.6, а capture 1280×720 — 1.777… .
Это конкретный geometry gap, который нужно исправлять вместе с input mapping,
а не одиночной заменой CSS или width/height. 1 октября source `2bed596` / 1.2.38
связала native размер **только opt-in GPU canary** с live gesture mapping;
default CPU/DAG coordinates не заменены. Native 960×540 format принят на двух
canary, smooth video/quality/Android 14 geometry пока не приняты. Текущие факты:
[540p control и ограничения](../../operations/VIDEO-CADENCE-CANARY.md#native-540p-и-независимый-android-control-1-октября).

**Geometry implementation gates, 1 октября:** `H264Encoder.start` принудительно
задаёт `AVCLevel31`, выбирая encoder by MIME без negotiated geometry. Просто
подставить native width/height недостаточно. Android
[VideoCapabilities](https://developer.android.com/reference/android/media/MediaCodecInfo.VideoCapabilities)
публикует alignment, size/rate support и bitrate range; reported performance
estimate не является измеренной гарантией плавности. План Sphere: negotiated
native-or-explicit-scaled профиль, подтверждённые codec dimensions и причины
fallback, затем atomic geometry/input contract и canary на движущемся экране.
Новый native размер включён в configured debug GPU canary 1.2.38, но universal
codec geometry negotiation и Android 14 app-window/insets acceptance остаются
открытыми. Старые скриптовые 720p coordinates не изменены.

Визуальный инспектор должен ограничивать sensitive text и размеры XML; «вся
информация» означает все доступные разрешённые свойства, не password values,
содержимое скрытых окон или несуществующие accessibility nodes. Данные automation
в будущем не должны зависеть от того, открыт ли браузер оператора.

Amnezia/VPN upstream adapter, protocol updates, rotation triggers и переход от
game-specific сущностей к общей project/workspace основе **отложены по явному
запросу владельца**. Текущий этап не меняет VPN или удаляет game accounts/pipelines.
Когда этот этап начнётся, он потребует отдельного upstream/license/update contract;
сейчас это граница scope, не начатая интеграция.

### Порядок с зависимостями

Сначала воспроизводимые дефекты APK-I01/I02/I04 и metadata/mapping видео; затем
viewer demand ownership и lightweight snapshot path, protected UI snapshot
и дерево/outline. После canary — массовая проверка. Debug playback следует
за inspection contracts. UI и backend не обещают capability, пока установленная
APK не поддерживает и не подтвердила её. Код, собранный артефакт, опубликованный
manifest и установленная версия отслеживаются раздельно.

1. APK-I01/I02/I04: unit/process regressions → bounded runner/dump ownership и
   lazy root lifecycle →
   Android CI → один root remote canary. Не публиковать новый stable APK только
   по JVM tests: signer, version/manifest/hash и фактическая OTA установка отдельны.
2. APK-I03: log byte budgets/drop counters и server retention; воспроизвести
   storage pressure, reconnect/offline upload и повтор receipt без нового action.
3. VIDEO-I01: bounded profiles и viewer lease ownership, без смены остального
   работающего transport; canary detail + grid одновременно.
4. UI-I01: защищённый snapshot contract, затем actual tree/overlay/XPath;
   root/normal-phone capability matrix и mapping tests до live input.
5. VIDEO-I02: конечный 20–30-device stream + safe script run с сохранёнными
   task/pipeline receipts; stop/recovery, ресурсные измерения и точный итог.

Дизайн и operational UI продолжаются по
[web audit](../2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md). Prometheus/Grafana
реально подключены, но их наличие не означает готовые панели всех Android
стадий, RPS/p95, tracing, fleet incident timeline или полную централизованную
доставку логов. Каждая такая интеграция получает собственный источник и gate.
