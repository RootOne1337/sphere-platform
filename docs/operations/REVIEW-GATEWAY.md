# Review gateway: локальный UI и адресный публичный маршрут

**Проверенная установка:** UI `c17332eb` / API `c17332eb`.

**10 октября — последняя UI коррекция:** автоматическая готовность после reconnect
и навигации;1996frontend tests. Конечный PH011 scope не закрывает latency/direct/fleet.
[Актуальная установка и ограничения](../audits/2026-10-10/CONTINUOUS-AUTO-RECOVERY-INSTALLED.md).

**Дополнение9октября16:21UTC:** публичный Nginx сжимает только static-assets
`/observability/grafana/public/` с negotiation/Vary и `gzip_proxied any`.
Через туннель без этого воспроизвелись JS parse errors и отказ dashboard;
3015 работал. Два открытия после graceful reload показали реальные графики.
Проверять исполнение dashboard, не только HTTP200 его HTML/JS. Anonymous static
по-прежнему401; API/WS/bootstrap не менялись,46контейнеров сохранены.
[QA, byte-integrity test и ограничения](../audits/2026-10-09/PUBLIC-WEB-SUPPLEMENTAL-QA.md).

## Действующий публичный UI — 10 октября 2026

Точный Tuna-host по прежнему приватному map использует review UI639b6ad5, как3015;
API369 установлен отдельно. Public UI/Next observability идут через review gateway,
business API/WS/health/bootstrap сохраняют прежние маршруты. Каждая адресная
установка сохранила45соседних контейнеров. [Последняя установка и границы](../audits/2026-10-10/CONTINUOUS-AUTO-RECOVERY-INSTALLED.md).
Direct probe выключен; stream/input остаются server WS, public idle reliability
не принята. [Сравнение с3015](../audits/2026-10-10/IDLE-LOCAL-PUBLIC-COMPARISON.md).
Последний [конечный ICE canary и cleanup](../audits/2026-10-10/DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md):
177requests/0responses,0RTT; исходный APK восстановлен, probeoff. Стандартный
UI639b6ad5 не включает экспериментальную панель; временные3016/3017 остановлены.
Review stack остаётся зависимостью public UI. Проверять оба адреса после rollout;
не пересоздавать API или volumes ради отката UI. Историческая Grafana коррекция
и маршруты выше сохранены; это не новый global tunnel rollout.

[Действующий реестр](WORK-STATUS.md) · [Текущая установка](CURRENT-STATE.md).
Ниже сохранены датированные результаты; они не описывают сегодняшнюю версию контейнера.

