# Маршруты, вкладки и действия веб-интерфейса

[Аудит и доказательства](WEB.md) · [Построчный каталог JSON](evidence/web-inventory.json) · [Генератор](evidence/web-inventory.cjs) · [Браузерная загрузка 29 страниц](evidence/web-browser.md)

В каталоге 29 страниц, 5 серверных обработчиков Next.js, 339 файлов TypeScript/TSX, 1 488 JSX-объявлений контролов и 257 распознанных вызовов транспорта. Для каждого файла записан SHA-256 содержимого в рабочем дереве. Маршрут содержит свой входной файл, файлы layout и транзитивные импорты. В записи контрола есть файл, строка, компонент, текст или выражение, свойства доступности, условие отключения и обработчик, если они явно указаны. В записи вызова есть файл, строка, владелец и выражение пути. `api` использует базовый путь `/api/v1` по умолчанию, а `reconstructionRequest` использует отдельный сервис реконструкции.

Одна JSX-строка может развернуться в несколько вкладок или действий, например `VIEWS.map`, строки таблицы и состояние отдельного устройства. Общий компонент может встречаться на нескольких маршрутах. Каталог включает объявления из достижимых импортов и прочих исходников. Условная видимость, реальное число экземпляров, доступность по ролям и исполнение удалённой операции требуют запуска. Выражения в каталоге могут быть усечены, а значения динамических пропсов разрешаются в исходнике. Ссылки на существующие тесты обозначают выборочные сценарии Jest/jsdom.

## Общая оболочка

- [Провайдер сессии](../../../frontend/app/providers.tsx) запускает проверку аутентификации и выбирает `/login` или рабочую область. [Хранилище](../../../frontend/lib/store.ts) вызывает `/auth/refresh` и `/auth/logout`. React Query меняет клиент при смене пользователя, роли, организации или версии сессии. Проверены тесты `session` и `stores/authStore`.
- [Меню](../../../frontend/src/features/navigation/navigationCatalog.ts) содержит 22 пункта. [NOCSidebar](../../../frontend/src/features/navigation/NOCSidebar.tsx) фильтрует их по capabilities и управляет мобильным меню, закреплением, выходом и открытием оформления. [Палитра](../../../frontend/src/features/navigation/GlobalCommandPalette.tsx) добавляет поиск маршрута и переход. [Оформление](../../../frontend/src/features/preferences/AppearanceDrawer.tsx) содержит «Стиль» и «Компоновка». Проверены тесты `navigation` и `stores`.
- [Layout](../../../frontend/app/%28dashboard%29/layout.tsx) подключает навигацию, панель контекста и изменение размера. Сценарии редактора с незаписанными изменениями проходят через [guard](../../../frontend/src/features/navigation/workspaceNavigationGuard.ts). Точки API capabilities доступны из [Capabilities](../../../frontend/src/features/access/Capabilities.tsx).

## Страницы

