# Remote WSS и OTA: срез перед расширением pilot · 27 сентября 2026

**Область:** только изолированная установка `sphere-pilot-20260911`.
Legacy Docker-проекты не менялись. Оператор вручную установил 10230 на несколько
удалённых Android; в этом проходе агент не переустанавливался массово.
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
| P1 | Remote WSS закрывается, устройство колеблется между состояниями | PH022/PH025: по 20 завершённых сеансов за 20 минут на public gateway; большинство длиной ровно 40 или 60 секунд; backend close 1005. PH013 воспроизвёл 40,001 с и через отдельный Cloudflare HTTP/2 connector | Получить Android `onFailure`/close; QUIC→HTTP/2 не устранил сбой, но Cloudflare как единственная причина **не доказан** |
| P1 | Резервный ingress неработоспособен | Primary `/api/v1/health/readyz` → 200; подписанный fallback LocalTunnel → 502. `sphere-pilot-alt-ingress-20260926` запущен и из него origin gateway отвечает 200, но у контейнера нет healthcheck и restart policy | Не считать опубликованный fallback отказоустойчивым; восстановить управляемый второй ingress и принять health/WSS/command/frame на одном canary |
| P1 | Дистанционная OTA не доказана | `android/dev` каталог отдаёт только 10209. Canary-каталог содержит 10231; PH022 ранее вернул `failed/timeout` на 10230, PH017 теперь вернул `failed/timeout` на 10231, версии остались 10222/10230 | Не открывать общий канал до адресной установки с PackageManager, SHA и свежим heartbeat |
| P1 | Новый адресный grant дошёл до PH017, но APK не установилась | `40357ca` отправил тот же подписанный command ID через обычный WS; PH017 вернул `failed/timeout`, durable receipt сохранён и ACK отправлен; версия осталась 10230. Два artifact GET на public gateway дали HTTP 200, но полная доставка байтов клиенту не измерена | Разделить download body / installer timeout клиентскими bounded стадиями и проверить независимый ingress; общего rollout нет |
| P2 | Прямой Redis OTA обходил сохранённую выдачу | За 20 минут backend записал 37 `ota_recovery_receipt_unrecognized` для remote PH025 и 40 для local PH010. Android помечает все `OTA_UPDATE` как recovery receipt, backend признаёт только подписанный и сохранённый grant. Путь `POST /updates/recovery` уже существует; прямой Redis dispatch его обходит. `966e56f` классифицирует отказ, но **не ACK** | Не использовать прямой Redis как rollout-путь; испытать адресный recovery grant и receipt, сохранив fail-closed проверку |
| P1 | Удалённый viewer не получает IDR/P | Повторный PH022-пробник: Android сообщил 11 encoded frames / 67906 байт и 13/13 локально принятых WS queue calls; сводка четырёх backend worker показала только SPS/PPS — 2 пакета / 61 байт, Redis и public viewer те же 61 байт | Потеря между локальной очередью OkHttp и ASGI binary ingress; проверить отправку/разрыв на Android и сравнить независимый ingress, не объявляя Cloudflare доказанной причиной |
| P1 | `/metrics` показывает неполные счётчики | 120 параллельных GET показали четыре разных `process_start_time_seconds`, а deployment не включает Prometheus multiprocess mode; один scrape читает память одного Gunicorn worker. Поэтому прошлые ingress/Redis/viewer totals нельзя выдавать за общие | Спроектировать worker-safe сбор без бесконечной per-device cardinality; проверить 4-worker aggregation на изолированном runtime до pilot rollout |
| P2 | Удалённые журналы недоступны в момент обрыва | Для PH013/PH017/PH019 после установки 10230 нет periodic upload в контейнере, а адресный `REQUEST_LOGS` к PH013/PH025 завершается 504; локальный PH011 upload имеет. Каталог `/tmp/sphere_device_logs` не переживает пересоздание backend container | Перед deploy сохранять приватный snapshot; перенести bounded storage в управляемый volume с retention, дать heartbeat-диагностику результата HTTP upload и проверить remote delivery |
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
В 00:28 UTC повторена **одна** короткая read-only проверка на другом удалённом
PH025, который до вызова был `online`: `mode=sphere`, `lines=1`, 4 KiB budget.
Через 15 секунд API снова вернул HTTP 504. Контрольные данные остались в
ignored `.local-pilot/rollout/ota-ui-20260927/remote-short-logs-private.json`.
Повторного запроса не было; причина потери ответа между сервером и APK не
установлена. В тот же момент read-only inventory: 16 устройств, 9 online,
7 offline; PH022 сообщил 10222 и был offline.

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

