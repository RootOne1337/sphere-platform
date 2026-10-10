# N09 — безопасное восстановление H.264 после потери серверного кадра

Дата: 3 октября 2026, Asia/Yekaterinburg. Продолжение F36; исходный аудит
сохранён. Этот документ отделяет исправленную ошибку очереди от ещё открытой
приёмки плавности и задержки выбранного устройства.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Evidence](STREAM-REFERENCE-RECOVERY-EVIDENCE.json) ·
[Реестр исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Предыдущий ABR fix](STREAM-BITRATE-RECOVERY.md)

## Реальные измерения до этого изменения

На установленном API **facba9a** и APK **1.2.44-dev/10244** запущен один
конечный тест на PH025 и один на PH010. PH025 относится к удалённым устройствам
по ранее сообщённому пользователем размещению; измерение не определяет геолокацию.
Для каждого создан один authenticated viewer и ровно один запуск встроенного
debug `StreamCadenceProbeActivity`. Он рисует движущуюся полосу и детали,
сам завершается через 30 секунд, не меняет настройки/аккаунты. Глобальный stop
не отправлялся. Сохранялись только метаданные пакетов и bounded telemetry,
**0 байт видео**. Host ADB и PC Agent не используются.

| Устройство | Окно движения | Доставленные picture access units | Средняя доставка | Средние wire bytes ×8 |
|---|---:|---:|---:|---:|
| PH025, удалённое | 20   с | 597 | 29,85 кадра/с | 1,065 Мбит/с |
| PH010, локальное | 20   с | 598 | 29,90 кадра/с | 1,038 Мбит/с |

В свежих heartbeat APK сообщал capture 59–60, submission 29–30, encoder 29–30
кадров/с, 0 read/render/encoder errors и 0 локальных WS rejection. Это отдельные
срезы с временем `observed_at`; повторное чтение одного heartbeat не является
новым замером. Raw frame throttle объясняет capture выше encoder, а не потерю
уже закодированных reference pictures.

Получатель — инструментальный WebSocket-клиент, **не браузерный decoder/canvas**.
Это подтверждает Android→туннель→API→Redis→viewer delivery в этих конечных окнах.
Не подтверждены rendered FPS, визуальная чёткость, glass-to-glass или
input-to-photon latency, стабильность всего парка и 20–30-device stream+scripts.
Первый readback: 19 в каталоге /14 online, все14 с10244;16 контейнеров сохранены.

## Доказанная ошибка N09

Старый `VideoStreamQueue` удалял отдельный P-frame при переполнении/просрочке,
но оставлял более новые P-frames. При цепочке IDR0→P1→P2→P3 удаление P1
не делает P2/P3 независимо декодируемыми. Decoder может получить отсутствующую
reference picture, скрыть ошибку либо показать повреждённую картинку.

Дополнительно deadline200мс проверялся только при следующем `put`, а IDR
вообще не истекал. Застрявший consumer мог позже получить10-секундный IDR.
Leading SEI/AUD в целом access unit также нельзя считать отдельным безопасным
metadata packet, если следом есть VCL-picture.

Воспроизведение: базовый source **09a3dae** с новыми требованиями дал семь
assertion failures. Восьмой case остановился на отсутствующем callback API;
это проверка нового контракта, а не дополнительное воспроизведение старого бага.
Предшествующий запуск без test JWT не собрал fixture и не включён в proof.

Нативный congestion trace старого backend в пользовательском сеансе отсутствует.
**N09 не объявляется установленной причиной прежнего слайд-шоу**. Более того,
29,85/29,90 delivery FPS получены до его установки.

## Исправленный контракт

1. Потеря кадра переводит только затронутую очередь в ожидание нового IDR.
2. Удаляется зависимая buffered chain; SPS/PPS могут пройти во время recovery.
3. Более новые delta pictures не выдаются до настоящего IDR. Один wire flag
   или ведущий SEI не заменяет проверку содержащихся NAL types.
4. Deadline проверяется и на `get`, включая IDR. Configuration не истекает
   как picture. Count 50 / bytes 8MiB остаются жёсткими ограничениями.
5. Оба участка — agent→Redis и Redis→viewer — используют этот контракт.
6. При неизвестном исходе Redis publication зависимая цепочка также блокируется.
7. Запрос нового keyframe планируется отдельно от queue lock/Redis reader.
   На устройство действует общий cooldown 1  с и не более одной owned task;
   task удаляется после completion/cancellation, учитывается в shutdown.
8. Медленный зритель не удаляет кадры из очереди другого зрителя. Запрос IDR
   общий для encoder; конфигурация и права viewer не меняются.
