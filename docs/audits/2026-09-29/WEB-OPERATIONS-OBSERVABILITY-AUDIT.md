# Веб-панель Sphere: аудит операционной глубины и наблюдаемости

**Дата среза:** 29 сентября 2026 года

**Проверенный source:** `e27d5621e5e5431583b472a432e32a4be6e0911c` (`codex/enterprise-audit-20260905`)

**Объект проверки браузера:** локальный preview `http://127.0.0.1:3012`, только чтение
**Статус:** source-аудит и точечные исправления; production rollout и проверка удалённых устройств не выполнялись.

## Вывод для оператора

Главный риск сейчас — не только недостаток визуальной плотности. Браузерный preview на `3012` и checkout, который разработчик проверяет и меняет, **не согласованы по данным и поведению**. В browser snapshot инфраструктура показывает пять зелёных компонентов, графики истории, `0` туннелей и ресурсы отдельных worker/edge. Текущий backend source возвращает четыре проверки (API responder, PostgreSQL, Redis, диск), пустые массивы истории и `activeTunnels: null`. Локальные pilot-образы помечены `sphere-pilot-20260911-frontend:8fef5eb` и `sphere-pilot-20260911-backend:40357ca`, тогда как source checkout — commit `e27d562` от 29 сентября. Это доказывает расхождение preview/runtime с checkout; пока оно не устранено, screenshot с `3012` нельзя считать приёмкой текущего кода.

Снимок реестра на `3012` в момент проверки: 19 записей, 14 online/busy, 5 offline; среди показанных устройств смешаны Agent `1.2.22-dev`, `1.2.30-dev`, `1.2.32-dev` и `1.2.34-dev`. Это моментальное состояние текущего локального pilot API, а не гарантия стабильности парка, не 24-часовая статистика и не подтверждение удалённого production.

В source уже есть полезные основы: настоящий API-реестр устройств, heartbeat-возраст, события, диагностические ответы APK/браузера, DAG сценариев и виртуализация строк в Fleet Matrix. Но часть интерфейса пока не раскрывает имеющиеся данные; часть желаемых метрик ещё не существует; отдельный стек Prometheus/Grafana описан, но не работает в локальном pilot. Первое исправление — убрать портретный формат из страницы видеопотоков: viewport будет сначала `16:9`, затем примет реальные размеры декодированного кадра. Второе — не считать зелёные health probes полной наблюдаемостью при неполном payload метрик.

## Границы и доказательства

Проверены source на указанном commit, API-обработчики/клиенты, тесты frontend, Compose monitoring, локальные контейнеры и доступные страницы `/devices`, `/monitoring`, `/scripts` в браузере. Просмотр браузера не запускал stream, script, reboot, удаление, OTA или иные команды. Производственный URL и Android-устройства не менялись.

Факты из source можно проверить по следующим местам:

| Область | Текущий source |
| --- | --- |
| Страница реестра | `frontend/app/(dashboard)/devices/page.tsx`, `frontend/src/features/devices/FleetMatrix.tsx`, `frontend/lib/hooks/useDevices.ts` |
| Видео / H.264 | `frontend/app/(dashboard)/stream/page.tsx`, `frontend/components/sphere/DeviceStream.tsx`, `frontend/src/features/stream/streamAspectRatio.ts` |
| Метрики и health checks | `backend/api/v1/monitoring/router.py`, `frontend/app/(dashboard)/monitoring/page.tsx`, `frontend/src/features/monitoring/monitoringTypes.ts` |
| Сценарии | `frontend/app/(dashboard)/scripts/page.tsx`, `backend/api/v1/scripts/router.py` |
| Эксплуатационный контракт | [Fleet operations и observability](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) |

Два набора данных нельзя смешивать: «source имеет endpoint/поле» не означает «метрика записывается», «контейнер запущен» или «оператор видит её в текущем browser build». Пустой график, `null`, нулевое измерение и ошибка запроса — четыре разных состояния.

## Реестр проблем по приоритету

