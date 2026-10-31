# Документация Sphere Platform

Навигация по руководствам, контрактам, архитектуре и результатам проверок.
Начните с задачи, затем проверьте дату и область применимости выбранного документа.

[Главная проекта](../README.md) · [Правила актуальности](DOCUMENTATION.md) ·
[Записанное состояние](operations/CURRENT-STATE.md) · [Открытые работы](operations/WORK-STATUS.md)

## Начало работы и эксплуатация

| Задача | Документ |
| --- | --- |
| Подготовить новое окружение | [Startup](operations/STARTUP.md), [конфигурация](configuration.md), [deployment](deployment.md) |
| Работать с существующим локальным стендом | [Local pilot](operations/LOCAL-PILOT.md), [review gateway](operations/REVIEW-GATEWAY.md) |
| Подключить удалённые устройства | [Remote pilot](operations/REMOTE-PILOT.md), [Android cloud pilot](operations/ANDROID-CLOUD-PILOT.md) |
| Оценить готовность и восстановление | [Readiness](operations/READINESS.md), [runbooks](runbooks/README.md), [observability](operations/OBSERVABILITY.md) |
| Разобраться в правах и безопасности | [Пользователи и интеграции](operations/USER-ADMIN-GUIDE.md), [Доступ пользователей](operations/USER-ACCESS.md), [безопасность](security.md), [bootstrap учётных записей](security/user-auth-bootstrap.md) |

## Пользовательские сценарии

| Задача | Документ |
| --- | --- |
| Вход, обзор и навигация | [Вход и обзор](operations/WEB-ENTRY-GUIDE.md), [карта Web UI](web-ui-guide.md) |
| Устройства, группы и локации | [Каталог](operations/DEVICE-CATALOG.md), [устройства и поток](operations/DEVICE-STREAM-GUIDE.md), [группы](operations/GROUP-HIERARCHY.md), [локации](operations/LOCATION-HIERARCHY.md) |
| Сценарии и оркестрация | [Script Studio](operations/SCRIPT-STUDIO.md), [задания и оркестрация](operations/TASKS-AND-ORCHESTRATION.md), [каталог](operations/SCRIPT-CATALOG.md), [версии](operations/SCRIPT-VERSIONS.md), [pipelines](operations/PIPELINE-DEFINITIONS.md) |
| Видео и ввод | [Протокол continuous input](protocols/CONTINUOUS-INPUT-SERVER.md), [результаты ввода](protocols/CONTINUOUS-INPUT-RECEIPTS.md), [запись траекторий](operations/POINTER-PATH-RECORDING.md) |
| VPN | [Профили](operations/VPN-PROFILES.md), [результаты управления](operations/VPN-CONTROL-OUTCOMES.md) |
| Обучающая запись и маршруты | [Teaching в web](operations/TEACHING-WEB.md), [Route Studio](operations/ROUTE-STUDIO.md), [пилот маршрута](operations/WALK-ROUTE-PILOT.md), [Motor Worker](operations/MOTOR-WORKER.md) |

[Карта Web UI](web-ui-guide.md) содержит маршруты и основные действия,
сверенные с исходниками; установленную версию и конкретные сценарии проверяйте отдельно.

## Разработка и интеграция

| Тема | Документ |
| --- | --- |
| Среда и проверки | [Development](development.md), [Contributing](../CONTRIBUTING.md), [workflows CI](../.github/workflows/) |
| HTTP API | [Генерируемый каталог](api-endpoints.md), [OpenAPI JSON](openapi.json), [пояснения](api-reference.md) |
| Архитектура и решения | [Architecture](architecture.md), [ADR](adr/README.md), [архитектурные документы](architecture/) |
| Android и PC | [Android agent](android-agent.md), [протокол подключения](architecture/ANDROID-CONNECTION-PROTOCOL.md), [PC agent](pc-agent.md) |
| Контракты и проектирование | [Протоколы](protocols/), [design](design/), [исходные спецификации](../specs/) |

Сгенерированный HTTP-каталог отражает декларации OpenAPI, но не описывает все
WebSocket-протоколы и не доказывает работоспособность конкретного окружения.

## Статус, история и границы доказательств

- [CURRENT-STATE](operations/CURRENT-STATE.md) и [WORK-STATUS](operations/WORK-STATUS.md)
  содержат записанные срезы и открытые задачи. Дата наблюдения и область проверки
  важны: предыдущий результат не подтверждает нынешнее состояние установки.
- [STATUS-REGISTRY.json](operations/STATUS-REGISTRY.json) связывает ряд статусов с
  доказательствами; [DOCUMENT-INVENTORY.json](operations/DOCUMENT-INVENTORY.json)
  классифицирует Markdown. Это не построчная аттестация всей документации.
- [Аудиты и evidence](audits/) фиксируют результаты отдельных проверок в их время.
  [Оценка документации](audits/2026-11-01/DOCUMENTATION-ASSESSMENT.md) и
  [карта покрытия Web](audits/2026-11-01/WEB-COVERAGE-MATRIX.md) показывают
  границы сверки на исходном срезе.
  Не переносите их версии и выводы на новые развёртывания без повторной проверки.
- [Design](design/) и [specs](../specs/) могут содержать предложения и исторические
  требования. Наличие спецификации не означает реализованную и принятую возможность.

Как обновлять документы и что проверяет автоматизация, описано в
[правилах актуальности](DOCUMENTATION.md) и [процессе обновления](operations/DOCUMENTATION-WORKFLOW.md).
