# Headless motor worker: транспорт и конечный ввод

**20 октября ·0.6.0:** общий `StickPolicySession` с явным opt-in и calibrated scene guard,
continuous held-center stick для NitroGen/WASD, точный request/result binding, bounded RTP
stall recovery и телеметрия scheduler/ACK/SCTP.145 motor tests прошли. На PH025 выполнен
положительный12-секундный learned movement-only опыт:61 ответ NitroGen и62/62 APPLIED.
Повторные запуски выявили SCTP retransmissions/RTO1000мс; устойчивый совместный gameplay
не принят. [Испытания и открытые условия](../audits/2026-10-20/MOTOR-PH025-EXECUTION06.md).

### Явный API исполнения стика

`motor_worker.stick_execution.StickPolicySession` принимает `SessionConfig` с
`probe_control=True`, `shadow_policy=True`, без static `pointer_probe`, а также
`StickProfile(StickGeometry(...), source="gamepad_left" | "wasd")`, асинхронный `policy`,
`scene_guard(frame: PolicyFrame) -> bool` и `execution_enabled=True`.
Это API для доверенного локального адаптера; автоматического обнаружения игры и готового
scene detector нет. Guard должен отличать рабочий HUD от меню/отключения/загрузки.
Значение `True` по наличию одного видео не является калибровкой.

Provider создаётся/прогревается до старта сессии через существующий `ProcessPolicy`.
Жизненный цикл provider нужно закрывать в `finally`/`async with`; токен передаётся в
`session.run` из существующего окружения, без записи в аргументы и отчёт.
`mask_other_channels=False` по умолчанию отклоняет unmapped mouse/buttons/right stick.
Явное `True` допускает только ограниченный movement-only опыт и считает masked results.
Обычный CLI `python -m motor_worker` сохраняет транспортный/shadow режим без model execution.
`stickExecution` в отчёте разделяет scene refusal, accepted/rejected results, физические
события и APPLIED; успешная передача не подтверждает достижение игровой цели.
Guard проверяется и при занятом GPU. Если inference занял немного больше одного периода,
следующий запуск выбирает свежий кадр сразу после освобождения слота, без пропуска ещё200мс.
Частота RGB guard checks и количество принятых model results — разные величины.
Последние600мс finite run отведены на отпускание контакта и его подтверждение.
`sctpTransport` наблюдает ретрансляции/T3/RTO без изменения таймеров и reliability;
это диагностика всей association, включая закрытие. Отдельный retry команды не выполняется.
Только этот opt-in executor создаёт ordered PR-SCTP control channel с
`maxPacketLifeTime=200мс`; обычный HeadlessSession остаётся reliable. Просроченная
ретрансляция не заменяет неизвестный ACK. Это не ограничивает задержку первоначального
пакета в сети: APK-side action deadline с согласованными часами остаётся открытым условием.

**Recovery-примитивы:** доступны bounded `NavigationSupervisor`, `PointerSequence` и optional background-motion sensor.122 tests прошли; obstacle perception, runtime integration и multi-touch ещё нужны. Живая калибровка jump/camera заблокирована loading самой игры. [Результаты и границы](../audits/2026-10-17/MOTOR-NAVIGATION-RECOVERY.md).

**Новый конечный опыт:** NitroGen8 на PH011:235 решений/5.182Гц,571/571 native APPLIED, один непрерывный контакт, подтверждённое закрытие. Добавлены pure held-center contact, latest gamepad trajectory и explicit WASD adapter. Цель не передавалась; метка241→241м, навигация не принята. [Результаты, свежесть и goal conditioning](../audits/2026-10-17/MOTOR-STICK-CONTACT-LIVE.md).

Исторический срез17 октября · версия модуля `0.5.1` · **транспорт, opt-in single-finger probe и изолированный shadow provider**. Общий локальный RGB pipe для NitroGen/P2P уже был; загрузчики моделей и AMD preprocessing остаются отдельными пилотными адаптерами. Тогда поставляемого игрового executor не было; отдельный private12-секундный [learned WASD опыт](../audits/2026-10-17/MOTOR-LEARNED-WALK-PILOT.md) подтвердил15native событий. [Начальные AMD-измерения](../audits/2026-10-17/MOTOR-AMD-LOCAL41.md).

Предыдущие этапы — [process provider](../audits/2026-10-17/MOTOR-PROCESS-POLICY05.md), [выбор свежего RGB0.5.1](../audits/2026-10-17/MOTOR-PROCESS-POLICY051.md) и [готовность0.3](../audits/2026-10-17/MOTOR-WORKER03-READINESS.md). UI/API15ce2b62 и APK82 сохранены; обновлялся только локальный Python-клиент.

