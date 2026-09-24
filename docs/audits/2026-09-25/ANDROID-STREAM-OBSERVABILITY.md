# AUD-168 · Диагностика Android-стрима от захвата до браузера

**Дата:** 25 сентября 2026 · **Статус:** source implementation + unit/regression
tests; remote APK acceptance **OPEN** · **Fleet32 gate:** NO-GO до canary.

[Документация](../../README.md) · [Текущий удалённый A/B](../2026-09-24/REMOTE-INGRESS-AB.md) ·
[Fleet32 readiness](../2026-09-20/FLEET32-PREFLIGHT.md) ·
[Android guide](../../android-agent.md) · [Операционный observability-дизайн](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md)

## Результат

В source добавлена диагностика, которая разделяет стадии Android-захвата,
поверхности encoder, MediaCodec и локальной очереди WebSocket, а на одиночной
странице устройства показывает отдельно приём и отрисовку пакетов в браузере.
Backend сохраняет только последний валидированный snapshot в Redis. APK теперь
включает сохранённый crash record в обычную загрузку логов и ограничивает общий
пакет размером 480 KiB, то есть ниже серверного лимита 512 KiB.

Это закрывает заметную дыру в наблюдаемости, но не является исправлением
потери удалённой картинки само по себе. APK пока не подтверждает получение
байта сервером, backend не связывает кадр с browser decode общим ID, а новый
APK ещё не принят на удалённом canary. Нельзя называть это «стрим исправлен»
или разрешать массовую публикацию.

## Приоритетные findings

| ID / severity | Root cause и доказательство | Изменение | Остаточный риск |
| --- | --- | --- | --- |
| AUD-164 / P0, OPEN | В разных сохранённых ingress-срезах локальный `auto-ph-000` доставлял IDR/P через Cloudflare, а удалённый `auto-ph-008` — только SPS/PPS через локальный, Cloudflare и LocalTunnel viewers. В одном 25 Sep конкурентном snapshot PH000 получил 12–13 пакетов и IDR около 40.5 KiB; PH008 на всех трёх viewer ingress получил по 2 пакета / 61 B, SPS/PPS без picture NAL. Это указывает на отсутствие picture NAL выше browser decoder, но Android egress в том сравнении не переключался. Смотрите [A/B evidence](../2026-09-24/REMOTE-INGRESS-AB.md); сырые сетевые captures остаются в локальном ignored evidence. | Новые counters позволяют локализовать часть Android pipeline при установке candidate APK. | Нужны подтверждённый remote APK version, стабильный device identity, подтверждённый command receipt и A/B самого Android egress на независимом маршруте. Cloudflare остаётся гипотезой, не выводом. |
| AUD-168 / P1 | Старые FPS/queue counters показывали только суммарный результат у APK; очередь OkHttp могла принять кадр, но это не доказывало отправку, получение backend или вывод browser. Счётчик encoded frames также обновлялся после FPS throttle и скрывал намеренно отброшенные кадры. В backend не было API для свежего snapshot, UI не показывал decoder stages. | v2 Android counters считаются на стадиях; backend проверяет схему и tenant, кеширует последний snapshot; UI показывает APK и browser отдельно; Grafana и alerts разделяют capture/render/encoder/queue. Counter encoder теперь снимается до throttle, а throttle drops учитываются отдельно. | Нет server-side per-frame receipt, общего `frame_id`, tunnel hop receipts или корреляции кадра в UI. Remote acceptance остаётся OPEN. |
| AUD-169 / P2 | `CrashHandler` писал uncaught exception в `sphere_crash.log`, а `LogUploadWorker` отправлял file logs/logcat без этого файла. Кроме того, Android logcat collector допускает до 2 MiB, а `/api/v1/logs/upload` отклоняет тело свыше 512 KiB; шумный пакет мог получать HTTP 413 и повторяться без конца. | Worker добавляет tail crash record, держит полный UTF-8 body не более 480 KiB и удаляет crash snapshot только после успешного HTTP ответа, если файл не изменился во время передачи. Новая crash запись и неуспешный upload сохраняются к следующей попытке. | Worker планируется WorkManager; отправка не мгновенная и зависит от сети, регистрации и следующего успешного запуска. Размер retention на сервере всё ещё требует quota. |

## Доказательная цепочка видеокадра

```text
MediaProjection / VirtualDisplay
  → ImageReader acquired image
  → rendered and posted to encoder Surface
  → MediaCodec picture output
  → Android FPS throttle
  → OkHttp WebSocket local queue
  → Android management WSS / public ingress
  → backend binary ingress
  → bounded agent-to-Redis queue
  → Redis Pub/Sub publish / subscriber count
  → bounded per-viewer queue
  → backend ASGI viewer send
  → browser WebSocket packet validation
  → H.264 decoder submission / decoded VideoFrame
  → canvas draw
```

