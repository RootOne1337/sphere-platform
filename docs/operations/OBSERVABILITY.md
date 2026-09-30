# Prometheus и Grafana внутри Sphere

**Дата:** 30 сентября 2026, Asia/Yekaterinburg. **Область:** первый рабочий этап
серверной истории и встроенной Grafana. Это не приёмка всего парка Android.

[Текущее состояние](CURRENT-STATE.md) · [Каталог документации](../README.md) ·
[Операционный аудит веба](../audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md)

> Принятый runtime 30 сентября, 21:37–21:44 UTC+5: backend `85c8014`, frontend
> `4024ccf`, маршрут `3015 → UI 3017 / API 18080`. Dependency update не меняет
> контракт метрик: PyJWT 2.15.1 / cryptography 50.0.2 проверены в exact image,
> старый access token и Grafana работают. Семь post-recovery срезов подтвердили
> 14 **новых** session dates и свежие heartbeat после initial flapping; ранний
> failure сохранён. Нельзя принимать только первый online count после restart
> или выдавать минутный recovery за SLA. Полные версии/CI/ресурсные gates — в
> [CURRENT-STATE](CURRENT-STATE.md); source введения probe UI ниже — `4024ccf`.

## Что подключается

`/monitoring` сохраняет существующие проверки API и добавляет серверную историю
Prometheus, цели сбора, активные алерты и Grafana в той же странице.
Данные не генерируются браузером. Сбор продолжается при закрытом вебе.

В первом этапе измеряются:

| Показатель | Источник | Что доказывает |
| --- | --- | --- |
| Доступность `/metrics` | `up{job="sphere-backend"}` | Prometheus получил метрики; не доказывает stream/DAG/OTA |
| Время сбора | `scrape_duration_seconds` | Продолжительность HTTP scrape; не latency команд Android |
| Измерений после фильтрации | `scrape_samples_post_metric_relabeling` | Объём последнего среза; не число устройств |
| Ряды хранилища | `prometheus_tsdb_head_series` | Размер текущего TSDB head; не размер БД Sphere |
| Потеря сбора | `SphereBackendMetricsUnavailable` | `up == 0` в течение минуты |

Исторический пробел до rollout 30 сентября 18:09 UTC+5: backend имел четыре
Gunicorn worker без multiprocess directory и отдавал registry выбранного worker.
Backend `85c8014` использует общий multiprocess registry; exact image и
live rollout записаны в [CURRENT-STATE](CURRENT-STATE.md).
**Панели общих RPS, p95, CPU и количества устройств пока не подключены.**
Сырые HTTP/pool метрики сохраняются для исследования; prepared dashboard и
веб-показатели не строят по ним общие KPI или алерты. Высококардинальные
device series не собираются этим профилем.

Исторический deployed monitoring API отдельно отдавал 12/8 точек истории без
`observedAt`, фиксированные worker/edge cards и нулевое число туннелей. Новый
frontend отвергает такой metrics payload и node list без `details` источника
probe. Новый contract введён в pilot `4024ccf` и сохранён в текущем `85c8014`; frontend `4024ccf` на `3015`
проверен с настоящими RAM/Redis/TX/RX и четырьмя probes. Неполное покрытие метрик
не отменяет независимый сбор Prometheus и не превращается в «всё здорово».

### Structured service probe details

Карточки читают документированные scalar поля `/monitoring/nodes`: pool_size,
checked_out, pong, used_memory_mb, free_gb, total_gb, usage_percent. Пул относится
к API worker, disk — к filesystem / внутри backend, Redis latency — к PING.
Число клиентов Redis находится в отдельной `/monitoring/metrics` card из INFO
clients; исторический health payload синтезировал 0 из INFO memory, и это поле
inspector не показывает. Producer исправлен и развёрнут в pilot `4024ccf`; acceptance — в
[CURRENT-STATE](CURRENT-STATE.md).

Возраст процесса API не является uptime зависимости. Обновление списка сохраняет
выбранный ID и показывает новые детали. Отрицательные/нечисловые/небезопасные
числа не отображаются как валидные measurements; настоящий 0 сохраняется.
Error присутствие видно, raw exception скрыт, поскольку может содержать DSN/
credentials. Перечень полей ограничен: этот inspector не является универсальным
экспортом log/error payload и не подменяет защищённые журналы backend.

## Доступ и границы интеграции

