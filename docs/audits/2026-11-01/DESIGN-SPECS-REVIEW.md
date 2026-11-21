# Проектные материалы и исторические ТЗ: реестр сверки

Срез **1 ноября 2026**: инвентарь на время проверки относил **90 Markdown** к роли
`DESIGN_SPECIFICATION`. Из них 20 путей в `docs/design` (17 основных файлов и
3 файла preview), 66 — в `specs`, 3 — планы `docs/load-test`, 1 —
`docs/architecture/AI-READINESS.md`. [Отчёт load-test](../../load-test/04-EXECUTION-REPORT.md)
классифицирован отдельно как датированное evidence. Значения относятся к прежнему
инвентарю; новое [оглавление design](../../design/README.md) ещё нужно включить
в итоговый инвентарь. Это классификация путей скриптом, а не подтверждение содержания.
Рабочее дерево и HEAD меняются параллельно; это не новый runtime readback.

## Основные материалы `docs/design`

| Путь или группа | Назначение по просмотренным вводным | Граница |
| --- | --- | --- |
| [ANDROID-FILE-MANAGER](../../design/ANDROID-FILE-MANAGER.md) | Предложение проводника и передачи Android-файлов. | Текст помечает проект нереализованным на 15 октября; новая полная проверка исходников не проводилась. |
| [APK-1.3-COMPATIBILITY-AND-RELEASE](../../design/APK-1.3-COMPATIBILITY-AND-RELEASE.md) | План совместимости и release gates, смешанный с исторической поставкой. | Старый APK и конечный canary не подтверждают stable release или актуальные пакеты. |
| [BROWSER-DIRECT-TRANSPORT](../../design/BROWSER-DIRECT-TRANSPORT.md), [DIRECT-RECORDER](../../design/DIRECT-RECORDER.md), [CLIENT-STUDIO-PLATFORM](../../design/CLIENT-STUDIO-PLATFORM.md) | Исследование прямого транспорта и планы записи/Studio, с датированными частичными проверками. | Не все предложенные состояния реализованы или приняты; для отдельного действия нужны source и live evidence. |
| [MOTOR-AI-PLATFORM](../../design/MOTOR-AI-PLATFORM.md), [GAME-CONTROL-PROFILES](../../design/GAME-CONTROL-PROFILES.md) | План моторного клиента и профилей, с экспериментами. | Модели, игровой исполнитель, маршруты и длительная приёмка не выводятся из существования проекта. |
| [ANDROID-CAPTURE-AND-NAVIGATION-EVIDENCE](../../design/ANDROID-CAPTURE-AND-NAVIGATION-EVIDENCE.md), [LIVE-ROUTE-RECONSTRUCTION](../../design/LIVE-ROUTE-RECONSTRUCTION.md), [RECORDED-ROUTE-SPATIAL-MAP](../../design/RECORDED-ROUTE-SPATIAL-MAP.md), [VISUAL-ROUTE-RELOCALIZATION](../../design/VISUAL-ROUTE-RELOCALIZATION.md), [LONG-ROUTE-TEACH-REPEAT](../../design/LONG-ROUTE-TEACH-REPEAT.md) | Исследование захвата, сцен, геометрии и локализации знакомого маршрута. | Рендер или реконструкция не доказывают проходимость; последний файл имел чужие незакоммиченные изменения и не изменялся. |
| [VPN-EGRESS-ARCHITECTURE](../../design/VPN-EGRESS-ARCHITECTURE.md), [VPN-FLEET-CONTROL](../../design/VPN-FLEET-CONTROL.md), [VPN-ALL-EXCEPT-SPHERE](../../design/VPN-ALL-EXCEPT-SPHERE.md), [WG-ROUTER-PROVIDER-INTEGRATION](../../design/WG-ROUTER-PROVIDER-INTEGRATION.md) | Проект провайдеров, каталогов, областей приложений и ограниченные сетевые эксперименты. | Профиль, подготовленный APK, finite canary, применённая конфигурация и приёмка production — разные состояния. |
| [WEB-DESIGN-CONCEPTS](../../design/WEB-DESIGN-CONCEPTS-2026-09-28.md), [preview README](../../design/previews/admincn-sphere-2026-09-28/README.md), [CONCEPTS-RU](../../design/previews/admincn-sphere-2026-09-28/CONCEPTS-RU.md), [notices](../../design/previews/admincn-sphere-2026-09-28/THIRD-PARTY-NOTICES.md) | Визуальное исследование, изолированные демонстрации и атрибуция. | Макет с fixtures не доказывает работу основного приложения; старые localhost preview адреса не проверены как действующие. Лицензирование template следует оценивать по отдельным notices. |

## Группы исходных ТЗ `specs/`

Это исходные требования и проектные сплиты, не текущий тестовый или эксплуатационный
контракт. Подсчёт 66 относится к tracked Markdown на момент проверки; каждую из
66 спецификаций построчно с кодом не сравнивали.

