# Выборочная сверка эксплуатационных документов по областям

Срез **1 ноября 2026**: исходники и изменявшееся рабочее дерево; во время прохода
`HEAD` изменился с `ea153f52` на `6b08f09f` в результате параллельной работы.
Ниже перечислено реально просмотренное, а не заявка на построчную аттестацию всех
файлов. Работа не выполняла HTTP-запросы к установке, команды устройствам,
развёртывание или миграции. Изменения относятся к документации.

## Исправления этого прохода

| Документ | Что уточнено | Опора |
| --- | --- | --- |
| [Задания и оркестрация](../../operations/TASKS-AND-ORCHESTRATION.md) | `fire-now` устанавливает `next_fire_at`, но не активирует отключённое расписание и не исполняет задачу синхронно. Сообщение UI «Расписание запущено!» не подтверждает фактическое срабатывание. | [ScheduleService](../../../backend/services/scheduler/schedule_service.py), [scheduler engine](../../../backend/services/scheduler/scheduler_engine.py), [страница оркестрации](../../../frontend/app/%28dashboard%29/orchestration/page.tsx). Scheduler выбирает активные записи с наступившим `next_fire_at`; отказ или остановка scheduler требуют отдельной проверки. |
| [Каталог сценариев](../../operations/SCRIPT-CATALOG.md) | Установка `eb7a7c26` и результаты 6 октября помечены как исторический срез; адрес 3015 не выдан за подтверждённый нынешний endpoint. | Прежняя датированная [квитанция](../2026-10-06/SCRIPT-CATALOG-DELIVERY.md); новую установку в этом проходе не проверяли. |
| [VPN profiles](../../operations/VPN-PROFILES.md) | Процедура schema-free batch installer обозначена как специфичная историческому frozen baseline, с необходимостью проверить применимость перед использованием. | [CLI](../../../scripts/pilot/install_vpn_catalog_batch.py) и [release boundary](../../../scripts/pilot/vpn_catalog_batch_release.py) задают базовую ревизию `7d2a6846`, Alembic head и точные файлы/хеши. Чтение этого кода не является разрешением его запускать. |

## Реестр просмотренных областей

