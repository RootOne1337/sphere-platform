# Инвентаризация эксплуатационных руководств

Дата: 1 ноября 2026. Снимок файлов инвентаря и рабочей директории поверх Git `ea153f52711a`;
другие незакоммиченные изменения не считались подтверждённым runtime. Отчёт только
о документации; эксплуатационные действия, запросы к устройствам, развёртывание,
восстановление и сервисные прогоны не выполнялись.

## Метод и границы

В таблице 80 файлов: список взят из `DOCUMENT-INVENTORY.json`, затем к нему
применена текущая `document_role` из `scripts/check_documentation_status.py`.
Исторический `docs/history/README-20261022.md` исключён: обновлённая классификация
относит `docs/history/` к `DATED_EVIDENCE`. Таблица отражает машинную роль, не
аттестацию действительности инструкции. Файл может содержать историческую ленту,
проектный текст и команды наряду с действующим руководством.

Для каждого файла автоматически прочитаны текст, первый заголовок, число строк и
заголовков, а также признаки даты/runtime в первых 45 строках и наличие fenced
блоков во всём файле. Назначение взято из заголовка, а не установлено детальным
анализом. Объём и количество заголовков — только признаки навигации; они не
доказывают удобство, точность, безопасность или полноту документа. Индикаторы —
эвристика: отсутствие метки не доказывает отсутствие устаревания и команда в
блоке не обязательно выполняется. Полная смысловая проверка каждой строки, ссылки,
команды, роли и инсталляции для этих файлов не выполнена.

## Приоритетный ручной проход и подтверждённые изменения

- **Первый запуск**: [STARTUP](../../operations/STARTUP.md) сопоставлен с
  `scripts/full-deploy.ps1`, `scripts/full-deploy.sh` и выбранными Compose files.
  Исторически недокументированная разница: Bash исполняет `.env.local` через
  `source`, PowerShell передаёт выбранный env через `--env-file`. В руководстве
  разделены генерация и запуск, добавлена проверка существующих env и выхода
  генератора; запуск и содержимое существующих конфигураций не проверялись.
- **Разработка и восстановление**: [development](../../development.md) и
  [runbooks](../../runbooks/README.md) сопоставлены с workflow и соответствующими
  исходниками. Индекс runbooks предупреждает о выборе env/project; старый migration
  head в database runbook обозначен как исторический. Реальные backup/restore и
  полнота проверки прав/окружения остались вне этого прохода.
- **Host resources**: [HOST-RESOURCES](../../operations/HOST-RESOURCES.md) содержал
  заголовок «актуальный статус» для 13 октября и историческое разрешение обхода
  ремонтного действия. Добавлена явная маркировка даты и границ разрешения; сами
  наблюдения и evidence сохранены. Нового осмотра хоста не было.
- **Remote**: [REMOTE-PILOT](../../operations/REMOTE-PILOT.md) содержал текущую
  формулировку о резервном Serveo, выбранном profile и publisher в сентябрьском
  отчёте. Они обозначены как исторические наблюдения, не текущая инвентаризация.
  Профиль и маршруты не запускались и не проверялись.
- **Поставка**: [LOCAL-BACKEND-DELIVERY](../../operations/LOCAL-BACKEND-DELIVERY.md)
  и [BUILD-PROVENANCE](../../operations/BUILD-PROVENANCE.md) прочитаны на уровне
  назначения и описанных ограничений планирования/применения; детали admission,
  исходники установщика и фактическая поставка в этом проходе не переаттестованы.

## Очередь проверки

1. Сопоставить локальный и удалённый pilot, gateway, host resources и delivery с
   выбранным стендом, сохраняя границу между source, installed и dated evidence.
2. Отдельно разобрать архитектуру Android, OTA/VPN и протоколы на совместимость
   версий, права, неизвестные исходы и реальные устройства; исторический отчёт не
   даёт fleet acceptance.
3. Для оставшихся руководств пройти команды и ответы API по текущему коду и тестам,
   особенно где есть длительные исторические ленты. Длинные документы требуют
   навигации и выделения действующего текста от доказательств, а не удаления receipts.
