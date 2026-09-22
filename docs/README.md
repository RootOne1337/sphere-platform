<div align="center">

# 📚 Документация Sphere

**От первого подключения до воспроизводимого разбора отказа.**

[Главная](../README.md) · [Готовность](operations/READINESS.md) · [Открытые работы](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [Помощь](../SUPPORT.md)

</div>

> [!NOTE]
> **Срез навигации: 23 сентября 2026.** Текущий pilot и границы его приёмки описаны
> в [Local pilot](operations/LOCAL-PILOT.md). Старые отчёты сохраняют свои даты и
> версии; их показатели нельзя переносить на текущий код. [Правила актуальности](DOCUMENTATION.md).

## 🧭 Выберите задачу

| Мне нужно | Начать здесь | Дальше |
| --- | --- | --- |
| Войти в готовый pilot и взять APK | [Local pilot](operations/LOCAL-PILOT.md) | [Приёмка первого устройства](operations/PILOT-ACCEPTANCE.md) |
| Поднять новую установку | [Startup / bootstrap](operations/STARTUP.md#first-install) | [Configuration](configuration.md) · [Deployment](deployment.md) |
| Подключить удалённые Android | [Remote pilot](operations/REMOTE-PILOT.md) | [Signed discovery](architecture/ANDROID-SIGNED-DISCOVERY.md) |
| Понять оставшиеся проблемы | [Fleet32: актуальная таблица](audits/2026-09-20/FLEET32-PREFLIGHT.md) | [Roadmap](../ROADMAP.md) · [Readiness](operations/READINESS.md) |
| Разобрать сбой по времени и устройству | [Support: что собрать](../SUPPORT.md) | [Runbooks](runbooks/README.md) |
| Изменить код | [Contributing](../CONTRIBUTING.md) | [Development](development.md) · [Тесты](../tests/production/README.md) |

## 🚀 Запуск и эксплуатация

| Руководство | Что внутри |
| --- | --- |
| [Startup](operations/STARTUP.md) | Первый запуск, повторный старт, env precedence и значение readiness |
| [Local pilot](operations/LOCAL-PILOT.md) | Установленные версии, веб, APK, учётная запись и отдельный Compose project |
| [Remote pilot](operations/REMOTE-PILOT.md) | Устройства в другой сети, ingress и ограничения резервирования |
| [Deployment](deployment.md) · [Полный guide](../FULL-DEPLOYMENT-GUIDE.md) | Bootstrap, конфигурации и обслуживание; оценки масштаба требуют своей приёмки |
| [Discovery publisher](operations/DISCOVERY-PUBLISHER.md) | Публикация подписанных маршрутов и восстановление publisher |
| [Redis memory](operations/REDIS-MEMORY.md) | Dataset/container budget, persistence, pressure test и остаточные риски |
| [Redis concurrent AOF follow-up](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md) | AUD-143: CI OOM, source budget and pilot rollout boundary |
| [OTA transport retry](audits/2026-09-20/OTA-TRANSPORT-RETRY.md) | AUD-144 / F32-33: bounded retry after interrupted APK body, candidate and remote-acceptance gates |
| [LDPlayer network recovery](operations/LDPLAYER-NETWORK-RECOVERY.md) | Диагностика сети станции и границы Windows watchdog |
| [Overnight soak](operations/ANDROID-OVERNIGHT-SOAK.md) | Безопасные DAG, receipts, видео, завершение и evidence |
| [Runbooks](runbooks/README.md) | Backend outage, PostgreSQL, fleet offline и VPN incidents |

## 🧩 Компоненты и интерфейсы

| Компонент | Документы |
| --- | --- |
| Общая архитектура | [Обзор](architecture.md) · [Архитектурные решения](adr/README.md) |
| Backend | [Генерируемый API-каталог](api-endpoints.md) · [OpenAPI JSON](openapi.json) · [Обзор API](api-reference.md) |
| Web UI | [Экранные сценарии](web-ui-guide.md) · [Сессии и cache lifecycle](security/frontend-sessions.md) |
| Android | [Agent guide](android-agent.md) · [Протокол соединения](architecture/ANDROID-CONNECTION-PROTOCOL.md) |
| Discovery / recovery | [Подписанный manifest](architecture/ANDROID-SIGNED-DISCOVERY.md) · [Сохранённые маршруты](architecture/ANDROID-SAVED-ROUTES.md) · [Фоновая регистрация](architecture/ANDROID-BACKGROUND-ENROLLMENT.md) |
| PC-agent | [Workstation identity, локальные инструменты и подключение](pc-agent.md) |
| PostgreSQL | [RLS / runtime roles](security/postgresql-rls.md) · [Worker RLS](audits/2026-09-20/PIPELINE-RLS.md) |
| Задачи | [Task control protocol](security/task-control-protocol.md) · [Durable cancellation](audits/2026-09-20/DURABLE-CANCELLATION.md) |
| Оркестрация | [Pipeline recovery](audits/2026-09-20/PIPELINE-RECOVERY.md) · [Batch recovery](audits/2026-09-20/BATCH-RECOVERY.md) · [Nested waiting](audits/2026-09-20/PIPELINE-NESTED-WAIT.md) |
| Identity / credentials | [User bootstrap](security/user-auth-bootstrap.md) · [Device bootstrap](security/device-credential-bootstrap.md) · [Device refresh](security/device-refresh-recovery.md) · [Account credentials](security/account-credentials.md) |
| VPN | [Реестр ограничений F32-11/12/21](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [VPN intents](audits/2026-09-05/VPN-LEASE-DESIGN.md) · [Runbook](runbooks/02-vpn-incident.md) |

## 🔬 Что подтверждено проверкой

| Последняя контрольная точка | Доказательства и границы |
| --- | --- |
| Согласованный rollout backend/APK 1.2.8 | [Canary 21 сентября](audits/2026-09-20/CANARY-20260921.md): OTA, backup/restore, 15 tasks, два pipeline |
| Frontend `9924eb1` | [AUD-138](audits/2026-09-20/DECODER-RECOVERY.md): decoder bounds/recovery и два живых потока после restart |
| Первый IDR и восстановление | [AUD-140 / F32-29](audits/2026-09-20/STREAM-FIRST-FRAME.md) · [AUD-142 / F32-31](audits/2026-09-20/ANDROID-KEYFRAME-STARTUP.md): browser retry, отложенный Android keyframe до старта encoder, backend forwarding regression; удалённая приёмка ещё OPEN |
| Standalone-сборка frontend | [AUD-141 / F32-30](audits/2026-09-20/FRONTEND-STANDALONE.md): Linux CI build/root-entrypoint passed; отдельный frontend Docker image не проверен; Windows trace warning remains |
| Redis budget | [AUD-143](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md): 1536 MiB воспроизвёл OOM; 2048 MiB probe прошёл, peak достиг потолка; 32-stream/live rollout open |
| OTA transfer | [AUD-144 / F32-33](audits/2026-09-20/OTA-TRANSPORT-RETRY.md): local before/after regression and bounded retry; candidate 1.2.10/10210 is not yet published or remotely installed |
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
