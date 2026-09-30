# Одиночный видеопоток: GPU canary и критерии приёмки

**Дата:** 1 октября 2026, Asia/Yekaterinburg.<br />
**Scope:** один явно выбранный Android, отдельный APK и собственный viewer;
не массовая замена парка, не подтверждение 20–30 FPS по unit tests.

[Текущее состояние](CURRENT-STATE.md) ·
[APK/video audit](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md) ·
[Android guide](../android-agent.md)

## Что меняется

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