4. Проверить автоматический инвентарь и локальные ссылки после добавления отчёта;
   их прохождение не заменяет смысловой или runtime-проверки.

## Реестр по роли OPERATING_GUIDE

### Эксплуатация

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [ANDROID-CLOUD-PILOT.md](../../../docs/operations/ANDROID-CLOUD-PILOT.md) | Облачная упаковка настроенного pilot APK | 83 строк, 4 заголовков | дата в начале |
| [ANDROID-NAVIGATION.md](../../../docs/operations/ANDROID-NAVIGATION.md) | Навигация Android в одиночном видеопотоке | 116 строк, 5 заголовков | дата в начале, возможный runtime-срез |
| [ANDROID-OVERNIGHT-SOAK.md](../../../docs/operations/ANDROID-OVERNIGHT-SOAK.md) | Ночной прогон Android без игр | 163 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [AUDIT-INVESTIGATION.md](../../../docs/operations/AUDIT-INVESTIGATION.md) | Журнал аудита: поиск и ограниченный экспорт | 103 строк, 5 заголовков | дата в начале, возможный runtime-срез |
| [BUILD-PROVENANCE.md](../../../docs/operations/BUILD-PROVENANCE.md) | Build provenance in the operator UI | 104 строк, 6 заголовков | возможный runtime-срез, блоки примеров |
| [CODEC-INPUT-CANARY.md](../../../docs/operations/CODEC-INPUT-CANARY.md) | Android codec input: synthetic control и настоящий capture canary | 231 строк, 10 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [CONTINUOUS-INPUT-TIMINGS.md](../../../docs/operations/CONTINUOUS-INPUT-TIMINGS.md) | Серверные тайминги непрерывного управления | 124 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [DEVICE-CATALOG.md](../../../docs/operations/DEVICE-CATALOG.md) | Реестр устройств: пагинация и смысл live-статусов | 87 строк, 8 заголовков | дата в начале, возможный runtime-срез |
| [DEVICE-LOG-STORAGE.md](../../../docs/operations/DEVICE-LOG-STORAGE.md) | Хранение полученных Android-журналов | 92 строк, 6 заголовков | дата в начале |
| [DEVICE-STREAM-GUIDE.md](../../../docs/operations/DEVICE-STREAM-GUIDE.md) | Устройства, потоки и обнаружение: действия оператора | 163 строк, 9 заголовков | нужна смысловая сверка |
| [DISCOVERY-PUBLISHER.md](../../../docs/operations/DISCOVERY-PUBLISHER.md) | Автоматическая публикация адреса Android-сервера | 162 строк, 8 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [DOCUMENTATION-WORKFLOW.md](../../../docs/operations/DOCUMENTATION-WORKFLOW.md) | Как поддерживать документацию при изменениях | 75 строк, 9 заголовков | блоки примеров |
| [GROUP-HIERARCHY.md](../../../docs/operations/GROUP-HIERARCHY.md) | Иерархия групп: контракт записи и восстановления | 88 строк, 5 заголовков | дата в начале, возможный runtime-срез |
| [HOST-RESOURCES.md](../../../docs/operations/HOST-RESOURCES.md) | Ресурсы хоста: диск, Windows commit, WSL и контейнеры | 766 строк, 20 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [HTTP-METRICS.md](../../../docs/operations/HTTP-METRICS.md) | HTTP-метрики backend: контракт и ограничения | 105 строк, 5 заголовков | дата в начале, возможный runtime-срез |
| [LDPLAYER-NETWORK-RECOVERY.md](../../../docs/operations/LDPLAYER-NETWORK-RECOVERY.md) | LDPlayer запущен, но APK не выходит в сеть | 152 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [LOCAL-BACKEND-DELIVERY.md](../../../docs/operations/LOCAL-BACKEND-DELIVERY.md) | Локальная упаковка и установка backend | 68 строк, 4 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [LOCAL-PILOT.md](../../../docs/operations/LOCAL-PILOT.md) | Локальный стенд для совместного тестирования | 718 строк, 20 заголовков | дата в начале, блоки примеров |
| [LOCATION-HIERARCHY.md](../../../docs/operations/LOCATION-HIERARCHY.md) | Локации: география, иерархия и безопасное редактирование | 143 строк, 9 заголовков | дата в начале, возможный runtime-срез |
| [MOTOR-WORKER.md](../../../docs/operations/MOTOR-WORKER.md) | Headless motor worker: транспорт и конечный ввод | 460 строк, 12 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [OBSERVABILITY.md](../../../docs/operations/OBSERVABILITY.md) | Prometheus и Grafana внутри Sphere | 578 строк, 13 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [OTA-ADDRESSED-UPDATES.md](../../../docs/operations/OTA-ADDRESSED-UPDATES.md) | Адресное обновление Android: действия и проверка результата | 118 строк, 7 заголовков | дата в начале, возможный runtime-срез |
| [OTA-PUBLICATION-AND-APK-CHECKS.md](../../../docs/operations/OTA-PUBLICATION-AND-APK-CHECKS.md) | Проверки публикации и совместимости APK | 178 строк, 8 заголовков | дата в начале, возможный runtime-срез |
| [PILOT-ACCEPTANCE.md](../../../docs/operations/PILOT-ACCEPTANCE.md) | Первый рабочий пилот: что осталось до использования | 291 строк, 24 заголовков | дата в начале, возможный runtime-срез |
| [PIPELINE-DEFINITIONS.md](../../../docs/operations/PIPELINE-DEFINITIONS.md) | Pipeline: определение, редактирование и допуск запусков | 141 строк, 8 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [POINTER-PATH-RECORDING.md](../../../docs/operations/POINTER-PATH-RECORDING.md) | Запись непрерывной траектории | 54 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [REDIS-MEMORY.md](../../../docs/operations/REDIS-MEMORY.md) | Redis: память, сохранение и приёмка | 141 строк, 7 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [REMOTE-PILOT.md](../../../docs/operations/REMOTE-PILOT.md) | Удалённый пилот: исходящий туннель и реальные проверки | 194 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [REVIEW-GATEWAY.md](../../../docs/operations/REVIEW-GATEWAY.md) | Review gateway: локальный UI и адресный публичный маршрут | 235 строк, 3 заголовков | дата в начале, возможный runtime-срез |
| [ROUTE-STUDIO.md](../../../docs/operations/ROUTE-STUDIO.md) | Студия маршрутов: запись, ориентиры и просмотр | 276 строк, 13 заголовков | дата в начале, возможный runtime-срез |
| [SCRIPT-CATALOG.md](../../../docs/operations/SCRIPT-CATALOG.md) | Каталог сценариев: чтение метаданных и порядок включения | 179 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [SCRIPT-VERSIONS.md](../../../docs/operations/SCRIPT-VERSIONS.md) | Сценарии: версии, контролируемый откат и архив | 105 строк, 6 заголовков | дата в начале, возможный runtime-срез |
| [STARTUP.md](../../../docs/operations/STARTUP.md) | Запуск Sphere: bootstrap, повторный старт и readiness | 333 строк, 22 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [STATIC-STREAM-INPUT.md](../../../docs/operations/STATIC-STREAM-INPUT.md) | Управление одиночным потоком при статичном экране | 67 строк, 4 заголовков | дата в начале, возможный runtime-срез |
| [TASKS-AND-ORCHESTRATION.md](../../../docs/operations/TASKS-AND-ORCHESTRATION.md) | Задания, конвейеры и расписания | 123 строк, 7 заголовков | возможный runtime-срез |
| [TEACHING-DENSE-RECONSTRUCTION.md](../../../docs/operations/TEACHING-DENSE-RECONSTRUCTION.md) | Локальная реконструкция записанного прохода | 338 строк, 10 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [TEACHING-SURFACE-MODEL.md](../../../docs/operations/TEACHING-SURFACE-MODEL.md) | Текстурированная 3D-модель записанного прохода | 194 строк, 7 заголовков | дата в начале, возможный runtime-срез |
| [TEACHING-WEB.md](../../../docs/operations/TEACHING-WEB.md) | Ручная запись маршрута в вебе | 242 строк, 8 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [USER-ACCESS.md](../../../docs/operations/USER-ACCESS.md) | Пользователи: подтверждённые изменения доступа | 95 строк, 6 заголовков | дата в начале, возможный runtime-срез |
| [USER-ADMIN-GUIDE.md](../../../docs/operations/USER-ADMIN-GUIDE.md) | Пользователи, события и интеграции: руководство оператора | 190 строк, 11 заголовков | возможный runtime-срез |
| [VIDEO-CADENCE-CANARY.md](../../../docs/operations/VIDEO-CADENCE-CANARY.md) | Одиночный видеопоток: capture canaries и критерии приёмки | 383 строк, 13 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [VPN-CONTROL-OUTCOMES.md](../../../docs/operations/VPN-CONTROL-OUTCOMES.md) | VPN control: targets, receipts and recovery | 135 строк, 7 заголовков | дата в начале, возможный runtime-срез |
| [VPN-LAN-GATEWAY-CANARY.md](../../../docs/operations/VPN-LAN-GATEWAY-CANARY.md) | Локальный шлюз AWG2: ограниченный canary | 92 строк, 5 заголовков | дата в начале, блоки примеров |
| [VPN-PROFILES.md](../../../docs/operations/VPN-PROFILES.md) | Зашифрованные VPN-профили: контракт и эксплуатация | 385 строк, 10 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [WALK-ROUTE-PILOT.md](../../../docs/operations/WALK-ROUTE-PILOT.md) | Первый пеший повтор по видеозаписи | 154 строк, 5 заголовков | дата в начале, возможный runtime-срез |
| [WEB-ENTRY-GUIDE.md](../../../docs/operations/WEB-ENTRY-GUIDE.md) | Вход в Sphere, обзор и навигация | 160 строк, 8 заголовков | возможный runtime-срез |

