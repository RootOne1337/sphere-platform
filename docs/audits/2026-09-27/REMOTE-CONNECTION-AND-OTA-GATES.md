# Remote WSS и OTA: срез перед расширением pilot · 27 сентября 2026

**Область:** только изолированная установка `sphere-pilot-20260911`.
Legacy Docker-проекты и удалённые Android-устройства не переустанавливались.
Сырые журналы, идентификаторы сессий и параметры доступа хранятся только в
ignored `.local-pilot/rollout/ota-ui-20260927/`.

## Решение для оператора

**Fleet32 и массовая OTA пока NO-GO.** На проверке 26 сентября около 19:05 UTC
API вернул 16 зарегистрированных записей: 12 `online`, 4 `offline`. Эти значения
являются моментальным снимком, а не длительным uptime. Десять удалённых online
устройств всё ещё сообщили `1.2.22-dev / 10222`; локальные `auto-ph-010` и
`auto-ph-011` имели 10228 и 10229 соответственно. Уже после снимка локальный
`auto-ph-011` получил canary 10230; установку и OFF/ON проверили отдельно.

| Приоритет | Дефект / ограничение | Доказательство | Текущее действие |
| --- | --- | --- | --- |
| P1 | Remote WSS закрывается, устройство колеблется между состояниями | PH022/PH025: по 20 завершённых сеансов за 20 минут на public gateway; все HTTP 101, большинство длиной ровно 40 или 60 секунд; backend close 1005. У локальных PH010/PH011 за тот же интервал не было завершившихся WSS-сеансов | Требуется контролируемый A/B ingress одного remote canary с client-side close/failure и gateway timing; Cloudflare как единственная причина **не доказан** |
| P1 | Резервный ingress неработоспособен | Primary `/api/v1/health/readyz` → 200; подписанный fallback LocalTunnel → 502. `sphere-pilot-alt-ingress-20260926` запущен и из него origin gateway отвечает 200, но у контейнера нет healthcheck и restart policy | Не считать опубликованный fallback отказоустойчивым; восстановить управляемый второй ingress и принять health/WSS/command/frame на одном canary |
| P1 | Дистанционная OTA не доказана | `android/dev` каталог отдаёт только 10209. 10230 опубликован только в `android-canary/dev`; одна адресная попытка на PH022 завершилась `failed/timeout`, версия осталась 10222 | Не открывать общий канал до адресной установки с PackageManager, SHA и свежим heartbeat |
| P2 | Прямой Redis OTA обходил сохранённую выдачу | За 20 минут backend записал 37 `ota_recovery_receipt_unrecognized` для remote PH025 и 40 для local PH010. Android помечает все `OTA_UPDATE` как recovery receipt, backend признаёт только подписанный и сохранённый grant. Путь `POST /updates/recovery` уже существует; прямой Redis dispatch его обходит. `966e56f` классифицирует отказ, но **не ACK** | Не использовать прямой Redis как rollout-путь; испытать адресный recovery grant и receipt, сохранив fail-closed проверку |
| P1 | Удалённый viewer не получает IDR/P | Повторный PH022-пробник: Android сообщил 11 encoded frames / 67906 байт и 13/13 локально принятых WS queue calls; сводка четырёх backend worker показала только SPS/PPS — 2 пакета / 61 байт, Redis и public viewer те же 61 байт | Потеря между локальной очередью OkHttp и ASGI binary ingress; проверить отправку/разрыв на Android и сравнить независимый ingress, не объявляя Cloudflare доказанной причиной |
| P1 | `/metrics` показывает неполные счётчики | 120 параллельных GET показали четыре разных `process_start_time_seconds`, а deployment не включает Prometheus multiprocess mode; один scrape читает память одного Gunicorn worker. Поэтому прошлые ingress/Redis/viewer totals нельзя выдавать за общие | Спроектировать worker-safe сбор без бесконечной per-device cardinality; проверить 4-worker aggregation на изолированном runtime до pilot rollout |
| P2 | Веб скрывал canary-релизы | `/updates` запрашивал только `android`; backend хранит 12 релизов, включая `android-canary` 10228 | Исправлено `213402b`, regression до/после; pilot frontend развёрнут из `8fef5eb` |