**Историческая установка 6 октября, 01:37 UTC+5 — ограничен приём загружаемых APK-журналов:**
Установленный API `76596c39`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Body больше 512 KiB отвергается до полного buffering; total ASGI intake deadline 60 s.
Четыре uploads на worker включают приём и filesystem writer; весь FS lifecycle
в отдельном executor. 8 MiB fixture: declared oversize 0 receive, unknown length
9 вместо 128 chunks; Python traced peak около 8 MiB → 0,506 MiB для unknown case.
Это не общий RSS limit или установленная причина расхода Windows C:.
В packaged image прошли 537 device/status/WS/VPN cases, включая 35 новых upload,
и 35 resource cases: **572 passed**; mypy/scoped Ruff/OpenAPI check прошли.
Сохранены 14 original-byte prefixes / 3614902 bytes и 45 соседних контейнеров.
В 01:42 UTC+5 после переключения подтверждены новые uploads в пяти файлах;
живые declared/chunked oversize POST вернули 413, PH025 GET — 1000 строк.
В браузере проверены непустой журнал, поиск, refresh и границы данных.
Online 14 / offline 5 из 19 — конечный срез, не SLA; UI/APK/OTA/туннели сохранены.
Source CI пока не принят целиком; последующий docs head проверяется отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: общие квоты, независимая очистка,
rotation/delete concurrency, backup/restore и leak/load gates остаются.
[Контракт и результат](../audits/2026-10-06/DEVICE-LOG-UPLOAD-BUDGET.md) · [Pinned evidence](../audits/2026-10-06/DEVICE-LOG-UPLOAD-EVIDENCE.json) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 00:55 UTC+5 — ограниченное чтение и постоянное хранение логов:**
API `9889c9ac`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Предел чтения — 2 MiB, JSON-массива строк — 512 KiB; четыре операции на worker
без растущей очереди. Файловый I/O вынесен из event loop. На одинаковом архиве
24 MiB совпали последние 1000 строк; Python traced peak снизился с 46,04 до 0,447 MiB.
Это не замер RSS и не установленная причина расхода Windows-диска.
14 файлов / 902996 bytes перенесены в постоянный том; исходные байты проверены
после rollback и пересоздания контейнера. Сохранены 45 соседних контейнеров.
Проверки образов: 502 + 35 тестов reader, затем 26 тестов final storage image;
23 Compose-проверки, 1307 frontend-тестов / 121 suite, build/types и scoped lint прошли.
В живом браузере проверены ширины 1440/390 px, обе темы, поиск и обновление;
настоящий GET для PH025 вернул 483 строки. Срезы online 14→9 и 14→11 сохранены;
устранение reconnects и непрерывная стабильность ещё не подтверждены.
Полный CI не прошёл: GitHub не выделил runner для backend Tests и Security.
Android CI storage-source прошёл; CI последующего docs-коммита учитывается отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: квоты, независимая очистка, upload budget,
backup/restore и проверки утечек/нагрузки ещё впереди.
[Результат и ограничения](../audits/2026-10-06/DEVICE-LOG-READ-BUDGET.md) · [Доказательства](../audits/2026-10-06/DEVICE-LOG-READ-EVIDENCE.json) · [Приоритеты](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Исторический срез 6 октября, 00:00 UTC+5 — tenant-сводка EP-010 Stage B:**
API `7fef9c53`, веб `9ad0a69e` на [3015/monitoring](http://127.0.0.1:3015/monitoring).
Шесть отдельных источников: активный парк, связь, VPN-отчёт Android, назначения,
сохранённые handshakes и неподключённые проверки публичного транспорта.
Живое окно 19:00 UTC: 19 устройств, 14 online + 5 unknown; 14 VPN inactive + 5 unknown.
Первая установка выявила text/binary Redis mismatch; отдельный фикс и регрессия
подтвердили исправление. 476 + 35 exact-image tests, 1298 frontend tests, Node24
build/types, scoped Ruff и OpenAPI прошли. Сохранены 45 соседей; APK/OTA не менялись.
CI исходников API `7fef9c53`: backend 2754 passed / 30 skipped; frontend, Android
и остальные gates прошли. CI последующего docs-коммита проверяется отдельно.
**9 принято / 41 открыто**, EP-010 OPEN: независимый producer, транспортные probes
и нагрузочный прогон ещё не приняты. [Доказательства и ограничения](../audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE.md) ·
[Pinned receipts](../audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE-EVIDENCE.json).

**Историческая установка foundation — 5 октября, 21:11 UTC+5:** API `d656b579`,
UI `cb5b3f91` сохранён. VPN-отчёт Android имеет независимое серверное время и
владельца сеанса; атомарная запись защищена от запоздавшего старого подключения.
После 120 с отчёт не считается свежим. Живое окно16:20 UTC:14 свежих false и5
unknown при14 online/5 offline из19. Это не проверка VPN-трафика или SLA.
Exact image444+35 tests; source CI backend2722 passed/30 skipped, frontend и
Android прошли. Сохранены 45 соседей. **9 принято/41 открыто**, EP-010 ещё OPEN.
[Результат, ограничения и следующие критерии](../audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md) · [Pinned evidence](../audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json).

**Историческая установка Stage A — 5 октября, 20:31 UTC+5:** backend `66714f26`,
UI `cb5b3f91` сохранён. Список peers и pool counts теперь одинаково исключают
устаревший/future handshake, неназначенные и непривязанные peers; добавлено время
SQL-среза. Exact image: 99 VPN + 27 resource tests, mypy 231/Ruff прошли; сохранены
45 соседних контейнеров. Живой текущий VPN-каталог пуст: нули не доказывают работу
VPN на Android. Последующее окно 6×3 с: 14 online из 19, без утверждения SLA.
**9 принято / 41 открыто**: весь EP-010 ещё открыт.
[События, polling и оставшиеся источники](../audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-NEXT.md) · [Image/runtime evidence](../audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json).

**5 октября, 19:55 UTC+5 — EP-009 принят на живом 3015:** API/UI **`cb5b3f91`**,
gateway config **`993d9eac`** сохранён. Реальная история CPU в использованных ядрах
и памяти в GiB cgroup контейнера: окна 1/6/24 h, сбор/обновление 15 с, среднее CPU за 1 минуту.
Лимит памяти 2 GiB подтверждён; CPU quota не подменяется нулём. Host/RSS сюда не
смешиваются. 1275 frontend tests/120 suites, production Node24 build/types и 27
tests в exact API image, mypy 231/Ruff, promtool и живые queries прошли. Браузер
1600/390 px, обе темы и автоматическое обновление проверены. При замене каждого
API/UI сохранены 45 соседей; Prometheus reload без replacement всех 46.
Сохранена временная потеря 14→12→13 online; последующее конечное окно 6×3с:
14 online /5 offline из19. Это не непрерывный SLA или устранение утечки.
**9 закрыто / 41 открыто из 50**; следующий EP-010, host leak attribution, Studio
и stream+script load/soak открыты.
[Ресурсная история и границы](../audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md).

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
