# Headless motor worker: первый транспортный этап

16 октября 2026 · версия модуля `0.2.0` · **пилот транспорта, без модели и игрового ввода**.

Основной план — [MOTOR-AI-PLATFORM](../design/MOTOR-AI-PLATFORM.md).
Код — [motor_worker](../../motor_worker/session.py). Это реализация части P0-C/G02:
настоящий WebRTC receiver без браузера и отдельная проверка shared native admission.
Игровой профиль, multi-touch, task delegation и autonomous model loop пока не реализованы.

## Что делает модуль

- Получает H.264 непосредственно с APK через WebRTC, декодирует в PyAV.
- Держит один последний decoded frame; выбирает до заданной частоты наблюдения.
- Преобразует выбранные кадры в RGB 256×256, считает hash и RGB mean. Это pilot transform,
  не принятый preprocessing конкретной модели. По умолчанию не записывает изображения/видео.
- Различает video binding, открытый control data channel, APK `READY`, idle `ALIVE` и закрытие участника.
- С `--probe-control` отправляет только `touch_open`, idle heartbeat action=4 и `touch_close`.
  Tap, swipe, key, text и motor plan отсутствуют в этом этапе.
- Ограничивает setup, длительность прогона, собственные очереди, количество candidates и диагностический хвост.
  Внутренние decoder/thread buffers библиотеки требуют отдельной нагрузочной приёмки перед парком.
- Сохраняет отчёт с фиксированными reason codes, не печатает token, SDP, owner или IP.

## Установка в отдельное окружение

Проверено на Python 3.12.12 / Windows. Версии полного разрешённого dependency set закреплены
в [requirements-motor-worker.txt](../../requirements-motor-worker.txt). Torch, browser и model weights
не нужны. Linux/GPU runtime и wheel hashes проверяются заново перед SSH-поставкой.
Файл задаёт версии; он не является криптографически закрытым lock для всех OS.

```powershell
python -m venv .local-pilot/motor-worker-venv
.local-pilot/motor-worker-venv/Scripts/python.exe -m pip install --only-binary=:all: -r requirements-motor-worker.txt
```

Токен передаётся только через `SPHERE_ACCESS_TOKEN` окружения процесса из существующего
авторизованного клиента/хранилища. Не вставлять его в аргументы CLI, Git или отчёт.
Текущий допуск использует обычный short-lived user JWT. Worker service principal ещё требуется;
пилот не обходится без RBAC и не становится самостоятельным администратором.

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m motor_worker `
  --base-url http://127.0.0.1:3015 `
  --device 414ce0e9-4b93-4f96-b9ca-ee675f53835e `
  --seconds 15 --observation-hz 5 --probe-control `
  --output .local-pilot/my-motor-probe.json