Основной план — [MOTOR-AI-PLATFORM](../design/MOTOR-AI-PLATFORM.md).
Код — [motor_worker](../../motor_worker/session.py). Это реализация части P0-C/G02:
настоящий WebRTC receiver без браузера и отдельная проверка shared native admission.
Общий finite model-stick loop доступен; поставляемый игровой профиль/scene detector,
камера/multi-touch, task delegation и автономная навигация ещё нужны.

## Что делает модуль

- Получает H.264 непосредственно с APK через WebRTC, декодирует в PyAV.
- Держит один последний decoded frame; выбирает до заданной частоты наблюдения.
- Преобразует выбранные кадры в RGB 256×256, считает hash и RGB mean. Это pilot transform,
  не принятый preprocessing конкретной модели. По умолчанию не записывает изображения/видео.
- Различает video binding, открытый control data channel, APK `READY`, idle `ALIVE` и закрытие участника.
- С `--probe-control` отправляет только `touch_open`, idle heartbeat action=4 и `touch_close`.
  При дополнительном явном `--pointer-probe` доступен ограниченный DOWN/MOVE/UP. Keys/text, игровой profile и model plan здесь не реализованы.
- С `--shadow-policy neutral` передаёт исходный RGB нейтральной тестовой policy и проверяет асинхронный lifecycle без физических команд. Это не нейросеть и не model inference. С `--pointer-probe` этот режим несовместим.
- Ограничивает setup, длительность прогона, собственные очереди, количество candidates и диагностический хвост.
  В0.4.1 guarded aiortc1.15 video receiver использует2048 RTP packet slots с prefetch0: stock128 терял крупные high-quality IDR. Счётчики `h264PacketBuffer` сохраняют превышения прежнего лимита, PLI и emitted frames.
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

**Требуется backend с реализацией `3d427a13` или её потомком. На 3015 и Tuna установлен API15ce2b62.**
Историческая проверка PH011 с APK77: одиночный и два перекрывающихся headless прогона на основной установке:
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
Защита, впервые установленная в backend27f3a61f и APK78, отвергает source-bearing recvonly offers до JNI; sendonly answers
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
| `participantClosedConfirmed` | Подтверждено закрытие своего participant; не произвольный global release |
| `nativeActionAppliedVerified` | По умолчанию false; в pointer probe — точные APPLIED всех точек и подтверждённое закрытие, не игровой результат |
| `captureLifecycle` | Режим capture-only, source readiness, нулевые server bytes и продления привязанного peer |

RTP PTS и receiver sequence показывают прогресс транспорта. Они не являются общим capture frame ID
и не доказывают, что повторно закодированный статичный source frame новый. Cross-host clock mapping,
capture freshness, правильные цвета на всех устройствах и source/action correlation остаются отдельными gates.

## Локальные проверки

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m unittest tests.test_motor_worker_protocol tests.test_motor_worker_pointer_probe tests.test_motor_worker_policy tests.test_motor_worker_integration
.venv-audit/Scripts/ruff.exe check motor_worker tests/test_motor_worker_protocol.py tests/test_motor_worker_pointer_probe.py tests/test_motor_worker_policy.py tests/test_motor_worker_integration.py
```

Protocol tests не требуют media dependencies. Integration tests используют настоящий H.264/DTLS/SCTP
между двумя локальными программными peers и fake APK: реальные цвета, video-only, admission/close,
lost ALIVE, video stall, cancellation, foreign capture binding и capture lifecycle handover.
В обычном backend окружении integration tests явно skipped; такой skip не считается положительной media проверкой.

Историческая поставка APK78 и её device results —
[PH030-STARTUP78-RECOVERY.json](../audits/2026-10-16/PH030-STARTUP78-RECOVERY.json).
APK78: восстановление после startup-отказа до первого input packet; PH011 headless READY/ALIVE/CLOSE и 871 decoded frame за15с, server→worker video0байт. В том этапе физический ввод ещё не был добавлен.
Первоначальные отрицательные прогоны и отдельный кандидат —
[MOTOR-CAPTURE-ONLY.json](../audits/2026-10-16/MOTOR-CAPTURE-ONLY.json).
Предыдущая версия0.1 и её стартовая серверная копия — в архиве
[HEADLESS-MOTOR-WORKER.json](../audits/2026-10-16/HEADLESS-MOTOR-WORKER.json).
Следующие этапы: общий игровой profile executor, frame/clock contract,
worker service identity и atomic DAG→episode delegation. GPU/model/gameplay пока не приняты.

## Конечная проверка настоящего ввода ·0.3

По умолчанию физических касаний нет. `--pointer-probe` явно включает настоящие действия выбранного Android:

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m motor_worker `
  --base-url http://127.0.0.1:3015 `
  --device 414ce0e9-4b93-4f96-b9ca-ee675f53835e `
  --seconds 8 --observation-hz 5 --probe-control `
  --pointer-probe examples/motor-pointer-probe.json `
  --output .local-pilot/my-pointer-probe.json
```

