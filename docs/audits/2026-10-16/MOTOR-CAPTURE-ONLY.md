# Запуск headless-клиента без начальной серверной копии видео

16 октября 2026 · `motor_worker 0.2.0` · реализация `3d427a13`.
Продолжение [первого транспортного пилота](HEADLESS-MOTOR-WORKER.md), часть P0-C/G02
[общего плана](../../design/MOTOR-AI-PLATFORM.md).

**Этап проверен на PH011 через отдельный локальный API-кандидат. Основная установка не заменялась.**
Это проверка транспорта и idle admission, а не подключение моторной модели или управление игрой.
Полные счётчики, исходники и границы — [MOTOR-CAPTURE-ONLY.json](MOTOR-CAPTURE-ONLY.json).

## Поведение

`/ws/stream/{device}` теперь принимает явный первый пакет `{token, delivery: "capture_only"}`.
JWT, принадлежность устройства организации, `stream:read`, отзыв доступа, общая Redis presence
и остановка после ухода последнего зрителя сохраняются. Этот режим не создаёт video queue,
sender task или подписку на Redis video channel. Перевести его в relay нельзя.
Другие обычные зрители сохраняют свои очереди и fallback независимо от него.

Публикация `start_stream` ещё не означает готовность. Backend читает существующий live RPC
`stream_quality: get` и ждёт completed receipt с активным источником. Только явно неактивные
снимки повторяются, до 40 чтений с интервалом 250 мс и общим deadline 10 секунд. Неопределённый,
потерянный или неправильный ответ не повторяется. Настройки качества не записываются.

Затем клиент получает `capture_ready` с идентификатором своего сеанса и размером. Это ещё не
доказательство получения картинки. Точный capture epoch устанавливает существующий `SV1` через
DTLS; несовпадение размеров завершает пилот. Управление отдельно требует native READY.
Сам lifecycle socket не предоставляет touch/key/text admission.

Стартовая аренда ограничена 40 секундами. После подтверждения привязанного direct peer действует
10-секундная аренда с продлением каждые 3 секунды. При её истечении presence удаляется и socket
закрывается с `capture_lease_expired`. Автоматического перехода этого потребителя на relay нет.
Исправлена гонка перехода с длинного стартового таймера на короткий активный срок.

## Фактический прогон

| Измерение | PH011 / установленный APK 10276 |
| --- | --- |
| Основное окно | 15,007 с |
| Decoder outputs | 873 за прогон; 57,507 FPS в основном окне |
| RGB observations | 75; 4,998 Гц |
| Server → headless media с первого пакета | **0 байт** |
| После handover / relay decode | 0 байт / 0 кадров |
| Native control | READY, 49 idle ALIVE, CLOSED подтверждены |
| Последний ALIVE RTT | 3,757 мс; не полная capture→action latency |
| Pointer/key/text команды | 0 |
| ICE | UDP host/prflx; отсутствие VPN этим не доказано |

Кандидат собран локально из Git archive точного commit поверх установленного image с сохранением
его dependency layers. Сеть build отключена, зависимости не устанавливались. Временный API слушал
только loopback, использовал настоящие stream/direct routes и общие authenticated lease/command
механизмы. Оркестрационные циклы в нём не запускались. После проверки контейнер удалён; Docker ID,
image и время старта всех ранее существовавших контейнеров совпали до и после прогона.
Процесс APK PH011 остался прежним, PID 31355.

**Ноль байт означает отсутствие server→headless видеокопии.** В начале захвата APK по прежнему
может отправлять legacy video серверу до согласования direct suppression. Отсутствие этого трафика
не проверено и не заявляется. Signaling, авторизация и продление по прежнему используют backend.

## SDP и проверки

На backend и в исходниках Android добавлено отклонение `recvonly` offers, которые объявляют
sender SSRC/SSRC-group/MSID. Эта форма ранее сопровождалась native abort WebRTC146 на PH011.
Проверка выполняется до JNI. Локальные sendonly answers сохраняют свои source identifiers;
`msid-semantic` не запрещён. Worker уже формирует совместимый offer.

Это сужение поддерживаемого контракта, а не общее правило стандарта WebRTC. C++ причина прежнего
abort не символицирована. Все возможные SDP/native сбои этим этапом не считаются устранёнными.
Android guard скомпилирован и проверен unit-тестами, но новый APK не устанавливался.

Проверено локально:

- 968 WebSocket-тестов и 44 подслучая, включая fallback обычных зрителей и capture-only lease.
- 18 protocol и 10 настоящих программных H.264/DTLS/SCTP integration tests, без media skips.
- 4 PostgreSQL/RLS проверки: своё/чужое устройство, обычный/capture-only режим, runtime role
  `NOSUPERUSER NOBYPASSRLS`, RLS реально активна. Временные PostgreSQL/Redis удалены.
- 3 Android protocol tests на свежем build output, включая новые неподдерживаемые source declarations.
- Quality RPC regression tests, Ruff и scoped mypy прошли.

Hosted GitHub Actions для этого этапа не запускались. Проверки не являются полным production CI
или нагрузочной приёмкой 50 устройств. Архивная квитанция первого пилота остаётся неизменной.

## Следующий объём

Нужна штатная локальная упаковка и приёмка поставки, затем контролируемое обновление основного
backend и APK. Текущая основная установка: UI19c4272b/API969a7444/APK76. Candidate image не выдаётся
за установленный production artifact; прежний installer рассчитан на подтверждённый hosted CI archive.

Далее: source frame ID/clock/freshness, внутренние очереди decoder и нагрузочный предел, общий
game profile с удержаниями и simultaneous controls, neutral release, atomic DAG→episode delegation,
затем model adapter и supervised gameplay после получения доступа к GPU. Эти gates остаются открытыми.
