# Надёжность видеопотока и ввода: повторный аудит

Дата: 11 октября 2026, UTC+5. Статус: активный аудит; production и stable 1.3 не приняты.
Запрос пользователя: прямое браузер ↔ APK соединение, устойчивый ввод при лаге
эмуляторов и reconnect, достоверные задержка/FPS, отсутствие ручного восстановления
после временных сбоев. PH030 выключен; пользователь перезагружает удалённый хост.

## Текущий срез перед direct-input установкой

UI/API `6ee80c1f` доставлены после исходного среза ниже. APK53 был установлен
по SHA и завершённому OTA command на семи устройствах; PH010 затем получил54.
Текущие девять подтверждений пакета:54 — одна машина,53 — шесть,52 — PH019/PH025.
PH030 выключен и исключён, ещё пять были offline. Реальный PH010 root
helper без input packets истёк по watchdog, вернул normal exit 0; это проверка
idle cleanup, не held-input CANCEL или полной работы управления.

В новом PH010 сеансе временный `runtime_unavailable` был через 22 мс дополнен
terminal rejection следующего сообщения во время retirement. Автовосстановление
ошибочно остановилось. В source `e9af9e60` валидный in-flight input завершаемого
owner отбрасывается без dispatch/ACK; exact RELEASE всё ещё обязателен. Проверены
635 WebSocket tests и44 subtests. Полные CIe9 также прошли. Runtime correction
не установлена: reviewed installer остановился до image load/container replacement,
Windows снова сообщает C: `Full Repair Needed`. Новый результат scan ожидается.

В новой PH01054 проверке:41 server-fallback кадр,0 decode/render errors, Home
подтверждён Android, controller ready. Native ICE report:237 requests sent,
0 responses received,0 successful pairs. Предыдущий53 срез содержал242/0;
эти окна не складываются. PH011 тоже использует server fallback. Это отдельный
сетевой пробел; source прямого ввода и APK54 не доказывают его устранение.
[Текущая неизменяемая квитанция](CURRENT-STREAM-DELIVERY.json) ·
[Source/build/OTA и условия доставки](DIRECT-INPUT-DELIVERY-BLOCKED.md).

Последующий source дополняет автоматическую историю browser ICE counts и
отдельным control transport, сохраняя null для неизвестного счётчика и лимиты
10 sessions/device,32KiB/session,7 days.647 WS tests +44 subtests и549 frontend
stream tests прошли. Эта telemetry ещё не установлена; native progress пока
локальный, без автоматической привязки к истории сеанса.

## Проверенный исходный срез

- UI/API `8fe2915a` установлены на 3015 и действующем Tuna-host.
- На обоих адресах проверены 29 одинаковых JS/CSS assets и готовность API/Redis/PostgreSQL.
- APK 1.2.52-dev/10252 ранее проверен по фактическому установленному SHA на 15 устройствах.
- Адресный canary разрешает основное WebRTC-видео. Android-ввод всё ещё server WebSocket.
- Историческая вкладка PH011 сообщила 1804 primary frames и выбранный NAT-путь.
  Это доказательство прямых кадров в том окне, не localhost, не новая приёмка и не video latency.
- На PH010 после установки: 16 fallback-кадров, 0 decode/render errors,
  подтверждённые Home/Recents; в коротком окне 0 восстановлений.
- На PH025 до первого касания воспроизведены `native_startup_busy`, затем
  `server_rejected` после трёх восстановлений. Прямых кадров в этом окне нет.
- Перезагрузка удалённого хоста может снять блокировку процесса. Это не устраняет
  дефект и не доказывает исправность повторного подключения.

[Неизменяемая установка и границы](DIRECT-PRIMARY-VIDEO-INSTALLED.json) ·
[Подробный результат и кандидат APK](DIRECT-PRIMARY-VIDEO-CANDIDATE.md).

## Подтверждённые дефекты и исправления

### 1. Ошибочный выход native watchdog блокировал следующие сеансы

`RootTouchBridge` раньше завершал процесс с кодом 2 при timeout даже тогда,
когда касание не удерживалось или CANCEL был принят. `ProcessTouchPipe`
считает ненулевой exit неподтверждённым освобождением; supervisor сохраняет
`resetRequired`. Поэтому следующие открытия могли постоянно возвращать busy.

Исправление `b53a1758`, кандидат APK 1.2.53: нормальный exit разрешён только
после закрытия сеанса, отсутствия удерживаемого касания и известного результата
CANCEL. Неуспешный/исключительный CANCEL остаётся неизвестным и не может стать
успешным от повторного `close` или запоздалого пакета. Истёкшее действие не
становится выполненным от успешной очистки. Старое касание не повторяется.