**Новый диагностический fix `7a3d761`.** Regression сначала воспроизвёл, что
`package_installer_result_timeout` и `root install timed out` классифицируются
как общий `timeout`. Теперь backend сохраняет соответственно
`package_install_callback_timeout` и `root_install_timeout`; 238 targeted
WS/recovery tests и Ruff прошли. Source-pinned pilot backend image `7a3d761`
развёрнут с проверкой исходника, внутреннего health и неизменности APK-каталога,
frontend и legacy-контейнеров. После deploy именно старая квитанция PH022
несколько раз снова имела `failure_code=timeout`, не новые install-коды.
PH022 использует APK 10222, в котором ещё нет позднего
`PackageInstallerResultAwaiter`: это сужает гипотезу, но не доказывает, что
таймаут возник при загрузке. Не выдавать классификатор за успешную OTA.

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

### Ручная установка 10230 на remote и контроль без картинки · 00:30–00:35 UTC

Оператор установил свежую APK на несколько удалённых Android. API независимо
подтвердил `1.2.30-dev / 10230` на PH013, PH017 и PH019; локальный PH011 тоже
сообщает 10230. Следовательно, это **не только проблема старой установленной
APK**. Статусы трёх remote 10230 колебались между online/offline даже в соседних
read-only снимках. PH019 был `online` при inventory и `offline` к preflight
видеопроба; поэтому для него проба без viewer не засчитана как результат видео.

Для PH013, когда API показал `online`, провели отдельный local/public viewer
probe. Локальный viewer за ~20 секунд получил 0 бинарных пакетов; публичный
viewer получил 0 и закрылся с `ConnectionClosedError` через 0,862 с.
Worker-safe delta counters по четырём процессам backend для PH013 за пробу:
**0 ingress packets, 0 ingress bytes, 0 Redis publish, 0 viewer bytes**.
После пробы heartbeat snapshot Android был `stale` (~62 с) и устройство offline;
за этот capture-session Android указал 20 закодированных кадров / 253619 байт,
24 попытки отправки в локальную WS-очередь, 15 принятых / 80359 байт и
9 отвергнутых, encoder errors 0. Это локальное принятие OkHttp, не wire ACK;
нельзя утверждать, что эти 15 пакетов вышли в сеть.

Логи backend по тому же device ID: соединение в 00:30:10 UTC прошло auth и
первый heartbeat (`latency_ms` ~166), viewer в 00:30:35 запросил `start_stream`,
management WS закрылся в 00:30:49 с code 1005 (без штатного close-frame).
Public gateway для нескольких management WS PH013 записал успешный HTTP 101
и длительности **39,999 и 39,998 с**; origin nginx имеет
`proxy_read_timeout=3600s`, public gateway — `120s`. Это доказывает частые
обрывы уже установленного соединения, но не определяет, какая сторона первой
его оборвала. После авторизации короткий `REQUEST_LOGS` к PH013 10230 всё же
вернул HTTP 504 через 15 с. Тот же результат ранее получен на PH022/PH025.
Временные файлы проб и wire payload оставлены только в ignored `.local-pilot`.

Расширенная выборка gateway за 00:25–00:39 UTC подтверждает, что PH013 имел
12 завершённых WSS-сеансов (медиана 41,824 с, 6 около 40 с), PH017 — 13
(медиана 40,000 с, 8 около 40 с), PH019 — 13 (медиана 40,001 с, 6 около
40 с). У локальных PH010/PH011 за тот же интервал завершённых WSS-сессий не
было. Это сильная корреляция remote route и частых обрывов, **не** измерение
первопричины и **не** универсальный лимит Cloudflare. В конфигурации наших
nginx proxy 40-секундного read timeout нет.