### Инциденты

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [01-backend-outage.md](../../../docs/runbooks/01-backend-outage.md) | 01 — Backend недоступен или не готов | 83 строк, 7 заголовков | дата в начале, блоки примеров |
| [02-vpn-incident.md](../../../docs/runbooks/02-vpn-incident.md) | Runbook 02 — VPN incidents and address-pool exhaustion | 141 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [03-database-failure.md](../../../docs/runbooks/03-database-failure.md) | 03 — PostgreSQL: отказ, соединения, миграции, восстановление | 74 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [04-fleet-offline.md](../../../docs/runbooks/04-fleet-offline.md) | 04 — Массово пропали устройства | 147 строк, 10 заголовков | дата в начале, возможный runtime-срез |
| [README.md](../../../docs/runbooks/README.md) | Диагностика и восстановление | 54 строк, 3 заголовков | дата в начале, блоки примеров |

### Безопасность

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [account-credentials.md](../../../docs/security/account-credentials.md) | Доступ к credentials игровых аккаунтов | 131 строк, 7 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [device-credential-bootstrap.md](../../../docs/security/device-credential-bootstrap.md) | Device credentials: tenant discovery and runtime rollout | 123 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [device-refresh-recovery.md](../../../docs/security/device-refresh-recovery.md) | Device refresh: восстановление потерянного ответа | 194 строк, 10 заголовков | дата в начале, блоки примеров |
| [frontend-sessions.md](../../../docs/security/frontend-sessions.md) | Frontend session boundaries | 64 строк, 1 заголовков | дата в начале, возможный runtime-срез |
| [postgresql-rls.md](../../../docs/security/postgresql-rls.md) | PostgreSQL RLS: доказательства и условия внедрения | 201 строк, 8 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [task-control-protocol.md](../../../docs/security/task-control-protocol.md) | DAG control identity and cancellation limits | 149 строк, 3 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [user-auth-bootstrap.md](../../../docs/security/user-auth-bootstrap.md) | User authentication with a non-owner PostgreSQL role | 104 строк, 4 заголовков | возможный runtime-срез, блоки примеров |

