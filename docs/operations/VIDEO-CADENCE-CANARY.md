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

## Приёмка

| Gate | Что требуется | Что не является доказательством |
| --- | --- | --- |
| Source | Android tests обеих flavors, compile, ресурсы/startup/stop | Native EGL или codec FPS из Robolectric |
| Artifact | SHA, package, прежний signer, configured discovery, GPU flag | Номер версии в исходниках |
| Installed | OTA completed receipt + свежая reported version | Принятие grant/download queue |
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