Периодическая HTTP-выгрузка журналов создаёт отдельный диагностический пробел:
на 05:05 UTC в `/tmp/sphere_device_logs` пилотного backend не найдено файлов
PH013, PH017, PH019 с новой `ws_lifecycle` записью; у локального PH011 файл
существует и содержит категории закрытий. `REQUEST_LOGS` к PH013/PH025
завершился 504. Нельзя выводить точную клиентскую причину из одного серверного
`1005` и нельзя считать отсутствие файлов отсутствием сбоев Android.

### Адресная диагностика через heartbeat · 05:17–05:20 UTC

Регрессии сначала показали отсутствие прежней клиентской ошибки в `PONG` и в
серверном журнале. Fix `3dbb915` передаёт после reconnect только bounded поля:
тип/фазу lifecycle, номер маршрута, длительность, код закрытия/HTTP и имя
класса исключения; URL, token, close reason и exception message не передаются.
Backend валидирует значения и пишет одно структурированное событие на WS-сеанс
только после успешного Redis presence write. При временном отказе Redis запись
повторно рассматривается на следующем PONG. Следующий коммит `9d8874a`
устранил ошибку статического сужения `int | None` в CI без изменения runtime
контракта. Пилотный backend image `:9d8874a` собран из Git archive, SHA
`backend/websocket/heartbeat.py` проверен внутри образа; readiness 200,
frontend, APK-каталог и непилотные контейнеры не изменились. Перед каждым
пересозданием контейнера его прежние журналы сохранены приватно в `.local-pilot`.

Canary `1.2.31-dev / 10231` собрана из Android source `3dbb915` с неизменным
signed discovery v25 и тем же pilot debug signer, что у 10230. Файл
`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.31-dev-3dbb915.apk`,
SHA-256 `6439fc7234ba863123f6f47bbb95931bbdf986f3dfce26157dda9a640e41d5b6`.
Unit suites devDebug/enterpriseDebug: по 685 тестов, 0 failures/errors;
`lintDevDebug`, обе debug assemblies, 205 backend WS tests и Ruff прошли.
Локальный PH011 обновлён поверх 10230 с сохранением app data: Android
PackageManager показывает 10231, процесс и `SphereAgentService` работают,
backend видит `online / 1.2.31-dev`. После deploy backend принял его первый
реальный отчёт `android_ws.previous_failure`: `onFailure`, route slot 1/2,
`pre_auth`, `IOException` с `EOFException`, elapsed 1004 ms. Это доказывает
сериализацию и доставку канала **на одном локальном Android**; оно не объясняет
обрывы удалённых PH013/PH017/PH019. В локальном canary не запускали видео.
APK 10231 опубликована только в `android-canary/dev`, не в общем `android/dev`;
на remote она не установлена, считать её исправлением стрима нельзя. CI
`9d8874a` прошёл.
Один idle-снимок PH011 без захвата экрана после установки дал 47 678 KiB PSS
(`dumpsys meminfo`) и 0,0% CPU (`top`); выборка не характеризует среднее,
стриминг или 32–64 эмулятора и не закрывает performance gate.

### Реальная адресная OTA и закрытый пробел обычного WS · 05:35–10:45 UTC

Сначала локальный PH010 (1.2.28) получил ровно один подписанный grant на 10231.
Специализированный recovery-сеанс выдал команду; backend записал `received`,
`running`, terminal `completed`, сохранил receipt перед ACK, затем Android
PackageManager, API и новый процесс подтвердили 10231. Это **локальная** приёмка.

