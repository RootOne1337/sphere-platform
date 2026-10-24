# Нативный SIGABRT WebRTC при двух прямых клиентах

16 октября 2026. Сбой найден при проверке нового веба, а не объявлен сетевой задержкой.

## Измеренный инцидент APK78

На PH011, APK 1.2.78-dev /10278, два обычных Chrome-клиента через Tuna установили
прямые video/control, выполнили совместные mouse/touch и по четыре native Android
кнопки. Во время последующего наблюдения процесс APK аварийно завершился:

- 02:46:09.336 UTC: SIGABRT, EncoderQueue, PID32237.
- WebRTC: `rate_utilization_tracker.cc:43`, проверка `time >= last_data_point.time`.
- Два значения времени: 128705268941 и 128705268983 микросекунд; регресс 42 мкс.
- 02:46:09.498: сервер зарегистрировал потерю Android WebSocket.
- 02:46:10.853: Android запустил новый процесс PID15001.
- 02:46:11.849: агент снова зарегистрирован; затем восстановились оба peer.

Следовательно, server_runtime_retry и пересоздание клиентов здесь являются
следствием смерти процесса. Они не доказывают ошибку маршрута ICE или нажатия Home.
Взаимосвязь с конкретной командой, причиной clock regression, CPU migration или
внутренней очередью SDK отдельно ещё не установлена.

Приватные исходные доказательства: `startup-budget-ph011-logcat.private.log`,
`startup-budget-tunnel-backend-window.private.log`,
`startup-budget-direct-system-input-tunnel.private.json` в `.local-pilot`.
Датированная [квитанция UI](INPUT-STARTUP-WEB-DELIVERY.json) сохраняет failed result.

## Исследование и кандидат

В опубликованном исходнике SDK RateUtilizationTracker требует неубывающее время
и завершает процесс при нарушении. Это не capture/RTP timestamp, который уже
проверяет Sphere. [Исходник tracker](https://raw.githubusercontent.com/GetStream/webrtc/145.8.0/video/rate_utilization_tracker.cc).

EncoderBitrateAdjuster содержит отдельный переключатель
`WebRTC-BitrateAdjusterUseNewfangledHeadroomAdjustment`: при Disabled используются
прежние overshoot/utilization detectors без создания этого media-rate tracker.
Остальная адаптация остаётся активной. [Исходник adjuster](https://raw.githubusercontent.com/GetStream/webrtc/145.8.0/video/encoder_bitrate_adjuster.cc).
Публикатор указывает, что координата 146.7.0 соответствует upstream build145.8.0;
версию зависимости в этом исправлении не меняем.
[Примечание издателя](https://github.com/GetStream/stream-video-android-webrtc/releases/tag/145.8.0).

Кандидат APK79, source `9c9ef56cd3ef487b4fa19010ff9b8b5a68748445`, добавляет
этот supported field trial ко всем direct PeerConnectionFactory. Прежнее отключение
raw FrameDropper сохраняется для уже закодированной reference chain. Capture/RTP
timestamps не подменяются; bitrate allocation и MediaCodec onRate feedback сохранены.

**На момент этого среза APK79 ещё собирается.** Статический тест флагов не заменяет
проверку нативной библиотеки. Перед распространением нужны полный подписанный build,
canary OTA, подтверждение установленного хеша, два клиента и более длительный
прогон с проверкой PID, отсутствия SIGABRT и фактической передачи video/control.
Даже успешный конечный прогон не станет доказательством устранения всех clock issues
или общим production SLA.
