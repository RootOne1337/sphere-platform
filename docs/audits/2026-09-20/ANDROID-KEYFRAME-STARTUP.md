# AUD-142 — Android терял ранний запрос ключевого кадра

**23 сентября 2026 · F32-31 · P0 / High до Fleet32 · исправление в исходниках PR19; удалённая приёмка OPEN.**

[Fleet32 readiness](FLEET32-PREFLIGHT.md) · [Эксплуатационная готовность](../../operations/READINESS.md) · [Связанный browser fix AUD-140](STREAM-FIRST-FRAME.md)

## Влияние и доказательство

WebSocket viewer отправляет `start_stream`, затем `viewer_connected`. Android
обрабатывает команды отдельно: `start_stream` запускает activity захвата экрана
асинхронно. До исправления `StreamingManagerImpl.onViewerConnected()` сразу
вызывал `encoder?.requestKeyFrame()` и возвращался, если MediaProjection или
MediaCodec ещё не успели создаться. Одноразовая команда терялась без ошибки.

В сохранённом backend snapshot удалённого pilot за 21 сентября есть **26** отправок
`viewer_connected` и **0** отправок `request_keyframe` старым веб-клиентом. В
отдельной 18-секундной выборке viewer получил 18 NAL: девять SPS, девять PPS и
ноль IDR. Это согласуется с пропуском первого запроса, но логи не доказывают, что
эта гонка была единственной причиной отсутствия IDR в каждом удалённом сеансе.
Срезы сохранены приватно в `.local-pilot/remote/clone-stream-20260922`; сырые логи,
адреса и учётные данные в отчёт не включаются.

## Исправление

- `ViewerKeyFrameCoordinator` coalesce-ит ранние запросы в один pending marker,
  пока encoder/capture не готовы. После создания VirtualDisplay marker доставляется
  encoder; после stop новые запросы снова ждут следующего старта.
- `onViewerConnected()` синхронизирован со start/stop, поэтому состояние readiness
  не теряется в окне инициализации.
- `H264Encoder.requestKeyFrame()` возвращает результат и ловит ожидаемые ошибки
  codec state/parameters. Командный путь пишет, что viewer запросил кадр,
  manager — что запрос отложен или принят codec. Принятие `setParameters` не
  считается доказательством выдачи IDR.
- Backend regression проходит viewer WebSocket handler и проверяет, что
  `request_keyframe` действительно передан Android agent.

Изменённые файлы: [StreamingManagerImpl](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt),
[ViewerKeyFrameCoordinator](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/ViewerKeyFrameCoordinator.kt),
[H264Encoder](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/H264Encoder.kt),
[CommandDispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt),
[Android state-machine tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/streaming/ViewerKeyFrameCoordinatorTest.kt),
[backend WS regression](../../../tests/test_ws/test_stream_viewer_keyframe.py).

## Регрессионные проверки

- Android dev: **108 связанных JVM-тестов**, 0 failures.
- Android enterprise: **108 связанных JVM-тестов**, 0 failures.
- Включены streaming, command dispatcher, клонированная identity, повторная
  регистрация и конкурентный тест: **64 одновременных ранних keyframe requests**
  схлопываются в один запрос после готовности encoder.
- Backend stream handler, bridge и clone registration: **31 passed**; в их числе
  отдельная проверка viewer-to-agent `request_keyframe`.
- Текущий PR CI для `e635de8` относится к исходникам до этого изменения: в нём
  1 996 backend tests прошли, но Redis persistence acceptance получил OOM. Новый
  APK/CI результат для AUD-142 ожидается после push; сборку на старом head не
  выдаём за проверку этого изменения.

## Остаточный риск и следующий шаг

Этот backstop исправляет потерю раннего запроса на стороне Android. Он не доказывает,
что конкретный LDPlayer codec принимает sync-frame параметр, что после него реально
выходит IDR, что binary frame доходит до Redis/backend или что браузер его декодирует.
После устранения identity/OTA блока нужен один удалённый экземпляр без конкурирующих
клонов и сопоставленные безопасные счётчики: command received → encoder request
accepted/rejected → IDR emitted → APK WS send → backend receive/publish → browser
decode. Пока 20 удалённых копий не получили подтверждённую версию с identity fix,
их одна общая карточка ожидаема и не является доказательством результата нового APK.
Fleet32 остаётся **NO-GO**.
