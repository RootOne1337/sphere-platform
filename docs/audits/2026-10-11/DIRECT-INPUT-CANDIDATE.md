# Прямые касания браузер ↔ APK: кандидат и границы проверки

11 октября 2026, UTC+5. Источник реализации: `7b6251817f42423a1ae90fb0c8837a8e976b3f60`.
Это документ реализации и проверки; факт установки фиксируется отдельной квитанцией.
Production, stable 1.3, минимальная задержка и полная матрица сетей не приняты.

## Текущий срез доставки

UI/API `6ee80c1f` работают на 3015 и действующем туннельном адресе; повторно
совпали 29 JS/CSS assets. APK `1.2.54-dev / 10254` адресно установлен на PH010:
проверены SHA пакета и завершение того же OTA-command после перезапуска Android.
Ещё шесть проверенных устройств используют53, PH019 и PH025 —52.
PH030 выключен и исключён; ещё пять машин были offline.
[Неизменяемая текущая квитанция](CURRENT-STREAM-DELIVERY.json).

Полные Backend/Frontend/Android CI для `e9af9e60` завершились успешно. Новый API/UI
не установлен: reviewed installer получил `volume_not_ready` и остановился до
загрузки Docker-образа или замены контейнера. Windows сообщает C: `Full Repair Needed`;
результат нового административного `chkdsk C: /scan` ещё не получен.
`DIRECT_TRANSPORT_INPUT_ENABLED` в работающем API остаётся false.
[Подробные условия доставки](DIRECT-INPUT-DELIVERY-BLOCKED.md).

PH01054 проверен с работающим6ee: 41 серверный кадр, ноль decode/render errors,
Home подтверждён Android. Прямых кадров нет; native ICE сообщил237 исходящих
запросов и0 ответов. Это не приёмка прямых касаний или localhost.

Новая автоматическая браузерная ICE-история и отдельная подпись маршрута касаний
проверены в рабочем source:647 WebSocket tests +44 subtests,549 frontend stream
tests. Эти изменения ещё не установлены и не входят в Docker-артефактыe9.
Native counters пока читаются отдельно из локального canary log.

## История сборки и проверки кандидата

Подписанный APK `1.2.54-dev / 10254` собран из
`7b6251817f42423a1ae90fb0c8837a8e976b3f60`:
57 688 052 bytes, SHA-256
`a8286157a7f78dd64fd7e954770f076d744822572602f56a154ad40fbad023d0`.
Проверена прежняя подпись pilot package. В dev и enterprise вариантах по
1028 unit tests, 0 failures/errors, 3 skipped; lint и debug assembly завершены.
Эти проверки доказывают сборку. Последующая установка PH010 подтверждена в текущем
срезе выше; ни сборка, ни установленный пакет сами по себе не доказывают прямой ввод.

Повторная сверка 10 октября, 22:45 UTC подтвердила фактические APK SHA на девяти
включённых совместимых устройствах: семь используют 10253, PH019 и PH025 —
10252. PH030 исключён по указанию пользователя; ещё пять устройств offline.
54 включает watchdog correction, поэтому промежуточная установка 53 на
проверенные 52 не требуется. OTA выдаётся адресно после завершения exact-source
Android CI; повторная команда при неоднозначном результате запрещена.

В проверочном сеансе PH010 на UI/API `6ee80c1f`, APK 53 обнаружена дополнительная
гонка: `touch_event` сначала получил retryable `runtime_unavailable`, а через
22 мс следующее уже отправленное сообщение получило terminal rejection, пока
прежний owner ожидал native RELEASE. Поэтому автовосстановление было отменено.
Backend correction `e9af9e60be1b2dcb1f13f7dd8b17db93dc8bfa4c` отбрасывает только
валидный ввод завершаемого owner без dispatch, ACK или повтора. Malformed input
и новый open по-прежнему отклоняются; чужой owner не затрагивается.
635 backend WebSocket tests и 44 subtests прошли; опубликованный source ещё
не является установленным runtime.

Тот же PH010 не открыл прямое видео: native ICE summary сообщил 242 исходящих
запроса, 0 ответов, 0 успешных пар. Это отдельный сетевой отказ, который прямой
input parser сам по себе не исправляет. На PH011 также наблюдается ICE checking;
ранее полученные прямые кадры не доказывают текущий маршрут.

## Задача пользователя

Основное видео уже может идти прямо с APK по WebRTC, но касания и их Android ACK
в установленной версии ещё идут по server WebSocket. Требуется перенести
DOWN/MOVE/UP/heartbeat и native ACK в соединение браузер ↔ APK, сохранив
авторизацию, управление владельцем, безопасный reconnect и достоверную диагностику.

## Текущее до установки кандидата

- UI/API `6ee80c1f` установлены на 3015 и действующем Tuna-host.
- На обоих адресах проверены 29 одинаковых клиентских JS/CSS assets и readiness.
- APK 1.2.53-dev/10253 установлен по адресной OTA на PH010, 011, 012, 014, 015,
  017, 018. У каждой из этих семи машин совпал SHA установленного пакета,
  получен completed того же update-command и снят его точный grant.