### Архитектура агентов

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [ANDROID-BACKGROUND-ENROLLMENT.md](../../../docs/architecture/ANDROID-BACKGROUND-ENROLLMENT.md) | Фоновая регистрация APK и запуск связи | 180 строк, 7 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [ANDROID-BOOTSTRAP-DISCOVERY.md](../../../docs/architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) | APK: смена адресов без переустановки | 155 строк, 6 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [ANDROID-CONNECTION-PROTOCOL.md](../../../docs/architecture/ANDROID-CONNECTION-PROTOCOL.md) | Подтверждение подключения Android APK | 124 строк, 5 заголовков | дата в начале, блоки примеров |
| [ANDROID-DISCOVERY-RECOVERY.md](../../../docs/architecture/ANDROID-DISCOVERY-RECOVERY.md) | Android discovery: восстановление конфигурации | 136 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [ANDROID-EMULATOR-GOLDEN-IMAGE.md](../../../docs/architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md) | Golden image и переносимое клонирование Android-эмуляторов | 430 строк, 22 заголовков | дата в начале, возможный runtime-срез |
| [ANDROID-OTA-RELIABILITY.md](../../../docs/architecture/ANDROID-OTA-RELIABILITY.md) | Отказоустойчивое обновление Android-агента | 308 строк, 11 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [ANDROID-SAVED-ROUTES.md](../../../docs/architecture/ANDROID-SAVED-ROUTES.md) | Сохранённые маршруты Android: основной и резервный | 190 строк, 7 заголовков | дата в начале, блоки примеров |
| [ANDROID-SIGNED-DISCOVERY.md](../../../docs/architecture/ANDROID-SIGNED-DISCOVERY.md) | Подписанная конфигурация Android и резервные источники | 178 строк, 8 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [FLEET-OPERATIONS-AND-OBSERVABILITY.md](../../../docs/architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) | Sphere fleet operations, observability, and media-plane architecture | 1960 строк, 112 заголовков | дата в начале, возможный runtime-срез, блоки примеров |