Пример выполняет короткое движение в области верхней шторки на экране960×540. Это явный тест устройства, не игровой профиль. Для другой геометрии требуется собственный файл: несовпадение с подтверждённым capture отклоняется до touch_open. JSON использует pointer_path vocabulary, но бюджет probe строже: до64точек/5секунд/16KiB. Неизвестные поля, порядок не DOWN→MOVE→UP, выход за кадр и дробные/boolean числа отвергаются. Между точками палец остаётся удержанным; heartbeat не создаёт новые DOWN.

Клиент связывает initial availability с session/capture, отдельно ждёт native READY и для каждого события требует точный sequence/gesture/action APPLIED. Отсутствующий/чужой ACK не вызывает повтора. Нет inference, модели, tap/key/text или мультикасания. Файл читается ограниченно до16KiB до открытия сети; output не перезаписывается.

Перед отправкой и во время удержания нужен свежий decoder output не старше250мс на локальных часах worker. Просрочка плановой точки более100мс прерывает probe. Это receiver freshness и pre-send schedule, не source-capture age или полная задержка. Потеря видео, отмена, automation и прерывание другим участником завершают проверку с попыткой подтверждённого закрытия только своего participant. Ошибка cleanup сохраняет неопределённость. Аварийное падение самого процесса всё ещё зависит от native lease;500мс crash-stop SLA не принят.

В отчёте `pointerProbe` разделяет attemptedPoints и appliedReceipts. `control.nativeActionAppliedVerified` означает точные receipts всех точек и подтверждённое закрытие, а не успешную игровую операцию. `pointerProbe.samples` хранит только bounded timing/counter tail, без координат/картинок. После конца monitoring и native cleanup отправляется goodbye; ожидаемое закрытие peer на этом этапе не считается потерей соединения. До этого этапа неожиданный close остаётся ошибкой.

Далее нужны модельный adapter/RGB preprocessing, profile/multi-touch, сквозные source IDs/clocks и episode ownership. Этот probe не превращает статическую траекторию в управление по результатам inference.

## Shadow policy ·0.4

`--shadow-policy neutral` включает отдельный loop: один активный запрос и один последний ожидающий кадр, без input sink. В отчёте `policyShadow` содержит counters, сроки и подтверждение очистки. Ошибка provider или неподтверждённая отмена не скрывается; при такой отмене новые запросы не запускаются. Timeout250мс/receiver-age500мс — бюджеты проверки, не игровой SLA и не измеренная задержка GPU.

Provider получает immutable bytes исходного RGB24 размера capture, максимум8Mi pixels, а не сжатое изображение из отчёта или RGB256 hash. Оригиналы не сохраняются. Сетевой GPU API и поставляемый checkpoint loader ещё не реализованы. [ActionChunk](../../motor_worker/policy.py) проверяет два стика и21 decoded button columns, до18состояний с явно заданной частотой. 16 denoising steps не являются горизонтом закреплённого NitroGen checkpoint. Read-only preview не является физическим исполнением удержаний.

```powershell
.local-pilot/motor-worker-venv/Scripts/python.exe -m motor_worker `
  --base-url http://127.0.0.1:3015 `
  --device 414ce0e9-4b93-4f96-b9ca-ee675f53835e `
  --seconds 15 --observation-hz 5 --shadow-policy neutral `
  --output .local-pilot/my-policy-shadow.json