Локально: build/lint двух flavors, по 1021 unit test, 0 failures/errors, 3 skipped;
19 независимых pure-Java проверок состояния; подпись совпала с pilot baseline.
Доставка APK и проверка native процесса на устройстве фиксируются отдельно.
Первоначальный exit исторического отказа PH025 не записан: причинная связь с
этим конкретным отказом ещё не доказана.

Код: [RootTouchBridge](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTouchBridge.java),
[RootTouchSession](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTouchSession.java),
[supervisor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousTouchSupervisor.kt).

### 2. Временный отказ допуска ошибочно выглядел как постоянный запрет

Периодическая проверка сервера отправляла один `control_revoked_or_unavailable`
и при реальном отзыве права, и при временной недоступности lease/SQL/topology.
Браузер превращал его в `server_rejected` и требовал ручное восстановление.

Подготовленная коррекция разделяет подтверждённый `control_denied` и
`input_temporarily_unavailable`. Ошибка привязана к прежнему owner; проверка,
завершившаяся после замены owner, не может остановить новый сеанс. Старый owner
в обоих случаях отзывается; повторная проверка не переотправляет ввод.

Код: [периодическая проверка](../../../backend/websocket/continuous_runtime.py),
[тесты гонок](../../../tests/test_ws/test_continuous_runtime.py).

### 3. Известное освобождение после native-ошибки оставляло ручной fence

Браузер автоматически обрабатывал receipt timeout, но не bound native failure,
даже если позже приходил точный RELEASE3. Подготовленная коррекция разрешает
новый viewer только после RELEASE3 прежнего owner, затем свежего кадра,
capability, owner и STARTUP0. Старые DOWN/MOVE/UP не повторяются. Отсутствующий,
чужой или неизвестный RELEASE не заменяется таймером. Смена прав, blur,
inspection, recording и handoff сохраняют свои ограничения.
Если настоящий RELEASE3 приходит после диагностического deadline, восстановление
продолжается автоматически. Явный RELEASE с неизвестным исходом остаётся sticky;
последующий противоречивый success не открывает тот же controller.

Код: [ContinuousPointer](../../../frontend/src/features/stream/continuousPointer.ts),
[DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx),
[интеграционные fixtures](../../../frontend/__tests__/stream/pointer-control.test.tsx).

### 4. История теряла точную причину отказа и протокол primary-пути

Общий `control_failure=other` не различал startup busy и неизвестный native outcome.
Primary video sample не сохранял UDP/TCP выбранной пары. Добавляются ограниченный
enum причины и выбранный протокол. Последняя причина с серверным временем
сохраняется в summary после вытеснения 15 детальных browser samples.
Сохраняются лимиты: 10 сеансов/устройство, 32 KiB/сеанс, retention 7 дней.
Нет raw exception, candidate IP, SDP, координат, картинки или траектории касания.

Код: [browser telemetry](../../../frontend/src/features/stream/streamSessionTelemetry.ts),
[серверная история](../../../backend/websocket/stream_session_history.py).

## Что показывают готовые решения и стандарты

