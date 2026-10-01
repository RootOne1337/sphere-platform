# Одиночный видеопоток: capture canaries и критерии приёмки

**Дата:** 1 октября 2026, Asia/Yekaterinburg.<br />
**Scope:** один явно выбранный Android, отдельный APK и собственный viewer;
не массовая замена парка, не подтверждение 20–30 FPS по unit tests.

[Текущее состояние](CURRENT-STATE.md) ·
[APK/video audit](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md) ·
[Android guide](../android-agent.md)

## Актуальный follow-up: planar input и статичный экран

APK **1.2.39 / 10239**, source `8a66afe`, установлен адресным OTA на PH010 и
PH025. GPU/Surface control ниже сохраняется как история измерений. Новый debug
canary использует RGBA ImageReader → reused I420 ByteBuffer → тот же Google AVC;
wire protocol и WebCodecs decoder не заменены. PH010: **30 и 29,9 pictures/s**
в двух настоящих десятисекундных capture/wire окнах, 462 pictures независимо
декодированы без ошибок. PH025: **1,9 / 1,7 pictures/s**, reported source **5 Hz**,
паузы 3–4 s в arrival имеют близкие producer PTS gaps. Это не подтверждение
удалённого профиля 10–15 FPS и не полная локализация источника пропусков.

[Методика, conversion CPU и дальнейшие gates](CODEC-INPUT-CANARY.md) ·
[Allowlisted capture/OTA/decode evidence](../audits/2026-10-01/PH010-PH025-PLANAR-CAPTURE-EVIDENCE.json).

Compiled single-device UI **b9a3f29** на **3015** сохраняет новый tap/swipe,
когда изображение текущего OPEN socket старше 10 s. Banner age не становится
video disconnect: первым условием остаётся успешный draw текущей сессии.
Error/transport timeout/decoder recovery/reconnect блокируют действия; held
gesture отменяется, новое действие не повторяется автоматически.
[Контракт и 576 frontend regressions](STATIC-STREAM-INPUT.md).
Browser visual/input-to-visible acceptance нового исправления пока открыта.

## GPU canary: исходная переменная эксперимента

Существующий путь CPU: VirtualDisplay → RGBA ImageReader → Bitmap copy →
Canvas → encoder Surface. Новый canary: VirtualDisplay → SurfaceTexture
external OES → recordable EGL → encoder Surface. Это готовые Android
MediaProjection/MediaCodec/OpenGL ES API, а не новый host agent или изменение
туннеля. GPU bridge не делает CPU pixel readback, не создаёт Bitmap на кадр
и не отправляет синтетические копии неподвижной картинки ради «30 FPS».

В обычной сборке `STREAM_GPU_BRIDGE=false`. Только explicit debug build с
`SPHERE_STREAM_GPU_BRIDGE=true` выбирает GPU startup; release-shaped tasks
с этим canary flag отклоняются. Размер 720p, 30 FPS encoder target и 1.5 Mbit/s
остаются прежними для проверки одной переменной. Это не конечный quality
profile; native 540p/aspect/input mapping и codec capabilities отдельные gates.
Для чёткости запрещено считать успешным тест, где target FPS достигается
за счёт непригодного для чтения изображения.

## Ownership и fallback

- EGL/context/SurfaceTexture/shader resources создаются и удаляются на одном
  HandlerThread. Input encoder Surface заимствован у H264Encoder.
- SurfaceTexture transform matrix учитывает producer crop/orientation.
  Presentation timestamp берётся из реального producer buffer; duplicate/
  non-increasing callbacks не считаются новыми pictures.
- Raw FPS gate действует перед GL submission; encoded access units не
  фильтруются. Capture/render/error counters остаются раздельными.
- Нет recordable EGL/OES/presentation-time support или shader init failure:
  partial native resources освобождаются до startup fallback на CPU; первый
  VirtualDisplay ещё не создан, projection token повторно не используется.
- Startup timeout или VirtualDisplay failure прекращает попытку. Не выполняется
  silent mid-session fallback/retry. Runtime GL failure останавливает session.
- Stop сначала освобождает VirtualDisplay, немедленно закрывает counters gate,
  затем ставит GL cleanup и codec stop в очередь owner thread после текущего
  draw. Main thread не ждёт native swap. Зависший GPU driver остаётся device
  failure, а не обещанием принудительного безопасного освобождения native calls.
- H264Encoder releases codec и input Surface независимо от stop exception;
  partial configure/start failure тоже освобождает принадлежащие ресурсы.
  Encoder callbacks старого capture generation не попадают в новую session.