| ID | Приоритет | Подтверждённый факт | Пользовательский/операционный риск | Статус |
| --- | --- | --- | --- | --- |
| WEB-01 | P1 | `/stream` жёстко задавал `aspect-[9/16]`, хотя `DeviceStream` уже знает `VideoFrame.displayWidth/Height`. | Горизонтальный экран эмулятора терял площадь; поток выглядел как узкая вертикальная колонка. | Исправлено в source: fallback `16:9`, далее aspect ratio по реальному декодированному кадру. |
| WEB-02 | P1 | Monitoring считал все health probes healthy достаточным основанием для общего зелёного статуса, когда `/monitoring/metrics` успешно ответил, но большинство измерений было `null`/истории пусты. | Оператор мог принять «сервисы ответили» за «получены CPU/RAM/Redis/network/tunnel метрики». | Исправлено в source: неполное покрытие метрик отдельно подсвечивается; здоровье probes сохраняется отдельным фактом. |
| WEB-03 | P1 | `/devices` и `/stream` запрашивают до 5000 устройств. `useDevices` повторяет запрос каждые 30 секунд; поиск, часть фильтров и сортировка выполняются по всей загруженной выборке в браузере. API уже поддерживает server filters и pagination. | На 500–1000 устройствах избыточный JSON и частые полные обновления, лишняя нагрузка на backend/browser, задержка до актуального статуса. DOM virtualization не уменьшает объём сетевого ответа. | Открыто: перейти к серверной пагинации/фильтрам, суммарному fleet endpoint и отдельной стратегии свежести. |
| WEB-04 | P1 | В browser `3012/monitoring` были 5 зелёных узлов (включая Worker и Edge), история `12/8` точек и `0` туннелей. Source checkout содержит `history: []`, `activeTunnels: None`, а `/nodes` создаёт только API/PostgreSQL/Redis/disk probes. Локальные frontend/backend images датированы `20260911`; HEAD — `e27d562` от 29 сентября. | Проверяется и обсуждается интерфейс, который не соответствует исходникам; графики и число туннелей могут выглядеть правдоподобно, но не доказывают текущие измерения. | Открыто: добавить build/revision stamp в UI и API, сверить точный proxy/upstream и пересобрать только локальный isolated preview из HEAD. Production не трогался. |
| WEB-05 | P1 | Monitoring API даёт host load per reported CPU (не CPU utilization), cgroup memory, Redis info и накопительные сетевые byte counters; history намеренно не хранится, активные туннели не инструментированы. `/nodes` не проверяет отдельный worker/edge. | Страница инфраструктуры не отвечает на вопросы «как менялось», «насколько быстро», «какой worker», «почему device offline/stream stale». Накопительный счётчик — не Mbps. | Открыто: инструментировать фактические источники, сохранять временной ряд в monitoring backend и точно подписывать границы измерений. |
| WEB-06 | P1 перед включением monitoring stack | В `infrastructure/monitoring/docker-compose.monitoring.yml` заданы прямые host-публикации Prometheus/Grafana/Alertmanager, fallback admin/database credentials и отдельная external Docker network. В локальном `docker ps` этих трёх сервисов, exporters, Loki и OTel Collector нет. | Compose-файл не означает, что стек запущен или защищён. Его развёртывание без private bind, обязательных секретов, network policy и проверки маршрутизации создаст ненужную поверхность доступа. | Открыто; проверить hardened config и подключение только после отдельной config/secret проверки. Значения fallback-секретов здесь не копируются. |
| WEB-07 | P2 | Сценарии показывают имя/описание/число шагов и кнопки «Запустить»/«Открыть». Backend отдаёт текущую версию и DAG через `GET /scripts/{id}?include_dag=true`; до исправления frontend типизировал `current_version` как число и ожидал отсутствующий `node_count`. | Нельзя было достоверно увидеть структуру, версию и hash сценария; ложное число шагов расходилось с фактическим DAG. | Исправлено в source: тип контракта принимает version object, шаги выводятся только из имеющегося DAG/legacy count; добавлен явный read-only инспектор с version/hash и редактированием нечувствительных значений через маскировку. Receipt/run detail и ссылки на execution logs остаются открытыми. |
| WEB-08 | P2 | Dashboard регулярно показывает fleet summary, health и device events, но не сводит stream first-frame/stale age, reconnects, command/OTA receipts и queue age в один operator drill-down. | Для RCA приходится переходить по страницам и вручную сопоставлять временные точки. | Открыто: общий incident timeline с device/task/run/stream identifiers и ссылками на факт-источники. |
| WEB-09 | P2 | Settings смешивает русский интерфейс с англоязычными заголовками вкладок; части настроек выглядят отдельными карточками без единой группировки по профилю, безопасности и организации. | Тяжелее отличить персональную настройку от tenant-wide изменения и понять область действия. | Открыто: навигация, владельцы настроек, dirty state, validation, audit and impact labels; проверять существующие мутации до изменения UX. |
| WEB-10 | P1 | В Compose monitoring зафиксированы версии Prometheus 2.48.0, Grafana 10.2.0, Alertmanager 0.26.0 и exporters 2023/2024 поколений; stack не запущен для проверки совместимости. | README/Compose могут быть устаревшим планом, а «обновить latest» без проверки — риск несовместимости/разрыва конфигурации. | Открыто: отдельная совместимая matrix, image digest/SBOM, migration notes и deployment smoke tests; версии не менялись в этом проходе. |
| WEB-11 | P1 | API `ScriptResponse` возвращает `current_version` как объект версии/DAG и не объявляет `node_count`; предыдущий frontend contract ожидал число версии и использовал `node_count` как всегда доступное поле. `include_dag=true/false` также разделяли один query key и могли читать друг у друга кэш с неполной формой ответа. | Ошибочное представление количества шагов, скрытая структура сценария или кэширование ответа без DAG в инспекторе. | Исправлено в source: тип контракта, distinct query keys, count только из фактического DAG/legacy count; read-only inspector с version/hash и маскированием очевидных credential-ключей. Инспектор не запускает сценарий. |

