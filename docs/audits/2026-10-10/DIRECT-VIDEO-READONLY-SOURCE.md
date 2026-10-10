# Прямое видео: конечный canary поверх существующего H.264

Состояние этого документа: **UI/API установлены, APK собран**. Установка APK на
PH030 и живое RTP-изображение ещё не приняты: агент был офлайн при доставке.
Фактические версии и последующие результаты находятся
в [WORK-STATUS](../../operations/WORK-STATUS.md). Запись об установке должна быть
отдельным receipt, привязанным к точному CI commit, образам и SHA APK.

Положительный [результат пользователя с PH030](PH030-LAPTOP-CHANNEL-USER-OBSERVATION.md)
подтвердил 20/20 echo, p95 25,8 мс NAT/UDP. Он не подтверждает передачу видеокадров,
Android input, localhost или задержку изображения.

## Что добавлено

Отдельный просмотр до 30 секунд передаёт существующие H.264 access units APK в
WebRTC RTP. MediaProjection, capture surface и MediaCodec не создаются второй раз.
Это не перенос видеопакетов в DataChannel: DataChannel используется для короткого
binding захвата и echo, видеодорожка — для RTP/H.264.

Обычный canvas, серверный WebSocket и управление пока сохраняют свой транспорт.
Отдельная `<video>` область read-only: касания, текст, навигация и запуск команд
через новый канал не разрешены. Звук не запрашивается. Это этап интеграции, не
завершённый основной клиент и не стабильный релиз 1.3.0.

## Допуск и совместимость

- Новый server flag `DIRECT_TRANSPORT_VIDEO_PROBE_ENABLED` по умолчанию false.
- Используется существующий явный allowlist; установка разрешает ровно PH030.
- HTTP capability сообщает `readonly_video_enabled` отдельно от echo scope.
- Требуется свежая активная native session с APK **1.2.51-dev / 10251** или новее.
- Video auth: `sphere-video-probe-v1`; media binding: `readonly_video_v1`.
- Старый echo auth/SDP остаётся data-channel-only; его допуск нельзя расширить SDP.
- Video offer имеет ровно application + recvonly video; answer — application +
  sendonly video, H.264, SHA-256 DTLS fingerprint. Audio и дополнительные секции
  отклоняются. SDP до 32 KiB, до 64 candidates.
- RBAC `stream:read`, tenant/device/activity, точная native generation, token
  revalidation и одно глобальное finite lease на устройство сохраняются.
- TURN использует существующие временные browser/agent grants только после auth
  и резервирования lease. TURN в текущем рабочем окружении не настроен.

## Видеопайплайн и пределы

Capture tap связывает каждый AU с epoch, геометрией, sequence и исходным PTS.
Существующий SPS/PPS прикладывается к IDR. При пропуске, перестановке или reset
delta-кадры не продолжают повреждённую reference chain: требуется свежий IDR.
Raw crop/scale и конвертация в I420 недопустимы для уже закодированных байтов.

Adapter объявляет constrained-baseline H.264 level 3.1 и проверяет реальный SPS.
Не больше 3600 macroblocks на кадр, один AU до 1 MiB. Java input retention — до
3 кадров / 2 MiB, encoded output retention — отдельно до 3 / 2 MiB, включая
удержание `EncodedImage` после callback. Release exact-once; при закрытии новые
reservations запрещены, существующие освобождаются после release владельца.
Эти лимиты не являются измерением всей native памяти WebRTC или браузера.

Adapter использует существующую политику битрейта MediaCodec. Нулевой RTP target
останавливает публикацию, возобновление требует IDR; ненулевой RTP target пока
не управляет общим source encoder. Координация ABR и RTP pacing — открытый
production gate. Нельзя считать этот этап готовым для произвольной плохой сети.

## Lifecycle и доказательство изображения

Peer, DataChannel, track, VideoSource, factory, callbacks и таймеры закрываются
при stop, скрытии страницы, смене устройства/токена/профиля и окончании lease.
APK detach использует точного владельца; поздний callback не получает новое
capture epoch. В retirement log сохраняется один агрегат counters без SDP,
IP, ключей, кадров и логирования каждого кадра.

Успех картинки определяется через `requestVideoFrameCallback`, а не открытие
DataChannel или 20 echo. Размер отображённого кадра сверяется с binding APK.
Кадр до binding не даёт раннего успеха. При отсутствии первого подтверждённого
кадра за 8 секунд после binding просмотр останавливается с явным результатом.
RTT контрольных пакетов подписан отдельно; он не измеряет video latency.

## Проверка исходников

Локально пройдены два Android варианта: unit tests и lint. Дополнительные tests
проверяют реальный Java VideoEncoder callback, byte identity, геометрию, потерю
reference chain, input/output retention, паузу/IDR и retirement. Это JVM fixture:
JNI round-trip и настоящий RTP decoder требуют отдельного живого теста.

Backend: strict mode, version/gate denial, two-worker routing, read-only answer,
temporary TURN grants и installation boundaries. Frontend: track lifecycle,
поздние события, metadata/frame ordering, неверная геометрия, отсутствие картинки,
admission isolation, type check и scoped lint. CI и итоговое число тестов должны
быть записаны в receipt конкретной установки.

API библиотеки сверено с локальным pinned AAR
`io.getstream:stream-video-webrtc-android:146.7.0`. Основание adapter — официальные
[VideoEncoder](https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/api/org/webrtc/VideoEncoder.java)
и [native Java buffer bridge](https://webrtc.googlesource.com/src/+/refs/heads/main/sdk/android/src/jni/video_frame.cc).
Наличие API не заменяет проверку pinned native binary на целевом устройстве.

## Что ещё требуется

1. Точная signed сборка, адресное OTA на PH030, проверка фактического package SHA.
2. Exact-source CI UI/API, включение отдельного флага только PH030, два origin.
3. Реальное изображение laptop browser ↔ laptop APK, выбранный ICE route,
   первый кадр, decoder outcome и сохранение capture dimensions.
4. Native memory/CPU, работа рядом с игрой, reconnect и смена orientation.
5. Долгоживущий media lease, production ABR, primary viewer switch, direct input
   ownership/release/revocation и fallback без повтора жестов.
6. LAN/WAN/VPN/TURN matrix; end-to-end frame/input timestamps и latency budget.

До выполнения этих пунктов конечный canary не закрывает CHAT-15, direct client
или стабильный APK 1.3.0. Исторические отрицательные и положительные наблюдения
разных топологий сохраняются отдельно.