## Воспроизводимый workload

Debug APK содержит private `StreamCadenceProbeActivity`; в release source set
её нет, component `exported=false`, отдельный task, без recents. Через уже
авторизованный локальный Android root shell можно явно запустить activity:

```text
am start -W -n <installed-pilot-package>/com.sphereplatform.agent.debug.StreamCadenceProbeActivity
```

Она показывает двигающуюся полосу, маркер, мелкий текст и линии 30 секунд;
использует настоящий display vsync через Choreographer и затем закрывается.
Apps/accounts/settings не изменяются. On pause frame callback удаляется.
Без успешного результата запуска и измеренного окна движения test не считается
continuous-motion acceptance. Сам workload может нагружать слабое устройство;
результат относится к указанному разрешению, CPU и producer workload.

Собственный viewer считает packets, picture access units, bytes и timestamps
по секундным окнам. Учитываются fresh APK capture/render/encode counters;
stale telemetry не выдаётся за согласованность всех стадий. Закрывается только
собственный viewer, global STOP не отправляется. Параллельный operator viewer
и его restart отмечаются в записи теста.


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

## Сравнение той же GPU сборки и измерение стадий, 1 октября

На локальной PH010 установлен **тот же APK 1.2.36 / source 5118525** одним
адресным OTA, completed + online 10236. Тот же 52-second motion workload
получил **65 picture packets за 20 s (3.25/s)**, 110 packets / 745483 bytes
за весь viewer interval, GPU marker найден, CPU fallback отсутствует.
Следовательно, remote display mode 5 Hz **не единственная причина**:
общий capture/encode path остаётся медленным даже при local mode ~60 Hz.
Heartbeat capture=87 / render=85 / encode=83, rates=4, errors/rejected=0 —
один delayed snapshot, не точная сверка всего viewer interval.

Два отдельных viewer cycles PH025 получили pictures; первые pictures через
5.625 и 4.704 s, Android PID 31976 до/после одинаков. Operator viewer мог
работать параллельно: это ограниченное recovery evidence, не leak-free или
изолированный lifecycle benchmark. Global STOP не отправлялся.

Три read-only echo commands дали local PH010 **375/250/250 ms**, remote PH025
**313/172/187 ms**. Это полный REST/queue/Android root execution/return путь,
**не ICMP ping и не input-to-visible latency**; высокая video задержка
не объясняется этим коротким срезом command RTT.

Source **1.2.37 / 10237** добавляет instrumentation, без изменения bitrate,
размеров, выбора codec или callback thread: actual MediaCodec name в startup
log и GPU texture/draw/Surface swap mean/max раз в 5 s. Native calls измеряются
monotonic clock; aggregate bounded, нет per-frame history/pixels/new timer.
Skipped submissions не получают вымышленные draw/swap samples; stop flush
однократный, отдельные counters и negative/capped durations покрыты tests.
Это измерение вызовов, не producer-to-browser latency. Конфигурированная
canary APK и native readback проверяются отдельно после сборки; default GPU
и массовая OTA остаются закрыты до performance/quality acceptance.

Source validation: streaming suite passed; обе debug flavors **739 tests каждая,
738 passed / 1 skipped / 0 failures / 0 errors**, dev debug compiled, 3m51s.
126 distinct relative documentation targets существуют. Configured artifact
validation и native timing evidence не подменяются этим JVM результатом.

**Установленный 1.2.37 native timing:** адресный PH010 OTA completed + reported
10237; configured source `9455a96`, SHA256
`fef080fd9e3655e8752f781cd59372f6a9c7728c257d74fd5fe79816ad09bc5d`, прежний
pilot signer. Тот же workload: 68 pictures / 20 s (3.4/s), 114 packets /
849412 bytes за 52 s. Actual selected codec `OMX.google.h264.encoder`,
1280×720, target 30, initial bitrate 1500000. Во время движения texture read
mean 0.44–1.77 ms, GL submission 0.36–0.70 ms, **Surface swap 277–306 ms**
по последовательным 5-second windows. Swap включает driver/consumer waits:
это локализованная backpressure на Android encoder input path, **не отдельно
измеренное codec CPU time и не network/browser latency**. После stop короткий
flush также может присутствовать. [Allowlisted evidence](../audits/2026-10-01/PH010-GPU-STAGE-EVIDENCE.json).