### Отдельно: что означает зелёный статус

Health check отвечает на ограниченный вопрос: «этот probe в данный момент получил ожидаемый ответ?». Он не доказывает полноту метрик, свежесть каждого источника, работу мобильного стрима, корректность task worker или стабильность OTA. В интерфейсе эти факты теперь отделены: статус сервисных проб остаётся health-сводкой, а отсутствие конкретных измерений показывает предупреждение о покрытии.

## Изменения этого прохода

1. Страница потоков больше не ограничивает viewport вертикальным `9:16`. До первого кадра применяется `16:9`, при первом декодированном кадре берутся его реальные размеры, при смене ориентации ratio обновляется. Одинаковые размеры повторных кадров не создают React state updates. Подключение потока по-прежнему выполняется только явным действием оператора.
2. Для infrastructure UI добавлен список недостающих сигналов: значения не превращаются в ноль, а «healthy checks» не выдаются за полную телеметрию. Состояние ожидания метрик остаётся состоянием проверки, а не ложной зелёной отметкой.
3. Добавлены regression tests на landscape/portrait frame shape, отсутствие лишнего dimension callback для каждого кадра, null/history gaps и расхождение между healthy probe и неполными метриками.
4. Сценарии теперь читают форму `current_version` из backend API, выводят число узлов DAG только при наличии данных, а иначе честно показывают «Шаги не указаны». Read-only inspector раскрывается по явному запросу и показывает DAG, версию, hash и доступную историю; значения полей с именами `password`, `token`, `secret`, `credential` и другими распространёнными credential-ключами маскируются. Панель не исполняет и не меняет сценарий.
5. Добавлены unit/page tests на форму версии, отдельные cache keys `include_dag` режимов, подсчёт массива и keyed-object nodes, отсутствие ложного значения и credential redaction.

Это изменения source текущего checkout. Они не являются сборкой/раскаткой в контейнеры `18080`, облачный web endpoint или на APK.

## Целевая модель веб-панели

### 1. Сигналы и временная шкала

Для каждой цифры интерфейс должен показывать источник, время измерения, возраст данных и точный смысл единицы. Нужны отдельные бейджи «probe healthy», «metrics partial», «data stale», «API request failed» и «value is zero». Ноль допустим только после успешного измерения; unknown остаётся unknown. Тренд рисуется только по хранимому временному ряду, а не по случайным/синтетическим значениям.

Операторский сквозной идентификатор — `device_id`, `task_id`/`run_id`, `stream_session_id`, `command_id`, `artifact_version` и `trace_id`; интерфейс должен уметь связать timeline, APK diagnostics, backend logs, command receipts и browser decoder stats. Это не означает помещать каждый ID в label каждой временной серии.

### 2. Наблюдаемость Android fleet

В существующем Android-only агенте полезны ограниченные и versioned snapshots: последняя успешная регистрация/heartbeat, возраст heartbeat, connect/reconnect reason, stream requested/started, capture/encode frames, очередь/отброшенные кадры, переданные bytes, first-frame time, decode/render FPS в viewer, last rendered frame, command accepted/started/result ACK, OTA offered/downloaded/verified/install/boot confirmation, crash ANR и permission state. У каждого события — UTC timestamp, schema/app version, bounded payload и correlation IDs. APK обязан продолжать работать без verbose-логов; диагностический режим и upload должны быть ограниченными, с TTL, лимитом байтов, redaction и запретом на секреты.