Каждая стадия доказывает только себя. Системное уведомление Android означает,
что MediaProjection session заявлена системой; оно не доказывает кадр в
ImageReader. `queue accepted` означает, что OkHttp принял сообщение в локальную
очередь; это не подтверждение WAN write, backend receive, subscriber fanout,
H.264 decode или canvas render.

| Наблюдение | Что это подтверждает | Что ещё не подтверждает |
| --- | --- | --- |
| Android capture FPS / total | ImageReader отдал непустые изображения в callback | Что Bitmap преобразован или поступил в encoder |
| Surface FPS / total | `drawBitmap` и `unlockCanvasAndPost` завершились без ошибки | Что MediaCodec выдал picture NAL |
| Encoder FPS / total / bytes | MediaCodec callback выдал picture output; codec-config SPS/PPS не считаются picture frame | Что FPS throttle пропустил его или очередь приняла его |
| FPS-throttle drops | Агент намеренно отсёк encoded delta frame до пакетизации; keyframe и codec config сохраняются | Сетевую потерю кадра |
| WS attempts / accepted / rejected | Результат вызова `WebSocket.send` на агенте | Фактический socket write, ingress, backend или viewer |
| Backend ingress frame/bytes/NAL label | Android binary message дошёл до backend WebSocket handler; `nal_type` — первый распознанный NAL packet type | Redis publish, очередь, subscriber или viewer |
| Redis publish calls/bytes/subscribers | Backend вызвал Redis `PUBLISH`, получил ответ и число subscribers | Факт получения Redis каждым subscriber или отправку браузеру |
| Backend viewer send frames/bytes | `send_bytes` завершился на ASGI viewer socket; счётчик суммирует всех viewers | Browser receipt, JS callback, decode или отображение пикселя |
| Server queue drops | Сколько packets ограниченная publish/viewer queue отбросила, по фиксированным этапу и причине | Потери до помещения в queue или удалённую сетевую потерю |
| Browser packet / SPS / PPS / IDR / delta | Viewer WebSocket получил и проверил бинарные пакеты | Что пакет пришёл от того же Android capture counter: общего frame ID нет |
| Decode submitted / decoded output / canvas render | Браузер принял input, WebCodecs вернул кадр, UI вызвал `drawImage` | Видимые пиксели на физическом дисплее при свёрнутой/замороженной вкладке |

Обратите внимание: browser `drawImage` callback означает вызов canvas API, а не
гарантированное физическое обновление панели или perceptual motion. Приёмка
плавности всё равно требует motion source и измерения frame presentation.

## Контракт телеметрии APK

В heartbeat pong активного стрима добавляется `stream.schema_version = 2`.
Legacy v1 остаётся принимаемым для APK, которые ещё не обновились. Все счётчики
валидируются как конечные неотрицательные значения с верхней границей `2^53`;
FPS ограничен 240, отношение keyframe — `[0, 1]`, число queue attempts обязано
совпадать с accepted + rejected.

| Поле | Смысл / reset |
| --- | --- |
| `capture_fps`, `capture_frames_total` | Непустые images, которые ImageReader отдал callback; total на текущую stream session |
| `render_fps`, `rendered_frames_total` | Успешно posted images на encoder Surface |
| `capture_read_failures_total` | Исключения при `acquireLatestImage`; пустой результат сам по себе не считается exception |
| `render_failures_total` | Ошибки преобразования/Surface draw/post и отсутствие encoder canvas |
| `encoder_fps`, `encoded_frames_total`, `encoded_bytes_total` | Picture output MediaCodec до agent FPS throttle; codec config не входит в frame count |
| `encoder_errors_total` | Ошибки MediaCodec callback |
| `frame_throttle_drops_total` | Delta picture output, намеренно отброшенные заданным FPS limit |
| `ws_queue_attempts_total`, `ws_queue_accepted_total`, `ws_queue_rejected_total`, `ws_queue_accepted_bytes_total` | Решение `WebSocket.send` на OkHttp client; session cumulative, accepted bytes не равно bytes received by server |

Счётчики сбрасываются при stop/start. Heartbeat передаёт snapshot без image data
и без отдельной записи на каждый кадр. Backend пишет в Prometheus текущие
session gauges и сохраняет последний snapshot в Redis на 24 часа. При свежести
heartbeat более 75 секунд endpoint возвращает `stale`; без snapshot —
`not_streaming` при online heartbeat или `unavailable` при отсутствии состояния.
`active_report` намеренно означает только «APK заявляет активный local capture».

### API и UI

