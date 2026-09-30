# Sphere: актуальное состояние и критерии приёмки

**Обновлено:** 30 сентября 2026, Asia/Yekaterinburg; даты отдельных runtime/CI срезов указаны ниже.<br />
**Область:** исходники и документация ветки PR #19, записанные runtime-наблюдения, Android APK и готовность следующего прогона.<br />
**Канонический документ текущего состояния:** этот файл. Исторические отчёты ниже сохраняют исходные даты и факты.

[Главная](../../README.md) · [Каталог документации](../README.md) · [Readiness](READINESS.md) · [Fleet32 gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

> [!IMPORTANT]
> Это сверка исходников, CI и отдельных runtime-срезов. 30 сентября на отдельном локальном `3015` работает frontend `ea7f9cf` с настоящим pilot API `18080` и встроенной Grafana; прежний `3012` сохранён. Backend, публичный frontend, APK и туннели этим этапом не обновлялись. Отдельные canary не являются приёмкой всего парка. Исторические срезы сохраняют свои даты.

## Состояние на дату проверки

### Dependency-aware type gate — source dac2319, 30 сентября

Полный mypy **2.3.1** с установленными backend dependencies теперь проходит
**219 source files**, включая `check_untyped_defs`. Исправлены типы SQLAlchemy
predicate/sort expressions, ASGI Message и Pydantic response boundaries;
nullable script/device ID проверяются до записи регистрации/фарм-задачи.
Три новых PostgreSQL regression tests воспроизвели ошибки на исходной версии;
после исправления **372 tests passed / 1 deprecation warning** в затронутых
device/WS/VPN/orchestration сценариях. Общий suite завершился:
**2123 passed / 5 warnings**, **596.50 s**, exit **0**, без load/soak и coverage.

CI lint теперь устанавливает backend dependencies и выполняет `pip check`,
поэтому отсутствующие импорты больше не превращают эти границы в `Any`.
Версии инструментов закреплены: Ruff **0.15.2**, mypy **2.3.1**.
Это source validation; live backend/3015/APK на этом этапе не переключались.
Структурный protocol VPN command publisher сохраняет прежнее поведение:
существующий stub возвращает `False`, реальная доставка kill-switch не
объявляется реализованной этой правкой.

### Ресурсный lifecycle метрик — source canary 30 сентября

На прежнем packaged image `e3b4fe7` повторены два независимых прогона с
**64** заменами workers каждый. После каждого сохранены точные HTTP totals,
четыре live workers и отсутствие duplicate samples. Registry вырос с
**18 files / 1 179 648 bytes** до **146 files / 9 568 256 bytes**; прирост
**128 KiB на worker replacement**. Максимальный scrape — **21.62 ms** в
изолированной fixture с 1 CPU / 384 MiB. Это измерение конечной synthetic
нагрузки, не production performance SLA.

Новый entrypoint маркирует private registry владельцем/master PID. `on_exit`
проверяет путь, marker, владельца и отсутствие live children, затем удаляет
только свой каталог. Неподтверждённый/чужой каталог сохраняется. Production/full
Compose ограничивает `/tmp/sphere-metrics` отдельным **128 MiB tmpfs**;
SIGKILL остатки исчезают при остановке контейнера. Пока master работает,
counter/histogram files сохраняются: tmpfs **не** делает рост бесконечно безопасным.
При заполнении нужны controlled maintenance/capacity alerts; многосуточный
высоконагруженный budget ещё не принят.

**188 monitoring/deployment tests passed / 1 warning** для нового lifecycle.
Проверка graceful/SIGKILL в packaged image выполняется отдельно; source tests
не выдаются за image/runtime acceptance. Свежий CI прежнего remote head
`59ba4c7` завершил исполняемые checks success, deploy skipped.

### Multiprocess метрики — изолированная image acceptance 30 сентября

Source **`e3b4fe7`** собран из Git archive в production Linux-образ
**`sha256:638d609659232a9fcf8b2f4969e481b0ae1c39eba9afd4d40353c5b53593dd15`**.
В контейнере без сети и host ports проверен настоящий Gunicorn: отдельное
keepalive соединение с каждым worker подтвердило **32 × 4 = 128** requests.
После SIGTERM child hook удалил live gauges, новый worker появился, а totals
сохранились; ещё 32 requests дали **160**. После рестарта master сценарий
повторён: новый private registry начал с нуля. Дублирующихся samples нет.
Pool gauges **40/4** в этом canary заданы синтетической HTTP fixture: они
доказывают агрегацию, **не** количество connections живого PostgreSQL.

Свежая packaged PostgreSQL/Redis установка с миграциями, login/enrollment,
реальным app lifespan, audit/visibility и повтором в новом процессе прошла
отдельный runtime probe. Bootstrap image checks также passed. В обоих canary
backend source из checkout не монтировался; mounted только test adapters.
Созданные контейнеры удалены с проверкой ownership. Private evidence —
`.local-pilot/metrics-20260930-final-{image,runtime}-evidence`.

Per-device snapshots остаются в diagnostics API; production Prometheus
использует bounded fleet families. HTTP templates сохраняют параметры `{id}`,
не создают серии из произвольных URL/method и учитывают необработанные 500.
Два новых ASGI regressions воспроизвели failures на baseline. Первый полный
suite выявил четыре несовместимых UUID labels; нормализация восстановлена,
audit invariants не ослаблены. После этого **194** monitoring/stream/deployment/
audit-path tests passed. Повторный общий suite окончательного source завершился
**2120 passed / 5 warnings**, **608.15 s**, exit **0** (`tests`, без load/soak).
Coverage в этом локальном запуске не измерялось; coverage gate нового CI —
отдельная проверка. Deprecation warnings не скрыты.

Ruff **0.15.2** и targeted mypy нового кода passed; API docs `--check` passed.
Полный mypy **1.8.0** дал 17 errors в 9 неизменённых файлах, а **2.3.1** с
установленными backend dependencies — 14 errors в 8 неизменённых файлах.
Полностью чистый dependency-aware type gate не заявляется. CI последнего
remote doc head **`4dff726`** завершил все исполняемые checks success, deploy
skipped; это не результат нового source. CI lint устанавливает mypy/ruff без
backend dependencies и не заменяет этот локальный dependency-aware check.

Backend `40357ca`, APK и туннели на этом этапе сохраняют прежний runtime.
В браузере **16:42–16:45 UTC+5** `3015` подтвердил frontend `ea7f9cf`, подключённые
events, обновляемую историю **241 point**, iframe Grafana и **0 console errors**
в новой вкладке. Backend metadata endpoint отсутствует, legacy monitoring
payload отвергается; карточки не становятся здоровыми нулями. Resource retention
при долгом worker recycling ещё требует отдельной приёмки; см.
[multiprocess contract](OBSERVABILITY.md#multiprocess-contract--исходники-30-сентября-2026).

### Принята локальная сборка ea7f9cf — 30 сентября, 15:54–15:56 UTC+5

Владелец выполнил guarded updater в своей PowerShell-сессии. Receipt **15:54:12**
и readback портов: Next **5552 / 3014**, прежний relay **31892 / 3015**.
В браузере виден **`WEB ea7f9cf7`**, события подключены; Grafana открылась,
показала панели и больше не зарегистрировала OpenFeature error. В сохранённом
console остаются два исторических errors предыдущей сборки, новых после
переключения на этом canary нет. Это ограниченный browser smoke, не гарантия
отсутствия ошибок во всех страницах/сценариях.

Независимый HTTP canary прошёл через **работающий Next**, без импорта handlers
из checkout: history **200 / 241 points**, anonymous **401**, session **200**,
Grafana user **200 / isGrafanaAdmin=false**, dashboard **200 / canEdit=false**,
OFREP **200 / 378 flags**, graph query **200 / 1 frame**. История в браузере
обновлялась без кнопки refresh: **15:54:51 → 15:55:06 → 15:56:06 → 15:56:36**.
На новом source повторена mobile-проверка: document width/scrollWidth **390/390**,
iframe **350 px**; затем обычный viewport восстановлен. Сырые receipts и
desktop/mobile screenshots остаются в private pilot evidence.

**Живой адрес:** `http://127.0.0.1:3015/monitoring`; `/devices` использует тот же
реальный API. OFREP rollout gate закрыт для этого локального preview. Это не
публичный rollout и не приёмка Android OTA/автономного DAG/20–30 stream sessions.
Старый monitoring contract и multi-worker aggregation остаются P1; следующие
этапы и частоты обновления описаны в [runbook](OBSERVABILITY.md).

### Живой веб, встроенная Grafana и следующий фикс — 30 сентября, 15:39–15:49 UTC+5

Владелец выполнил подготовленный launcher после отказа автоматического запуска.
Readback подтвердил `3015` relay PID **31892**, Next `3014` PID **44804**,
source **`ab0724dbc148466d3ff3eea5c924c6447e3c3856`**. Production build этого
source завершился с exit 0, 33 application routes. Старый `3012` не заменён.
Адрес актуальной живой проверки: `http://127.0.0.1:3015/monitoring`.

В браузере подтверждены `События: подключены`, настоящий каталог **19 / 14
online / 5 offline**, версия WEB, история Prometheus **241 точка** и обновление
срезов без ручного refresh: **15:40:30 → 15:40:45 → 15:41:16 → 15:45:01**.
Встроенная Grafana показывает реальные панели; повторное открытие после
перехода в реестр успешно. На ширине 390 px document/main имеют ширину 390,
iframe 350, горизонтального document overflow нет. Screenshot и исходные
receipts сохранены приватно. Сквозной hidden-tab recovery проверен unit
regressions; этот browser receipt не выдаётся за тест реального сна компьютера.

Найдена отдельная ошибка загрузки feature flags Grafana: native OFREP endpoint
отвечает 200, а текущий `ab0724d` bridge отклоняет этот POST с **405**. Это
объясняет console initialization error; сами графики доступны. Source fix
разрешает только bulk read для namespace `default`, body до 16 KiB, с фиксированным
серверным контекстом. Browser identity не пересылается, записи запрещены.
Direct handler canary: flags **200 / 378**, graph query 200, Viewer
`canEdit=false`, dashboard write **405**, anonymous history **401**.
Полный frontend **71 suites / 523 tests passed**, TypeScript и targeted ESLint
passed; до патча regression дал 7 failures с 405. Это source/canary приёмка
следующего фикса, **не** заявление, что он уже работает на `3015`.

Архивный production build **`ea7f9cf7a457b551610e22f0cfa5bf1d8d7110d1`**
завершился с exit 0: 33 application routes, build ID
`N052OkmjfrKz_g01iCqwC`. Source config сохранён; только local artifact отключает
`output: standalone`. Сохраняются legacy lint warnings других страниц.
GitHub этого source: Frontend tests/types/build, security, lint, RLS,
production-image bootstrap и guard success; Backend Tests и Android ещё
in progress, deploy skipped. Полностью зелёный PR не заявляется.

При попытке обновить только operator-owned Next `44804` проверка процесса
остановила script **до остановки/запуска**: Windows из сессии ассистента
возвращает `CommandLine=null`, хотя PID портов и CreationDate совпадают с
launch receipt. Проверка владельца не ослаблена; подготовленный updater должен
выполняться в той же PowerShell security context, что и первоначальный запуск.
В этом срезе receipt ещё отсутствовал; последующее успешное переключение
владельцем и проверка `ea7f9cf` зафиксированы в разделе выше.

Карточки старого deployed monitoring API остаются недоступными: payload не
имеет времени/источника измерения. Новый веб не подменяет это здоровыми нулями.
P1 backend rollout и multi-worker aggregation ниже остаются открыты.

### Канал событий и актуальность веб-данных — 30 сентября, 15:33 UTC+5

Через действующий proxy `3012` выполнен отдельный read-only WS canary:
авторизованный `snapshot`, затем три `pong` за 20 s, задержки **21.0 / 5.2 /
2.7 ms**. Тот же API-срез: **19 / 14 online / 0 busy / 0 connecting /
5 offline**. Это проверка доступности канала, не длительный soak и не
приёмка стримов всего парка. Сырые receipts и credentials остаются приватными.

В исходниках исправляются конкретные пробелы: проигнорированный reconnect
snapshot без REST reconciliation, отсутствие обновления Dashboard и смежных
таблиц по task events, отсутствие watchdog молча сломанного WS, пересоздание
канала при изменении callback. Добавлены bounded handshake/ping/backoff,
индикатор канала событий, batching refresh, background deferral и сверка
после возвращения вкладки. Prometheus обновляется каждые 15 s, отслеживаются
старые snapshots/targets; Grafana повторно авторизуется после скрытой вкладки.

Frontend regression: **71 suites / 511 tests passed**; TypeScript и targeted
ESLint прошли в этом проходе. Production build и browser acceptance этой
новой версии фиксируются отдельным receipt после подготовки артефакта.

**На момент этого среза runtime ещё не переключён:** попытка параллельного старта готового source
`603a8fc` на 3014 снова отклонена automatic approval review (`blocked by
policy`), без более конкретной причины. Последнее разрешение пользователя
продолжить работу не устранило технический блок запуска. Это не отсутствие
авторизации владельца. Старый Next `6936cac` и proxy продолжают обслуживать
3012; новые изменения не выдаются за уже видимые в браузере.
[Частоты, восстановление и ограничения realtime](OBSERVABILITY.md#обновление-данных-в-открытом-вебе).

### Prometheus / Grafana: реальные сервисы и подготовленная интеграция — 30 сентября

На 08:33 UTC+5 запущен отдельный Docker project
`sphere-observability-20260930`: Prometheus **3.15.0** и Grafana OSS **13.2.3**,
образы закреплены по digest. Оба контейнера healthy; targets `sphere-backend`
и `prometheus` — up. Сбор 15 s, TSDB retention 14 d / 2 GB, stdout/stderr
ограничены 3×10 MB. Backend `40357ca`, APK и туннели не пересоздавались.

Native Prometheus проверен в браузере: `up{job="sphere-backend"}` вернул один
ряд со значением 1; график показывает реально накопленную историю. Срез 08:19
содержал 77 точек. Grafana query API вернул 200 и один data frame; provisioned
dashboard `sphere-collection` содержит пять панелей, Viewer `canEdit=false`,
попытка save отвергнута 403. `promtool check config` passed. Это приёмка
отдельных сервисов, **не** встроенной Grafana в основной странице Sphere.

Source **`603a8fc491ae21611886bccd6ef234a5595da00e`** подготовлен: protected
server history, targets/alerts, iframe с read-only auth proxy, short-lived
HttpOnly cookie и проверкой super_admin через `/auth/me`. Полный frontend:
**71 suites / 496 tests passed**, TypeScript и targeted ESLint passed.
Production builds `459f001` и `603a8fc`: exit 0, 33 маршрута. Для local
`next start` в архивной копии отключён только `output: standalone`.

**На 08:33 новая веб-сборка ещё не запущена:** переключение Next и параллельный запуск
не выполнены из-за automatic approval review. Основной `3012`
сохраняет frontend `6936cac`, Next PID 46164 на 3013, proxy PID 5324.
Новый iframe, responsive layout и end-to-end auth ещё не прошли browser
acceptance. Подготовленная сборка не выдаётся за видимый rollout.

Подтверждены два P1:

- Четыре Gunicorn worker без `PROMETHEUS_MULTIPROC_DIR`; общий RPS/p95/CPU/fleet
  по worker-local counters не подтверждён. Новые графики используют только
  метрики собственного scrape/TSDB Prometheus, без таких KPI.
- Старый runtime monitoring API отвечает без авторизации HTTP 200, отдаёт
  12/8 точек истории без времени среза и Worker/Edge без provenance. Source
  `603a8fc` отвергает эти старые payloads в UI; source RBAC fix WEB-12 уже есть,
  но backend rollout не выполнен и runtime endpoint этим не защищён.

На previous head `07ade6f` все GitHub code checks success, deploy skipped
(сверка 30 сентября); это historical CI, не приёмка нового source. На
`459f001` Frontend/Backend Tests/bootstrap/lint/security/RLS/guard success,
Android и Alembic ещё in progress в предыдущем срезе этого прохода. Новый head требует своего CI.
[Runbook, лицензии, источники и ограничения](OBSERVABILITY.md).

### Карточка устройства и интерактивные действия — 30 сентября

На `3012` работает production build source **`6936cacd20624ce8de624bcfde2d523b12acf68b`**:
30 маршрутов, exit 0; build stamp `WEB 6936cacd`. API остаётся `40357ca` на
`18080`. Перед заменой Next-процесса проверены его command line и владелец порта;
3012 proxy и Docker backend не перезапускались. Public deployment не выполнен.

Полная карточка и боковой инспектор используют общий компонент с API-запросом
по ID и polling 15 s. Отдельно видны реальная версия APK, heartbeat, CPU/RAM,
каталог, задачи/события, видеодиагностика и сохранённые логи. Отсутствующее начало
связи не выдаётся за uptime. Dialog управляет фокусом и закрывается при смене
маршрута. PNG берётся из успешно отрисованного свежего canvas; старый PC Agent
screenshot stub не вызывается.

Исправлены fake `Connected` в терминале, продолжение shell-цепочки после ошибки,
старый Logcat после пустого результата и HTTP timeout 5 s при серверном ожидании
30/15/10 s. Новые HTTP waits shell/logs/reboot — 35/20/15 s только для этих
операций; timeout не означает отмену и не вызывает auto replay.
**69 suites / 463 tests passed**, TypeScript и targeted ESLint passed.
[Подробный отчёт и доказательства](../audits/2026-09-30/WEB-DEVICE-INSPECTOR.md).

На предыдущем source `4018756` в browser viewer получены 9 отрисованных кадров
1280×720 выбранного удалённого canary, decoder/render errors 0/0. Статичный экран
позднее дал stale-метку; это не streaming SLA. Каталог на 02:39 UTC+5: 19 записей,
14 online. Перед этой проверкой GET карточки/истории/диагностики/логов вернули 200.

На source `0e04459` выбранный canary через shell вернул Android `9` за 3 777 ms;
явный запрос к APK вернул 500 строк логов. В browser source `6936cac` подтверждён
возврат фокуса после замены строк при resize; drawer desktop имеет ширину 640 px,
на mobile — 390 px без document overflow. Полная карточка использует тот же API
и закрывает drawer при переходе. Это отдельные canary, не приёмка reboot/OTA/DAG.

CI source `0e04459`: Frontend tests/types/build, lint/security/RLS/guard и
production-image bootstrap passed; Backend Tests и Android ещё in progress
по срезу 02:54 UTC+5. Последний source `6936cac` имеет отдельные проверки;
pending не объявляются passed. Текущий PR полностью зелёным не считается.

### Предыдущие этапы 30 сентября: настройки и таблица

Раздел `/settings` переведён на общую систему интерфейса. Профиль и MFA используют
`/auth/me`; неподтверждённые даты сессии и VERIFIED удалены. Ошибки списка ключей
отделены от пустого результата, отзыв/отключение требуют подтверждения, мутации
не повторяются автоматически. На source `96ea973`: полный frontend Jest —
**67 suites / 440 tests passed**; settings — 12 passed, FleetMatrix + DevicesPage —
17 passed, provenance — 7 passed. Types и targeted lint passed.
[Отчёт и оставшиеся этапы](../audits/2026-09-30/WEB-SETTINGS-ACCOUNT-SECURITY.md).
Последняя локальная production compile: `96ea973c928a80c2e475547398b827691cf4d759`,
exit 0, 30 маршрутов. В архивной копии frontend для `next start` отключён только
`output: standalone`; source config сохранён. На `3012` видно `WEB 96ea973c`,
настоящие профиль и каталог API; mobile tabs и dialog проверены на 390×844,
desktop — 1440×1000. Ширина документа на телефоне 390 px, таблица прокручивается
в собственном контейнере (934 px), dialog имеет ширину 358 px.

Preview теперь проксирует обычные API-действия и `/ws/*` в существующий backend,
а не блокирует их blanket 403. Проверка без device IDs и без авторизации получила
401; WebSocket с заведомо неверным токеном открылся и был отклонён backend с 4001.
Это подтверждает relay/auth boundary, а не живой stream или успешную команду.
Выбор строки → Delete открывает диалог; отмена сохраняет каталог из 19 записей.
Снимок на 02:16–02:17 UTC+5: 14 online и 5 offline, не измерение длительного uptime.

Первый CI `29a0f6d` обнаружил TypeScript-ошибку matcher в тесте; она исправлена.
Frontend CI следующего source `80e981e` прошёл tests/types/build. На `96ea973`
по срезу 02:17 UTC+5 Frontend, backend Tests/image bootstrap и Android ещё pending;
lint/security/RLS/preview guard прошли, deploy skipped. Полностью зелёный текущий
PR не заявляется. Public deployment не выполнен.

Повторная сверка в 02:19 UTC+5: на `96ea973` Frontend tests/types/build и
production-image bootstrap тоже прошли. Backend Tests и Android ещё выполняются;
по-прежнему нет основания объявлять все проверки завершёнными.

Дополнительно в реестре исправлена совместимость с прежним API: отсутствующий
`presence_available` не считается отказом Redis; локальные счётчики страницы
подписаны отдельно от глобальных; первый отказ API оставляет KPI неизвестными.
Runtime `40357ca` пока не публикует новые метаданные каталога. [Контракт и пределы](DEVICE-CATALOG.md).

Fleet Matrix получила отдельную колонку Android / агент и «Heartbeat / контакт»:
реальный heartbeat больше не теряется при пустом `last_seen`; отсутствие начала
сессии не объявляется подтверждённым uptime. Основные данные видны без hover,
доступ/server/tags доступны через меню. [Доказательства](../audits/2026-09-30/WEB-FLEET-READABILITY.md).
Header различает отсутствующий revision endpoint (404, `no metadata`) и отказ
lookup; эти состояния не объявляют API неработающим. [Provenance](BUILD-PROVENANCE.md).

Нижеследующие численные версии/наблюдения относятся к исходному срезу 29 сентября,
а не к заново измеренному uptime Android-парка. Exact-head CI исходника `e8b4c40`
успешно завершился; прежний статус queued ниже сохранён только как история того среза.

| Область | Подтверждённое состояние | Что это не доказывает |
| --- | --- | --- |
| PR | PR #19 открыт как draft. Последний полностью успешный exact-head source CI на `5c9e56c` завершился 28 сентября 2026, 00:46:11 UTC; Preview deploy был пропущен. На текущем head `70f9367` см. свежий снимок ниже: Frontend и Android ещё in progress, поэтому текущий PR полностью зелёным не считается. | Нет merge, production deploy или подтверждения работающей публичной версии сайта. Успешная историческая сборка не подтверждает запуск этих image в production. |
| APK source | Кандидат исходников PR задаёт **1.2.35 / 10235**. Последний записанный оператором/сервером canary — отдельный **1.2.34-dev / 10234**. Релизный путь и пределы доказательств описаны в [Android release-readiness audit](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md). | Source version 1.2.35 не удостоверяет собранный production APK, его подпись, OTA-публикацию или установку на устройства. Для rollout нужны пакет/flavor, `versionCode`, signer, SHA-256, OTA entry и installed report. |
| APK release pipeline | Локально кандидат прошёл все 4 тестовых варианта (2 764 запуска, 0 failures/errors, 4 существующих skips), lint (0 ошибок, 74 warnings), fail-closed проверку без ключа и подписание обоих release flavors одноразовым smoke-сертификатом с успешной проверкой `apksigner` и package/version metadata. GitHub Android CI на final PR head `92cc21c` прошёл за 12:55 с обновлёнными action majors; прежние Node 20/cache restore warnings исчезли. | GitHub Actions secret inventory показал отсутствие всех 5 production signing secret names. Одноразовые APK и ключ удалены после smoke; это не production signing. Tag/Release, OTA entry, deployed backend, реальная удалённая установка и canary здесь не проверялись. Не устанавливать smoke APK как обновление. |
| APK release / OTA | В записанном canary-контексте кандидат `1.2.34-dev / 10234` был **локальным артефактом**, `published_to_ota=false`; оператор вручную установил его на несколько удалённых эмуляторов. Сервер увидел три свежих agent reports с кодом 10234. | Массовая OTA не публиковалась и не подтверждена. Последнее чтение OTA-каталога для этой даты не выполнялось; версию канала нельзя назвать без нового read-only запроса. Установка трёх пакетов с конкретным SHA независимо не доказана. |
| Удалённое видео | 28 сентября в 03:18 оператор подтвердил видимую живую картинку в браузерной Device Stream странице во время canary. Это прямое наблюдение минимум одного просмотренного потока. | Не зафиксированы точный device/session ID этого viewer, активный маршрут Tuna/fallback, browser decode/render counters, FPS, latency, длительный soak или успех для всего удалённого парка. |
| Парк | Последний записанный read-only snapshot в canary-аудите: **29 записей каталога, 19 active, 14 с heartbeat/WS не старше 45 секунд и 5 active без свежего статуса**. Оператор обозначил 14 устойчиво работающих устройств как базу сравнения. | Число 14 — базовая выборка на момент прежнего наблюдения, а не заново измеренный uptime на момент этой документации. Ожидаемые 23 и масштаб 20–30 устройств не прошли приёмку. |
| Backend / frontend runtime | CI на `b30a849` прошёл проверки сборки/тестов backend, frontend и Android. Source содержит обновлённую truthful monitoring-страницу. | Источник не равен deployed image. Не перечитывались активные container digests, runtime readiness, публичный URL и фактический frontend/backend commit. |
| Frontend dependencies | В PR source обновлены Next.js и `eslint-config-next` с `15.5.13` до `15.5.26`, PostCSS до `8.5.28`; lockfile содержит исправленный Handlebars `4.7.9` и совместимые транзитивные обновления. Локальные Jest (41 suites / 306 tests), type-check и `npm audit` по `frontend/` прошли; аудит сообщает 0 уязвимостей. GitHub frontend CI на `5c9e56c` также прошёл `npm ci`, tests/types/build и standalone entrypoint check. | Это ещё не означает, что версия попала в production image или развёрнутый сайт. Аудит относится к frontend lockfile, а не ко всему репозиторию или production runtime. Подробности и условные advisory — в [отчёте по frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). |
| Default-branch dependency alerts | На 29 сентября GitHub API подтвердил 145 открытых Dependabot alert records на `main`: 5 critical, 64 high, 63 moderate, 13 low. PR branch содержит Next.js `15.5.26` и Handlebars `4.7.9`; оба полного frontend `npm audit` завершились с 0 findings. | Alerts останутся открыты на `main` до merge и повторного сканирования; 140 high/moderate/low alerts и backend/Android dependency inventory отдельно не triaged. Это не доказывает состояние deployed images. |

## Снимок PR и браузера — 29 сентября 2026

PR #19 остаётся draft; latest source-code change — `9e3e979`; последующие `70f9367` и `74fd1cb` — doc-only commits. Исходники на `9e3e979` проверены: полный frontend Jest — **63 suites / 402 tests**, type-check и targeted ESLint прошли, production build завершил exit 0 и сгенерировал 30 маршрутов. На source head `9e3e979` Frontend, lint/security/RLS и production-image checks прошли; Backend `Tests` и Android smoke на последнем poll ещё выполнялись. На docs head `74fd1cb` Frontend/guard/Android checks были queued; deploy skipped. Backend-test job на docs-only head не запускался. Поэтому PR CI полностью зелёным не считается.

Read-only браузерный срез `3012` показал API-fed каталог из 19 записей (14 online/busy, 5 offline); stream, script, reboot и DELETE не запускались. Старый runtime `18080` показал мониторинговые CPU/RAM/network и Worker/Edge значения, которые текущий backend source не публикует; на странице устройств DOM отображал выбранными все 19 строк, поэтому Delete не нажимался. Точный frontend/backend SHA этих runtime не установлен. Подробное доказательство и ограничения — в [аудите веб-операций](../audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md).

Source-only fixes в этой серии не раскатаны: `3012`, `18080`, Cloudflare/Tuna, production backend и Android-парк не обновлялись. Видимый в PR код не должен выдаваться за live-результат до синхронной сборки frontend/backend с известными revision stamp и отдельной приёмки на безопасном test scope.

Подробные основания: [Android release-readiness](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md), [Tuna remote-stream canary, включая обновление 28 сентября](../audits/2026-09-27/TUNA-REMOTE-STREAM-CANARY.md), [truthful monitoring AUD-152](../audits/2026-09-28/INFRASTRUCTURE-MONITORING-TRUTHFUL-TELEMETRY.md), [старые удалённые connection/OTA gates](../audits/2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md). Версии из отчётов 25–27 сентября относятся только к указанным в них снимкам.

## Что APK реально умеет сообщить

| Сигнал | Реализованное поведение в исходниках | Граница наблюдаемости |
| --- | --- | --- |
| Идентичность и версия | Агент отправляет device identity и `agent_version`/`agent_version_code`; регистрация и clone rebind — отдельные шаги. | Version code не равен SHA-256 установленного APK и сам по себе не доказывает уникальность клона. |
| Связь/presence | Management WebSocket, ping/pong, reconnect, сохранённые маршруты и recovery state. Backend/UI различают факт принятого соединения и heartbeat/pong. | `online`/сокет не означает, что video frames дошли до браузера или команда успешно завершилась. Для точной диагностики нужны device + session + timestamps и receipts. |
| Видео | APK измеряет локальные capture/render/encode и очередь отправки; backend и viewer имеют отдельные диагностические счётчики. Кадры создаются при callback захвата экрана; неизменившийся экран не обязан повторно слать тот же кадр. | APK queue-accepted не подтверждает backend ingress. Android counters не являются browser FPS. Старый кадр в UI не доказывает текущую связь. Для приёмки нужен контролируемый движущийся экран и корреляция до browser decode/presentation. |
| Файловые логи | Timber logs пишутся асинхронно в app-private storage: кольцевая ротация до пяти файлов по 2 MiB; очередь ограничена 4096 записями; чтение хвоста до 256 KiB. Переполнение очереди отбрасывает новые записи. Ошибки записи выводятся в `System.err`. | Это ограниченный локальный буфер, не постоянный полный event journal. При нехватке места или переполнении часть логов может потеряться. |
| WebSocket lifecycle | Отдельный sidecar ограничен 64 KiB и при ротации оставляет около 32 KiB; uploader берёт до 32 KiB приоритетных lifecycle-записей. | Это диагностические события о lifecycle, не packet capture и не полная трасса каждого сообщения. |
| Android logcat | `LogcatCollector` просит до 5000 строк и удерживает не более 2 MiB; режим `full` запускает unfiltered `logcat` через `ProcessBuilder`, без `su`. | `READ_LOGS` — signature/privileged permission. APK не обещает видеть чужие app logs, системные crash buffers, kernel/native tombstones, LMK и полный ANR-след. Root в эмуляторе не меняет UID этого конкретного collector. |
| Crash | `CrashHandler` сохраняет необработанные Java/Kotlin исключения в app-private файл и обрезает старую часть, когда файл превышает 256 KiB. Log worker может передать до 128 KiB снимка при следующей успешной загрузке и удалить его только если он не изменился во время передачи. | Нельзя гарантировать файл при native `SIGABRT`/`SIGSEGV`, убийстве ядром/LMK, power loss или сбое диска. Их нужно сверять с baseline системного crash buffer или отдельным разрешённым collector. |
| Доставка диагностики | `LogUploadWorker` ставит периодическую работу раз в 15 минут с условием наличия сети и exponential backoff; разовая диагностика имеет случайный сдвиг до 2 минут. В upload включаются до 32 KiB обычных файловых логов, до 300 Sphere logcat строк, lifecycle tail и crash snapshot; общий request ограничен 480 KiB. | WorkManager расписание — best-effort и может задержаться из-за Doze, условий сети, OEM политики или процесса. Это не потоковая телеметрия и не гарантия немедленной доставки. Успех upload подтверждает HTTP ответ, но не полноту всех системных логов. |

### Серверное хранение логов и capacity risk

Backend принимает `POST /api/v1/logs/upload` до 512 KiB, проверяет device API key и пишет дневные файлы по device. Код задаёт дневной file rollover при превышении 50 MiB; файлы старше 30 дней удаляются **только во время следующей загрузки этого же устройства**. Путь по умолчанию — `/tmp/sphere_device_logs`; production должен задать `SPHERE_LOGS_DIR` и обеспечить нужный persistent volume. GET по устройству доступен с `device:read` и по умолчанию читает до трёх последних дневных файлов.

Это не общий disk quota: отдельного per-device/global budget и независимой ежедневной retention-задачи код не задаёт. Грубая оценка при полном использовании дневного cap — порядка 1.5 GiB на устройство за 30 дней (без filesystem overhead; отдельный дневной файл может немного превысить порог на один upload). Это расчётный worst case, не измеренное потребление. Перед ростом fleet требуется persistent-volume capacity, свободное место alerts, глобальная/per-device quota, гарантированный sweeper и политика безопасной деградации при заполнении. См. [`backend/api/v1/logs/router.py`](../../backend/api/v1/logs/router.py) и [stream/logging audit](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md).

Исходники: [`FileLoggingTree.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt), [`LogcatCollector.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/LogcatCollector.kt), [`CrashHandler.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/CrashHandler.kt), [`LogUploadWorker.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/LogUploadWorker.kt), [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt), [`CommandDispatcher.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt), [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt), [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt).

### Вывод об отладке

APK уже даёт полезную удалённую диагностику Sphere, включая версии, состояние управления, ограниченные application logs, некоторые crash records и локальные этапы видеоконвейера. Этого хватает, чтобы локализовать часть отказов при хорошем временном/device/session correlation. Это **не «видим всё на устройстве»**: нет гарантированной полной системной телеметрии, записи каждого кадра, native tombstone, packet capture или точного browser FPS без viewer-side данных. Важный следующий разрыв — связать единым trace/correlation ID APK → backend worker/ingress → Redis/broker → viewer receive/decode/render и хранить результат с определённым retention/quota.

## Выполнение скриптов и автономность

### Что уже умеет код

Серверное orchestration API хранит pipeline и конкретные PipelineRun; шаг
`execute_script` может создать device task. APK принимает `EXECUTE_DAG` по
management WebSocket и исполняет сценарий внутри Android. В текущем runner есть:

- Ввод и время: `tap`, `swipe`, `type_text`, `sleep`, `key_event`, `long_press`,
  `double_tap`, `scroll`, `scroll_to`.
- Экран и UI: `screenshot`, `find_element`, `find_first_element`,
  `tap_first_visible`, `wait_for_element_gone`, `tap_element`, `get_element_text`,
  `input_clear`, `launch_app`, `stop_app`, `get_device_info`.
- Поток и значения: `condition`, `assert`, `set_variable`, `get_variable`,
  `increment_variable`, `loop`, `start`, `end`.
- Сеть/система: `http_request`, `open_url`, `clear_app_data`, `shell`, `lua`.

`condition` ограничен проверками `element_exists`, `text_contains`,
`battery_above`; `assert` — проверками элемента, текста, переменной и HTTP status.
Эти predicate-наборы описаны в [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt); это не произвольный набор библиотек или вызовов ОС. Backend orchestration также содержит `execute_script`, `condition`, `action`, `delay`, `wait_for_event`, `parallel`, `loop`, `sub_pipeline` и `n8n_workflow` handlers.

На APK-стороне есть защитные пределы: до 500 DAG nodes, вложенность выполнения
до 10, максимум 500 routing hops, timeout DAG по умолчанию 300 секунд и node
timeout по умолчанию 30 секунд; вывод node log и loop logs также ограничен.
Lua sandbox удаляет `os`, `io`, `require`, `dofile`, `load`, `debug`, `package`,
`luajava` и raw/metatable escape-функции. Встроенные Lua bindings дают ограниченный
доступ к tap/swipe/type/key, sleep/log/screenshot, UI-element helpers и запуску/
остановке приложения. Это исполняемая автоматизация с результатами/прогрессом,
а не произвольный внешний Python/ADB runtime.

**Открытый Lua-риск из source review:** `executeWithTimeout` использует coroutine `withTimeout`, тогда как LuaJ `chunk.call()` синхронный. В просмотренном коде нет Lua instruction budget или preemption hook. Поэтому 30-секундный coroutine timeout сам по себе не доказывает остановку CPU-bound/infinite Lua loop; такой payload может занять interpreter thread дольше ожидаемого. Пока нет жёсткого лимита инструкций и регрессии на cancellation, на удалённых устройствах запускать только доверенный, review-нутый Lua. См. [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt) и [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt).

### Важные ограничения

- «Автономно» означает: сохранённый pipeline/task может быть запущен расписанием/событием на сервере, доставлен подключённому Android-агенту и выполнен без открытого UI оператора; затем нужно сверить terminal task/pipeline receipt. Это не означает выполнение APK произвольного задания, пока устройство offline, приложение force-stopped или ОС не разрешает нужную операцию.
- После потери связи получение команды и доставка результата имеют отдельные состояния. Не считать `queued`, `sent`, локальный ACK или зелёный progress окончательным успехом. Для каждого canary сверять серверный terminal receipt; `unknown`/timeout требует reconciliation, а не слепого повтора.
- DAG `shell`/`SHELL` вызывает `su -c` и имеет root-эффект; оболочка фильтрует ряд shell metacharacters и ограничивает один вызов пятью секундами, но это всё равно привилегированная удалённая команда. Не направлять непроверенные пользовательские тексты в shell. До массового запуска требуются tenant/RBAC, audit actor, allowlist сценариев, review payload и rollback/stop procedure.
- Один Android device исполняет один DAG одновременно; в backend параллельный `execute_script` для одного device не поддерживается. Pipeline `parallel` нельзя трактовать как безопасный способ параллельно послать конкурирующие скрипты одному устройству.
- Lua sandbox и лимит размера DAG не являются доказательством безопасности/детерминизма всего сценария: действия зависят от root, permission, версии игры, состояния экрана, сети и OEM/Android. Скрипт может менять устройство; тестировать сначала на изолированном canary.
- Интеллектуальный агент, LLM/motor policy, самогенерация безопасного сценария и автоматический выбор игрового аккаунта не входят в подтверждённые возможности данного APK/PR.

Итак: можно выдать заранее определённое, ограниченное задание и позволить серверу оркестрировать его, а APK выполнить device actions после получения. Нельзя на текущем подтверждении обещать «любые скрипты» или полностью автономную работу при любых состояниях сети и Android.

## Android platform guarantees и разрешения

Текущая конфигурация Android: `minSdk 26`, `targetSdk 35`, `compileSdk 35`. Долгоживущий management agent объявлен как foreground service типа `specialUse`; screen capture отделён в `mediaProjection`; фоновые recovery/log jobs используют WorkManager/dataSync. Разрешения и декларации в manifest — не доказательство, что OEM, пользовательские настройки или конкретная Android версия разрешат бесшумный старт во всех случаях.

Android 14+ требует пользовательское согласие для каждого нового MediaProjection capture session и запрещает повторно использовать один projection token. Android 15 для target 35 вводит 6-часовой в 24 часа лимит для `dataSync` foreground services и ограничивает их запуск из `BOOT_COMPLETED`; это отдельно важно для фоновых рабочих задач. В проекте основной management service имеет другой тип, `specialUse`, но WorkManager/boot paths и screen capture должны валидироваться на реальных API/OEM профилях. У WorkManager точное время запуска не гарантируется.

Источники платформы (первичные, сверены 28 сентября 2026):

- [Android 14: MediaProjection consent per session](https://developer.android.com/about/versions/14/behavior-changes-14)
- [Android 15: target 35 behavior changes and FGS limits](https://developer.android.com/about/versions/15/behavior-changes-15)
- [Android 15: foreground-service type restrictions](https://developer.android.com/about/versions/15/changes/foreground-service-types)
- [WorkManager persistent work and retry semantics](https://developer.android.com/develop/background-work/background-tasks/persistent)
- [WorkManager timing depends on constraints/system optimization](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work)
- [Android `READ_LOGS` permission level](https://developer.android.com/reference/android/Manifest.permission#READ_LOGS)

## Следующий приёмочный этап: 20–30 устройств, видео + сценарии

Это **планируемый gate**, тест в рамках этого документа не запускался. Сохранить выбранные оператором 14 стабильных устройств как read-only comparison baseline; сначала завести отдельный canary cohort и зафиксировать устройства/версии до любых команд.

| Шаг | Доказательство на выходе | Условие перехода |
| --- | --- | --- |
| 0. Заморозить build | Build provenance: source SHA, flavor/package ID, `versionCode`, signer, SHA-256, bootstrap/discovery config fingerprint без секретов. | Артефакт и server OTA entry проверены отдельно; если OTA не опубликована — явно использовать ручной canary и не называть это OTA. |
| 1. Сверить идентичность | Для каждого тестового Android — уникальный server device ID, org, последняя версия, boot/session epoch; клоны не должны делить действующие credentials/ID. | Число уникальных свежих устройств соответствует размеру тестовой ступени; duplicate IDs и stale records разобраны, а не переименованы вручную. |
| 2. Одно устройство | Свежий heartbeat; определить фактический маршрут; запустить контролируемое движение экрана; сопоставить Android capture/encode/queue, backend ingress/bridge, viewer receive/decode/present; записать command/session IDs и время. | Видимый кадр принадлежит той же сессии и есть stage-by-stage counter deltas. Статичный idle интервал проверяется отдельно и не требует повторной отправки идентичного кадра. |
| 3. Безопасный DAG на canary | Один заранее reviewed idempotent сценарий, например `get_device_info` + screenshot + проверка результата; связать pipeline run → task/command ID → APK progress/terminal receipt → серверный receipt. | Все receipts терминальны и согласованы. Потеря ACK проверяется reconciliation; нет слепого повтора root/игрового действия. |
| 4. Ступени 14 → 20 → 30 | На каждой ступени сохраняются уникальные устройства, heartbeat-age distribution, reconnect counts, stream session counts, кадры по стадиям, браузерные FPS/age/latency, task receipts, CPU/RAM/network/Redis/DB и crash/ANR delta. | Переход разрешён только если ступень полностью собрана, контрольные данные актуальны, ресурсы не ухудшаются сверх заранее утверждённых SLO, нет новых crash/ANR и нет необъяснённых offline/unknown receipts. |
| 5. Отказ и восстановление на canary | Поочерёдные тесты потери WAN/device-side и backend-side, затем восстановление; один короткий управляемый reconnect. | Тот же device identity возвращается, сессии/receipts корректно reconciled, кадр снова доходит до viewer, duplicate command effects не появляется. Не вводить несколько fault одновременно на первом прогоне. |

Измеряемые SLO/stop thresholds следует согласовать и зафиксировать **до** запуска: задержку first frame, frame age/FPS на движущемся экране, heartbeat freshness, reconnect budget, command terminal receipt latency, crash delta и host capacity. Старый проектный документ нагрузочных метрик содержит синтетические и не привязанные к текущему профилю цифры; не переносить их как production SLO без пересчёта и утверждения. Использовать [Fleet32 readiness/evidence gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md), [метод stream observability](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) и [операционный runbook](READINESS.md).

Ступень немедленно остановить при новом Sphere crash/ANR, смене PID без запланированного рестарта, повторяющихся identity collision, потерянном/противоречивом receipt, отсутствии stage correlation, деградации baseline либо неконтролируемом root effect. Сырые логи, токены и signing material держать вне Git; в отчет включать очищенные выдержки и ссылки на приватный evidence.

## Проверки PR #19

На `5c9e56c` GitHub Actions завершил успешно backend real-service regression tests, production-image/bootstrap, lint (`ruff` + `mypy`), security (`bandit` + `pip-audit`), RLS coverage, Alembic single-head, Android build/unit tests и frontend tests/types/build. Последний check завершился в 00:46:11 UTC 28 сентября 2026; Preview deploy job **skipped**. Frontend job подтвердил Linux `npm ci`, tests/types/build и standalone entrypoint. Это подтверждает source CI на указанном SHA, но не production deployment. Локальная Windows-сборка и предупреждение Next standalone tracing, npm audit и остальные границы описаны в [отчёте по безопасности frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). Статусы новых коммитов смотрите по актуальной вкладке Checks в [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

Для навигации и истории см. [CHANGELOG](../../CHANGELOG.md), [readiness](READINESS.md), [локальный pilot](LOCAL-PILOT.md), [Android guide](../android-agent.md) и [правила поддержания документации](../DOCUMENTATION.md).