**Canary source 1.2.38 / `2bed596`:** opt-in GPU capture сохраняет native размеры
и density (960×540 вместо искусственного 1280×720). Initial bitrate не снижен,
default CPU resolution не изменён. Live gesture использует snapshot capture
geometry и raw physical input; DAG legacy coordinate contract сохраняется.
Inactive capture, resized/rotated source и любой out-of-bounds point отклоняют
целый gesture. Stop инвалидирует mapping. Настроенный APK собран и установлен
на PH010 и PH025; измерения ниже не принимают 20–30 FPS/quality/latency.

## Native 540p и независимый Android control, 1 октября

APK **1.2.38-dev / 10238**, configured source `2bed596`, SHA256
`15c2392be0d8c6e845a84234302d1ccde4b04ed41d3f8b97c38fd76f73c00381`,
8459015 bytes, прежний pilot package/signer, discovery v27 и opt-in GPU flag.
746 tests каждого debug flavor: **745 passed / 1 skipped / 0 failures / 0 errors**;
configured dev build compiled. Backend/Frontend/Android CI этого source success.
Два отдельных addressed OTA — PH010 и remote PH025 — подтвердили completed и
reported code 10238. Existing `android-canary` release использован для PH025;
normal/global channel, stable/latest GitHub aliases не менялись.

| Контроль на PH010 | Размер | Реальный результат | Граница доказательства |
| --- | --- | --- | --- |
| Sphere GPU 1.2.37 | 1280×720 из 960×540 | 68 pictures / 20 s = 3.4/s; swap mean 277–306 ms | Wire count, не browser draw |
| Sphere GPU 1.2.38 | 960×540 | 113 pictures / 20 s = 5.65/s; swap mean 169.62–180.10 ms | Пять последовательных motion windows, quality не оценена |
| Android screenrecord, 8-second limit | 960×540, 1.5 Mbps target | Final MP4: 47 video samples / 7.845044 s = 5.991 FPS | Нет Sphere video WS/backend/tunnel/browser в записи; не статистический simultaneous A/B |
| Android screenrecord, отдельный 3-second limit | 960×540, 1.5 Mbps target | stdout: 18 frames / 3 nominal seconds | Короткий повторный control, не длительный soak |

Второй control также сравнил process `gfxinfo` deltas, пока private motion activity
была foreground: **195 rendered frames / 3.265 s** без recording, **240 / 4.016 s**
в observation interval с recording. Это около 60 draw/s в обоих окнах, тогда как
штатный recording дал около 6 encoded/s. Интервалы включают время API/dumpsys и
границы observation, поэтому не являются точными per-frame render timestamps.
Процессовые counters накопительные; они не доказывают FPS всех приложений.

Контроль локализует недостаток FPS в **Android display-capture/encoding path**:
оно воспроизводится без Sphere video transport. Default codec фактически
`OMX.google.h264.encoder`; shader submission и `eglSwapBuffers` не равны
изолированному CPU encoding time. Нельзя объявить codec единственным виновником:
driver readback/conversion, BufferQueue и consumer waits требуют разделения.
Остальные remote network/input latency риски этим локальным control не исключены.

Первый screenrecord command вышел за APK shell **5-second read timeout**:
получен `execution_read_timeout` через 5.203 s, команда не повторялась. Позднее
подтверждены завершённый MP4 `moov`, число samples/duration и отсутствие recorder
(`pidof` exit 1). Прочитаны только atom headers/container metadata, encoded video
payload не выгружался. Оба конкретных файла тестового pattern удалены с readback;
чужие файлы/приложения/настройки не изменялись. Второй 3-second control завершился
обычно за 3.735 s полного command round trip.

Live click `(384,216)` в локальной 1.2.38 дошёл до private View, которая сообщила
`x=384,y=192`. Y относится к **локальным координатам View** после 24-pixel content
offset, а не к physical display Y. Это подтверждает delivery в test activity,
не абсолютную Y accuracy, не UIAutomator mapping и не input-to-visible latency.
Pure geometry tests покрывают native/scaled/rotation/out-of-bounds contract;
они не заменяют Android 14 app-window/insets/rotation native gates.

**Remote PH025 / 1.2.38:** 52 s viewer получил **81 packets / 470417 bytes**,
GPU marker и actual codec **960×540** подтверждены, CPU fallback не найден.
Private motion launch получил root read timeout, поэтому **motion FPS — unknown**,
а не zero и не passed. Live input не отправлялся после unknown launch. Read-only
reconciliation: online / not_streaming, private activity уже не resumed; это не
ретроспективное подтверждение motion. Android по-прежнему сообщает **5 Hz**.
Stage windows включают GL draw max **3064.61 ms** и texture read max **1126.49 ms**;
данные реальные, но эти окна нельзя представлять как подтверждённый одинаковый
motion workload с PH010. Старые строки до текущего 960×540 startup исключены.

