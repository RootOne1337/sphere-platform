# Prometheus и Grafana внутри Sphere

**Дата:** 30 сентября 2026, Asia/Yekaterinburg. **Область:** первый рабочий этап
серверной истории и встроенной Grafana. Это не приёмка всего парка Android.

[Текущее состояние](CURRENT-STATE.md) · [Каталог документации](../README.md) ·
[Операционный аудит веба](../audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md)

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

Отдельно подтверждён пробел: текущий backend имеет четыре Gunicorn worker,
`PROMETHEUS_MULTIPROC_DIR` не задан. `/metrics` возвращает локальный registry
выбранного worker. Смена процесса выглядит как сброс/скачок счётчика.
**RPS, p95, CPU и количество устройств по этим счётчикам не заявляются.**
Сырые HTTP/pool метрики сохраняются для исследования; prepared dashboard и
веб-показатели не строят по ним общие KPI или алерты. Высококардинальные
device series не собираются этим профилем.

Старый deployed monitoring API отдельно отдаёт 12/8 точек истории без
`observedAt`, фиксированные worker/edge cards и нулевое число туннелей. Новый
frontend отвергает такой metrics payload и node list без `details` источника
probe. Для прежних API-карточек нужен согласованный backend rollout; их отказ
не отменяет независимый сбор Prometheus и не превращается в «всё здорово».

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

Следующий P1 — правильная multi-worker агрегация: общий endpoint registry,
раздельная семантика gauge (worker/local/global), очистка умерших workers,
проверка рестартов и отсутствие double counting. Приёмка минимум на четырёх
worker с известным количеством HTTP requests и сравнению с API receipts.
До этого HTTP-rate/latency алерты не включаются. Затем — структурированные
логи с bounded retention и корреляцией device/task/run/session, DB/cache
exporters с минимальными правами, tunnel probes и Android stage/SLO metrics.

Официальные основания конфигурации:
[Docker Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/installation/docker/),
[auth proxy](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/auth-proxy/),
[embedding](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/),
[Prometheus security](https://prometheus.io/docs/operating/security/),
[TSDB retention](https://prometheus.io/docs/prometheus/latest/storage/).