Новый маршрут: `GET /api/v1/devices/{device_id}/stream-diagnostics`.
Требуется `device:read`; перед доступом к Redis handler проверяет tenant-владение
через SQL. В ответе: `state`, `agent_status`, `last_heartbeat`, `age_seconds`,
`diagnostics.observed_at`, `agent_session_id` и последняя схема counters.
Snapshot остаётся в Redis 24 часа после отсоединения, чтобы диагностика не
исчезала мгновенно при reconnect; endpoint всё равно помечает её `stale`.

На одиночной странице `/stream/{id}` кнопка «Диагностика» включает опрос
Android snapshot раз в 15 секунд и чтение уже существующих browser counters раз
в секунду. Панель показывает время последнего Android heartbeat, browser packet
и browser canvas frame. Пока панель закрыта, эти дополнительные API
polling/timer не идут. Fleet Matrix не включает эти polling timers на каждую
плитку.

В Prometheus `/metrics` доступны `sphere_stream_capture_fps`,
`sphere_stream_render_fps`, `sphere_stream_fps`, session totals для counters,
queue, ошибок и throttle drops, backend binary ingress, Redis publish, ASGI
viewer sends и queue drops. Обновлён dashboard
`infrastructure/monitoring/grafana/dashboards/android-agents.json`; добавлены
alerts на нулевой capture/encoder, остановку Surface после capture и заметные
накопленные queue rejections, ingress без Redis publish и подключённый viewer
без server-side send. Android queue rejections считаются накопленно за session, не
скользящей скоростью; alert требует не менее 100 attempts и долю выше 1%.

Frame/byte counters на server plane — `sphere_stream_backend_ingress_*`,
`sphere_stream_redis_publish_*`, `sphere_stream_viewer_send_*`; queue drops —
`sphere_stream_server_queue_drops_total{queue_stage,reason}`. Backend ingress
counts binary messages even when the bridge is absent, so it is an actual
server-side WebSocket receipt. The viewer-send stage counts each viewer
separately; with multiple viewers its frame/byte rate is expected to exceed
Redis publish. Redis subscriber count is the response from the latest successful
publish and can be stale after the last frame. These boundaries are aggregate
counters, not a per-frame acknowledgement protocol.

Per-device Prometheus samples are process-local. Scrape every backend instance
and aggregate by `device_id`; a load-balanced scrape URL can sample one worker
and hide counters held by another process. Current pilot topology is not a
measured multi-worker scrape acceptance.

У Prometheus все stage metrics имеют `device_id` label: это удобно для пилота и
32 устройства, но требует измерения series/memory при тысячах устройств.
Не добавляйте `frame_id`, serial, IP или error text как Prometheus labels.

## Crash / log evidence и retention

`CrashHandler` запускается до Hilt и сохраняет необработанный stacktrace в
app-private `sphere_crash.log`, ограничивая локальный файл примерно 256 KiB.
Обычный periodic `LogUploadWorker` добавляет до последних 128 KiB crash log к
file logs и Sphere-tagged logcat. Полное тело UTF-8 ограничено 480 KiB с учётом
серверного лимита 512 KiB. На успехе файл удаляется только если его длина и
mtime совпадают со снимком, прочитанным до запроса. HTTP error, network failure
или появление новой записи во время upload оставляют evidence локально.

Загрузка может произойти не сразу: расписание WorkManager — каждые 15 минут
при наличии сети; Doze, отсутствие регистрации и restart могут задержать её.
Для немедленной диагностики используйте текущую команду запроса логов или
локальный crash file через управляемый доступ. `READ_LOGS` — Android
signature/privileged permission; обычный install не даёт права читать полный
системный buffer. На phone без root/managed grant считайте доступными логи
самого Sphere приложения, а не полные логи сторонней игры.

Backend принимает не более 512 KiB на upload, пишет дневной файл не более 50
MiB и очищает файлы старше 30 дней при следующем upload этого device. У него
пока нет общего per-device quota, глобального disk quota или независимого
scheduled sweep. При максимальном заполнении одной дневной записи и сохранении
каждый день верхняя грубая граница — до ~1.5 GiB на устройство; при 1,000
устройств теоретический worst-case до ~1.5 TiB, до учёта filesystem overhead.
Это консервативный предел, не измеренное потребление. Per-device/global quota,
retention worker, disk alerts и безопасное удаление при достижении квоты — P1
capacity follow-up до крупного парка.

CrashHandler ловит необработанные Java/Kotlin exceptions, пока процесс жив и
успевает записать файл. Он не может гарантировать запись при native SIGABRT,
SIGSEGV, убийстве процесса ядром/LMK, отключении питания или потере диска.
Для native tombstone потребуется разрешённый системный сбор через root/MDM либо
платформенный crash service; обычный app-only APK не должен обещать полный
Android crash dump.

