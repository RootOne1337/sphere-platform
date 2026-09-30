# Android: наблюдаемость, два режима видео и UI-инспекция

**Дата проверки:** 30 сентября 2026, Asia/Yekaterinburg.<br />
**Source baseline:** `f092a16`; frontend selection follow-up `3132afc`.<br />
**Статус:** аудит кода и план приёмки; новый APK этим проходом не выпущен.

**Android source follow-up:** APK-I01 исправлен в `3148668`: concurrent bounded
process runner и запрет продолжения DAG при неопределённом результате shell;
обязательные GitHub jobs success. Последующий APK-I02 source follow-up добавляет
private serialized dump и validation. Исходные наблюдения ниже сохранены как
baseline. CI и device acceptance отмечаются раздельно; runtime APK ещё не заменён.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Device inspector](WEB-DEVICE-INSPECTOR.md) ·
[Stream stage audit](../2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) ·
[OTA / remote gates](../2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md) ·
[Каталог](../../README.md) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Вывод и границы проверки

Рабочий транспорт уже передаёт H.264, а веб декодирует его через WebCodecs и
рисует canvas. Скрипты умеют искать UI-элементы, включая XPath. Это не означает,
что реализованы отдельный экономичный fleet-профиль, гарантированная плавность
при 20–30 потоках, полноценный UIAutomator2 server или визуальное дерево с
выделением элементов. Эти возможности требуют отдельных контрактов и приёмки.

Подтверждение remote video в предыдущих опытах сохраняется. Оно не доказывает
доставку обновления каждому APK или отсутствие последующих обрывов. Последний
принятый runtime: API `85c8014`, UI `3132afc` на `3015 → UI 3018 / API 18080`;
срез 22:29:40 — 14 online / 5 offline / 0 connecting. Ранее конечная
проверка восстановления 21:40:40–21:41:40 показывала 14 online / 5 offline.
Точные условия и первый неуспешный
post-restart замер находятся в CURRENT-STATE; здесь они не заменены SLA.

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

Source `VirtualDisplayManager.createConfig` принудительно выбирает 16:9/9:16.
Например, экран 1920×1200 имеет ratio 1.6, а capture 1280×720 — 1.777… .
Это конкретный geometry gap, который нужно исправлять вместе с input mapping,
а не одиночной заменой CSS или width/height. Native capture пока не принят.

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

Сначала воспроизводимые дефекты APK-I01/I02 и metadata/mapping видео; затем
viewer demand ownership и lightweight snapshot path, protected UI snapshot
и дерево/outline. После canary — массовая проверка. Debug playback следует
за inspection contracts. UI и backend не обещают capability, пока установленная
APK не поддерживает и не подтвердила её. Код, собранный артефакт, опубликованный
manifest и установленная версия отслеживаются раздельно.

1. APK-I01/I02: unit/process regressions → bounded runner/dump ownership →
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
