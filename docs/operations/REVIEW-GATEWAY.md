# Review gateway: стабильный приватный маршрут UI

**Дата:** 5 октября 2026, Asia/Yekaterinburg.
[HTTP metrics acceptance](../audits/2026-10-05/ENTERPRISE-HTTP-METRICS.md) ·
[Текущее состояние](CURRENT-STATE.md)

**Принятая установка5 октября13:56 UTC:** config `993d9eac`, UI image/source
`7c985feb`; preflight/tests `00ed391f`. Сохранены остальные44 контейнера.
Контрольная замена UI:23 probes200/502, конечный200; gateway не перезапускался,
ошибочные upstream после исправления указывают только172.30.0.3.
HTTP/Grafana повторно приняты14:00–14:03 UTC; zero downtime не заявляется.

Во время пересоздания review UI на3015 Nginx получил для временно отсутствующего
`review-ui` адрес192.168.0.1. Логи13:48:55–13:49:02 UTC фиксируют timeout while
connecting к192.168.0.1:3000 для `/login` и `/api/observability/http`; последовал
guard rollback. Точный внешний DNS producer не установлен. Доказано ошибочное
назначение upstream во время replacement, а не падение backend или Android.

Review network теперь имеет свой явно заданный IPAM и reserved static UI address.
В Nginx подставляется только этот адрес, без DNS lookup для UI. Контейнер gateway
остаётся non-root/read-only, с cap_drop ALL, loopback host binding, конечным
log rotation и временным `/tmp/nginx.conf` в ограниченном tmpfs. `envsubst`
получает whitelist одной переменной и сохраняет `$request_uri`, `$http_host`,
`$review_api` и другие nginx variables. Образ gateway остаётся прежним.

| Настройка | Default | Инвариант |
| --- | --- | --- |
| SPHERE_REVIEW_NETWORK | sphere-review-stable_ui | Отдельная owned review network |
| SPHERE_REVIEW_SUBNET | 172.30.0.0/24 | Не пересекается с существующими Docker networks |
| SPHERE_REVIEW_DYNAMIC_RANGE | 172.30.0.128/25 | Внутри subnet, не содержит static UI |
| SPHERE_REVIEW_NETWORK_GATEWAY | 172.30.0.1 | Валидный адрес subnet |
| SPHERE_REVIEW_UI_IP | 172.30.0.3 | Совпадает у UI и gateway environment |

Review network `internal: true`; gateway сохраняет отдельную существующую
API network. Observability overlay дополнительно сохраняет UI tools address
172.29.0.3 и exact Grafana whitelist. Адрес UI в review network и адрес прокси
в tools network — разные интерфейсы, их не следует смешивать.

Настройка IPAM/статических service addresses описана официально:
[Docker networks/IPAM](https://docs.docker.com/reference/compose-file/networks/#ipam),
[service addresses](https://docs.docker.com/reference/compose-file/services/#ipv4_address-ipv6_address).
На другом host проверять диапазоны до создания; для параллельного review project
задавать согласованно другое network name/subnet/pool/gateway/UI IP.

## Установка и проверка

1. Сохранить прежние immutable compose command, images, start times и volume/log config.
2. Проверить rendered compose: static address совпадает с gateway env,
   исключён из dynamic pool; сети UI/gateway и API boundary соответствуют контракту.
   Read-only validator: `python scripts/pilot/review_gateway_preflight.py <private-compose-config.json>`.
   Вход — результат `docker compose config --format json` в локальном private
   файле; не публиковать его, поскольку environment может содержать credentials.
   Validator проверяет bounds/boundaries и не создаёт resources, не проверяет live health.
3. Выполнить `nginx -t` на конфигурации, отрендеренной тем же gateway image.
   Не подставлять все env variables без whitelist.
4. Обновить только owned review UI/gateway, сохранив остальную инфраструктуру.
   Весь reverse proxy путь проверить после container health конечной серией GET;
   internal healthcheck UI сам по себе не доказывает доступ через gateway.
5. Проверить login, authorized real HTTP history, Grafana Viewer/query/revocation,
   API build и fleet count. На отказ — rollback обеих review services.
6. Отдельно проверить replacement canary: временный UI outage допустим, но
   gateway upstream должен оставаться reserved IP и восстановиться без DNS cache
   адреса другого хоста. Это не blue/green и не zero-downtime rollout.

Маршрут gateway→backend продолжает использовать существующее Docker DNS имя.
Из этого исправления не следует доказательство его поведения при остановке
backend или исправление всех DNS/network recovery случаев платформы.