[Allowlisted artifact/OTA/windows/controls evidence](../audits/2026-10-01/PH010-PH025-NATIVE-SIZE-EVIDENCE.json)
содержит только измерения и ограничения, без tokens, signed grant URLs, pixels,
raw app logs или root output. UI `4c79ef6` восстановлен на 3015 → 3020 в
03:35:34 UTC+5; API `85c8014` и tunnels не заменены. Browser review остаётся
blocked, поэтому native packet count не выдан за displayed FPS.

### Следующая проверка по доказанной зависимости

После этого среза оператор подтвердил prior LDPlayer limit **5 FPS** и выбрал
**10 FPS**. Read-only PH025 snapshot **04:00:55 UTC+5** всё ещё сообщает 5 Hz;
restart/application нового лимита не подтверждены. 10 FPS — выбранный владельцем
профиль для управления, не 20–30 FPS acceptance: encoder target 30 не создаёт
новые source pictures сверх actual source rate.

1. На одном remote экземпляре подтвердить/поднять LDPlayer multi-instance FPS
   limit до выбранных оператором 10 и перезапустить; повторить Android display
   mode readback. Для отдельного 20–30 FPS acceptance нужен source rate ≥20. Не
   повышать source rate всего парка, не генерировать duplicate frames для FPS.
2. На том же canary подтвердить видимую private motion activity до сравнения.
   Unknown launch не повторять: сначала проверить текущую Activity и endpoint
   result. Отдельно измерить длительные GL calls на удалённом host.
3. Получить runtime codec list/capabilities и разделить conversion/consumer
   waits. XML объявляет Google AVC encoder; опубликованные historical CTS
   measured-frame-rate numbers не являются benchmark текущего LDPlayer.
   Предпочтение hardware codec возможно только при реально подтверждённой
   capability; обещание 30 FPS по `KEY_FRAME_RATE` не допускается.
4. После native ≥20 pictures/s измерить browser receive/draw, читаемость pattern
   и input-to-visible latency. Только затем менять default capture path и
   normal OTA; fleet snapshot demand и single-device video принимаются отдельно.

## Native CPU control, 1 октября 04:52 UTC+5

На локальном PH010 / 10238 подтверждён idle launcher и отсутствие стрима, затем
один раз запущена собственная debug Activity с движением и возвратом через 30 s.
Foreground подтверждён до измерений и в конце CPU sample серии. Собственный
wire viewer получил **63 реальных pictures за 10 s**, секундные окна —
`6, 6, 7, 6, 6, 7, 6, 7, 6, 6`. Native geometry 960×540, target 30 FPS,
1.5 Mbit/s; codec `OMX.google.h264.encoder`. Четыре stage окна: swap means
154.67–160.91 ms, texture/draw means <1 ms.

Три кратких `top -b -n 2 -d 1 -m 20` snapshots показывают media.codec
92/96/100% **одного ядра**, при total basis 200% для двух guest CPUs. APK — 8%,
SurfaceFlinger — 4–8%; private canary рисуется внутри того же APK процесса,
поэтому 8% не отделяет capture/управление от test UI. Собственные su permission broadcasts observer тоже
расходовали CPU. Это не доказательство, что production idle APK постоянно
расходует 8%, и не isolated codec microbenchmark. Сопоставление с Android
screenrecord control и swap wait усиливает гипотезу software encoding/consumer
limit; thread-level причины и альтернативы ещё требуют проверки.

За то же окно spans arrival и presentation timestamps — 9.781/9.778 s:
нарастающего backlog не видно, но это **не абсолютная transport latency**.
`stream-diagnostics` во время ранней серии вернул старый `not_streaming` snapshot;
он не используется как синхронная per-frame telemetry. После окончания viewer
и finite Activity отдельным read-only snapshot подтверждены `not_streaming`
и launcher. Ни кликов, ни global stop, ни новых device settings не отправляли.
[Allowlisted evidence](../audits/2026-10-01/PH010-CODEC-CPU-EVIDENCE.json).

### Следующая проверка кодека и условия изменения

**Этапы runtime capabilities и isolated input выполнены 1 октября 05:32 UTC+5.**
Surface AVC/VBR/VP8 дают 6.67 pictures/s; тот же AVC с planar YUV — 30 pictures/s
на короткой synthetic scene, без реального RGBA conversion/capture/transport.
Это уточняет гипотезу CPU limit: сначала проверять graphics input path.
[Методика, численные результаты и acceptance ограничения](CODEC-INPUT-CANARY.md).
Ни VP8 transport, ни global default по этому control не продвигались.