У PH025 за тот же интервал backend записал 21 успешную аутентификацию и 21
`Agent heartbeat established`; у PH022 — 20 и 20. Событий `Agent heartbeat
timeout` для этих устройств в срезе нет. Следовательно, каждый новый сокет
хотя бы раз доставлял `ping`/`pong`; проблема возникает **после** установления
живой сессии. Код `1005` сообщает об отсутствии штатного close-frame, но сам
по себе не указывает, какая сторона первой оборвала TCP/WSS. Счётчики gateway
собраны по завершённым сеансам; отсутствие локальных строк за окно также не
доказывает, что локальный Android шёл в обход gateway — его длинный сокет мог
оставаться открытым и поэтому не попасть в access log.

### Что именно удалось и не удалось проверить в вебе

После замены **только** pilot frontend образа из `8fef5eb` контейнер стал healthy,
`/updates` и `/readyz` вернули 200; все остальные контейнеры и SHA файла каталога
сохранились. Авторизованный read-only API `/updates/` вернул 12 релизов, среди
них canary 10228. Frontend regression проверил default запрос без platform filter
и видимость canary; полные 39 suites / 297 tests, type-check и production build
прошли. CLI-браузер на этой Windows-сессии завершился при запуске Chrome, поэтому
фактический DOM в браузере оператора здесь **не принят**; HTTP 200 и Jest не
подменяют эту проверку.

### Почему новый APK пока не приходит автоматически

`UpdateCheckWorker` проверяет каталог при старте/восстановленном management
соединении с jitter до 120 секунд и периодически каждые шесть часов при сети.
Его запрос — `platform=android&flavor=dev`. На pilot этот канал всё ещё указывает
на **10209**, поэтому версия 10222 правомерно получает `update_available=false`.
Canary 10230 доступен через отдельный platform и не выбирается штатным worker.
Регистрация релиза в каталоге не загружает APK в GitHub или на Android.

Второй репозиторий `sphere-agent-config` содержит **конфигурацию обнаружения
маршрутов, а не APK**. Pilot APK использует подписанный документ v25 из ветки
`codex/pilot-bootstrap-20260911`; локальный и публичный signed manifest совпали.
`main` второго репозитория всё ещё содержит исторический Serveo v2 и не является
источником текущей pilot-сборки. Подписанный адрес fallback может устареть:
наличие корректной подписи не означает health доступного туннеля.

### Fix: проверка OTA-каталога через сохранённые маршруты

**Root cause.** Worker использовал только `getServerUrl()`. Если сохранённый
активный fallback возвращал 502 или TCP reset, он выдавал `Result.retry()` без
попытки обращения к доверенному primary, хотя `AuthTokenStore` уже хранил оба
маршрута, а скачивание APK в 10229 уже разрешало оба HTTPS origin.

**Reproduction → fix → regression.** Тест с активным fallback (502) и рабочим
primary сначала падал: было одно обращение и `retry`. В `0e259bc` worker
перебирает уникальные сохранённые management routes, не меняя владение активным
WebSocket-маршрутом. На 502 или IOException он пробует следующий маршрут;
401/403/429 прекращают перебор и возвращают WorkManager retry, чтобы не
рассылать отклонённый токен/лимит по другим адресам. Тесты проверяют 502,
connection reset, 401 и запуск OTA ровно один раз после удачного каталога.
Обе полные flavor suites прошли **683 теста каждая**, 0 failures/errors,
1 штатный skip; `lintDevDebug`, `assembleDevDebug` и `assembleEnterpriseDebug`
прошли. Следует отдельно проверить refresh истёкшего токена при смене маршрута:
этот fix не утверждает, что весь auth failover закрыт.