| Группа | Файлов | Тема | Куда сверять реализацию |
| --- | ---: | --- | --- |
| [TZ-00](../../../specs/TZ-00-Constitution/) | 5 | Репозиторий, DB, Redis, secrets, CI | [Startup](../../operations/STARTUP.md), [разработка](../../development.md), workflows |
| [TZ-01](../../../specs/TZ-01-Auth-Service/) | 5 | Auth, MFA, RBAC, ключи, аудит | [Security](../../security.md), [user access](../../operations/USER-ACCESS.md), [audit](../../operations/AUDIT-INVESTIGATION.md) |
| [TZ-02](../../../specs/TZ-02-Device-Registry/) | 5 | Устройства, группы, состояние, bulk, discovery | [Devices](../../operations/DEVICE-STREAM-GUIDE.md), [groups](../../operations/GROUP-HIERARCHY.md) |
| [TZ-03](../../../specs/TZ-03-WebSocket-Layer/) | 5 | Управление соединениями, PubSub, heartbeat | [Android connection](../../architecture/ANDROID-CONNECTION-PROTOCOL.md), [протоколы](../../protocols/) |
| [TZ-04](../../../specs/TZ-04-Script-Engine/) | 5 | DAG, сценарии, очередь, batch, результаты | [Задания и оркестрация](../../operations/TASKS-AND-ORCHESTRATION.md) |
| [TZ-05](../../../specs/TZ-05-H264-Streaming/) | 5 | Захват, codec, транспорт, WebCodecs | [Поток и устройства](../../operations/DEVICE-STREAM-GUIDE.md), [Android](../../android-agent.md) |
| [TZ-06](../../../specs/TZ-06-VPN-AmneziaWG/) | 5 | VPN, конфигурация, пул, recovery, kill switch | [VPN outcomes](../../operations/VPN-CONTROL-OUTCOMES.md), [profiles](../../operations/VPN-PROFILES.md) |
| [TZ-07](../../../specs/TZ-07-Android-Agent/) | 5 | Android агент, WS, команды, Lua, OTA | [Android](../../android-agent.md), [адресное OTA](../../operations/OTA-ADDRESSED-UPDATES.md) |
| [TZ-08](../../../specs/TZ-08-PC-Agent/) | 5 | PC агент, LDPlayer, ADB, топология | [PC agent](../../pc-agent.md) |
| [TZ-09](../../../specs/TZ-09-n8n-Integration/) | 5 | n8n nodes, интеграции и webhook | [Пользователи и интеграции](../../operations/USER-ADMIN-GUIDE.md), routers и тесты |
| [TZ-10](../../../specs/TZ-10-Web-Frontend/) | 5 | Web auth, парк, VPN, Studio | [Web UI](../../web-ui-guide.md) и [источники frontend](../../../frontend/) |
| [TZ-11](../../../specs/TZ-11-Monitoring/) | 5 | Метрики, Grafana, alerts, logging, health | [Observability](../../operations/OBSERVABILITY.md), [HTTP metrics](../../operations/HTTP-METRICS.md) |
| [TZ-12 Orchestrator](../../../specs/TZ-12-Orchestrator/) | 5 | Lifecycle, cache, события, pipeline, расписания | [Задания и оркестрация](../../operations/TASKS-AND-ORCHESTRATION.md), [pipeline](../../operations/PIPELINE-DEFINITIONS.md) |
| [TZ-12 Agent Discovery](../../../specs/TZ-12-Agent-Discovery/PLAN.md) | 1 | Исторический план discovery и provisioning | [PC agent](../../pc-agent.md), [Android discovery](../../architecture/ANDROID-DISCOVERY-RECOVERY.md) |

Примеры причин не воспринимать ТЗ как текущую реализацию: старое ТЗ на расписания
говорит только о ручных запусках, хотя [schedule router](../../../backend/api/v1/schedules/router.py)
и [scheduler engine](../../../backend/services/scheduler/scheduler_engine.py) есть в
исходниках. Это не доказывает работающий scheduler на конкретном стенде. ТЗ на VPN
kill switch — требование, тогда как [VPN outcome contract](../../operations/VPN-CONTROL-OUTCOMES.md)
различает unsupported и доказанное применение.

## Остальные три плана и AI-readiness

[Load-test architecture](../../load-test/01-ARCHITECTURE.md),
[scenarios](../../load-test/02-SCENARIOS.md) и [metrics/criteria](../../load-test/03-METRICS-AND-CRITERIA.md)
— проект синтетической нагрузки. [Отчёт](../../load-test/04-EXECUTION-REPORT.md)
описывает mock-среду и не доказывает мощность настоящего парка. В
[AI-readiness](../../architecture/AI-READINESS.md) старые подписи «текущий веб/APK»
заменены датированным обозначением наблюдения 16 октября; автономную работу модели
или сегодняшний runtime это не подтверждает.

## Что уточнено и что осталось

В девяти основных design-документах и двух preview-файлах только датированные
статусы/устаревшая ссылка на preview обозначены как исторические; содержание
проектных решений не объявлено текущим состоянием. Визуальный документ теперь
различает выбор направления и принятие каждого экрана. Ревизии из записанного
[STATUS-REGISTRY](../../operations/STATUS-REGISTRY.json) и последующие наблюдения
[CURRENT-STATE](../../operations/CURRENT-STATE.md) имеют собственные границы и
не являются опросом live-среды. Снимки и чужие незакоммиченные файлы не менялись.

Проверены заголовки и вводные всех tracked design Markdown, структура инвентаря и
выборочные ТЗ/тексты. Не сверены все требования, команды, кодовые фрагменты,
исторические URL, научные источники или каждое предложение с реализацией. Нет
новых browser/native/production испытаний и не изменена приёмка проекта. Для
следующего прохода полезно связать устаревшие сплиты с профильными контрактами
и вести вопрос о полном или частичном статусе по отдельной evidence, не переписывая
исходные ТЗ как текущую спецификацию.
