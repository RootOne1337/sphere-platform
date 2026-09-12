# Документация Sphere Platform

**Навигация по текущим контрактам, эксплуатационным ограничениям и доказательствам.**
Обновлено 12 сентября 2026. [Вернуться на главную](../README.md).

## С чего начать

| Задача | Документ |
| --- | --- |
| Оценить реальную готовность и порядок работ | [Эксплуатационная матрица](operations/READINESS.md) |
| Найти подтверждённый дефект/исправление | [Audit report и evidence](audits/2026-09-05/AUDIT-REPORT.md) |
| Узнать, что осталось до первого рабочего запуска | [Пилот: этапы, ориентиры сроков и критерии](operations/PILOT-ACCEPTANCE.md) |
| Открыть текущий стенд / получить APK | [Local pilot](operations/LOCAL-PILOT.md), [Remote profile и native acceptance](operations/REMOTE-PILOT.md) |
| Запустить и понимать readiness | [Startup contract](operations/STARTUP.md) |
| Подготовить окружение | [Development](development.md), [Configuration](configuration.md) |
| Подключить устройство/станцию | [Android](android-agent.md), [PC-agent](pc-agent.md) |
| Использовать интерфейс | [Web UI](web-ui-guide.md) |
| Найти API | [Генерируемый каталог](api-endpoints.md), [OpenAPI](openapi.json), [Обзор API](api-reference.md) |
| Подготовить rollout | [Deployment](deployment.md), [Full guide](../FULL-DEPLOYMENT-GUIDE.md) |
| Разобрать сбой | [Observability contract](operations/READINESS.md), [Runbooks](runbooks/README.md) |
| Спроектировать будущий AI-контур | [AI readiness](architecture/AI-READINESS.md) |

## Технические контракты

- [Архитектура платформы](architecture.md) и [ADR](adr/README.md).
- [Подтверждение Android-соединения / порядок обновления](architecture/ANDROID-CONNECTION-PROTOCOL.md).
- [Фоновая регистрация APK: повторный запуск, конкуренция и device identity](architecture/ANDROID-BACKGROUND-ENROLLMENT.md).
- [Основной и резервный адрес APK: настройка, переключение, ограничения](architecture/ANDROID-SAVED-ROUTES.md).
- [Android discovery: HTTP budget, конкуренция и остановка](architecture/ANDROID-DISCOVERY-RECOVERY.md).
- [Смена адресов без переустановки: архитектура](architecture/ANDROID-BOOTSTRAP-DISCOVERY.md).
- [Signed discovery: реализованный opt-in контракт, CLI и проверки](architecture/ANDROID-SIGNED-DISCOVERY.md).
- [Task control / rollout](security/task-control-protocol.md).
- [Device credential bootstrap](security/device-credential-bootstrap.md).
- [Device refresh recovery / rollout](security/device-refresh-recovery.md).
- [User login/refresh/MFA](security/user-auth-bootstrap.md).
- [PostgreSQL runtime roles и RLS](security/postgresql-rls.md).
- [Account credential storage/backfill](security/account-credentials.md).
- [Frontend session/cache lifecycle](security/frontend-sessions.md).
- [VPN intents и recovery](audits/2026-09-05/VPN-LEASE-DESIGN.md).
- [Тесты на выделенных PostgreSQL/Redis](../tests/production/README.md).

## Как читать статус

**Реализовано** означает наличие кода. **Проверено** всегда имеет сценарий,
окружение, ревизию и результат. **Предложено** — проектное решение, которое ещё не
является возможностью продукта. Успешная сборка не доказывает runtime и capacity.

Сначала используйте operational matrix и свежий audit report. Старые отчёты,
load-test документы и руководства отдельных модулей сохраняют историю;
их метрики нельзя автоматически переносить на текущую ветку. Runbooks сверены
с текущими health paths и Compose service names; recovery drills ещё не пройдены. API
catalog генерируется из registered routes, но не удостоверяет успех всех операций.
Систематическая сверка остальных руководств продолжается.

Каждый следующий PR обновляет затронутый контракт, команды воспроизведения,
миграционные ограничения и remaining risks. Изменение цели парка или deployment
топологии отражается сначала в operational matrix, затем в runbooks и тестах.

- [Автоматический publisher: настройка, supervision и восстановление](operations/DISCOVERY-PUBLISHER.md).
- [Signed discovery на установленном APK: отказ, миграция и возврат](audits/2026-09-05/SIGNED-DISCOVERY-NATIVE.md).