На удалённом PH017 (1.2.30) такой же адресный grant был активен, однако агент
подключался с действительным JWT и проходил обычный management WS: специальный
OTA-only путь его не выбирал. Предполагаемое несоответствие `issued_before`
не проверено декодированием токена и не считается доказанной причиной. До fix
обычный путь grant не отправлял. Два новых
регрессионных теста сначала падали: команда не отправлялась и terminal receipt
не сохранялся. Fix `40357ca` проверяет подпись, tenant/device и срок grant на
обычном соединении и отправляет **тот же** command ID до публикации сокета;
Android журнал защищает от повторного исполнения после reconnect. Сервер
распознаёт terminal receipt по сохранённому grant, атомарно сохраняет его до
ACK; неизвестные receipts по-прежнему не превращаются в DAG task result.
Boundary tests закрывают чужую организацию, изменённый digest, истёкший grant,
неактивное устройство и replay. Локально 71 recovery/OTA API test passed;
полный CI коммита `40357ca`, включая Tests, APK build, mypy, security,
Alembic и frontend, прошёл. Pilot backend пересобран из Git archive и
развёрнут как `:40357ca`, внутренний readiness 200; frontend и OTA-каталог
побайтно не изменились, legacy containers не затронуты.

PH017 переподключился в 05:46:35 и 05:48:03 UTC. На обоих соединениях backend
записал `android_ws.ota_grant_sent_normal`. Public gateway увидел GET точного
APK digest в 05:46:37 и 05:47:07, оба со статусом HTTP 200 и временем запроса
1,912/1,724 с. Текущий access format не содержит числа байтов, дошедших до
Android; `200` на gateway не является доказательством полного скачивания.
В 05:48:06 агент прислал terminal `failed`; сервер сохранил sanitized
`failure_code=timeout`, убрал активный grant и отправил ACK. На 10:44 API
по-прежнему показывает PH017 1.2.30, `offline`; до этого он продолжал
циклически устанавливать heartbeat и терять WSS примерно через 40 секунд.
Это доказывает доставку команды и квитанции, но **не** доставку APK или видео.

Адресный `REQUEST_LOGS` PH017 в 10:45 UTC вернул HTTP 504; его periodic файл
в `/tmp/sphere_device_logs` отсутствует. По одному bounded `timeout` нельзя
строго выбрать между HTTP-body read и установщиком. Два GET с интервалом ~30 с
согласуются с предусмотренным Android retry через HTTP/1.1 после IOException,
но этот вывод пока только гипотеза. Повторный grant без новой диагностики
бессмысленен и не выполнялся. Сырые идентификаторы, intent, receipt и журналы
хранятся только в ignored `.local-pilot/rollout/ota-ui-20260927/`.