Оператор открывает детальную карточку устройства и видит последнюю точку каждого этапа и промежуток, где цепочка оборвалась: capture → encode → agent queue → transport → backend bridge → browser WS → decoder → canvas. То же для task: accepted → leased → started → step receipts → terminal result. До появления фактического источника шаг отображается «не инструментирован», а не зелёным.

### 3. Fleet scale 500–1000 и выше

- API выдаёт ограниченную страницу и агрегаты, а не 5000 полных записей раз в 30 секунд. Поиск, status/group/location/version фильтры, сортировка и counts должны иметь server-side contract; cursor pagination предпочтительна для часто меняющегося парка, если backend может обеспечить стабильный порядок.
- Сводка парка обновляется лёгкими агрегатами и событиями изменения; подробная карточка устройства загружается по требованию. В UI у каждого ответа есть `as_of` / cursor / age; устаревший кэш виден.
- Таблица остаётся виртуализированной, с закреплённым идентификатором и компактным режимом; колонки можно скрывать, длинные значения доступны в карточке/tooltip/copy. Для мобильного экрана таблица превращается в информационную карточку с теми же полями.
- Video viewer отделён от Fleet Matrix: грид не открывает WebSockets сам по себе. Сессия должна иметь видимые лимиты, budget по bitrate/FPS, stop-all, ошибки подписки и сетевую оценку. Автоматически масштабировать просмотр до сотен потоков нельзя без замеров CPU/канала браузера.
- Сравнивать rollout по версии APK/backend/frontend нужно по cohort и receipt; успешный update — это не только download, а checksum/signature verification, install result и подтверждённая работа нового процесса.

### 4. Monitoring stack и технологическая граница

В source уже есть отдельный Compose набросок Prometheus/Grafana/Alertmanager/exporters и Prometheus exposition у backend. Он не запущен в локальном pilot окружении, а browser `3012` отдаёт противоречивую картину. Предлагаемый следующий шаг — сначала зафиксировать build provenance и безопасно поднять этот стек в изолированной среде, затем добавить реальные API/worker/DB/Redis/host targets и тест «каждый dashboard panel ссылается на существующую метрику».

Для инструментирования сервисов можно использовать OpenTelemetry API/SDK и Collector gateway для приёма traces, metrics и logs от backend/worker; Prometheus/Grafana остаются возможным metrics/dashboard backend, Alertmanager — маршрутизация оповещений. Это не требует отдельного Windows PC Agent и не заменяет Android APK: Android сообщает только те app/device telemetry, которые уже разрешены его протоколом и настройками приватности. Collector — инфраструктурный сервис, который нужно включать после threat/config review, capacity и egress-тестов.

Для метрик оставлять низкую кардинальность: service, environment, region, status/result class, operation. Не добавлять `device_id`, `task_id`, `run_id`, raw URL, request/trace ID в labels без отдельной cardinality модели. Пер-устройственные детали держать в bounded event/receipt store или logs/traces и искать по structured metadata/фильтру. Число устройств/стримов не должно умножаться на все метрики API и HTTP пути.

## Очерёдность следующей работы