Logs/crash stacktraces могут содержать внутренние данные и аргументы исключений.
Сырые логи не входят в Git audit report. Не включайте tokens, credentials,
полные shell-команды или личные данные в UI и labels.

## Воспроизведение и регрессии

Source regression должен доказать все границы, а не только успешную сборку:

1. Android unit tests проверяют capture/render/encode/queue stage counters,
   сохранение crash snapshot при HTTP error, удаление после успешной доставки,
   сохранение изменившегося во время запроса crash file и aggregate UTF-8 cap.
2. Backend tests проверяют v1 compatibility, v2 schema/counter invariants,
   Redis latest snapshot + TTL, stale/idle/active API states и 404 при чужом
   tenant.
3. Backend ingress/queue tests доказывают, что бинарный route учитывается даже
   если bridge отсутствует, Redis publisher возвращает subscriber receipt,
   viewer send counter увеличивается только после завершения ASGI send, а queue
   drop использует ограниченные labels.
4. Frontend tests проверяют отдельное отображение Android и viewer counters,
   включая capture FPS, queue rejection, полученные IDR/delta и реальный decoder
   output.
5. `python -m scripts.export_api_docs --check` сверяет route с `docs/openapi.json`
   и `docs/api-endpoints.md`; `promtool check rules` проверяет новые alert rules.

Проверка этой ревизии 25 сентября 2026: Android `:app:testDevDebugUnitTest` —
644 теста, 0 failures/errors; backend stream/heartbeat/queue/API regression —
71 passed; frontend decoder/diagnostics — 26 passed; `npm run type-check`, Ruff,
OpenAPI export check и `git diff --check` завершились успешно. `promtool check
rules` на Prometheus 2.48.0 проверил все 16 alert rules; JSON dashboard и YAML
rules также успешно разобраны. Локальный `assembleDevDebug` собрал
`1.2.19-dev` / versionCode `10219`; это debug candidate, не опубликованный и не
установленный на удалённые устройства. Для диагностики его нужно координированно
сочетать с backend и frontend из этой же ревизии. Android Gradle Plugin 8.3.2
предупреждает, что compileSdk 35 выше его проверенной версии 34; тесты и сборка
прошли, но обновление toolchain остаётся отдельной задачей.

После установки candidate нужен remote canary с подтверждённым versionCode:

| Проверка | Приёмка |
| --- | --- |
| Нет Android capture | Свежий endpoint показывает нулевой capture; browser counters не подменяют source |
| Capture идёт, encoder/render нет | Разные счётчики и соответствующий Grafana alert указывают участок Android pipeline |
| Encoder идёт, очередь отвергает | Android totals растут и queue rejection виден в API/dashboard |
| Android queue принимает, browser получает только SPS/PPS | Это доказывает разрыв после локальной очереди APK, но для причинности нужен server ingress receipt |
| Browser получил IDR/delta, output не растёт | Decoder/config/recovery counters локализуют viewer boundary |
| Browser output растёт, canvas output нет | UI callback/Canvas path проверяется отдельно |
| WAN outage и reconnect | Snapshot становится `stale`, после pong возвращается к `active_report`, device ID сохраняется, новая stream session counters reset |

Команды для локальной проверки из корня репозитория:

```powershell
uv run pytest tests/test_ws/test_stream_metrics.py tests/test_ws/test_heartbeat.py tests/devices/test_stream_diagnostics.py -q
uv run pytest tests/test_ws/test_stream_observability.py tests/test_ws/test_video_queue.py tests/test_ws/test_video_queue_limits.py -q
Set-Location android
.\gradlew.bat :app:testDevDebugUnitTest --tests "com.sphereplatform.agent.streaming.StreamQualityMonitorTest" --tests "com.sphereplatform.agent.commands.CommandDeliveryTest" --tests "com.sphereplatform.agent.workers.LogUploadWorkerTest"
Set-Location ..\frontend
npm test -- --runInBand --runTestsByPath __tests__/stream/h264-decoder.test.ts __tests__/stream/diagnostics.test.tsx
```

Ни один из этих source tests не заменяет проверку установленного APK, remote
gateway и движущихся кадров. Для текущего открытого инцидента см. также
[remote ingress evidence](../2026-09-24/REMOTE-INGRESS-AB.md), где отмечено, что
viewer-only LocalTunnel не меняет маршрут Android egress.

## Источники платформы

- [Android MediaProjection](https://developer.android.com/media/grow/media-projection) — согласие пользователя, lifecycle и projection token.
- [Android 15 foreground service changes](https://developer.android.com/about/versions/15/changes/foreground-service-types) — ограничения запуска mediaProjection foreground service.
- [Android READ_LOGS permission](https://developer.android.com/reference/android/Manifest.permission#READ_LOGS) — signature/privileged protection.