```

Без `--probe-control` native input participant не открывается. Отчёт различает `HEADLESS_POLICY_SHADOW_NOT_GAMEPLAY` и физический probe. Receiver freshness, model latency и source capture freshness — разные величины. Полная корреляция с часами Android остаётся открытой.

## Изолированный локальный provider ·0.5

[ProcessPolicy](../../motor_worker/process_policy.py) запускает явно выбранный доверенный Python script
в отдельном окружении; [model_stdio.serve](../../motor_worker/model_stdio.py) задаёт его протокол.
Media worker не импортирует Torch. Shell не используется; parent Sphere/HF/cloud token environment
не наследуется: передаётся только ограниченный набор OS/GPU переменных. Это разделение процессов,
**не sandbox**: доверенный script всё ещё имеет обычные права пользователя и доступ к его файлам.

Модель должна загрузиться и прогреться **до** `serve()`. Затем callback `predict(PolicyFrame)` получает
исходный RGB24 без потери разрешения; адаптер отвечает plain JSON lists/scalars. Синхронизация GPU,
checkpoint hash, exact preprocessing и значения model provenance — обязанность модельного адаптера.
`reset()` вызывается перед первым кадром и при изменении capture epoch. Отдельного episode/task
контракта здесь ещё нет. Child должен явно иметь доступ к Python-модулю `motor_worker`; скрытый
`PYTHONPATH` родителя не используется.

Контракт `sphere-policy-stdio-v1`: READY с точным adapter → JSON header с request/epoch/sequence/geometry
→ ровно width×height×3 binary bytes → один JSON reply с теми же bindings, prediction и `inferenceWallMs`.
Header до4KiB, ответ до32KiB, исходный кадр до8Mi pixels. Duplicate JSON keys, NaN, boolean IDs,
чужие bindings, неизвестные prediction fields и переполнение vocabulary отвергаются без clipping.
До6000 запросов на один child; новый запуск создаётся вызывающим кодом явно.

Поддерживаются две разные схемы ответов:

| Adapter | Ответ и время | Граница |
| --- | --- | --- |
| `nitrogen-decoded-v1` | До18 gamepad states,60 тиков/с | Стики и21 decoded binary button columns; не Android input |
| `open-p2p-150m-decoded-v1` | Одно keyboard/mouse state,20 тиков/с | До4 keys из pinned vocabulary и2 mouse buttons, integer relative mouse; не Android keycodes |

P2P state на20Гц покрывает50мс. Частота наблюдения5Гц сама по себе **не продлевает** его до200мс
и не задаёт безопасное физическое удержание. Растяжение временной шкалы, модельная history и
profile executor проверяются отдельно в игре. NitroGen chunk аналогично не перезапускается от
начала на каждом позднем callback.

Пример Python API после создания своего проверенного script (пути абсолютные):

```python
from pathlib import Path
from motor_worker.process_policy import ProcessPolicy, ProcessPolicyConfig
from motor_worker.session import HeadlessSession, SessionConfig

async def shadow(token, base_url, device_id, model_python, model_script):
    config = ProcessPolicyConfig(Path(model_python), Path(model_script), "nitrogen-decoded-v1")
    async with ProcessPolicy(config) as provider:
        session = HeadlessSession(
            SessionConfig(base_url, device_id, duration=20, observation_hz=5, shadow_policy=True),
            policy=provider, policy_timeout=0.75, policy_max_receiver_age=1,
        )
        result = await session.run(token)
    result["policyProcessAfterCleanup"] = provider.report()
    return result
```

Модельный процесс запускается до регистрации video viewer, поэтому прогрев не занимает input lease.
Один запрос активен, capacity ожидающего RGB — один кадр. В0.5.1 media session во время inference
держит последний декодированный кадр и переводит его в RGB только после освобождения provider;
ранняя RGB-выборка больше не добавляет возраст к следующему inference. Generic shadow API по-прежнему
ограничивает ожидающий RGB одним заменяемым slot. На timeout, partial write, чужой или неизвестный
ответ child уничтожается и ожидается его завершение; поздний ответ не переиспользуется и кадр не
повторяется. Неподтверждённая отмена блокирует новые inference. Известному `ProcessPolicy` shadow
cancellation даёт2,5с вокруг двухсекундного retirement;100мс оставлены для других providers.
Эти сроки не являются crash-stop SLA или гарантией закрытия произвольных grandchildren.

`policyShadow` содержит receiver→result wall time и drops. `policyProcess` содержит counters и
хвост64 samples с pipe RTT и **сообщённым моделью** callback time, без pixels/predictions/argv/paths.
READY подтверждает protocol readiness, не загрузку конкретного checkpoint: `modelInstalled: null`
при external provider и `modelWeightsVerifiedByBridge: false` сохраняют эту границу. `--shadow-policy neutral`
по-прежнему явная заглушка CLI; внешний provider включается только через Python API.

Проверки используют настоящий отдельный процесс, binary pipes и H.264/DTLS/SCTP fake APK.
Проверены обе схемы, reset, no-token inheritance, timeout, cancel при spawn/predict,
конкурентный close, неправильные bindings, stdout flood и завершение child.
Это не подтверждает model/gameplay качество, стабильность нескольких GPU или парк50устройств.