1. Parsec использует TCP для backend/API, STUN и peer-to-peer UDP для интерактивного
   потока. Его документация отдельно оговаривает firewall, NAT/CGNAT и резервный relay.
   Это поддерживает разделение control plane/media plane; близость двух компьютеров
   сама по себе не гарантирует прямой маршрут или заданный RTT.
   [Parsec Connectivity Requirements, обновлено 8 июля 2026](https://support.parsec.app/hc/en-us/articles/32381460716180-Parsec-Connectivity-Requirements).
2. Parsec отдельно измеряет encode, decode и network RTT. Число network RTT не
   равно пути от касания до изменившегося пикселя. Наш серверный Android ACK также
   нельзя подписывать как задержку видеокадра.
   [Parsec overlay и метрики](https://support.parsec.app/hc/en-us/articles/32381603663636-Stream-Overlay-Stats-and-Logging).
3. WebRTC уже предоставляет ICE/STUN/TURN, DTLS, RTP и DataChannel. Сервер сигнализации
   обменивается SDP/candidates; успешный signaling не доказывает рабочую ICE-пару.
   TURN нужен как резерв для сетей, в которых прямой путь не установлен.
   [Официальное руководство WebRTC](https://webrtc.org/getting-started/peer-connections).
4. DataChannel поддерживает надёжную и частично надёжную доставку. Доставка байтов
   не является подтверждением применения Android InputDispatcher. Поэтому direct
   input должен сохранить native ACK, binding и deduplication; замена WebSocket
   на DataChannel сама по себе не решает неизвестный исход команды.
   [RFC 8831](https://www.rfc-editor.org/info/rfc8831/).
5. W3C определяет `currentRoundTripTime`, накопленные `jitterBufferDelay`,
   `jitterBufferEmittedCount`, `totalDecodeTime` и `framesDecoded`. Для текущего окна
   нужны разности счётчиков. Нет frames в окне — нет основания делить на ноль
   или показывать искусственное время декодирования.
   [WebRTC Statistics API](https://www.w3.org/TR/webrtc-stats/).

Не заменяем существующий native WebRTC второй сетевой библиотекой ради названия.
Pion уместен для Go-компонента/relay, но не устраняет Android input ownership,
ошибки браузерного lifecycle или отсутствие достижимой пары между этими peers.
[Официальный проект Pion WebRTC](https://github.com/pion/webrtc).

## Достоверные измерения

| Измерение | Источник | Что оно не доказывает |
|---|---|---|
| Android ACK RTT | браузерный send → bound native receipt | задержку видеокадра и реакцию приложения |
| Direct network RTT | selected ICE pair `currentRoundTripTime` | половину RTT как точный one-way delay |
| Decode ms | delta `totalDecodeTime` / delta `framesDecoded` | encode/capture/network/display delay |
| Jitter buffer ms | delta delay / delta emitted count | полную capture-to-display задержку |
| Primary decoded FPS | delta decoded / delta stats timestamp | частоту захвата или частоту экрана Android |
| Presented frames | video frame callback | успешное Android-действие |
| Frame age | локальное время последней отрисовки | синхронизацию часов Android и браузера |
| Capture-to-display | коррелированный frame ID/clock protocol или внешняя съёмка | сейчас полного измерения нет |

Статичный экран может давать 0 кадров/с в коротком окне при живом соединении.
Зависший эмулятор нельзя заставить произвести новый кадр сетевым reconnect.
Это должно отображаться отдельно от ICE/DTLS failure и от отсутствия контроллера.

## Следующие обязательные проверки

- Реальный native watchdog APK 1.2.53: idle timeout без касаний → normal exit;
  fresh control после него. Для held failure дополнительно известный CANCEL.
- PH025 после загрузки: точные версия/подпись/SHA, startup, idle, Home/Back,
  continuous gesture, повторный viewer, журнал без бесконечного startup busy.
- Локальная, LAN и WAN топологии — отдельные прогоны; PH030 не считать доступным.
- Выбранная пара и UDP/TCP, direct frames, native ACK, fallback и число recovery
  фиксируются вместе. Server-only control не маркируется прямым.
- VPN только на signaling-сервере; VPN на одном из peers; restricted UDP;
  CGNAT/symmetric NAT; TURN UDP и TLS — разные сценарии.
- ICE restart/краткий `disconnected` не должен уничтожать исправный control owner.
  Ended track, auth revoke, capture mismatch и native unknown остаются отдельными причинами.
- Два и более зрителя: один текущий controller, понятный takeover, отсутствие
  переключения owner от позднего RELEASE прежней вкладки. Direct input пока OPEN.
- Lag/CPU pressure, encoder очередь, decoder очередь, скрытая вкладка, reconnect
  backend/agent/browser и смена адреса проверяются раздельно и затем совместно.
- Soak с ограниченным объёмом журналов: рост очередей/RSS/диска, остановка и
  освобождение ресурсов. Короткий успешный запуск не заменяет длительный прогон.

## Надёжность клика при разрыве

Требование пользователя сохраняется: один принятый клик должен иметь видимый
результат, а временный сбой — восстанавливать дальнейшее управление автоматически.
Нужен отдельный контракт логического действия: stable action ID, deadline,
Android deduplication, receipt и запрос исхода после reconnect. Ответ «применено»
может выдавать только Android; отсутствие ACK не доказывает отсутствие действия.
После crash между применением и записью receipt исход может остаться неизвестным.

Для непрерывного жеста нельзя отложить старую траекторию на несколько секунд,
а затем воспроизвести её поверх нового экрана. MOVE устаревает и объединяется;
terminal/CANCEL освобождает прежний owner. Транспортный retry допустим только в
контракте, который исключает двойное применение и проверяет актуальный capture.
Пока такого прямого action-контракта нет, очередь повторов намеренно не включена.
Это открытая функциональная работа, а не обещание «клик прошёл» при неизвестном исходе.

## Приёмка

Исходники, локальные fixtures, подписанный build, установка и runtime-проверка
фиксируются разными доказательствами. Отказ PH025, direct input, localhost/LAN/WAN,
TURN, полная задержка и стабильная 1.3 остаются OPEN до фактических результатов.
Текущий реестр: [WORK-STATUS](../../operations/WORK-STATUS.md).