`GET /api/observability?window=1h|6h|24h` проверяет Bearer token через настоящий
`/api/v1/auth/me`. Только ответ с `role=super_admin` даёт доступ к метрикам
всей платформы. Роль из client store/JWT payload не является авторизацией.
Tenant administrator/viewer получает `403`; недоступная авторизация закрывает
доступ, а не разрешает его. Проверки обычного monitoring API сохраняют свой
существующий RBAC и не заменяются глобальными метриками.

Здесь нет публичного PromQL proxy: четыре фиксированных выражения, до восьми
рядов на выражение, до 1 441 точки на ряд, JSON response до 2 MB, upstream
timeout 5 s. Окна 1/6/24 h имеют шаг 15/30/60 s. Ошибка/неполный upstream
response скрывает прежние графики; `NaN` означает пропуск, а не ноль.

## Обновление данных в открытом вебе

События парка и история метрик имеют разные источники и частоты. Это не
обещание мгновенного обновления всех таблиц или доставки каждого PubSub event.

| Данные | Доставка / сверка |
| --- | --- |
| Presence, задания, команды, VPN, аккаунты/сессии | `/ws/events`; события группируются по затронутым query keys в течение 500 ms |
| Состояние после обрыва событий | Повторное чтение активных REST queries после подтверждённого snapshot/pong; не повторное исполнение команд |
| Реестр без события heartbeat | Резервный polling 30 s; карточка устройства 15 s |
| Задания / progress / live logs | Резервный polling 10 / 2 / 3 s соответственно |
| Prometheus | Scrape и foreground polling 15 s; история 1/6/24 h имеет resolution 15/30/60 s |
| Grafana | Dashboard refresh 30 s; подтверждение сессии через Sphere через 60 s после завершения предыдущего запроса |
| Возврат на вкладку | Перечитываются stale queries; источник Prometheus сверяется всегда, Grafana получает новую cookie до создания iframe |

Канал событий показывает `connecting`, `live`, `reconnecting`, browser
`offline` и `unauthorized` в шапке. `live` требует ответа API, не только TCP
open. Auth handshake ограничен 15 s; при отсутствии прикладных сообщений
проверяется ping каждые 20 s, без ответа за 10 s соединение закрывается и
восстанавливается с jitter/backoff до 30 s. Close `4001` не повторяет старый
токен: требуется новая сессия/access token. Token остаётся первым WS message,
не query string. Статус этого канала не является статусом всех Android,
видеокадров или исполнения сценариев.

Burst progress events не отменяют незавершённые REST reads. После потери
событий нет replay cursor: REST восстанавливает текущее состояние, а не
гарантирует историю каждого пропущенного события. Polling остаётся страховкой
для обновлений без события и изменений во время уже выполняющегося запроса.
Неактивные query pages помечаются stale; только mounted queries перечитываются.
В скрытой вкладке накапливаются лишь query keys, без HTTP fan-out по каждому
событию. При logout/unmount timers, socket и отложенные refresh очищаются.

Срез Prometheus старше 45 s или с некорректным/будущим временем скрывает
графики, даже если HTTP response успешен. Target `up` со сбором старше 45 s
отмечается как задержанный, `unknown` не превращается в healthy. Разрыв серии
не рисуется непрерывной линией. Скрытый Grafana iframe убирается и заново
авторизуется на возвращении; просроченная cookie не остаётся в видимом iframe.
Query cancellation и смена пользователя не допускают показа позднего ответа
от предыдущей сессии. Проверки этих сценариев не заменяют browser acceptance
конкретной runtime-сборки.