### Протоколы

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [CONTINUOUS-INPUT-RECEIPTS.md](../../../docs/protocols/CONTINUOUS-INPUT-RECEIPTS.md) | Scoped подтверждения непрерывного ввода | 124 строк, 7 заголовков | дата в начале, возможный runtime-срез |
| [CONTINUOUS-INPUT-SERVER.md](../../../docs/protocols/CONTINUOUS-INPUT-SERVER.md) | Непрерывный ввод: серверный контракт владения и доставки | 194 строк, 8 заголовков | дата в начале, возможный runtime-срез |
| [VIDEO-CAPTURE-V2.md](../../../docs/protocols/VIDEO-CAPTURE-V2.md) | Binary video capture identity, version 2 | 120 строк, 7 заголовков | дата в начале, возможный runtime-срез, блоки примеров |

### Общие руководства

| Файл | Назначение по заголовку | Объём и структура | Индикаторы для ручной проверки |
| --- | --- | --- | --- |
| [android-agent.md](../../../docs/android-agent.md) | Android Agent | 700 строк, 28 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [api-endpoints.md](../../../docs/api-endpoints.md) | Generated HTTP endpoint catalog | 222 строк, 1 заголовков | дата в начале, возможный runtime-срез |
| [api-reference.md](../../../docs/api-reference.md) | API Reference | 1609 строк, 125 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [architecture.md](../../../docs/architecture.md) | Architecture | 378 строк, 30 заголовков | возможный runtime-срез, блоки примеров |
| [configuration.md](../../../docs/configuration.md) | Configuration Reference | 343 строк, 24 заголовков | возможный runtime-срез, блоки примеров |
| [deployment.md](../../../docs/deployment.md) | Deployment Guide | 600 строк, 72 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [development.md](../../../docs/development.md) | Разработка Sphere | 149 строк, 9 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [pc-agent.md](../../../docs/pc-agent.md) | PC Agent | 208 строк, 5 заголовков | дата в начале, возможный runtime-срез, блоки примеров |
| [security.md](../../../docs/security.md) | Security: границы исходной реализации | 203 строк, 19 заголовков | дата в начале, возможный runtime-срез |
| [web-ui-guide.md](../../../docs/web-ui-guide.md) | Web-интерфейс Sphere | 122 строк, 17 заголовков | нужна смысловая сверка |