| Маршрут | Действия и вкладки | Основные границы API или состояния | Выборочные проверки Jest |
|---|---|---|---|
| `/` | Переход на `/dashboard` | Серверный `redirect` Next.js | Код маршрута |
| `/login` | Email, пароль, показать пароль, отправить, MFA-код и возврат | `POST /auth/login`, `POST /auth/login/mfa`, состояние сессии | `session/login`, `session/providers` |
| `/dashboard` | Обновить сводку, повторить загрузку парка, перейти в устройства, события, VPN и мониторинг | `/devices/status/fleet`, `/health`, `/device-events`, `/vpn/pool/stats` | `dashboard/page`, `dashboard/dataFreshness` |
| `/monitoring` | Обновление, ресурсные панели, HTTP-метрики, охват парка, открытие Grafana | `/monitoring/metrics`, `/monitoring/nodes`, `/monitoring/fleet-coverage`, `/api/observability/*`, Grafana proxy | `monitoring/page`, `monitoring/*-panel`, `monitoring/*-server` |
| `/devices` | Таблица, карточки, сетка видео, поиск, группа и локация, состояние, колонки, выбор строк, пагинация, создание и изменение записи, bulk, inspector, удаление с подтверждением | `/devices`, `/devices/{id}`, `/devices/bulk`, `/devices/bulk/action`, `/groups`, `/locations` | `devices/device-list-page`, `devices/action-permissions`, `devices/DeviceBulkDeleteButton`, `devices/multi-stream-grid` |
| `/devices/[id]` | «Обзор», «Задачи», «События», «Видео», «Логи APK», дополнительно профиль Android, терминал, shell, reboot, снимок, UI hierarchy, история потока | `/devices/{id}`, `/devices/{id}/shell`, `/reboot`, `/logcat`, `/screenshot/native`, `/ui-hierarchy`, `/stream-sessions`, `/logs/{id}` | `devices/device-inspector`, `devices/device-interactive-actions`, `devices/native-screenshot`, `stream/inspector-live-workflow` |
| `/stream` | Обновить каталог, размер сетки, поиск, фильтр и сортировка, страницы, начать и остановить просмотр, остановить все, открыть поток | `/devices`, диагностические запросы устройства, WebRTC и сигнальный канал компонентов видео | `devices/multi-stream-grid`, `stream/device-stream-first-frame`, `stream/reconnect`, WEB-10 |
| `/stream/[id]` | Обычный поток, диагностика, качество, Android-навигация, fullscreen, клавиатура и указатель. В `?teach=1` режимы «Запись», «Библиотека», «Направление», управление записью, реконструкцией, просмотром и локализацией | WebRTC, WebSocket, `/devices/{id}/stream-diagnostics`, `/devices/{id}/stream-sessions`, локальная библиотека и worker `/jobs/*` | `stream/*`, включая изменённые тесты `reconstruction-compact`, `route-preparation`, `teaching-review` |
| `/discovery` | CIDR, диапазон портов, workstation UUID, timeout, авторегистрация, поиск, повтор, переход в парк | `POST /discovery/scan`, запрос содержит workstation | `discovery/request-context`, WEB-07 |
| `/fleet` | Переход на `/groups` | Серверный `redirect` Next.js | `groups/legacy-fleet-route` |
| `/groups` | Группы и дерево, создание, редактирование и удаление, перенос устройств, открытие реестра выбранной группы | `/groups`, `/groups/{id}`, `/groups/{id}/devices/move`, `/groups/tags` | `groups/group-hierarchy`, `groups/group-workflows`, `groups/organization-permissions` |
| `/locations` | Список и дерево, создать, изменить, удалить, выбор родителя и сохранение пустых полей | `/locations`, `/locations/{id}`, `/locations/{id}/devices` | `locations/geography`, `locations/edit-clear` |
| `/tasks` | Активные задачи и запуски, поиск истории, фильтр статуса, пагинация, запуск сценария и переход к задаче | `/tasks`, `/pipelines/runs`, `/scripts`, `/batches`, выбор устройства | `tasks/history`, `scripts/run-script-modal` |
| `/tasks/[id]` | Обновить, остановить, повторить, открыть связанный объект, отчёт, журнал, скриншоты и прогресс | `/tasks/{id}`, `/logs`, `/live-logs`, `/screenshots`, `/progress`, `POST /stop`, `POST /rerun` под ID задачи | `tasks/detail-outcomes`, `tasks/rerun`, `tasks/screenshots`, `tasks/cancellation-status`, WEB-11 и WEB-14 |
| `/orchestration` | `Pipelines`, `Pipeline Runs`, `Schedules`. Создать, открыть определение, редактировать, активировать, запуск и batch, pause/resume/cancel, создать и редактировать расписание, история, включение и fire-now | `/pipelines`, `/pipelines/{id}/run*`, `/pipelines/runs/*`, `/schedules`, `/schedules/{id}/executions`, `/schedules/{id}/fire-now` | `orchestration/*`, WEB-01, WEB-02 и WEB-14 |
| `/pipeline-settings` | Обновить, переключатели, параметры регистрации и замены, выбор скриптов, сохранение | `/pipeline-settings`, `/status`, `/servers`, `/toggle/{feature}` и каталог сценариев | `pipeline-settings/settings-write` |
| `/accounts` | Поиск, фильтры, сортировка, страницы, создание, редактирование, импорт, детали, назначение и освобождение, удаление, копирование | `/game-accounts`, `/game-accounts/{id}`, `/stats`, `/servers`, `/import`, `/assign`, `/release` | `accounts/form-search`, WEB-04–06 |
| `/scripts` | Каталог и фильтры, создание, редактирование, удаление, версии, сравнение, rollback, запуск, переход в Studio | `/scripts/catalog`, `/scripts/{id}`, `/scripts/{id}/versions/*`, `/tasks`, `/batches` | `scripts/page`, `scripts/catalog-pagination`, `scripts/version-workflow`, `scripts/run-script-modal` |
| `/scripts/builder` | Граф, палитра действий, узлы и соединения, параметры, импорт/экспорт, валидация, сохранение, запуск, подтверждение выхода | `/scripts/{id}?include_dag=true`, `/scripts/validate`, `POST /scripts` и `PUT /scripts/{id}`, команды записи в рабочей области | `scripts/builder-load`, `scripts/studio-*`, `scripts/action-parameters` |
| `/events` | Фильтры, обновление, выбрать событие, показать детали, отметить обработанным | `/device-events`, `/device-events/stats`, `/device-events/{id}`, `POST /device-events/{id}/processed` | `events/page` |
| `/event-triggers` | Поиск текущей страницы, фильтр активности, страницы, создать, редактировать, включить или выключить, удалить, условия, цели и лимит | `/event-triggers`, `/event-triggers/{id}`, `/event-triggers/{id}/toggle`, выбор pipeline через `/pipelines?per_page=200` | `event-triggers/catalog-pagination`, `event-triggers/read-evidence`, WEB-09 |
| `/sessions` | Поиск текущей страницы, фильтры активности и причины, сортировка, страницы, детали, подтверждение завершения | `/account-sessions`, `/account-sessions/stats`, `/account-sessions/{id}/end` | `sessions/page`, WEB-03 и WEB-08 |
| `/vpn` | «Подключения», «Профили», «Инфраструктура», «Политика трафика». Диагностика «Соединение» и «Идентификаторы», фильтры, страницы, импорт и ревизии профилей, назначение адреса, раскатка и статус | `/vpn/runtime`, `/vpn/profiles`, `/vpn/profiles/{id}/revisions`, `/vpn/profiles/batch/*`, `/vpn/peers`, `/vpn/assign`, `/vpn/health`, политика VPN | `vpn/workspace`, `vpn/runtime`, `vpn/profile-*`, `vpn/control-outcomes`, WEB-12 |
| `/webhooks` | Добавить endpoint, выбор событий, однократное копирование секрета, включить или выключить, удалить с подтверждением, повторить загрузку | `/n8n/webhooks`, `/n8n/webhooks/{id}` | Статический проход, отдельная suite страницы не обнаружена |
| `/users` | Добавить, сменить роль, деактивировать, подтверждение и пагинация | `/users`, `/users/{id}/role`, `/users/{id}/deactivate` | `users/workflows` |
| `/audit` | Фильтры, расследование, ссылки на связанные записи, экспорт CSV, обновление и пагинация | `/audit/logs`, `/audit/logs/export` | `audit/page`, `audit/investigation*` |
| `/logs` | Выбрать устройство, фильтр уровня, поиск, обновление и пауза, очистка с подтверждением | `GET /logs/{id}`, `DELETE /logs/{id}`, каталог и подтверждение ID устройства | `logs/page`, `logs/source-ownership`, WEB-13 и WEB-14 |
| `/updates` | Платформа, публикация релиза, загрузка, история и адресное восстановление устройства | `/updates/`, `/updates/downloads/latest`, `/updates/recovery/{id}/dispatch`, `/devices/{id}` | `updates/catalog-contract`, `updates/release-publication`, `updates/download`, `updates/recovery-workflow` |
| `/settings` | «Профиль», «Безопасность», «API-ключи». Обновить, настроить и подтвердить MFA, выключить MFA, создать, скопировать и отозвать ключ | `/auth/me`, `/auth/mfa/setup`, `/auth/mfa/verify-setup`, `/auth/mfa`, `/auth/api-keys` | `settings/page`, `session/*` |

## Серверные обработчики Next.js

| Маршрут | Метод и владелец |
|---|---|
| `/api/observability` | `GET`, `getObservability` |
| `/api/observability/http` | `GET`, `getHttpMetrics` |
| `/api/observability/resources` | `GET`, `getResourceMetrics` |
| `/api/observability/session` | `POST`, `createGrafanaSession` |
| `/observability/grafana/[[...path]]` | `GET`, `HEAD`, `POST`, `PUT`, `PATCH`, `DELETE`, proxy `handler` |

Динамические состояния WebRTC, Android, VPN, фонового worker, браузерной загрузки и Grafana остаются отдельными end-to-end сценариями. На дату этого прохода ни один маршрут из таблицы не отмечен как полностью проверенный во всех состояниях, ролях и разрешениях экрана.