**Вывод для приоритета:** обновление APK подтвердило версию, но не восстановило
передачу кадров и ответ интерактивной диагностики на удалённом маршруте.
Первый следующий шаг — получить клиентский `ws_lifecycle` (`onFailure` тип,
route slot, elapsed, close code) из периодического upload либо адресного
доступного журнала; затем A/B на втором живом ingress. Не менять туннель
массово по одному совпадению 40 секунд. Официальная документация Cloudflare
[подтверждает WebSocket](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/)
и [рекомендует heartbeat/проверку idle timeout](https://developers.cloudflare.com/network/websockets/),
а [Quick Tunnel описывает как тестовый без SLA](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/);
она не доказывает конкретный 40-секундный лимит этого инцидента.

### Сбой pilot ingress при проверке · 10:54–10:56 UTC

При reload только `public-gateway` после изменения access log оба внешних пути
временно возвращали `502`. Внутренний upstream `nginx:8081` был недоступен:
проверка socket в работающем pilot Nginx показала только 80/443, а его
`/tmp/nginx.generated.conf` не содержал listener 8081. Шаблон из репозитория
уже содержал его. Причина — старый сгенерированный runtime config; прежний
Docker health статус не проверял gateway→upstream. Старый `sphere-platform` и
`sphere-tunnel` не менялись.

Сгенерированный конфиг **только** pilot Nginx был синхронизирован с исходным
шаблоном и проверен `nginx -t`, затем graceful reload восстановил socket 8081.
Внутренний readyz и внешний Cloudflare route снова вернули 200; read-only guard
`scripts/check_pilot_gateway_runtime.py` теперь сверяет source и файл generated
config, затем проверяет действующий внутренний HTTP-маршрут до следующего gateway
reload. Регрессионный тест
воспроизводит stale listener. Инструкция восстановления —
[Remote pilot runbook](../../operations/REMOTE-PILOT.md).

Новый access format `public-gateway` содержит hostname, method/path без query,
статус, время, байты gateway→connector, размер upstream-ответа и completion.
Из него можно проверить, передал ли gateway всё тело на свой выход, но нельзя
объявлять успешное скачивание Android или работоспособный видеоканал. Контрольный
LocalTunnel в этот день ответил HTTP readyz, однако WSS upgrade не подтвердился;
временный контейнер остановлен, второго рабочего ingress нет. Эти факты не
закрывают remote OTA `failed/timeout` и чёрный stream.

### Контроль границы Android → ingress · 11:03–11:38 UTC

Повторная read-only сверка API показала 16 логических устройств: локальные PH010/011
сообщали 10231, удалённые PH013/017/019 — 10230, остальные удалённые в основном
10222 либо без актуального heartbeat. Поэтому наличие APK 10231 в canary-каталоге
**не** означает, что она установлена на удалённом парке. Состояния remote
online/connecting/offline менялись между снимками.

Однократный viewer probe PH017 получил два бинарных пакета / 61 байт
(только SPS/PPS), без IDR/P. За пробу независимая сводка счётчиков четырёх
backend worker показала 4 ingress пакета / 122 байта (две пары SPS/PPS),
при этом клиентская telemetry на аналогичной remote пробе PH013 уже фиксировала
18 захваченных, отрендеренных и закодированных кадров / 87816 байт, но
0 из 20 попыток принятия в локальную WS-очередь на момент разрыва.
Системный индикатор захвата на Android поэтому не является доказательством
доставки видеокадра до сервера. В частности, нельзя свести дефект к
декодеру браузера.

У PH017 во время viewer probe backend зафиксировал auth и heartbeat, а затем
`android_ws.disconnected` с `1005`; gateway записал HTTP 101 и ровно 40,000 с
WSS-сеанса. По нескольким remote устройствам длительность завершённых
management WSS снова концентрировалась около 40 с, иногда 60 с. Локальные
PH010/011 не появлялись в **публичных** gateway-записях этой проверки: путь
локальных эмуляторов нельзя считать доказательством работоспособности того же
интернет-маршрута. Код `1005` не раскрывает, кто первым закрыл сокет.

Контроль с этого ПК через **тот же** Cloudflare hostname держал публичный viewer
WSS 65 с с keepalive и успешно передал первый auth message из 65921
несжимаемого байта на сервер; видео PH017 при этом не пришло. Это опровергает
гипотезу об универсальном запрете WebSocket или жёстком 64 KiB лимите на
маршруте, но не проверяет исходящий трафик Android через другую сеть и не
исключает асимметричный сбой.

Адресный `REQUEST_LOGS` к PH013, отправленный сразу после свежего heartbeat,
для 20 и 30 строк вернул HTTP 200 и 1702/2610 байт. Запросы на 45/60 строк
завершились HTTP 504 через 15 с; при одном из них backend увидел auth и
heartbeat, затем разрыв `1005` около 40 с. В коротком клиентском фрагменте
есть OkHttp `EOFException` при чтении HTTP/1.1 response headers и счётчик
reconnect attempt 776+. Это свидетельство нарушенного HTTP/WSS пути на
удалённом клиенте, но разный состав строк и время запроса не позволяют
доказать порог размера ответа. Изменять лимиты наугад нельзя.
После возврата маршрута 22-строчный запрос, отправленный через 0,12 с после
heartbeat, также получил 504: даже небольшой ответ не гарантирован.

Для A/B только pilot контейнер `localhost.run` поднял временный HTTPS ingress:
readyz 200, WSS upgrade и ожидаемый auth reject с неверным токеном прошли.
**Одной** remote PH013 10230 отправили `UPDATE_CONFIG` с новым primary и старым
Cloudflare как fallback после свежего heartbeat. Terminal command receipt
`completed/updated=true` получен. Публичный gateway действительно увидел
её WSS через альтернативный hostname; backend подтвердил auth, но сеанс длился
лишь **0,705 с** и завершился `1005` до heartbeat. APK вернулся на Cloudflare,
где следующие management сеансы снова длились около 40 с. Следовательно,
второй HTTPS/WSS handshake доказан, **стабильная альтернативная связь и видео
не доказаны**; этот A/B не устанавливает вину Cloudflare.

Чтобы не оставить canary на временном endpoint, PH013 получила **одну**
обратную `UPDATE_CONFIG` на исходный primary с terminal receipt
`completed/updated=true`; последующие auth и heartbeat на исходном маршруте
видны серверу, как и очередной разрыв через 39,999 с. Временный pilot
`localhost.run` контейнер после отката остановлен. Остальные
Android, backend/APK и глобальный signed discovery не менялись. Raw route,
command IDs, snapshots и клиентские логи сохранены только в ignored
`.local-pilot/rollout/ota-ui-20260927/`. Текущий приёмочный статус remote
frame delivery и OTA остаётся **NO-GO**.

### Serveo и отдельный HTTP/2 connector · 14:38–14:43 UTC

Предложенный оператором Docker container ID принадлежит **старому** проекту
`sphere-platform`, является остановленным `sphere-tunnel` и не использовался.
Для нового pilot отдельно проверили Serveo SSH/443: сохранённый fingerprint
совпал с [официальным ED25519 fingerprint](https://serveo.net/docs/), однако
попытки анонимного соединения без ключа и с новым эфемерным ключом получили
`Permission denied (publickey,keyboard-interactive)`. Документация провайдера
допускает anonymous tunnel, но фактический доступ с этого стенда не получен;
Serveo A/B и рабочий резерв **не состоялись**. Секреты старой установки не
использовались.

Отдельный **pilot-only** Quick Tunnel на том же public gateway запущен с явно
заданным `--protocol http2`; его startup log подтвердил `Initial protocol
http2`. Независимые HTTPS readyz 200 и WSS upgrade с ожидаемым отказом на
невалидном токене прошли. PH013 10230 получила ровно одну адресную команду
смены маршрута с прежним Cloudflare hostname как fallback, ответила terminal
`completed/updated=true` после свежего heartbeat. На новом HTTP/2 маршруте
backend подтвердил auth и heartbeat, public gateway записал HTTP 101,
**40,001 с**, 6010 байт на выходе. Затем агент перешёл на старый маршрут;
следующий завершённый сеанс там длился **40,000 с**. Это контролируемое
опровержение гипотезы, что достаточно переключить *транспорт connector*
QUIC→HTTP/2. Оно не сравнивает двух независимых провайдеров и не указывает,
какая сторона рвёт сокет.

Однократная обратная команда на исходный адрес получила terminal
`completed/updated=true`; HTTP/2 тестовый connector остановлен. Глобальный
signed manifest, OTA-каталог, остальные APK и legacy Docker не менялись.
Сырые имена маршрутов, device/command ID и журналы остались приватно в
ignored `.local-pilot/rollout/ota-ui-20260927/`.

## Контрольные шаги для следующей итерации

1. Получить клиентский `ws_lifecycle` для короткого localhost.run и
   40-секундных QUIC/HTTP2 соединений PH013 (причину `onFailure`, route slot и
   время). Затем повторить A/B через *независимого* доступного провайдера с
   непрерывным health и замером Android `onFailure`/close, gateway duration,
   backend heartbeat, команды и IDR/P. Краткий WSS upgrade не является приёмкой.
2. Локальная OTA через сохранённый grant прошла; remote PH017 доказал нормальную
   доставку команды и durable `failed/timeout` receipt без установки APK.
   Следующий шаг — определить, завершилось ли чтение тела APK и какой именно
   таймаут случился на Android. Исторические 10222-квитанции требуют отдельной
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