1. Получить фактические `MediaCodecList`/capabilities на canary: MIME, input Surface,
   native-size support, bitrate modes и complexity range. Прочитанный vendor XML
   объявляет Google AVC/VP8/VP9; XML не доказывает complete runtime inventory или
   успешный configure. Hardware acceleration нельзя приписывать host GPU без
   доступного Android encoder.
2. Если AVC поддерживает более быстрый complexity mode, сравнить его в отдельном
   canary при **том же native разрешении** и читаемости. Android описывает меньшую
   complexity как возможную экономию времени, но это capability конкретного codec,
   не универсальный переключатель для всех MediaCodec implementations:
   [официальный EncoderCapabilities](https://developer.android.com/reference/android/media/MediaCodecInfo.EncoderCapabilities).
3. Если подходящего AVC mode нет, сначала измерить доступный альтернативный
   software codec на устройстве. Лишь после реального выигрыша и decoder
   acceptance менять negotiated wire format. VP8/VP9 нельзя отправить в существующий
   H.264 parser и назвать работающим fallback; нужны явный MIME, codec configuration,
   version/capability handshake, recovery и regressions. В этом проходе такой
   fallback **не реализован и не принят**.
4. Сравнить control profile **10–15 stable source pictures/s** и input-to-visible
   latency; прежний higher target 20–30 сохраняется отдельно для подходящей source.
   Дублирование кадров, уменьшение native resolution без выбора оператора или
   обещание FPS по одному `KEY_FRAME_RATE` не закрывают этот gate.

## Приёмка

| Gate | Что требуется | Что не является доказательством |
| --- | --- | --- |
| Source | Android tests обеих flavors, compile, ресурсы/startup/stop | Native EGL или codec FPS из Robolectric |
| Artifact | SHA, package, прежний signer, configured discovery, GPU flag | Номер версии в исходниках |
| Installed | OTA completed receipt + свежая reported version | Принятие grant/download queue |
| Source display | Capability readback, source workload не ограничен ниже target | Encoder `fps=30` при display mode 5 Hz |
| Capture/encode/wire | ≥20 pictures/s на движущемся workload, последовательные окна, очередь/errors | Среднее число за idle+motion вместе |
| Browser | Независимые receive/draw FPS, изображение и input, source/runtime stamp | Native wire count или operator «есть картинка» |
| Quality | Читаемость мелкого текста, линии и движение без сильных block artifacts | Высокий FPS ценой размытия/низкого bitrate |
| Recovery | Повтор start/stop, reconnect, без native crash/утечки и старых callbacks | Один удачный start |

Пока native/browser/quality/recovery gates не приняты, canary не становится
default production path и массовая OTA не публикуется. Fleet snapshot mode
и экономичный demand arbitration не закрываются одиночным GPU тестом.

## Источники и авторство

Контракты: [Android SurfaceTexture](https://developer.android.com/reference/android/graphics/SurfaceTexture),
[Android EGLExt](https://developer.android.com/reference/android/opengl/EGLExt),
[Android MediaCodec](https://developer.android.com/reference/android/media/MediaCodec).
Архитектурный reference: [Google Grafika TextureMovieEncoder](https://github.com/google/grafika/blob/master/app/src/main/java/com/android/grafika/TextureMovieEncoder.java),
Copyright Google 2013, Apache-2.0; репозиторий archived 15 апреля 2025, не
рекомендуется как поддерживаемая runtime dependency. Source Grafika не
копируется и новая зависимость не добавлена; Kotlin bridge написан в Sphere
на platform API. Не переносите тесты reference sample на наше устройство.

Host FPS controls: [LDPlayer official multi-instance FPS settings](https://ru.ldplayer.net/support/683.html), checked 1 октября 2026. Статья подтверждает наличие отдельного лимита; конкретное значение 5 Hz получено из Android dump, не из документации.

Native control reference: [AOSP Android 9 screenrecord source](https://android.googlesource.com/platform/frameworks/av/+/refs/tags/android-9.0.0_r33/cmds/screenrecord/screenrecord.cpp),
Copyright 2013 The Android Open Source Project, Apache-2.0; inspected 1 октября
2026. Он использует AVC MediaCodec input Surface и compositor display capture;
Sphere не копирует этот source и не добавляет screenrecord как production
dependency. Его device benchmark относится только к выполненному control.