9. Drop reasons доступны в существующей Prometheus series
   `sphere_stream_server_queue_drops_total`: `reference_gap`/`awaiting_idr`
   добавлены к прежним ограниченным значениям, без новых dynamic labels.

Стратегия намеренно консервативная: reference pictures не классифицируются
на безопасно пропускаемые temporal layers. После congestion возможна короткая
пауза до нового IDR. Нельзя обещать его выдачу за 1  с только из cooldown: codec
может не выполнить запрос; следующий delta позволяет повторить recovery.
Queue deadline не является пределом уже выполняющегося socket write.

## Проверки и дальнейшая приёмка

**230 WebSocket cases прошли**, включая 11 новых queue/bridge cases. Проверены
count/bytes bound, reference gap, idle dequeue deadline, mixed SEI+VCL,
configuration during recovery, uncertain publication, coalesced request,
shutdown ownership и изоляция медленного viewer. Два прежних теста требовали
сохранения просроченного IDR; обновлены именно под deadline contract.
Ruff изменённых файлов и mypy трёх production modules прошли.

**41 case прошёл на отдельных PostgreSQL/Redis**. Multi-worker test моделирует blocked writer:
healthy viewer получает исходную цепочку, slow viewer пропускает её после gap
и возобновляется с новым IDR. Runtime rollout фиксируется
отдельным readback после сборки immutable image.

Открытые действия по F36:

- Проверить фактическую browser decode/output/render cadence на движении,
  queue recoveries и stale drops; текущий visual gate OPEN_URL_POLICY_BLOCKED.
- Измерить input acceptance→Android execution→видимый кадр с корреляцией,
  а не вычитать timestamp разных часов без синхронизации.
- Согласовать requested/accepted encoder profile: сервер пока передаёт 2 Мбит/с,
  APK создаёт default 1.5M; отдельный preview profile ещё не реализован.
- Принять image quality, recovery/soak и simultaneous stream+scripts20–30.
- Stable signer/normal OTA promotion и пять offline targets вне этой приёмки.

## Установленный runtime и повторный тест

**Backend 37415e3 установлен 2026-10-03T15:47:56.242886+00:00** из git-archive image
`sha256:842c17003f240a3762092c10b1806becdc1daab5e4d46fb3934d108eba26368e`. Exact health revision/readiness совпали. Внутри этого
immutable image 271 cases passed; tests взяты из того же archive, backend source
не подмонтирован. UI 77fca37, APK 10244, Tuna, OTA catalog и15 соседних контейнеров
сохранены. Кандидат принят после двух автоматических rollback старого backend:
raw Docker inspect различался формой C-drive bind и порядком mount arrays.
На втором сравнении разница была только в порядке mounts неизменного Grafana.
Перед следующим deploy отдельно сверены фактическое содержимое owned config,
нормализованные mounts всех16 сервисов, ID/image/StartedAt соседей. Один preflight
остановился до mutation на прежнем Tuna config bind вне workspace; этот заранее
существовавший именованный путь включён в точную read-only сверку. Данные volume,
режимы RO/RW и destination не менялись. Первоначальные receipts не перезаписаны.

Повторено ровно по одному finite motion trial:

| Устройство | Access units /20  с | Delivery FPS | Wire Мбит/с |
|---|---:|---:|---:|
| PH025 |599|29,95|1,100|
| PH010 |599|29,95|1,104|

Разница с исходным29,85/29,90 не объявляется значимым приростом от N09: это
короткие измерения без forced congestion. Исправление предотвращает broken
reference chains; его fault acceptance — отдельный multi-worker regression.
Никакие видео/скриншоты этого прогона не сохранены; renderer не проверен.

**7 контрольных срезов 2026-10-03T15:52:56.720357+00:00–2026-10-03T15:53:57.247698+00:00** сохранили
все14 online10244, heartbeat<60  с и новые connection epochs. Restart backend
естественно сбросил прежние epochs; непрерывный uptime через deploy не заявляется.
Monitoring API читается; Prometheus `up{job="sphere-backend"}=1` подтверждён.
5 offline/production signer/normal OTA/браузер/input latency/soak/F36 остаются
OPEN. Source GitHub CI status записан с конкретными run IDs в Evidence;
Backend, frontend и Android source checks прошли. Docs head имеет собственные checks.

## Первичный источник

[RFC6184 §8.5.1](https://www.rfc-editor.org/rfc/rfc6184.html#section-8.5.1)
описывает recovery через IDR с доступными SPS/PPS. Используется свойство
H.264 reference recovery; Sphere остаётся WebSocket transport, не объявляется
RTP/RTCP реализацией. Допуск metadata во время ожидания не даёт права отправлять
VCL dependants потерянной picture.
