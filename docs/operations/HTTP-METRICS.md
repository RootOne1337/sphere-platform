# HTTP-метрики backend: контракт и ограничения

**Дата:** 5 октября 2026, Asia/Yekaterinburg. **Backlog:** EP-008.
Этот документ описывает реализацию. Установка и живые результаты фиксируются
отдельно в [журнале приёмки](../audits/2026-10-05/ENTERPRISE-HTTP-METRICS.md).

[Текущее состояние](CURRENT-STATE.md) · [Наблюдаемость](OBSERVABILITY.md) ·
[Исходный аудит](../audits/2026-10-05/ENTERPRISE-PRODUCT-AUDIT.md)

## Источник, окно и смысл

`/monitoring` запрашивает `/api/observability/http` с текущим Sphere Bearer token.
Сервер заново проверяет `/auth/me`; глобальные данные доступны `super_admin`.
Запрос без token не обращается к Prometheus. URL и credentials источников
задаются сервером, браузер не передаёт PromQL, upstream URL или label selectors.
Grafana имеет прежнюю отдельную проверку роли и отзываемой сессии.

| Панель | Измерение | Единица | Область |
| --- | --- | --- | --- |
| HTTP RPS | sum(rate(request counter[5m])) | запрос/с | job sphere-backend, все API workers |
| HTTP p95 | histogram_quantile(0.95, sum by(le)(rate(bucket[5m]))) | секунды | До response headers, без времени передачи тела |
| Ошибки 5xx | rate серверных ответов 500–599 | запрос/с | Тот же job и окно |
| Ответы 4xx | rate ответов 400–499 | запрос/с | В том числе штатные отказы авторизации; не автоматически авария |
| Маршруты | topk(30, rate по method + endpoint) | запрос/с и секунды | Нормализованные route templates, до 30 строк |
| Коды ответов | rate по status_code | запрос/с | Весь backend, независимо от выбранной строки |

Сначала вычисляется `rate` каждого counter, затем агрегируются series. p95 —
оценка по histogram buckets, не точный percentile отдельных сохранённых запросов.
Принцип и ограничения описаны в официальной документации
[Prometheus functions](https://prometheus.io/docs/prometheus/latest/querying/functions/)
и [histograms](https://prometheus.io/docs/practices/histograms/).
Нулевой traffic даёт нулевой RPS, но не определяет p95. `NaN` quantile показывается
как отсутствие измерения. Health endpoints, `/metrics` и favicon исключены
producer middleware; build health endpoint входит в обычный HTTP traffic.

Это не throughput видеокадров, не WebSocket latency, не длительность Android
команды и не доказательство исправности сценария. Метрики самой страницы,
проверок `/auth/me` и операторских запросов входят в HTTP traffic. При малой
нагрузке их вклад заметен. Endpoint-доступность по отсутствующему traffic не выводится.

## Ограниченный контракт

Допускается только один `window=1h|6h|24h`, по умолчанию 1h. Иные и повторные
параметры дают 400. Окно rate всегда 5 минут; выбранный интервал меняет длину
истории, а не определение метрики. Шаг истории — 15/30/60 секунд соответственно.
Один запрос выполняет четыре history queries, четыре endpoint instant queries,
один status instant query и чтение targets. Все expressions фиксированы в
[HTTP_QUERIES](../../frontend/lib/server/httpObservability.ts).
Route drilldown и поиск выполняются по полученным строкам, без произвольных
запросов от клиента. Все instant queries имеют одинаковый evaluation time.

History: до одного агрегатного ряда и 1441 точки, timestamps строго возрастают
и входят в запрошенное окно. Endpoint vector: до 30 уникальных method/template.
Status vector: до 100 уникальных допустимых HTTP codes. Каждый upstream JSON
ограничен 2 MB, fetch — 5 секунд, auth fetch — 3 секунды. Credentials,
raw exceptions и upstream warnings не публикуются. Responses `no-store`.
Rate вычисляется по существующим labels; при отсутствии error labels явный ноль
разрешён только через `0 *` успешно измеренного базового request rate.

Достигнутые 30 строк означают возможное усечение. Это не полный каталог API.
Остальные endpoints входят в общие показатели. Размер реального ответа,
нагрузка многих одновременно открытых admin dashboards и серверный query budget
нуждаются в отдельном нагрузочном тесте; лимит ответа не является гарантией
стоимости запроса на произвольно большой TSDB.

## Качество и свежесть

| Состояние | Условие | Поведение |
| --- | --- | --- |
| ready | Валидный свежий результат | Значение, включая настоящий 0 |
| empty | Пустой ряд / последний idle quantile NaN | Нет измерения, не подставляется 0 |
| partial | Prometheus warnings/infos или неполный join маршрутов | Явная отметка; неподтверждённое поле не заполняется нулём |
| error | Ошибка источника, неправильная shape/label/number, превышение bounds | Затронутая панель скрывает значения; независимые могут работать |
| stale | Нет свежего успешного scrape либо последний history point устарел | Текущие данные скрыты |

Targets `sphere-backend` должны иметь health up и lastScrape не старше 45 секунд
и не дальше 5 секунд в будущем. Ошибка/partial targets не маскируется под
здоровый collection. UI дополнительно проверяет возраст snapshot и lastScrape
по клиентским часам. Заметный clock skew потребует синхронизации времени.
Исторические пропуски разрывают линии SVG. На error refetch старый cached срез
не отображается как текущий. Опрошенная строка, исчезнувшая из нового top list,
теряет прежнюю детализацию вместо сохранения старых значений.

UI обновляется каждые 15 секунд, не опрашивает фоновые вкладки, отменяет запрос
при завершении query lifecycle и перепроверяет данные при возврате фокуса.
Ключ cache включает user id, session generation и history window.

## Проверки и эксплуатация

Серверные regression tests проверяют доступ, allowlist, интервалы, bounds,
partial results, idle quantiles, нулевые counters, source freshness и label joins.
UI tests проверяют drilldown, фильтр, разные состояния, исчезновение выбранной
строки, отказ/восстановление и скрытие устаревших данных.

1. Проверить `/api/v1/health/build` и UI stamp установленной сборки.
2. Открыть `/monitoring` на 3015 с super-admin сессией, проверить настоящий
   HTTP блок, route drilldown, time/window/scope, а затем collection/Grafana.
3. При empty проверить scrape и наличие двух counter samples для rate.
   При idle p95 не заменять его нулём и не генерировать рабочую нагрузку автоматически.
4. При error проверить private source logs; не экспортировать credentials.
5. Обновление UI не требует APK или backend restart: используются существующие
   агрегированные metrics producer и collection config.

CPU/RAM history, active tunnel inventory, полная карта endpoint inventory,
HTTP alert thresholds и Android latency/FPS остаются отдельными задачами.
