# N10 — отзыв доступа у уже открытого видеопотока

Дата аудита: 4 октября 2026 (UTC+5). Продолжение
[F39](../2026-10-03/SESSION-CAPABILITIES.md) и
[журнала исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md).
Замороженный аудит F01–F41 не изменяется.

## Дефект и доказательство

API/UI `00d5ad8` проверяют роль при подключении WebSocket. Однако
`stream_viewer_ws` сохранял `can_control` для всей сессии. После отзыва роли
HTTP-операции запрещались, а уже открытый WebSocket продолжал передавать ввод.
Проверка прав в интерфейсе не закрывала этот серверный разрыв.

В настоящих disposable PostgreSQL/Redis воспроизведены **четыре провала**:
tap, swipe, keyevent и text. После committed смены роли org_admin → viewer
каждая операция второй раз дошла через Redis до тестового приёмника Android.
Это проверка реальной серверной доставки, а не результат запуска команды на
живом Android; пользовательские устройства и их роли не менялись.

## Исправление

- Перед каждым вводом повторно проверяются подпись/срок JWT, Redis blacklist,
  активность пользователя, его организация, актуальная роль и принадлежность
  устройства. DB session закрывается до отправки команды.
- При stream:read без stream:control просмотр сохраняется, ввод получает
  `stream_control_denied`. Новое явное серверное разрешение может восстановить
  управление в той же сессии; старая роль в JWT не является разрешением.
- Пассивный просмотр проверяется на существующем интервале keepalive **10 с**.
  Проверка ограничена **2 с**. Это периодический отзыв просмотра, а не мгновенное
  удаление уже доставленной картинки и не гарантия абсолютного wall-clock SLA
  при остановленном event loop.
- Невалидная identity/expired/revoked JWT закрывает сессию кодом 4001; отзыв
  stream:read — 4003; потеря принадлежности устройства — 4004. Недоступная
  авторизация/таймаут — 1013. Непроверенный ввод не передаётся и не повторяется.
- Сначала удаляется sender из bridge, затем закрывается socket. Pending receive
  прерывается собственным событием отзыва, даже если клиент не подтвердил close.
  Задачи и подписки освобождаются; SQL connection не остаётся на время просмотра.
- Видео не ждёт SQL/Redis permission reads: они идут отдельно от binary delivery.
  Проверка перед вводом добавляет обращения к SQL/Redis; latency и нагрузка для
  тысяч одновременных viewers этим этапом не объявляются принятыми.

Уже отправленные действия не отзываются задним числом. Проверка и публикация
не являются одной транзакцией с изменением роли: проверяется свежий committed
state перед последующей операцией, без заявлений о глобальной сериализации.

## Проверки

Первый полный прогон: **293 passed / 0 failed / 0 skipped**, включая WebSocket,
реальные PostgreSQL/Redis, tenant/RLS, capability и control-routing regressions.
Отдельно добавлен случай отзыва stream:read; окончательный image gate записывается
после сборки. Changed Ruff и mypy для router passed.

Role-change сценарии проверены и от владельца БД, и от ограниченного runtime SQL
пользователя с настоящим RLS. Покрыты disable, перенос пользователя/устройства,
blacklist JWT, истечение подписанного JWT, passive revoke без close ACK, повторная
выдача управления, а также injected SQL/Redis failure и bounded authorization timeout.
Fault injection не объявляется остановкой живых production SQL/Redis.

Изменение не требует APK или frontend rebuild. Установка и её границы описаны ниже;
source passing и live acceptance учитываются отдельно.

## Незакрытые работы

F39 остаётся PARTIAL: права всех остальных action affordances и fresh browser
приёмка открыты. F34 preview transport, F35 XPath, F36 quality/FPS profiles и
20–30-device stream+scripts soak остаются отдельными этапами. Для этой работы
визуальная приёмка 3015 остаётся OPEN_URL_POLICY_BLOCKED.


## Собранный образ и runtime

API **37bb436** установлен 3 октября в 19:24:32 UTC / 4 октября в 00:24:32 UTC+5.
В immutable image повторены **294 теста, 0 failures/errors/skips**; backend source
не подменялся mount. Веб остаётся **00d5ad8**; ранее принятые 982 frontend cases
не выдаются за новый прогон. Backend/Frontend/Android/Preview CI 37bb436 — success.

Первый readback 19:25:14–19:26:15 не прошёл cohort/heartbeat/epochs gate: в конце
было 11 online. Он сохранён в evidence. Последующий readback 19:32:39–19:33:40
подтвердил те же 14 APK 10244, свежие heartbeat и одинаковые новые epochs.
Наблюдались 1012/502 около рестарта, затем SSL/Socket failures и переподключения
на route_slot 1. Номер route не является provider identity: его порядок зависит
от сохранённых маршрутов клиента. Причина этих повторных обрывов не установлена.
В первом окне не было viewer sessions: новый viewer permission path тогда не
выполнялся. Это ограничивает гипотезу о нём, но не доказывает причину сетевого сбоя.

Живой protocol probe PH025/PH010 длился по 12,5 с. Получены соответственно 15/2
H.264 pictures и keepalive после periodic authorization. Ввод не отправлялся;
автоматически отправлены capture controls start_stream/viewer_connected.
Кадры не сохранялись и не декодировались браузером. Тест неподвижного экрана
не устанавливает achievable FPS и не заменяет прежний motion trial 29,95 delivery FPS.

API build/readiness, capability 200/no-store, anonymous 401 и Prometheus up=1
подтверждены. Только API заменён; 15 соседних containers, UI, Tuna, volumes/mounts
и hash OTA catalog сохранены. Повторные старые unrecognized OTA receipts обнаружены
в логах; их reconciliation этим исправлением не закрыт.

[Публичные доказательства](VIEWER-AUTHORIZATION-EVIDENCE.json) ·
[Следующий этап F34](MATRIX-PREVIEW-PLAN.md). Полные логи/helpers остаются приватными.