| Область | Реально изучено | Результат и неохваченные границы |
| --- | --- | --- |
| Задания, batch, расписания и pipeline settings | [TASKS-AND-ORCHESTRATION](../../operations/TASKS-AND-ORCHESTRATION.md); фрагменты routers [tasks](../../../backend/api/v1/tasks/router.py), [batches](../../../backend/api/v1/batches/router.py), [schedules](../../../backend/api/v1/schedules/router.py), [pipeline settings](../../../backend/api/v1/pipeline_settings/router.py), [страницы orchestration](../../../frontend/app/%28dashboard%29/orchestration/page.tsx); сервис и engine расписаний. | Подтверждены ограничения прав, мягкая деактивация и значение `fire-now` выше. Не исследованы все гонки, конфликты и фактические запуски на устройствах. |
| Определения pipeline | [PIPELINE-DEFINITIONS](../../operations/PIPELINE-DEFINITIONS.md), [router](../../../backend/api/v1/pipelines/router.py), [schema](../../../backend/schemas/pipeline.py), [RBAC](../../../backend/core/rbac.py). | Выборочно сопоставлены permission, обязательный `active`, optional timestamp, пределы шагов и PATCH. Транзакционные блокировки и восстановление активного run заново не запускались. |
| Сценарии | Начало и разделы [SCRIPT-CATALOG](../../operations/SCRIPT-CATALOG.md), [SCRIPT-VERSIONS](../../operations/SCRIPT-VERSIONS.md); связанные источники и ранее изученный [API reference](../../api-reference.md). | Сохранены ограничения относительно опубликованной версии, архива и известных срезов. Не воспроизводились конфликт версий, backfill метаданных или исполнение DAG. |
| Группы и локации | [GROUP-HIERARCHY](../../operations/GROUP-HIERARCHY.md), раздел HTTP [LOCATION-HIERARCHY](../../operations/LOCATION-HIERARCHY.md), [groups service](../../../backend/services/group_service.py), [locations router](../../../backend/api/v1/locations/router.py), [RBAC](../../../backend/core/rbac.py). | Сверены назначение прав и выбранные поля/условия. Не проводились реальные PostgreSQL конкурентные испытания и проверка всех операций membership. |
| Устройства и журналы | Начальные разделы [DEVICE-CATALOG](../../operations/DEVICE-CATALOG.md), [DEVICE-LOG-STORAGE](../../operations/DEVICE-LOG-STORAGE.md), [DEVICE-STREAM-GUIDE](../../operations/DEVICE-STREAM-GUIDE.md); выборочные фрагменты [logs router](../../../backend/api/v1/logs/router.py), [reader](../../../backend/services/device_log_reader.py), [upload](../../../backend/services/device_log_upload.py). | Документ различает ограниченный хвост и ошибку, удаление и подтверждение физического удаления. Не исследованы все действия UI, подписки, реальные файлы или устройства. |
| VPN | Начало, batch и deployment-фрагменты [VPN-PROFILES](../../operations/VPN-PROFILES.md), [VPN-CONTROL-OUTCOMES](../../operations/VPN-CONTROL-OUTCOMES.md); [VPN router](../../../backend/api/v1/vpn/router.py), [profile router](../../../backend/api/v1/vpn/profile_router.py), [batch UI](../../../frontend/src/features/vpn/VpnProfileBatchImport.tsx), publisher и installer boundary. | Сверены выборочные лимиты, права и разделение подтверждения приёма от применения. Не выполнялись импорт профилей, установка, VPN/WAN/kill-switch или тесты живого парка. |
| Monitoring и HTTP API | Вводные [OBSERVABILITY](../../operations/OBSERVABILITY.md), [HTTP-METRICS](../../operations/HTTP-METRICS.md), начальные фрагменты [api-reference](../../api-reference.md), [backend main](../../../backend/main.py), [exporter](../../../scripts/export_api_docs.py), [HTTP observability](../../../frontend/lib/server/httpObservability.ts), [страница monitoring](../../../frontend/app/%28dashboard%29/monitoring/page.tsx). | Подтверждены выборочные пути, окно rate, выбор интервалов и polling; фактические Prometheus, Grafana, auth, текущий endpoint и окна данных не опрашивались. |
| PC-агент и пользовательские разделы | Выборочно [PC agent](../../pc-agent.md), [его конфигурация](../../../pc-agent/agent/config.py) и [клиент](../../../pc-agent/agent/client.py); отдельный [реестр 9 UI разделов](USER-SECTIONS-COVERAGE.md). | Дефолты и ограничения очереди сверены по source; Windows service, LDPlayer, внешние вебхуки, реальные права и исходы сетевых сбоев не проверялись. |

В ходе предшествующего прохода по тем же областям исторические срезы API и граница
VPN publisher/service уточнялись отдельно в [API reference](../../api-reference.md),
[VPN control](../../operations/VPN-CONTROL-OUTCOMES.md) и [VPN profiles](../../operations/VPN-PROFILES.md).
Это не доказательство нового readback после этих изменений.

## Остаток и проверка

Нужны отдельные воспроизводимые проверки настоящих ответов по каждой роли и
состоянию, сценариев создания/редактирования/конфликта и неизвестного исхода,
PostgreSQL/RLS, scheduler под нагрузкой, VPN и реального Android. Тексты с
датированными доказательствами следует проверять по ревизии и среде; старый
успешный тест не относится автоматически к новой установке. Неисследованные
разделы и неуспешные/незапущенные тесты не считаются проверенными.

Для изменённых файлов выполнены локальная проверка поддерживаемых относительных
inline-ссылок и `git diff --check`; они не проверяют anchors, содержание всех
документов, сетевые URL или визуальное отображение. Тесты приложений в этом проходе
не запускались, поскольку код и исполняемые контракты не менялись.