**Canary runtime.** Source-pinned pilot debug APK `1.2.30-dev / 10230` из
`0e259bc` имеет SHA-256
`525108a0e07962e8b76bb1aab33efa97f757682bda3f0f9d8fa21caeb2462498`,
тот же signer/package и signed discovery v25; адреса управления не зашиты.
Только `emulator-5554` установлен этим APK; установленный `base.apk` совпал по
SHA. После полного LDPlayer quit/launch без открытия Sphere Activity появились
новый Android boot ID, persisted boot job, PID `2224`, foreground service и
server heartbeat `online`/10230 в `19:22:26Z`, без нового crash Sphere.
Это доказывает автономный запуск на одном локальном Android 9, **не на удалённых
клонах и не на Android 14+**. Позднее 10230 опубликован в управляемом
`android-canary/dev` pilot-каталоге, но не в общем `android/dev` и не на
GitHub Releases; на remote он не установлен.

## Дополнительная live-проверка 26–27 сентября

После публикации 10230 в canary-каталог API возвращает **13** релизов.
Указанные выше 12 относятся к снимку перед публикацией.

Для **одного и того же удалённого PH022** локальный и публичный viewer получили
только один SPS-пакет (37 байт), без IDR/P. Android сообщил 15 encoded frames /
142002 байта и 17 успешных постановок в локальную WebSocket-очередь. Это ещё
не подтверждает сетевую доставку. Один scrape `/metrics` показал для PH022
9 NAL-пакетов / 281 байт, все SPS/PPS, и равные счётчики Redis/viewer; для
локального PH010 в том scrape были IDR/P и 80774 байта ingress.