```

HTTP разрешён только для loopback; для другого хоста нужен HTTPS. Token в URL не принимается.
Файл результата создаётся эксклюзивно: существующий не перезаписывается. Необязательный
`--snapshot .local-pilot/my-frame.png` сохраняет один последний decoded кадр. Это не native screenshot.
`--seconds` ограничен 1–300, наблюдения — 1–20 Гц. Default ICE без STUN/TURN; единственный
необязательный `--stun stun:stun.cloudflare.com:3478` задаётся явно. Relay candidates отвергаются.

## Capture-only lifecycle socket

Capture зависит от общего реестра stream viewers. Модуль регистрируется на `/ws/stream/{id}`
с первым сообщением `{token, delivery: "capture_only"}`. Backend сохраняет JWT/tenant/RBAC,
но не создаёт video queue, sender или media subscription. Получение серверного binary payload
считается ошибкой, даже на этапе запуска. Этот режим не может переключиться на relay.

Backend ждёт completed native `stream_quality: get` с активным источником и возвращает `capture_ready`
с session identity и размерами. Только явно inactive снимки повторяются: до 40 чтений/250 мс,
общий deadline 10 с. Готовность источника не заменяет первый direct кадр и точный epoch из `SV1`.

Затем `/ws/direct-probe/{id}` согласует настоящий peer, связывает history/control nonce и после
первого direct кадра подтверждает `video_delivery: direct`. Каждые 3 секунды клиент продлевает
10-секундную capture-only аренду; direct signaling grant продлевается раз в 5 секунд.
Стартовая аренда ограничена 40 секундами. Потерянная аренда закрывается без включения relay.
Сам lifecycle socket не предоставляет разрешение на команды ввода.

**Требуется backend с реализацией `3d427a13` или её потомком. На 3015 и Tuna установлен API27f3a61f.**
PH011 с APK77 прошёл одиночный и два перекрывающихся headless прогона на основной установке:
server→headless media =0 байт с запуска. Команда с 3015 выше проверена на установленной системе.
Прежний backend969a7444 не поддерживает этот admission; клиент не подменяет его relay fallback.
Это не доказательство нулевого APK→server bootstrap-трафика: legacy suppression включается позже.
[Поставка и точные границы](../audits/2026-10-16/MOTOR-TRANSPORT-DELIVERY.md).

`--existing-capture` отключает lifecycle socket и требует, чтобы capture уже поддерживался другим
авторизованным потребителем. Это специальный режим проверки, не способ обеспечить автономный запуск.
Завершение закрывает только созданные клиентом peer и participant; общий capture напрямую не останавливается.
Существующий backend сам управляет его остановкой по общей presence.

## Совместимость SDP

Для aiortc 1.15 потребовались три адаптации, не ослабляющие server/native admission:

1. Создать video transceiver **до** SCTP при MAX_BUNDLE. Обратный порядок оставлял один из transport
   без локальных candidates в проверенном библиотечном цикле.
2. Передать настоящий SHA-256 fingerprint своего сертификата; дополнительные SHA-384/512 не входят
   в нынешний Sphere protocol. Чужой fingerprint не подменяется.
3. Объявлять constrained-baseline H.264 receive level 4.2 для pinned software decoder и не объявлять
   sender SSRC/MSID в recvonly offer. Stock level 3.1 недостаточен для нынешнего 960×540/60 источника.

С неизменённым объявлением sender SSRC/MSID в recvonly offer на PH011 наблюдался native abort
в WebRTC146 после `setRemoteDescription`, до native input OPEN. После удаления объявлений
несуществующего источника последующие конечные прогоны завершились успешно. Это локализованная
совместимость нашего клиента; точное место abort в stripped C++ binary не символицировано.
Установленные backend27f3a61f и APK77 отвергают source-bearing recvonly offers до JNI; sendonly answers
и session `msid-semantic` сохраняются. На APK77 прошли конечные browser/native и headless проверки.
Защита от всех иных неподдерживаемых SDP не заявляется.
Похожий upstream [issue GetStream #123](https://github.com/GetStream/webrtc-android/issues/123)
содержит пользовательские наблюдения о codec factories; они не заменяют локальное воспроизведение.

## Как читать отчёт

| Поле | Значение и граница |
| --- | --- |
| `success` | Завершён конечный transport pilot с cleanup; не gameplay acceptance |
| `capture` | APK capture epoch и согласованный размер |
| `decodedFrames` | Полученные decoder outputs за весь прогон |
| `rgbObservationsDuringMonitor` / `observationHzDuringMonitor` | Реально выбранные RGB observations в основном окне |
| `decodedFpsDuringMonitor` | Частота decoder outputs; не измеренный FPS источника/игры |
| `decodedAgeAtSelectionMs` | Возраст после приёма decoder output на worker; не capture→action latency |
| `receiverStats.jitter` | RTP jitter из aiortc в единицах RTP clock; не миллисекунды |
| `route` | Только nominated ICE pair из отдельного guarded aiortc1.15 adapter; IP скрыты |
| `lanProven: false` | Даже private addresses/direct не доказывают отсутствие VPN |
| `nativeAdmissionConfirmed` | APK прислал точный READY для владельца и capture |
| `actorAliveReceipts` | Живость APK shared actor, не native tap/gesture execution |
| `participantClosedConfirmed` | Подтверждено закрытие своего idle participant; не произвольный global release |
| `nativeActionAppliedVerified: false` | Физические игровые действия этим этапом не проверялись |
| `captureLifecycle` | Режим capture-only, source readiness, нулевые server bytes и продления привязанного peer |

RTP PTS и receiver sequence показывают прогресс транспорта. Они не являются общим capture frame ID
и не доказывают, что повторно закодированный статичный source frame новый. Cross-host clock mapping,
capture freshness, правильные цвета на всех устройствах и source/action correlation остаются отдельными gates.

## Локальные проверки

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m unittest tests.test_motor_worker_protocol tests.test_motor_worker_integration
.venv-audit/Scripts/ruff.exe check motor_worker tests/test_motor_worker_protocol.py tests/test_motor_worker_integration.py
```

Protocol tests не требуют media dependencies. Integration tests используют настоящий H.264/DTLS/SCTP
между двумя локальными программными peers и fake APK: реальные цвета, video-only, admission/close,
lost ALIVE, video stall, cancellation, foreign capture binding и capture lifecycle handover.
В обычном backend окружении integration tests явно skipped; такой skip не считается положительной media проверкой.

Текущая поставка и device results —
[MOTOR-TRANSPORT-DELIVERY.json](../audits/2026-10-16/MOTOR-TRANSPORT-DELIVERY.json).
Первоначальные отрицательные прогоны и отдельный кандидат —
[MOTOR-CAPTURE-ONLY.json](../audits/2026-10-16/MOTOR-CAPTURE-ONLY.json).
Предыдущая версия0.1 и её стартовая серверная копия — в архиве
[HEADLESS-MOTOR-WORKER.json](../audits/2026-10-16/HEADLESS-MOTOR-WORKER.json).
Следующие этапы: общий игровой profile executor, frame/clock contract,
worker service identity и atomic DAG→episode delegation. GPU/model/gameplay пока не приняты.