Поведение перечитывания и invalidation сверено с официальной документацией
TanStack Query: [возврат на вкладку](https://tanstack.com/query/v5/docs/framework/react/guides/window-focus-refetching)
и [QueryClient / invalidateQueries](https://tanstack.com/query/v5/docs/reference/QueryClient).
Wire protocol snapshot/ping/pong проверен по `backend/api/ws/events/router.py`
и живому авторизованному canary через preview proxy; это основание выбранного
восстановления без изменения Android или server transport.

Кнопка «Открыть Grafana здесь» получает через `POST /api/observability/session`
подписанную HttpOnly cookie с `SameSite=Strict`, path `/observability/grafana`,
TTL 90 s. Она не содержит access token. Пока iframe открыт, Sphere заново
проверяет профиль каждую минуту. При отказе iframe убирается. **Серверное
отзывание доступа для уже выданной cookie ограничено TTL 90 s**; мгновенный
отзыв такой cookie не реализован. Смена/выход из аккаунта скрывает iframe в UI.

Next route `/observability/grafana/[[...path]]` принимает GET/HEAD и два точных
POST endpoints чтения: `api/ds/query` для графиков и
`apis/features.grafana.app/v0alpha1/namespaces/default/ofrep/v1/evaluate/flags`
для загрузки feature flags Grafana 13. OFREP читает значения, не меняет флаги;
body ограничен 16 KiB и проверяется как evaluation context. Контекст браузера
не передаётся: сервер задаёт `{context: {targetingKey: "default"}}` для своей
фиксированной Viewer-сессии. Другие namespaces, single-flag paths и write
methods не разрешены этим исключением. Иной deployment namespace требует
отдельной адаптации и проверки allowlist. Сверено с
[Grafana 13.2.3 source](https://github.com/grafana/grafana/blob/v13.2.3/packages/grafana-runtime/src/internal/openFeature/index.ts)
и [OFREP bulk evaluation](https://openfeature.dev/docs/reference/other-technologies/ofrep/openapi/).
Запись dashboards/users/
datasources запрещена; path traversal, external redirect и datasource proxy
bypass отклоняются. Query body до 100 KB, интервал до 24 h, не более восьми
queries. Browser identity/cookies/Authorization не передаются в Grafana.
Auth proxy задаёт фиксированного пользователя `sphere-observer`; native Grafana
роль — `Viewer`, anonymous/basic/login form выключены. Не предназначено для
полноценного редактирования Grafana или установки plugins через Sphere.

## Изолированный Docker-стек

Используется `infrastructure/monitoring/docker-compose.observability.yml`.
Это отдельный Compose project, без Docker socket и host filesystem mounts.
Он не пересоздаёт backend, Android, БД или туннели. Старый
`docker-compose.monitoring.yml` не следует запускать вместо этого профиля:
его старые версии, пароли по умолчанию, host ports и внешние receivers
не прошли текущую приёмку.

| Компонент | Закреплённая версия на 30 сентября | Лицензия |
| --- | --- | --- |
| Prometheus | [v3.15.0](https://github.com/prometheus/prometheus/releases/tag/v3.15.0) | [Apache-2.0](https://github.com/prometheus/prometheus/blob/main/LICENSE) |
| Grafana OSS | [13.2.3](https://github.com/grafana/grafana/releases/tag/v13.2.3) | [AGPL-3.0-only / exceptions](https://github.com/grafana/grafana/blob/main/LICENSING.md) |

Оба Docker image закреплены также по manifest digest в Compose. Используются
официальные немодифицированные бинарные образы, сторонние dashboard templates
не копируются. Provisioned dashboard и интеграционный код написаны для Sphere;
авторство и лицензии Prometheus Authors / Grafana Labs сохраняются. Не требуются
платные Grafana Enterprise plugins или cloud service.

Prometheus: retention 14 d **или** 2 GB, что наступит раньше. Это предел TSDB,
не гарантия общего использования диска 2 GB: WAL/head и служебным данным нужен
запас. Query timeout 5 s, concurrency 4, max samples 500 000. Сбор 15 s.
Контейнеры имеют `512m` RAM и `0.5` CPU каждый, cap drop и no-new-privileges;
данные сохраняются в отдельных volumes. Grafana cache/temp ограничен tmpfs.
Docker stdout/stderr ограничены тремя файлами по 10 MB на контейнер.
DB exporter, Windows host CPU, tunnel health, Loki и distributed tracing в этом
этапе **не подключены**; их отсутствие не подменяется нулевыми графиками.

Оба host ports привязаны к `127.0.0.1`: Prometheus `19090`, Grafana `13000`.
На loopback Prometheus доверяет процессам оператора. Не публикуйте эти ports
наружу. Из серверной сети Prometheus может читать backend; Grafana находится
только в сети tools. Auth proxy принимает только конкретный доверенный адрес
Next/proxy, заданный в private env, без диапазона всех Docker networks.

## Настройка новой установки

Создайте private env вне Git и два независимых случайных секрета: Grafana admin
password file и `OBSERVABILITY_SESSION_SECRET` (не менее 32 случайных символов).
Нельзя использовать пароли/ключи из примеров. Compose требует:

```dotenv
OBS_BACKEND_NETWORK=<существующая Docker-сеть backend>
OBS_GRAFANA_ADMIN_PASSWORD_FILE=<абсолютный private file>
OBS_GRAFANA_PROXY_WHITELIST=<точный адрес доверенного Next/proxy>
```

В backend network должен существовать DNS alias `backend`, порт 8000. Настройте
target явно при иной топологии. На текущем pilot это сеть
`sphere-pilot-20260911_backend-net`. Адрес whitelist определяется по реальному
peer address; он может отличаться при переносе с Docker Desktop на VPS.
Не расширяйте whitelist до всего Интернета ради устранения `invalid-ip`.

```powershell
docker compose --env-file <private-env> -p sphere-observability -f infrastructure/monitoring/docker-compose.observability.yml config --quiet
docker compose --env-file <private-env> -p sphere-observability -f infrastructure/monitoring/docker-compose.observability.yml up -d
```

Server-only env Next показаны в `frontend/.env.example`. Для текущего локального
preview AUTH API — `http://127.0.0.1:18080/api/v1/`, Prometheus —
`http://127.0.0.1:19090/`, Grafana — `http://127.0.0.1:13000/`.
Для Docker frontend используйте доступные ему service origins и точный trusted
proxy address. Не переносите localhost values внутрь контейнера вслепую.
На публичном HTTPS **обязательно** `OBSERVABILITY_SECURE_COOKIE=true`.
Reverse proxy должен передавать `/api/observability/*` и
`/observability/grafana/*` в Next, а `/api/v1/*` — в backend. Публичный rollout
этой интеграции требует отдельной проверки этого routing и HTTPS cookies.

## Проверки и продолжение

Перед приёмкой проверьте Compose health, `promtool check config`, обе target
health, источник dashboard `sphere-prometheus`, provisioned UID
`sphere-collection`, native роль Viewer, запрет save, авторизацию Sphere и
историю в iframe. Live receipts фиксируются в CURRENT-STATE с build SHA.

Multi-worker профиль прошёл image acceptance и развёрнут в pilot 30 сентября
18:09 UTC+5 (`1ac06ac`); см. [runtime receipt](CURRENT-STATE.md).
HTTP-rate/latency панели и алерты требуют отдельной проверки запросов и порогов,
длительный resource budget ещё не принят. Следующий этап — структурированные
логи с bounded retention и корреляцией device/task/run/session, DB/cache
exporters с минимальными правами, tunnel probes и Android stage/SLO metrics.

Network card в новом source показывает суммарные TX + RX bytes backend
namespace, отдельные counters/rates и отдельно coverage числа туннелей. `null`
для `activeTunnels` не скрывает измеренный трафик и не превращается в `0`.
Предупреждение Prometheus описывает неполное покрытие панелей, а не утверждает
worker-local instrumentation у любого подключённого backend. Дату rollout
frontend сверяйте в [CURRENT-STATE](CURRENT-STATE.md).

### Multiprocess contract — исходники 30 сентября 2026

Production Docker entrypoint перед импортом Python создаёт новый private
Linux-каталог `/tmp/sphere-metrics/master.<random>` для каждого Gunicorn master.
Заданный извне `PROMETHEUS_MULTIPROC_DIR` не переиспользуется и не удаляется.
Bootstrap/migration команды проходят без выделения registry. `full.yml` также
вызывает этот entrypoint в режиме Gunicorn; development/reload остаётся
однопроцессным. В `/metrics` `starlette-exporter 0.17.0` создаёт отдельный
CollectorRegistry с MultiProcessCollector на каждый scrape. Второй HTTP
middleware удалён: canonical request families — `sphere_http_*`, прежние
`starlette_*` HTTP families больше не создаются.

| Показатель | Контракт production |
| --- | --- |
| `sphere_http_requests_total`, histogram | Сумма всех workers; route template с параметрами `{id}` сохраняет прежние UUID labels. HTTP method allowlist и `__unmatched__` исключают произвольные URL/method. Необработанное исключение учитывается как 500 и передаётся handler. |
| `sphere_http_request_duration_seconds` | Latency до response headers; **не** время передачи streamed body, Android round-trip или end-to-end video latency. |
| `sphere_db_pool_size`, `sphere_db_pool_checked_out` | `livesum`: общий размер SQLAlchemy pools / текущее число выданных connections. Это не PostgreSQL max connections и не длительность SQL. |
| `sphere_metrics_worker_processes` | `livesum`: число живых процессов, импортировавших instrumentation; **не** readiness или доступность устройств. |
| `sphere_fleet_stream_*_total` | Аддитивные счётчики видео всех workers без `device_id`. NAL/stage/reason остаются ограниченными категориями существующей instrumentation. Смена имени явно отделяет их от старых device counters. |
| `sphere_fleet_stream_active_viewers` | `livesum`, без device labels. Умерший worker исключается через Gunicorn `child_exit`. |
| Device FPS/session gauges | В multiprocess Prometheus не экспортируются и не создают mmap keys. Подробные Android snapshots и stream diagnostics продолжают работать через device API / Redis. В single-process development старые device metric names сохранены. |
| Legacy device/task/VPN gauges | `livemax` исключает умножение одинакового global snapshot на число workers, но collector этих семейств ещё не реализован. Их нули **не** являются измерением fleet/queue/VPN; панели и алерты по ним не включать. |
| Native `process_*`, CPU/RAM | Custom collectors не входят в multiprocess exposition. Нужен отдельный exporter; нельзя выдавать один process за весь backend/host. |

Gunicorn hook удаляет только `live*` gauge files уже завершившегося процесса.
Counter/histogram files сохраняются до смены master, поэтому recycling worker
не сбрасывает request totals. Новый master начинает отдельный registry с нуля;
Prometheus `rate` обрабатывает этот reset. `--preload` не используется.
Удаление high-cardinality labels самим client в этом режиме не поддерживается,
поэтому device gauges отделены **до** создания Prometheus objects, а не только
фильтруются во время scrape.

Lifecycle hardening 30 сентября: registry создаётся в
`/tmp/sphere-metrics/master.<random>` с private `.owner` marker. После остановки
children Gunicorn `on_exit` удаляет только каталог своего master: проверяются
absolute path в заданном root, имя, отсутствие symlink, owner PID/uid, private
permissions и marker. Чужой каталог или живые children запрещают очистку.
Neighbouring registry работающего master и operator data не удаляются.
SIGKILL не запускает hook: production/full Compose использует отдельный
**128 MiB tmpfs**, который очищается при остановке контейнера. Прямой
`docker run` должен передать такой же mount; сам image не создаёт tmpfs.
Память tmpfs входит в memory cgroup limit контейнера.

Ресурсное ограничение сохраняется **внутри срока жизни master**: counter/
histogram files умерших workers накапливаются. На synthetic fixture source
`e3b4fe7` два прогона по **64** replacements дали прирост **128 KiB/replacement**,
registry **9 568 256 bytes / 146 files** и max scrape **21.62 ms** (1 CPU,
384 MiB, два registry после container restart). Устройство/путь не создают
дополнительных labels в этой fixture. Большой реальный route/label набор
может занимать больше; это не универсальная верхняя граница размера.

Не удалять mmap files работающего master и не пытаться compact counters
неподдерживаемым private API. Размер/число файлов, scrape latency и запас
tmpfs требуют operational alert/maintenance policy до длительного high-load
rollout. Hard cap может вызвать ENOSPC при исчерпании и **не** является
механизмом автоматического восстановления. Контролируемая смена master
сбрасывает counters; Prometheus `rate` учитывает reset. Короткая fixture и
тест с тысячами device IDs не доказывают многосуточный ресурсный бюджет.

Acceptance запускается на собранном образе, без сети и source mount backend:

```powershell
python tests/containers/run_multiprocess_metrics_probe.py --image <reviewed-image> --evidence-dir <private-evidence> --recycles 64
```

Probe закрепляет отдельное keepalive соединение за каждым из четырёх HTTP
workers: по 32 requests каждому, затем ещё 32 после replacement. Проверяет реальный exit
и replacement child, сохранение counters, очистку live gauges, отсутствие
duplicate samples, storage/scrape budget после worker recycling и новый registry
после рестарта master. Secondary master проверяет graceful cleanup без остановки
контейнера и сохранение active neighbour/operator data; SIGKILL проверяется
отдельно. В CI default — 16 replacements на master, local resource acceptance
использует 64. Он добавлен в
Production image bootstrap CI. Результаты source tests, image canary и live
rollout имеют разные статусы. Pilot `1ac06ac` принят отдельно: build stamp,
четыре live workers, один registry и отсутствие duplicate samples проверены
на развёрнутом контейнере; [даты и ограничения](CURRENT-STATE.md).
Основание: [официальный multiprocess contract Prometheus Python client](https://prometheus.github.io/client_python/multiprocess/).
Lifecycle hook: [Gunicorn Arbiter shutdown implementation](https://github.com/benoitc/gunicorn/blob/master/gunicorn/arbiter.py).
Ephemeral mount и memory budget: [Docker tmpfs documentation](https://docs.docker.com/engine/storage/tmpfs/).

### Обновление provisioned dashboard в Docker

Provider [`sphere.yml`](../../infrastructure/monitoring/collection/provisioning/dashboards/sphere.yml)
задаёт `updateIntervalSeconds: 30`. По [документации Grafana](https://grafana.com/docs/grafana/latest/administration/provisioning/),
интервал больше 10 s включает polling; filesystem watch при меньшем интервале
может не получать изменения Docker bind mount. В pilot новый файл читался
внутри контейнера, но отдавалась старая панель. После изменения provider сделан
один guarded restart собственной Grafana: healthy, те же image/auth и соседние
контейнеры. Новый текст подтверждён iframe в 20:23 UTC+5.
Это приёмка загрузки при restart и конфигурации polling; последующая мутация
файла без restart не тестировалась отдельным опытом.

Изменения provider требуют reload/restart с проверкой ownership. Native admin
reload API требует Basic auth; в данном профиле он отключён. Не включайте его
или write-access bridge ради reload: используйте контролируемый restart своей
Grafana, затем проверьте health и панель в Sphere. Datasources, queries, доступ
и image digest этим исправлением не менялись.

### Локальный UI/API relay и обрывы WebSocket

[`scripts/pilot/preview_relay.cjs`](../../scripts/pilot/preview_relay.cjs) нужен
только для локального browser preview. Это не PC Agent и не дополнительное
требование для подключения Android. Он слушает `127.0.0.1`, передаёт
`/api/v1/*` в pilot backend, `/ws/*` — в тот же backend, остальные HTTP paths —
в уже запущенный Next (включая `/api/observability/*` и Grafana bridge).
Backend auth/RBAC сохраняются; для существующего same-origin local routing
Origin/Referer API-запросов заменяются loopback upstream origin.

После проверки, что listen port свободен и существующий Next принадлежит
проверенному preview, пример запуска из root репозитория:

```powershell
node scripts/pilot/preview_relay.cjs --listen-port 3015 --ui-port 3017 --api-port 18080
```

На 30 сентября 20:49 UTC+5 `3015` передаёт UI в проверенный Next `4024ccf`
на `3017`, API — в `18080`; прежние Next `3014` и `3016` сохранены. Для входа нужен
`http://127.0.0.1:3015/login` и существующие operator credentials. Direct Next
`3017` не проксирует `/api/v1`: это ошибка выбора ingress, не повод сбрасывать
пароль. Не публикуйте credentials в документации/PR. Пример выше предполагает
уже запущенный Next на `3017`.

Не останавливать неизвестный процесс и не запускать второй relay на занятом
порту. Обновление UI требует самостоятельной проверки source SHA/ownership;
restart relay не компилирует frontend и не обновляет backend/APK.
Upgraded socket errors/clientError закрывают только соответствующее соединение;
ошибка HTTP upstream возвращает 502, если response ещё не начат. Команды не
повторяются. Разрыв после отправки означает неизвестный исход операции:
сначала сверить receipt, затем принимать решение о следующем действии.
SIGINT/SIGTERM закрывают server/proxy и принадлежащие relay sockets.

В реальном старом relay зафиксирован unhandled Socket `ECONNRESET`, после чего
Next остался alive, а общий preview port перестал отвечать. Новый relay
развёрнут 30 сентября 18:19 UTC+5 и проверен браузером. Test запускает отдельные
loopback fixture upstreams и ephemeral relay, проверяет RST с обоих концов,
сохранение HTTP/страницы UI при потере API и отсутствие POST replay:

```powershell
node --test tests/containers/test_preview_relay.cjs
```

Windows test passed; Linux test включён в frontend CI. Exact rare crash не
воспроизведён baseline test, поэтому результат не объявляется доказательством
устранения всех транспортных отказов. Private stderr/rollout receipts не
публикуются. Публичный reverse proxy/Tuna этим локальным relay не заменяются.

Официальные основания конфигурации:
[Docker Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/),
[auth proxy](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/auth-proxy/),
[embedding](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/),
[Prometheus security](https://prometheus.io/docs/operating/security/),
[TSDB retention](https://prometheus.io/docs/prometheus/latest/storage/).