**Ограничение измерения обнаружено позже.** Gunicorn запускает четыре worker,
а `/metrics` используется без `PROMETHEUS_MULTIPROC_DIR` и отдельного
`MultiProcessCollector`. В 120 параллельных GET обнаружены четыре разных
`process_start_time_seconds`: scrape читает один процесс. Следовательно,
9/281 и 8/80774 — показатели одного worker, **не глобальные суммы backend**.
Нельзя утверждать, что кадры потеряны обязательно до ASGI. Доказаны только
локальная постановка Android в очередь и отсутствие IDR/P у двух viewer;
разрыв находится где-то между ними, включая возможную backend/Redis-доставку.
Точный сетевой узел и гипотеза о Cloudflare как единственной причине не доказаны.
Официальные [Prometheus Python multiprocess constraints](https://prometheus.github.io/client_python/multiprocess/)
и [интеграция starlette-exporter](https://github.com/stephenhillier/starlette_exporter#multi-process-mode-gunicorn-deployments)
требуют предварительной очистки каталога и Gunicorn `child_exit`; кроме того,
`Gauge.remove` и `Counter` с `device_id` в текущем коде требуют отдельного
решения по cardinality до включения multiprocess mode.

**Повтор после выявления ограничения `/metrics`.** В 00:20 UTC выполнен новый
изолированный просмотр PH022, затем 120 параллельных scrape покрыли все четыре
различных Gunicorn worker (по `process_start_time_seconds`). Сумма их counters:
ASGI ingress — **2 пакета / 61 байт**, SPS и PPS; Redis publish — 2/61;
viewer send — 2/61. Прямой локальный viewer не получил видеопакетов, публичный
получил только эти два SPS/PPS. Свежий report Android в 00:20:42 UTC: 11
encoded frames / 67906 байт, 13/13 локально принятых WS queue calls /
68121 байт, `encoder_errors_total=0`. Это локальная очередь, не transport ACK.
Результат повторяет отсутствие IDR/P в браузере и теперь **локализует потерю
до ASGI ingress** для данного проба. Различить stale/недоставленную очередь
OkHttp, WAN, edge tunnel и gateway без client-side отправочных ACK и второго
ingress пока нельзя. После probe все данные оставлены приватно в
`.local-pilot/remote/live-stream-canary-20260927-ph022-multiprocess/` и
`.local-pilot/rollout/ota-ui-20260927/metrics-worker-aggregated-private.json`.

Попытка `REQUEST_LOGS` к PH022 вернула HTTP 504 через 15 секунд, а сохранённый
log upload устройства был пуст. Это отдельный пробел управляемости: состояние
`online` не гарантирует ответ интерактивной диагностической команды.

Одна экспериментальная команда `OTA_UPDATE` для PH022 отправлена напрямую через
Redis 26 сентября в 19:37:14 UTC. Этот способ **обошёл сохранение server-side
выдачи** и потому не является поддерживаемым production-путём OTA. В коде уже
есть `POST /api/v1/updates/recovery`, который сохраняет подписанный grant;
`get_ota_recovery` до обычного WS auth проверяет и действительный токен,
выпущенный раньше grant. Characterization regression для этого случая прошёл
(33 теста recovery suite). **Runtime-доставку через этот путь на удалённом
устройстве мы ещё не проверили.** Public
gateway записал два HTTP 200 GET управляемого APK за 2,831 и
2,129 с; его журнал не подтверждает число байт, полученных Android, поэтому
HTTP 200 не доказывает полную загрузку. PH022 остался на 10222. После
развёртывания backend `966e56f` повторная квитанция **того же device/command ID**
имеет `status=failed`, bounded `failure_code=timeout`. Сервер не ACK-ает её,
потому что не может связать с durable issuance; это корректный отказ, а не
повод доверять произвольному результату клиента. Квитанции
`download_origin_rejected` принадлежат другим командам/устройствам и не
являются доказательством причины отказа PH022. `timeout` пока не различает
сетевое чтение и стадию установки. Повторной OTA-команды не было.

Regression для `966e56f` сначала воспроизвёл отсутствие категории, затем
прошли 32 targeted и 235 backend WS/recovery тестов, Ruff и diff check.
Source-pinned pilot backend образ `sphere-pilot-20260911-backend:966e56f`
развёрнут с проверкой SHA исходника в образе, внутреннего readiness,
неизменности каталога, артефакта, frontend и непилотных контейнеров.
Два первых deploy-check откатились: сначала использовался неверный HTTP path,
затем gateway задержал ответ во время замены backend. Устаревший image tag в
частном compose override заставил откат временно поднять `2168c33`; после
исправления проверки финальный deploy `966e56f` прошёл. Следующий deploy
должен сохранять фактический предыдущий image ID, а не доверять старому
override. Сразу после замены было 2/16 online, после reconnect — 12/16;
это лишь моментальные снимки, не доказательство длительной стабильности.

Сырые wire-пакеты, OTA intent, gateway access и backend logs оставлены в
ignored `.local-pilot/remote/live-stream-canary-20260927-ph022/` и
`.local-pilot/rollout/ota-ui-20260927/`; идентификаторы и параметры доступа
не опубликованы.

## Следующий доказательный шаг

1. Поднять и постоянно проверять независимый второй ingress, не меняя старый
   Docker; провести на одном удалённом Android сравнительные WSS-сеансы с
   замером Android `onFailure`/close, gateway duration, backend heartbeat и
   command receipt. Внешний Quick Tunnel или LocalTunnel без health недостаточен.
2. Проверить существующий `POST /updates/recovery` и специализированный
   OTA-only WS path сначала на локальном canary: grant до доставки, совпадение
   tenant/device/command/status, persist-before-ACK, повтор после reconnect.
   Код допускает действительный device JWT, выпущенный до grant, но runtime
   для active remote не принят. Исторические 10222-квитанции требуют отдельной
   миграционной стратегии; неизвестный grant не подтверждать.
3. На одном remote canary уточнить стадию `timeout`, затем подтвердить
   delivery/download/SHA/PackageInstaller,
   установленный versionCode и heartbeat после перезапуска APK. Только после
   этого открыть общий `android/dev` канал по ступеням 1→4→8→16→32 с rollback.
4. Исправить worker-safe метрики, затем проверить moving frames независимо:
   encoder на Android, исходящий счётчик, ingress каждого worker, первый IDR/P,
   декодирование в браузере и поведение после
   40/60-секундного reconnect. `online` не является доказательством видео.

[Приёмка boot и прежней OTA](../2026-09-26/ANDROID-COLD-BOOT-AND-OTA-CANARY.md) ·
[Подробный remote control path](../2026-09-26/REMOTE-CONTROL-PATH-DIAGNOSIS.md) ·
[План Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md)