| Волна | Что делаем | Критерий приёмки |
| --- | --- | --- |
| A — доверие к сборке | **Source plumbing реализован**; CI build/security/lint на commit `8c8a5b2` прошли. Runtime preview и сверка WEB/API SHA остаются открыты: preview deploy skipped, `3012` показывает старый pilot. | UI, API, артефакты и git commit должны совпасть на целевом runtime; никакого доказательства deployment пока нет. |
| B — реестр | **Первый source increment реализован**: серверная страница, server-side поиск/group/location, live-status counts/filter, API snapshot time, unknown при недоступном Redis; оставшийся O(N) Redis scan и нагрузочный тест 1 000 ID открыты. | HTTP payload ограничен страницей; total/filter/status counts согласованы; отдельно пройдены location/group, concurrency, 1 000 synthetic IDs и query/byte budgets. |
| C — Device Stream | Первый кадр/last frame/fps/reconnect/decoder/output в едином Inspector; landscape/portrait auto ratio уже исправляется; состояния без кадров, stale, offline и transport error различимы. | 1/4/8 потоков проверены на реальном browser; кадры движутся; при 32 viewer есть профили нагрузки и отказы; за пределом лимита стримы не стартуют скрытно. |
| D — Infrastructure | Безопасно развернуть observability stack; API/worker/DB/Redis/host probes и scrape labels; история, p95/p99 и алерты только по реально измеренным сигналам. | Compose config проверен без fallback secret, сервисы bind к private network, Grafana доступна с auth; scrape targets healthy; worker метрики агрегируются ровно один раз. |
| E — Scripts/tasks | Read-only DAG source inspector, version/hash реализованы в source. Следом добавить run detail, terminal receipt и логи выполнения. Отдельно предусмотреть future config bundle как версионируемый, dry-run/validated artifact. | Оператор видит фактический DAG и завершение; просмотр не запускает сценарий; повторный run требует отдельного явного действия. |
| F — UX Settings/dashboard | Перегруппировать по scope (профиль/безопасность/организация), нормализовать локализацию; dashboard с degraded fleet, свежестью, недавними инцидентами и прямым RCA drilldown. | Каждая кнопка имеет проверенную API-мутацию или объяснённое read-only состояние; нет циклических ссылок и декоративных псевдометрик. |
| G — масштаб | Нагрузочная матрица 32 → 100 → 500 → 1000 устройств: heartbeat, DB/API, очередь, stream sessions, события, браузер и retention. | Заданы KPI после baseline; p95/p99, error budget, resource budget, reconnect/queue age и recovery проходят пороги без потери команд/receipt. |

Сначала выполняются A и B: иначе тяжело доказать, что наблюдаем нужный код, и текущая загрузка устройств не масштабируется. Параллельно можно закрывать C и E на уровне source, но массовый rollout не считается завершённым без canary и terminal receipts. Thresholds для SLO нужно вывести из baseline 20–30 устройств и профиля нагрузки; произвольные числа в dashboard здесь не назначены.

## Обязательные проверки перед каждым rollout

1. Unit/contract tests: null, zero, empty history, stale timestamp, error, retry, duplicates, late receipt и version skew.
2. API integration: pagination/filter totals, tenant isolation, stream diagnostics, script DAG/version, terminal task/OTA receipts; query count/response-size budgets.
3. Browser: 1440×900, 1280×720, 390×844; landscape и portrait кадр, loading/error/empty/degraded, keyboard, reduced motion, overflow, long identifiers и таблица 1000 записей.
4. Observability config: `promtool check config`/rules, secret absence, no public bind without gateway auth, exporter connectivity, restart/reload, retention and disk cap; compose services must be actually running before UI can claim they are.
5. Pilot: build SHA/versions, один canary, подтверждённая новая версия, stream moving-frame proof, safe DAG, receipts, reconnect/rollback; далее 20–30 устройств с явным resource budget. Запуск на 500–1000 не является продолжением маленького canary автоматически.

## Рекомендации и лицензии

Здесь используется документация проектов, а не копирование закрытых шаблонов/кода. Основные ориентиры:

- [OpenTelemetry Collector deployment patterns](https://opentelemetry.io/docs/collector/deploy/) и [agent-to-gateway pattern](https://opentelemetry.io/docs/collector/deploy/other/agent-to-gateway/) — разделение лёгкого сбора и централизованной обработки.
- [Prometheus instrumentation practices](https://prometheus.io/docs/practices/instrumentation/) — ограничение cardinality и выбор метрик для online-serving систем.
- [Grafana Loki label best practices](https://grafana.com/docs/loki/latest/get-started/labels/bp-labels/) и [structured metadata](https://grafana.com/docs/loki/latest/get-started/labels/structured-metadata/) — высококардинальные поля не превращать в индексные labels.

При выборе библиотек и контейнеров фиксировать точные версии/digests, license identifier, upstream и SBOM в PR. Данный аудит не добавляет внешние frontend-компоненты и не копирует исходный код AdminCN/Studio Admin; для этой работы это архитектурные рекомендации, а не runtime dependency.

## Подтверждение после source изменений

### Follow-up: provenance baseline (29 сентября 2026)

До этого изменения CI мог передать `BUILD_SHA` только в backend build action,
но backend Dockerfile не объявлял аргумент, frontend action не передавал SHA,
а UI не показывал ни одну из ревизий. Следовательно, старый pilot `3012` нельзя
было надёжно отличить от текущего checkout по интерфейсу.

В PR #19 добавлен публичный `/api/v1/health/build` с валидацией Git SHA,
маркировка `WEB`/`API` в общей шапке и передача `github.sha` в оба preview image
build. Исправлен также backend build context на корень репозитория, которого
требует `backend/Dockerfile`. Это закрывает source/build plumbing, но не является
доказательством работающего preview: требуется успешный image build/deploy и
сверка двух значений на target runtime. См. [runbook provenance](../operations/BUILD-PROVENANCE.md).

- `npm run type-check` — **PASS** после всех текущих изменений.
- Целевые regression tests — **7 suites / 35 tests PASS** до дополнительного cache-key теста; затем сценарные suites — **3 suites / 19 tests PASS**.
- Полный `npm test -- --runInBand` — **57 suites / 371 tests PASS** после всех frontend изменений.
- `npm run build` на копии текущего frontend source — **exit 0**; Next.js 15.5.26 скомпилировал приложение и сформировал все 30 маршрутов. Во время Windows standalone tracing были предупреждения `EPERM` на junction `node_modules` и `ENOENT` при копировании client-reference manifest в standalone output. Поэтому это подтверждает compilation/routes, но артефакт standalone не принимается как чистая сборка для release.
- Source preview на `3013` корректно потребовал отдельную авторизацию и перенаправил на `/login`; пароль не вводился. Нельзя заявить, что изменённые страницы визуально приняты через аутентифицированный браузер. Имеющаяся вкладка `3012` показывает отдельный старый pilot runtime, не этот build.
- Производственный URL, контейнеры production и Android-устройства не менялись. Сборка/rollout на `18080` или облачный домен не выполнялись.

### Follow-up: server-paged fleet catalogue (29 сентября 2026)

Страница устройств перестала запрашивать `per_page=5000` и фильтровать всю выборку в браузере. Она запрашивает 100 строк по умолчанию, даёт выбор 50/100/200, отправляет search/group/location/live-status фильтры на API и оставляет выбор операций внутри страницы. API возвращает точные для текущей DB-области live-счётчики, `scope_total`, filtered `total/pages`, `presence_available` и время `as_of`. Redis-состояния читаются единым MGET, а в страницу гидратируются только выбранные строки. Поиск теперь включает модель и полный UUID.

Live-фильтр использует Redis presence, а не DB `last_status`: при активном Redis отсутствующий ключ отображается как offline; при недоступном Redis отображается unknown, чтобы старый DB-статус не выглядел живым. Ошибки/maintenance без live-key остаются в группе внимания. В видеосетке busy корректно считается достижимым и может открыть viewer; ранее карточки считали его online, но сами не создавали поток.

Это уменьшает JSON payload и работу по ORM-гидратации, но полный scope всё ещё просматривается по ID и MGET для точных счётчиков. Backend cost остаётся O(N); нагрузка на 1 000+ устройств не заявлена. Следующий этап — проверка групп/локаций, гонок изменения реестра, network payload/latency на синтетическом масштабе и только затем индексированные live-агрегаты при необходимости. См. [контракт Fleet Matrix](../../operations/DEVICE-CATALOG.md).

Дополнительная проверка того же среза закрыла два contract/recovery edge case: hook приводит API `per_page` к используемому страницами `page_size`, а ошибки Redis `MGET`/соединения возвращают каталог со статусом `unknown` и `presence_available=false`, вместо ошибки всей страницы или ложного offline. Итоговые проверки после этих исправлений: `tests/devices/test_devices.py` — 46 passed; полный frontend suite — 58 suites / 377 tests; целевые device/hook suites — 3 suites / 18 tests; `npm run type-check`, Ruff и сверка сгенерированной API schema — passed. Backend выводит две существующие deprecation warnings в соседнем game_accounts/dateutil коде.

Изолированный production Docker build из `frontend/` завершился с exit 0 и включил все 30 Next.js маршрутов. Next.js напечатал предупреждение standalone tracing (`ENOENT` при копировании одного client-reference manifest), но последующая сборка runner-образа прошла. Образ был временно запущен на loopback-порту, `/login` вернул HTTP 200, после smoke test контейнер остановлен. Предупреждение tracing оставлено как открытый build hygiene item; smoke test не означает runtime acceptance авторизованных страниц или реального API. Контекст сборки был ограничен `frontend/`; случайную попытку с корневым контекстом остановили при обнаружении почти 1 GB локальных артефактов.

Изменения относятся к исходникам этого checkout. Публичный сайт, local pilot `3012`/`18080`, Cloudflare/Tuna и APK не обновлялись. CI для текущего коммита будет записан отдельно от уже завершённых локальных проверок; runtime rollout остаётся не подтверждённым.
