# Сверка security-документации с исходниками

Срез: **1 ноября 2026**, исходный `HEAD` `555b620a` и рабочее дерево на момент
сверки. Это проверка существенных документальных утверждений и выбранных путей
кода; не полная оценка безопасности, не анализ всех маршрутов и не проверка
установленной среды. База, сеть, учётные записи и устройства не изменялись.

## Исправленные расхождения

| Область | Ранее в [обзоре security](../../security.md) | Подтверждённая граница исходников |
| --- | --- | --- |
| Refresh token | Redis и недоступный JavaScript `SameSite=Strict` cookie. | [Auth service](../../../backend/services/auth_service.py) хранит SHA-256 refresh в SQL и ротирует; [router](../../../backend/api/v1/auth/router.py) устанавливает HttpOnly cookie с `SameSite=None` при secure и Lax иначе, а [frontend store](../../../frontend/lib/store.ts) сохраняет body refresh в localStorage как fallback. |
| MFA | Секрет TOTP якобы Fernet и 10 backup codes. | [Router](../../../backend/api/v1/auth/router.py) присваивает pending secret в `users.mfa_secret`, [model](../../../backend/models/user.py) содержит string поле; прикладное шифрование в исследованном пути не показано. [MFA service](../../../backend/services/mfa_service.py) реализует TOTP; заявленную систему backup codes эта сверка не подтвердила. |
| API key | bcrypt и наследование роли; приоритет перед JWT на всех routes. | [security.py](../../../backend/core/security.py) генерирует случайный ключ и SHA-256 hash; [auth router](../../../backend/api/v1/auth/router.py) принимает permissions и ограничивает делегирование. Приоритет описан для конкретной [зависимости](../../../backend/core/dependencies.py), не всех endpoints. |
| Login limit | 10/min через slowapi и 15-минутная блокировка аккаунта. | [Auth service](../../../backend/services/auth_service.py) запрашивает Redis limiter: 5 запросов по IP и окно 60 секунд. Поведение за proxy и при отказе Redis — отдельная проверка. |
| RLS | Абсолютная межорганизационная изоляция даже при произвольном SQL и общая org_id колонка у всех моделей. | [RLS contract](../../security/postgresql-rls.md) различает organization, tenant rows и M2M; необходимы корректная роль/привязка. Произвольный SQL caller с правом SET tenant GUC может выбрать tenant; owner/BYPASSRLS меняет гарантии. |
| Audit | Каждое изменение обязательно записывается, журнал неизменяем для всех. | [Middleware](../../../backend/middleware/audit.py) исключает пути, требует audit identity и сохраняет запись в отдельной фоновой сессии с обработкой ошибок. Это best-effort; ограничения runtime policies не доказывают неизменяемость для владельца БД. |
| Network и криптография | Общий hardware kill switch, все соединения/TOTP зашифрованы, известные настройки TLS в каждой установке. | [Nginx](../../../infrastructure/nginx/nginx.conf), [CORS](../../../backend/core/cors.py), [VPN](../../operations/VPN-CONTROL-OUTCOMES.md) и [account credentials](../../security/account-credentials.md) описывают разные реализации и границы; конкретное deployed состояние отдельно. |
| Уязвимости и SLA | Примерный адрес и обещанные сроки ответа и исправления. | [Реальная политика](../../../SECURITY.md) направляет в приватный GitHub advisory и не обещает сроки. |

В [continuous server](../../protocols/CONTINUOUS-INPUT-SERVER.md) и
[receipts](../../protocols/CONTINUOUS-INPUT-RECEIPTS.md) компонентные ограничения
раннего checkpoint отделены от последующей интеграции: на дату проверки исходников
[startup](../../../backend/websocket/startup.py) вызывает continuous runtime.
Исторический live receipt не является подтверждением текущей установки. В
[task control](../../security/task-control-protocol.md) исправлена формулировка
об установленном backend 2 октября: это датированное наблюдение, не текущий readback.

## Реестр проверенных источников

| Документ | Основа и охват | Открытая граница |
| --- | --- | --- |
| [Frontend sessions](../../security/frontend-sessions.md) | [auth router](../../../backend/api/v1/auth/router.py), [store](../../../frontend/lib/store.ts), [API](../../../frontend/lib/api.ts). Fallback в localStorage согласуется с кодом. | Не проверялись browser cookie/CORS и живой logout. |
| [User auth bootstrap](../../security/user-auth-bootstrap.md) | [AuthService](../../../backend/services/auth_service.py), отдельные SQL/Redis границы. | Старые evidence привязаны к своим ревизиям; не подтверждают текущие grants и runtime. |
| [Device credential bootstrap](../../security/device-credential-bootstrap.md), [device refresh recovery](../../security/device-refresh-recovery.md) | Документированные границы tenant lookup и операции ротации, прошлые regression evidence. | Не выполнялись новые PostgreSQL/Android recovery tests и миграция. |
| [PostgreSQL RLS](../../security/postgresql-rls.md) | Tenant GUC, ограничения роли и отдельных таблиц. | Не проводилась проверка текущих DB role, policies, FORCE RLS и конфигурации сервера. |
| [Account credentials](../../security/account-credentials.md) | [router](../../../backend/api/v1/game_accounts/router.py), [cipher](../../../backend/services/account_credentials.py), отдельный key ring. | Действительное наличие ключей, миграция всех строк и работоспособность установленного device dispatch не проверены. |
| [Task control](../../security/task-control-protocol.md) | Датированные source/rollout boundaries и разделение принятия команды от device outcome. | Не повторялись cancellation/race tests и приёмка на устройстве. |
| [Android connection](../../architecture/ANDROID-CONNECTION-PROTOCOL.md), [signed discovery](../../architecture/ANDROID-SIGNED-DISCOVERY.md), [bootstrap design](../../architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) | Требование `auth_ok`, опциональный signed discovery, старые evidence и оговорки о среде. | Не проверялись установленный APK, подпись конфигурации на действующем endpoint и live connectivity. |
| [Continuous input server](../../protocols/CONTINUOUS-INPUT-SERVER.md), [receipts](../../protocols/CONTINUOUS-INPUT-RECEIPTS.md) | [startup](../../../backend/websocket/startup.py), [runtime](../../../backend/websocket/continuous_runtime.py); исправлено смешение checkpoint и integration. | Не проверялись фактические flags, устройства, arbitration и native outcome. |

## Остаток

MFA-секрет в исследованном пути требует отдельного проектного и security review;
исправление кода, миграция секретов и оценка всех реплик/бэкапов не входили в эту
сверку. Не утверждается наличие или отсутствие иных компенсирующих мер окружения.
Требуют отдельного анализа все маршруты на единообразие авторизации, XSS и
хранение browser credentials, права SQL runtime, защищённость Redis и журналов,
а также фактическая настройка TLS/CORS и правила VPN на реальном устройстве.

Проверка relative inline paths этих документов не проверяет anchors, external URLs,
семантику, визуальный рендеринг или production. Git и все источники могут измениться
после этого снимка; пересмотрите вывод при изменении кода или конфигурации.