- PH030 выключен пользователем и исключён из обновления/приёмки.
- APK 53 исправляет известный дефект результата native watchdog cleanup.
  На PH010 отдельный idle watchdog без касаний завершился с exit 0.
  Это не доказательство успешного held CANCEL, длительного soak или исправления PH025.
- Повторный отказ PH025 до первого касания остаётся открытым. Первоначальный
  native exit того исторического отказа не записан; причина не объявляется доказанной.

## Архитектура кандидата

Один primary-video peer получает второй reliable ordered DataChannel
`sphere-control-v1`. Он независим от канала echo/metadata и RTP-видео.
Сервер согласует права, текущий viewer, текущую связь APK и единственного владельца
native-ввода. Координаты, движения и положительные native input ACK сервером
не пересылаются. Startup, release и ошибки остаются видимыми серверу.

1. Signaling привязывает peer к серверной 16-символьной stream-session, пользователю,
   организации, устройству и текущему agent WebSocket generation.
2. `touch_direct_open` ссылается на текущий peer и показанный capture/размер.
   Браузер не выбирает owner, user, tenant, TTL или Android connection.
3. Сервер проверяет scoped Redis peer lease через любой worker, затем выдаёт
   единственный native owner. APK проверяет текущий открытый DataChannel и capture.
4. Только Android STARTUP0 разрешает реальные касания.
5. Касания и input ACK используют DataChannel. Обычные команды, код сценария,
   shell и изменение прав через этот канал не принимаются.
6. Сервер повторно проверяет права/топологию и выдаёт sequenced authority renewals.
   TTL разрешения 1500 мс; heartbeat браузера не может продлить серверные права.
7. Независимый input watchdog требует heartbeat текущего владельца. Одного
   серверного renewal недостаточно для удержания зависшего пальца.
8. Потеря peer, capture, generation или прав отменяет прежнее касание. CLOSE
   остаётся доступен по независимому серверному пути. DOWN/MOVE/UP не повторяются.

Клавиши Back/Home/Recents/Menu и текст пока используют существующий server API.
Новый статус обязан явно говорить «прямые касания», а не «всё управление напрямую».
Это не реализация звука, прямой клавиатуры или richer gesture recorder.

## Переход маршрута

Маршрут фиксируется на время одного native owner. Переход с server input на
direct input разрешается только при idle owner, отсутствии pending ACK/обычной
команды и подтверждённом RELEASE3. Следующее открытие получает новую проверку
capture и native readiness. Уже начатый жест не переносится между маршрутами.

## Admission и обновление

- Серверный `DIRECT_TRANSPORT_INPUT_ENABLED` по умолчанию false.
- Кандидат требует primary-video admission, явный device allowlist и APK >=10254.
- Reviewed installer допускает `--direct-input` только вместе с `--live-video`
  и явным списком устройств. Смена БД, secret, портов и соседних контейнеров запрещена
  самим сравнением reviewed Compose; отключение probe выключает также direct input.
- API публикует `direct_input_enabled` отдельно от `live_video_enabled`.
- Read-only viewer не получает writable callback, native owner или право касаний.
- Публикация APK 54 и включение на машине допускаются после exact-source CI,
  подписи, package/version/hash и canary проверки. Факт PH010 установлен отдельно;
  распространение на остальные машины и direct-runtime приёмка ещё не завершены.

## Пройденные локальные проверки исходного7b

- Backend WS: 629 tests +44 subtests; scoped direct grants, cross-worker binding,
  single owner, отсутствие WS-касания для direct owner, fresh renewal, release.
- Focused backend/installer/history: 301 tests +65 subtests.
- Frontend: transport/channel/capture/cleanup и 102 canvas integration tests,
  включая direct MOVE до UP, отсутствие fallback-повтора, safe revoke и promotion.
- Android dev unit suite: 1028 tests, 0 failures/errors, 3 skipped. Direct touches
  дают native ACK только по DataChannel; потеря peer освобождает owner; просроченное
  server authority не продлевается heartbeat; ordinary commands отвергаются.
- TypeScript, mypy и Ruff прошли. Позднее подписанная сборка и exact-source CI
  завершились успешно; их номера и хеши приведены в текущей квитанции.

## Что ещё обязательно доказать

- Адресную установку APK54 остальным совместимым машинам после принятого canary.
  На PH010 пакет/SHA/completed command уже подтверждены, прямые касания ещё нет.
- Фактические reviewed API/UI на обоих origin, совпадающие assets и admission.
- Видимый direct touch ACK, native DOWN/MOVE/UP и отсутствие server touch dispatch.
- Reconnect, idle, несколько viewers, смена владельца и работа при lag APK.
- Ближайший путь localhost/LAN/WAN/VPN/TURN, а не только выбранный NAT-кандидат.
- Network RTT, native ACK RTT и capture-to-display latency — разные измерения.
  NAT/UDP не доказывает loopback, а успешный echo не доказывает доставку картинки.
- Без рабочего relay нельзя обещать 100% соединение через произвольный NAT/firewall.

[Основной рабочий реестр](../../operations/WORK-STATUS.md) ·
[Аудит надёжности](STREAM-RELIABILITY-AUDIT.md) ·
[Историческая установка основного видео](DIRECT-PRIMARY-VIDEO-INSTALLED.json)
