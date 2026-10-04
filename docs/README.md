<div align="center">

# 📚 Документация Sphere

**От первого подключения до воспроизводимого разбора отказа.**

[Главная](../README.md) · [Готовность](operations/READINESS.md) · [Открытые работы](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [Помощь](../SUPPORT.md)

</div>

> [!NOTE]
> **Срез навигации: 5 октября 2026.** Канонические source/runtime факты,
> версии Android, ограничения диагностики и будущий этап 20–30 устройств собраны
> в [актуальном состоянии](operations/CURRENT-STATE.md). Каталог не выполняет
> автоматическую проверку runtime; старые аудиты сохраняют собственные даты и
> версии и не должны читаться как текущий deploy. [Правила актуальности](DOCUMENTATION.md).

**Последняя проверка: 4 октября 2026, после перезагрузки ПК и установки в 17:14 UTC.
API/UI c1a6e79.** [Аудит диска, ОЗУ, сборки и RPC](audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md) ·
[Эксплуатационная процедура](operations/HOST-RESOURCES.md).

**5 октября — текущая работа с ресурсами:**
[ETW writer / exact VSS / 51 owned image / 10,938 GiB guest reclaim](audits/2026-10-05/DISK-WRITER-ATTRIBUTION.md) ·
[APK logger source fix / 1680 passed, 2 skipped / installed canary OPEN](audits/2026-10-05/APK-LOG-RETENTION.md).
Source recorder `1402612` / projection `9a9256f`, 8 Windows tests; API/UI c1a6e79,
Android10244 сохранены. AdGuard update объясняет отдельный короткий скачок,
но полная историческая атрибуция, VHD compaction и RAM soak ещё открыты.
[Предыдущие объёмные срезы](audits/2026-10-05/HOST-DISK-GROWTH.md) сохранены как история.

**22:52 UTC follow-up:** [VSS+1,969GiB /net free−2,033GiB, shadow inventory и retention review](audits/2026-10-05/VSS-RETENTION-REVIEW.md).
Read-only image planner14 tests /actual0 additional candidates. После одобрения
22:58 UTC VSS quota8GiB применена, обе system copies удалены Windows;
free C:+17,205GiB. Runtime/46 containers сохранены, VHD не сжат.

**Дополнительная инвентаризация, 17:50 UTC:** [размер Sphere / обход C: / package cleanup](audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP.md).
Workspace 8 GiB, tracked files 22 MiB; shared Docker VHD 219 GiB отдельно.
На C: free 41,43 GiB после дополнительной очистки; 46 контейнеров сохранены,
14 online10244. [Sanitized receipts](audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP-EVIDENCE.json).

В образах прошли 113 наборов / 1122 frontend-теста и 186 API-проверок; отдельно
18 проверок допуска сборки. Все четыре source CI прошли. Исправлены повторные
слои зависимостей; выполнена адресная очистка. Сжатие VHD и длительная утечка ОЗУ
ещё не приняты. Remote 504 сохранён рядом с отдельным успешным PNG 200;
первое окно связи FAILED: 11→14, последующее сохранило 14 online / даты подключений.
APK 10244, Tuna и OTA сохранены. Исходный реестр: 34 исправлено / 7 незакрытых;
визуальная приёмка, FPS/задержка, длительная нагрузка и Fleet32 admission открыты.

**Исторический follow-up: 4 октября 2026, 10:06 UTC+5. API/UI9716348**, APK 10244 unchanged.
[Native PNG, управление и manual Android profile](audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).
1117 frontend / 140 API cases в образах, schema178/140. PH025/PH010 original PNG accepted;
Android/server/file hashes matched. 14online в конечном UI readback; первый remote504
и seven code1005 disconnects сохранены. Human native download/keyboard, UA2/nonroot,
full visual/latency/load/soak OPEN; original ledger34/7 не изменён.

Историческая runtime-проверка этапа XPath — **4 октября 2026, 05:55 UTC+5**:
[F35 XPath: контракт и live Android](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md) ·
[Evidence](audits/2026-10-04/UI-HIERARCHY-INSPECTOR-EVIDENCE.json).
API **9274e50** / UI **84750e3** на 3015; 110 suites / 1043 frontend и 108 API cases
в образах. Вход в инспектор загружает дерево; выбор, атрибуты, подсветка и активное
автообновление покрыты 8 pointer workflow tests. PH010 45 / PH025 49 реальных узлов.
После UI rollout 14 online APK 10244 и прежние даты соединений во всех 7 срезах;
API/Tuna/OTA и 15 соседей сохранены. Предыдущее API окно FAILED 14→13/PH015
не скрыто. **34 source-fixed / 7 незакрытых, включая 3 PARTIAL**; browser/soak OPEN.

Предыдущая runtime-проверка — **4 октября 2026, 02:04 UTC+5**:
[F39: формы групп и локаций](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS.md) ·
[Evidence](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS-EVIDENCE.json).
API **37bb436** / UI **922f479** на 3015; 1013 frontend / 89 API проверок в образах.
14 online APK 10244, даты соединений сохранены. Остальные формы и визуальная приёмка OPEN.
Предыдущие [registry permissions](audits/2026-10-04/DEVICE-ACTION-PERMISSIONS.md) и
[N10 rollout](audits/2026-10-04/VIEWER-AUTHORIZATION.md) сохранены как датированная история.
[JPEG Matrix план](audits/2026-10-04/MATRIX-PREVIEW-PLAN.md) ещё не реализован.

Предыдущая проверка видео — **3 октября, 15:53 UTC**:
[H.264 recovery и измеренная доставка](audits/2026-10-03/STREAM-REFERENCE-RECOVERY.md).
Для прежнего API 37415e3 / UI 77fca37 на PH025/PH010 получено по 599 кадров за
20 с — 29,95 кадра/с до получателя. Отрисовка браузера и задержка ввода ещё не приняты.
Прошли 230 WebSocket-тестов и 41 PostgreSQL/Redis case, все 271 — в собранном образе.

[Native OTA 44](audits/2026-10-03/OTA-SIGNER-COMPATIBILITY.md) ·
[ABR proof](audits/2026-10-03/STREAM-BITRATE-RECOVERY.md) ·
[OTA contract](operations/OTA-PUBLICATION-AND-APK-CHECKS.md).
Normal/dev 10209; stable/manifest/bulk/visual/soak/F36 OPEN. Исходный аудит: 33/8.


## 🧭 Выберите задачу

| Мне нужно | Начать здесь | Дальше |
| --- | --- | --- |
| Проверить полный веб-аудит и текущие исправления | [Аудит всех маршрутов, меню и возможностей API — 1 октября](audits/2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md) | [Журнал исправлений F01–F41](audits/2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Fixes: актуальные tests / installed UI](audits/2026-10-01/WEB-AUDIT-FIXES-VALIDATION.json) · [Frozen audit evidence](audits/2026-10-01/WEB-FULL-CAPABILITY-AUDIT-EVIDENCE.json) · [Проверки документа](audits/2026-10-01/AUDIT-VALIDATION.json) |
| Выбрать UI-элемент рядом с видео устройства | [XPath-инспектор](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md) | Actual root APK/tree, limits, errors и [evidence](audits/2026-10-04/UI-HIERARCHY-INSPECTOR-EVIDENCE.json); nonroot/visual gate OPEN |
| Создать площадку, задать координаты или изменить иерархию | [Контракт локаций](operations/LOCATION-HIERARCHY.md) | [F26 proof](audits/2026-10-03/LOCATION-HIERARCHY.md) · [Receipts](audits/2026-10-03/LOCATION-HIERARCHY-EVIDENCE.json) |
| Просмотреть/изменить pipeline и допуск запусков | [Определения pipeline](operations/PIPELINE-DEFINITIONS.md) | [F28 proof](audits/2026-10-03/PIPELINE-DEFINITION-WORKFLOW.md) · [Receipts](audits/2026-10-03/PIPELINE-DEFINITION-WORKFLOW-EVIDENCE.json) |
| Просмотреть DAG версии, откатить сценарий или открыть архив | [Версии сценариев](operations/SCRIPT-VERSIONS.md) | [F27 proof](audits/2026-10-02/SCRIPT-VERSION-WORKFLOW.md) · [Receipts](audits/2026-10-02/SCRIPT-VERSION-WORKFLOW-EVIDENCE.json) |
| Опубликовать OTA и проверить package/signature перед install | [Publication/APK contract](operations/OTA-PUBLICATION-AND-APK-CHECKS.md) | [1.2.41 proof](audits/2026-10-03/OTA-RELEASE-IDENTITY.md) · [JSON receipts](audits/2026-10-03/OTA-RELEASE-IDENTITY-EVIDENCE.json) |
| Обновить одно Android-устройство и проверить receipt/heartbeat | [Адресное OTA](operations/OTA-ADDRESSED-UPDATES.md) | [F33 remote proof](audits/2026-10-02/OTA-ADDRESSED-DELIVERY.md) · [Evidence JSON](audits/2026-10-02/OTA-ADDRESSED-DELIVERY-EVIDENCE.json) |
| Найти audit событие за первой страницей и выгрузить CSV | [F37: source/installed evidence](audits/2026-10-02/AUDIT-INVESTIGATION.md) | [Контракт и лимит5000](operations/AUDIT-INVESTIGATION.md) · [JSON receipts](audits/2026-10-02/AUDIT-INVESTIGATION-EVIDENCE.json) |
| Проверить форму пользователя, смену роли и отключение | [F38: source/installed evidence](audits/2026-10-02/USER-ACCESS.md) | [Операторский контракт](operations/USER-ACCESS.md) · [JSON receipts](audits/2026-10-02/USER-ACCESS-EVIDENCE.json) |
| Проверить иерархию групп и сохранность audit отказов | [N04/N05: исправление и live readback](audits/2026-10-02/GROUP-HIERARCHY-AND-AUDIT.md) | [Evidence](audits/2026-10-02/GROUP-HIERARCHY-AND-AUDIT-EVIDENCE.json) · [Контракт иерархии](operations/GROUP-HIERARCHY.md) |
| Проверить discovery request/response и принадлежность результата | [F19/F20 + N02 — 2 октября](audits/2026-10-02/DISCOVERY-REQUEST-OWNERSHIP.md) | [Before/after/installed evidence](audits/2026-10-02/DISCOVERY-REQUEST-OWNERSHIP-EVIDENCE.json) · legacy errors N03 OPEN |
| Проверить восстановление веба и реальный rerun Android | [Docker review / remote PH025 — 2 октября](audits/2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md) | [Runtime + Android receipts](audits/2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN-EVIDENCE.json) · browser visual OPEN |
| Проверить снимки задания и повтор исходной версии | [Task artifacts / rerun — 2 октября](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN.md) | [Installed API/UI evidence](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN-EVIDENCE.json) · Android upload N01 открыт |
| Проверить страницы оркестрации и выбор цели расписания | [Каталоги без ограничения первой страницей — 2 октября](audits/2026-10-02/ORCHESTRATION-CATALOG-PAGING.md) | [F13 / текущая установка](audits/2026-10-01/WEB-AUDIT-REMEDIATION.md) |
| Сверить новый cross-layer audit, установленный APK10240 и API/UI | [Callbacks / runtime / OTA canary — 1 октября](audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY.md) | [Web ownership](audits/2026-10-01/STREAM-DIAGNOSTIC-OWNERSHIP.md) · [Pipeline terminal heartbeat](audits/2026-10-01/PIPELINE-TERMINAL-HEARTBEAT.md) · [Codec lifecycle](audits/2026-10-01/ENCODER-CALLBACK-OWNERSHIP.md) · [JSON evidence](audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY-EVIDENCE.json) |
| Узнать актуальные версии, что APK может диагностировать/исполнять и что реально подтверждено | [Текущее состояние](operations/CURRENT-STATE.md) | [Readiness](operations/READINESS.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19) |
| Сверить версию и OTA перед pilot install | [Текущее состояние](operations/CURRENT-STATE.md) | [Local pilot ledger](operations/LOCAL-PILOT.md) · [Приёмка первого устройства](operations/PILOT-ACCEPTANCE.md) |
| Поднять новую установку | [Startup / bootstrap](operations/STARTUP.md#first-install) | [Configuration](configuration.md) · [Deployment](deployment.md) |
| Подключить удалённые Android | [Remote pilot](operations/REMOTE-PILOT.md) | [Signed discovery](architecture/ANDROID-SIGNED-DISCOVERY.md) |
| Понять оставшиеся проблемы | [Текущее состояние и границы доказательств](operations/CURRENT-STATE.md) | [Fleet32](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [A/B ingress](audits/2026-09-24/REMOTE-INGRESS-AB.md) · [Readiness](operations/READINESS.md) · [Roadmap](../ROADMAP.md) |
| Проверить полноту веб-панели, источники метрик и расхождение preview с checkout | [Web operations / observability audit — 29 сентября](audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md) | Подтверждённые пробелы, риски масштаба 500–1000 устройств и очерёдность следующей работы |
| Подключить серверную историю и Grafana прямо в веб | [Prometheus / Grafana](operations/OBSERVABILITY.md) | Docker-стек, права доступа, лицензии, retention и границы multi-worker метрик |
| Сверить, какая сборка frontend и backend реально открыта | [Build provenance в интерфейсе](operations/BUILD-PROVENANCE.md) | SHA веб-сборки в шапке, SHA API из runtime endpoint и честные состояния unknown/unavailable |
| Проверить профиль, MFA и API-ключи | [Настройки аккаунта — 30 сентября](audits/2026-09-30/WEB-SETTINGS-ACCOUNT-SECURITY.md) | Контракты API, реальные даты/статусы, подтверждения и отказные сценарии |
| Проверить читаемость реестра и источники сигнала | [Fleet Matrix — 30 сентября](audits/2026-09-30/WEB-FLEET-READABILITY.md) | Отдельная версия APK, heartbeat/контакт, реальные даты и доступные колонки |
| Открыть диагностику конкретного устройства, его задачи, события и логи | [Карточка и инспектор — 30 сентября](audits/2026-09-30/WEB-DEVICE-INSPECTOR.md) | Источники API, отказные сценарии, PNG из фактического кадра, границы Android команд |
| Проверить пагинацию и значения статусов в Fleet Matrix | [Контракт реестра устройств](operations/DEVICE-CATALOG.md) | Scope/status counts, Redis live presence, поведение при недоступности Redis и пределы текущего масштаба |
| Проверить frontend dependency advisories и статус исправлений в PR #19 | [Frontend dependency security report](audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md) | [Текущее состояние](operations/CURRENT-STATE.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19) |
| Проверить подпись, release APK, CI, OTA и доказательства Android-кандидата | [Android release-readiness audit](audits/2026-09-28/ANDROID-RELEASE-READINESS.md) | [Android agent guide](android-agent.md) · [Текущее состояние](operations/CURRENT-STATE.md) |
| Разделить graphics input, захват и AVC encode на Android | [Codec input canary](operations/CODEC-INPUT-CANARY.md) | [Synthetic control](audits/2026-10-01/PH010-CODEC-INPUT-EVIDENCE.json) · [Real capture, OTA и независимый decode](audits/2026-10-01/PH010-PH025-PLANAR-CAPTURE-EVIDENCE.json) · [Video cadence](operations/VIDEO-CADENCE-CANARY.md) |
| Разобрать чёрный экран стрима по стадиям | [Android stream observability](audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) | APK capture/encode/queue · browser decode/render · ограничения доказательств |
| Проверить APK limits, grid/detail видео и визуальную XPath-инспекцию | [Android inspection / video modes — 30 сентября](audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md) | Source findings, готовые engines и лицензии, Android-only архитектура, следующий canary/mass-test plan |
| Разобрать offline после clone/re-enrollment | [AUD-172 — enrollment HTTP 401](audits/2026-09-25/CLONED-ENROLLMENT-401.md) | Reject в `/devices/register`, shared bootstrap file и границы подтверждённой причины |
| Разобрать ложный Online сразу после подключения | [AUD-173 — presence до первого heartbeat](audits/2026-09-25/DEVICE-PRESENCE-FIRST-HEARTBEAT.md) | `connecting` → первый pong → `online`, тесты и rollout gate |
| Разобрать live-стрим без новых кадров | [AUD-175 — stale frame при живом WebSocket](audits/2026-09-25/FLEET-STREAM-STALE-FRAME.md) | Отдельный таймер декодированного кадра, keyframe recovery и границы доказательств |
| Проверить, что локальные APK и логи не входят в Docker build context | [AUD-174 — private artifacts и Docker context](audits/2026-09-25/DOCKER-CONTEXT-PRIVATE-ARTIFACTS.md) | Реальный BuildKit `COPY` probe и CI gate для корневого context |
| Проверить адресный APK OTA и результат установки | [AUD-171 — terminal receipts](audits/2026-09-25/OTA-TERMINAL-RECEIPTS.md) | Receipt commit/ACK, повтор после потери ACK, tenant scope и текущий canary gate |
| Разобрать сбой по времени и устройству | [Support: что собрать](../SUPPORT.md) | [Runbooks](runbooks/README.md) · [Fleet operations, stream и observability](architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) |
| Изменить код | [Contributing](../CONTRIBUTING.md) | [Development](development.md) · [Тесты](../tests/production/README.md) |

## 🚀 Запуск и эксплуатация

| Руководство | Что внутри |
| --- | --- |
| [Навигация Android в видеопотоке](operations/ANDROID-NAVIGATION.md) | Back/Home/Recents/Menu, root/RBAC, подтверждённый результат, unknown без автоповтора и remote Back proof |
| [Управление статичным экраном](operations/STATIC-STREAM-INPUT.md) | Single-device tap/swipe по кадру текущего socket, first-frame/reconnect/error gates и отдельная свежесть PNG |
| [Startup](operations/STARTUP.md) | Первый запуск, повторный старт, env precedence и значение readiness |
| [Local pilot](operations/LOCAL-PILOT.md) | Установленные версии, веб, APK, учётная запись и отдельный Compose project |
| [Remote pilot](operations/REMOTE-PILOT.md) | Устройства в другой сети, ingress и ограничения резервирования |
| [Удалённое видео и OTA](audits/2026-09-24/REMOTE-VIDEO-OTA-DECISION.md) | AUD-163: публичный tunnel против Android first-frame, что реально опубликовано и почему общий OTA rollout пока остановлен |
| [Отказоустойчивая OTA-архитектура](architecture/ANDROID-OTA-RELIABILITY.md) | Слои bootstrap/control/artifact/install, подтверждённый canary, быстрые проверки, резервные origins, receipts и Fleet32 gates |
| [A/B ingress и три remote VM](audits/2026-09-24/REMOTE-INGRESS-AB.md) | AUD-164: локальный/альтернативный viewer, SPS/PPS без IDR на удалённом агенте, reconnect rate и гейт для проверки Cloudflare |
| [Android stream observability](audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) | AUD-168: stage counters, protected diagnostics API, viewer decode metrics, crash upload and what remains unproven remotely |
| [Cloned enrollment HTTP 401](audits/2026-09-25/CLONED-ENROLLMENT-401.md) | AUD-172: rejected enrollment credential, identical clone bootstrap and unresolved route/key source |
| [Presence до первого heartbeat](audits/2026-09-25/DEVICE-PRESENCE-FIRST-HEARTBEAT.md) | AUD-173: не считать authenticated socket живым устройством до первого pong; отдельный fleet `connecting` count |
| [OTA terminal receipts](audits/2026-09-25/OTA-TERMINAL-RECEIPTS.md) | AUD-171: persist-before-ACK, bounded replay history, lost-ACK recovery and pilot rollout gate |
| [Deployment](deployment.md) · [Полный guide](../FULL-DEPLOYMENT-GUIDE.md) | Bootstrap, конфигурации и обслуживание; оценки масштаба требуют своей приёмки |
| [Discovery publisher](operations/DISCOVERY-PUBLISHER.md) | Публикация подписанных маршрутов и восстановление publisher |
| [Redis memory](operations/REDIS-MEMORY.md) | Dataset/container budget, persistence, pressure test и остаточные риски |
| [Redis concurrent AOF follow-up](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md) | AUD-143: CI OOM, source budget and pilot rollout boundary |
| [OTA transport retry](audits/2026-09-20/OTA-TRANSPORT-RETRY.md) | AUD-144 / F32-33: bounded retry after interrupted APK body, candidate and remote-acceptance gates |
| [Clone binding v2](audits/2026-09-20/CLONE-BINDING-V2.md) | AUD-145 / F32-34: emulator serial binding, backend-first migration and 32-clone acceptance gate |
| [Golden image and portable clone provisioning](architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md) | Master can be launched and configured; portable identity contract, clone-rebind gates, LDPlayer adapter evidence and cross-emulator acceptance matrix |
| [LDPlayer network recovery](operations/LDPLAYER-NETWORK-RECOVERY.md) | Диагностика сети станции и границы Windows watchdog |
| [Overnight soak](operations/ANDROID-OVERNIGHT-SOAK.md) | Безопасные DAG, receipts, видео, завершение и evidence |
| [Runbooks](runbooks/README.md) | Backend outage, PostgreSQL, fleet offline и VPN incidents |

## 🧩 Компоненты и интерфейсы

| Компонент | Документы |
| --- | --- |
| Общая архитектура | [Обзор](architecture.md) · [Fleet operations / observability](architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) · [Архитектурные решения](adr/README.md) |
| Backend | [Генерируемый API-каталог](api-endpoints.md) · [OpenAPI JSON](openapi.json) · [Обзор API](api-reference.md) |
| Web UI | [Экранные сценарии](web-ui-guide.md) · [Сессии и cache lifecycle](security/frontend-sessions.md) |
| Android | [Agent guide](android-agent.md) · [Протокол соединения](architecture/ANDROID-CONNECTION-PROTOCOL.md) |
| Discovery / recovery | [Подписанный manifest](architecture/ANDROID-SIGNED-DISCOVERY.md) · [Сохранённые маршруты](architecture/ANDROID-SAVED-ROUTES.md) · [Фоновая регистрация](architecture/ANDROID-BACKGROUND-ENROLLMENT.md) |
| APK updates | [Отказоустойчивая OTA](architecture/ANDROID-OTA-RELIABILITY.md) · [Transport retry](audits/2026-09-20/OTA-TRANSPORT-RETRY.md) |
| PC-agent | [Workstation identity, локальные инструменты и подключение](pc-agent.md) |
| PostgreSQL | [RLS / runtime roles](security/postgresql-rls.md) · [Worker RLS](audits/2026-09-20/PIPELINE-RLS.md) |
| Задачи | [Task control protocol](security/task-control-protocol.md) · [Durable cancellation](audits/2026-09-20/DURABLE-CANCELLATION.md) |
| Оркестрация | [Pipeline recovery](audits/2026-09-20/PIPELINE-RECOVERY.md) · [Batch recovery](audits/2026-09-20/BATCH-RECOVERY.md) · [Nested waiting](audits/2026-09-20/PIPELINE-NESTED-WAIT.md) |
| Identity / credentials | [User bootstrap](security/user-auth-bootstrap.md) · [Device bootstrap](security/device-credential-bootstrap.md) · [Device refresh](security/device-refresh-recovery.md) · [Account credentials](security/account-credentials.md) |
| VPN | [Control outcomes](operations/VPN-CONTROL-OUTCOMES.md) · [F32 evidence](audits/2026-10-03/VPN-CONTROL-OUTCOMES.md) · [Реестр ограничений F32-11/12/21](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [VPN intents](audits/2026-09-05/VPN-LEASE-DESIGN.md) · [Runbook](runbooks/02-vpn-incident.md) |

## 🔬 Что подтверждено проверкой

| Последняя контрольная точка | Доказательства и границы |
| --- | --- |
| Согласованный rollout backend/APK 1.2.8 | [Canary 21 сентября](audits/2026-09-20/CANARY-20260921.md): OTA, backup/restore, 15 tasks, два pipeline |
| Frontend `9924eb1` | [AUD-138](audits/2026-09-20/DECODER-RECOVERY.md): decoder bounds/recovery и два живых потока после restart |
| Первый IDR и восстановление | [AUD-140 / F32-29](audits/2026-09-20/STREAM-FIRST-FRAME.md) · [AUD-142 / F32-31](audits/2026-09-20/ANDROID-KEYFRAME-STARTUP.md): browser retry, отложенный Android keyframe до старта encoder, backend forwarding regression; удалённая приёмка ещё OPEN |
| Standalone-сборка frontend | [AUD-141 / F32-30](audits/2026-09-20/FRONTEND-STANDALONE.md): Linux CI build/root-entrypoint passed; отдельный frontend Docker image не проверен; Windows trace warning remains |
| Redis budget | [Текущий бюджет и evidence](operations/REDIS-MEMORY.md): после нового OOM на 2 GiB source ceiling 3 GiB прошёл same-image Desktop и GitHub Linux pressure/restart; installed pilot 1536 MiB и fleet capacity проверяются отдельно. [AUD-143](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md) сохранён как история |
| OTA transfer | [AUD-144 / F32-33](audits/2026-09-20/OTA-TRANSPORT-RETRY.md): local before/after regression and bounded retry; 1.2.10/10210 is historical and was not a published OTA catalog entry |
| Clone binding and reconnect | [AUD-145 / F32-34](audits/2026-09-20/CLONE-BINDING-V2.md) · [AUD-162](audits/2026-09-24/REMOTE-RECONNECT-INCIDENT.md) · [Android-only clone plan](architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md): local 1.2.15 debug candidate contains terminal refresh and duplicate-start recovery; OTA rollout, remote identity and 3-clone acceptance remain open |
| Первый кадр на Android | [AUD-161](audits/2026-09-23/ANDROID-INITIAL-FRAME-RACE.md): воспроизведено отбрасывание раннего ImageReader callback; source fix и 621 тест на flavor прошли, удалённый canary ещё не принят |
| Сетевые отказы | [Native matrix](audits/2026-09-05/NETWORK-RECOVERY-NATIVE.md) · [Reconnect debt](audits/2026-09-05/ANDROID-RECONNECT-DEBT.md) |
| Автозапуск и разрешения | [Boot recovery](audits/2026-09-05/ANDROID-BOOT-RECOVERY.md) · [Root capabilities](audits/2026-09-05/ANDROID-UNATTENDED-CAPABILITIES.md) |
| Несколько viewers | [AUD-126](audits/2026-09-05/STREAM-MULTI-VIEWER.md) · [Критерий новых кадров](audits/2026-09-05/SOAK-VIEWER-MOTION.md) |
| Последний длинный прогон | [FAILED через 3 ч 33 мин](audits/2026-09-05/STREAM-START-DELIVERY.md); восемь часов не приняты |

Полная история: **[Audit report](audits/2026-09-05/AUDIT-REPORT.md)**.
Тестовая база: [PostgreSQL/Redis regressions](../tests/production/README.md) ·
[Container probes](../tests/containers/README.md) · [CI workflows](../.github/workflows/).

## 🛠️ Участие в проекте

[Contributing](../CONTRIBUTING.md) · [Support и диагностические формы](../SUPPORT.md) ·
[Security policy](../SECURITY.md) · [Changelog](../CHANGELOG.md) ·
[Как поддерживать документацию](DOCUMENTATION.md) · [Устройство GitHub-репозитория](../.github/REPOSITORY-GUIDE.md).

## 🗂️ Проекты и исторические материалы

Эти документы полезны для контекста. Они не подтверждают установленную возможность
или достигнутую производительность:

- [AI readiness](architecture/AI-READINESS.md) — будущие observation/action consumers; реализация отложена.
- [Synthetic load architecture](load-test/01-ARCHITECTURE.md) · [сценарии](load-test/02-SCENARIOS.md) · [KPI](load-test/03-METRICS-AND-CRITERIA.md) · [исторический execution report](load-test/04-EXECUTION-REPORT.md).
- [Bootstrap discovery design](architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) · [Discovery recovery design](architecture/ANDROID-DISCOVERY-RECOVERY.md).
- [Предметный анализ автоматизации](ANALYSIS-FARMING-SUMMARY.md) · [подробный анализ](ANALYSIS-FARMING-PLATFORM.md).

Не нашли ответ или нашли противоречие? [Открыть замечание к документации](https://github.com/RootOne1337/sphere-platform/issues/new?template=documentation.yml).
