# Security: границы исходной реализации

Срез исходников: `555b620a`. Документ — навигация по реализованным механизмам и
важным ограничениям, не аттестация deployed среды и не гарантия безопасности.
Настройки конкретной установки, применённые миграции, роль БД, ingress и версии
компонентов необходимо проверять отдельно. Для сообщения об уязвимости используйте
[политику репозитория](../SECURITY.md); записанные наблюдения и открытые условия —
в [текущем состоянии](operations/CURRENT-STATE.md) и [readiness](operations/READINESS.md).
[Реестр сверки security-документации](audits/2026-11-01/SECURITY-DOCUMENTATION-COVERAGE.md)
фиксирует источники и границы этой проверки.

## Table of Contents

1. [Threat Model](#1-threat-model)
2. [Authentication](#2-authentication)
3. [Authorization (RBAC)](#3-authorization-rbac)
4. [Data Encryption](#4-data-encryption)
5. [Network Security](#5-network-security)
6. [Input Validation](#6-input-validation)
7. [Audit & Logging](#7-audit--logging)
8. [Secret Management](#8-secret-management)
9. [Dependency Security](#9-dependency-security)
10. [Security Checklist](#10-security-checklist)
11. [Vulnerability Response](#11-vulnerability-response)
12. [v4.3–4.6 Security Enhancements](#12-v4346-security-enhancements)

## 1. Threat Model

Среди защищаемых данных и действий: учётные данные, API- и device-токены,
управление устройствами, конфигурации VPN, сценарии и журнал аудита. Важные
границы проходят между браузером, backend, базой, устройством и сторонними сетями.
Эта краткая карта не перечисляет все атаки и не заменяет отдельную модель угроз
для конкретной конфигурации. Компрометация хоста, произвольный SQL с полномочиями
runtime, XSS и доступ администратора к окружению требуют отдельной оценки.

## 2. Authentication

### JWT Implementation

Исходные настройки в [config.py](../backend/core/config.py): по умолчанию HS256,
access TTL 30 минут и refresh TTL 7 дней; значения конфигурируются. Access JWT
содержит `sub`, `org_id`, `role`, `jti`, `type`, `iat`, `exp` и подписывается
`JWT_SECRET_KEY`; реализация — [security.py](../backend/core/security.py).
Срок cookie в router задан отдельно, его не следует считать доказательством
фактической настройки TTL SQL refresh-токена.

Refresh token — случайное непрозрачное значение; его SHA-256 hash и состояние
хранятся в SQL, при успешном refresh происходит ротация. Redis также используется
для других auth-задач, включая blacklist access JTI и MFA state, но это не место
хранения SQL refresh records. [Bootstrap пользователей](security/user-auth-bootstrap.md)
описывает tenant lookup, отзыв и границы конкурентности.

[Auth router](../backend/api/v1/auth/router.py) устанавливает HttpOnly cookie:
`Secure` при `COOKIE_SECURE` или HTTPS request, `SameSite=None` если secure и
`SameSite=Lax` иначе. Login/refresh также возвращают refresh token в теле ответа;
[frontend](security/frontend-sessions.md) сохраняет этот токен в `localStorage` как
fallback. Эта копия доступна JavaScript и не получает защиты HttpOnly. Фактические
атрибуты и работа через прокси/CORS зависят от установки и browser policy.

### MFA (TOTP)

[MFAService](../backend/services/mfa_service.py) проверяет TOTP с `valid_window=1`.
Setup сохраняет временный секрет в Redis и после проверки кода присваивает его
полю `users.mfa_secret` в БД ([router](../backend/api/v1/auth/router.py),
[model](../backend/models/user.py)). В этом пути не показано прикладное Fernet
шифрование TOTP-секрета. Заявлять наличие backup codes и защищённое шифрование
секрета без отдельной реализации и проверки нельзя. Физическое шифрование диска
и контроль доступа к базе/Redis зависят от среды.

### Brute Force Protection

[AuthService.login](../backend/services/auth_service.py) вызывает Redis limiter с
`max_requests=5`, `window_seconds=60` по IP. Как определяется IP через прокси,
поведение при отказе Redis и защита других точек входа нужно проверять отдельно.
Это не доказательство ранее упоминавшейся 15-минутной блокировки аккаунта.

### Password Policy

[Схемы пользователей](../backend/schemas/auth.py) задают границы длины 8–128;
[hash_password](../backend/core/security.py) использует bcrypt с cost 12. Это не
подтверждает ограничения или обработку паролей всех внешних систем и агентов.

### API Keys

Генератор создаёт `sphr_{env}_{64 hex}`, где случайная часть — 32 байта; в SQL
сохраняется SHA-256 hash, а полное значение возвращается при создании.
Ключ относится к организации и содержит список permissions; сервер ограничивает
делегирование разрешениями создавшего оператора. Пустой список не означает полный
доступ. Источники: [security.py](../backend/core/security.py),
[api_key_service.py](../backend/services/api_key_service.py),
[auth router](../backend/api/v1/auth/router.py).

В [get_current_principal](../backend/core/dependencies.py) при наличии `X-API-Key`
ключ проверяется раньше Bearer; это свойство **этой зависимости**, не утверждение,
что каждый endpoint принимает ключ или использует такой приоритет. Конкретный
маршрут может требовать user JWT или отдельный device credential.

## 3. Authorization (RBAC)

[RBAC](../backend/core/rbac.py) и зависимости маршрутов проверяют роли или
permissions. Проверка может отличаться по endpoint: например, пользователи
используют `require_roles`, а webhook CRUD — текущего авторизованного пользователя
с привязкой к организации. Нельзя выводить защиту конкретного маршрута из наличия
общего middleware или скрытой кнопки. Смотрите router и профильный контракт.

PostgreSQL RLS и tenant context ограничивают доступ runtime-роли **при правильном
развёртывании и привязке проверенного tenant**. Не все таблицы имеют `org_id`;
ассоциативные таблицы и `organizations` требуют других правил. SQL caller с
правом самостоятельно установить tenant GUC может выбрать другой tenant, а owner,
SUPERUSER или BYPASSRLS изменяют гарантии. Поэтому RLS не обещает защиту от
произвольного SQL под скомпрометированными credentials. Условия внедрения,
проверки и исключения — в [postgresql-rls.md](security/postgresql-rls.md).

## 4. Data Encryption

- Пароли пользователей хешируются bcrypt. TOTP secret в исследованном пути хранится
  в поле модели без показанного прикладного шифрования.
- Пароли игровых аккаунтов используют отдельный `ACCOUNT_CREDENTIAL_KEYS` key ring
  и привязанный к организации/аккаунту envelope; см. [account credentials](security/account-credentials.md).
- В VPN-коде есть отдельные механизмы для peer key и каталога профилей; не считайте
  `VPN_KEY_ENCRYPTION_KEY` универсальным ключом всех секретов. См. [VPN profiles](operations/VPN-PROFILES.md).
- Шифрование файлов БД, хранилищ, бэкапов и каналов между сервисами зависит от
  выбранной среды; проверить это только по исходникам нельзя.

## 5. Network Security

[Production nginx configuration](../infrastructure/nginx/nginx.conf) содержит
TLS и ограничения запросов, но существуют другие dev/review/remote конфигурации.
Наличие файла не подтверждает, что он установлен, что все внешние пути защищены
TLS или что конкретные порты закрыты. Проверяйте фактический ingress, сетевые
маршруты, сертификаты, firewall и доверенные proxy headers для выбранной среды.

[CORS](../backend/core/cors.py) по умолчанию содержит localhost origins и читает
дополнительные значения `CORS_EXTRA_ORIGINS`; не предполагайте фиксированный список
или отсутствие ошибочной конфигурации. Для VPN не следует объявлять абсолютный
kill switch на основе архитектурного примера: подтверждённые границы отдельных
режимов указаны в [результатах управления VPN](operations/VPN-CONTROL-OUTCOMES.md)
и конкретных датированных испытаниях.

## 6. Input Validation

FastAPI/Pydantic schemas, типизированные идентификаторы и frontend формы помогают
проверять данные, но правила `extra`, типы и обработка ошибок зависят от схемы.
TypeScript-типы не валидируют произвольный JSON во время выполнения. JSX escaping
не является общей гарантией отсутствия XSS, SQL injection или небезопасного
выполнения команд. Для каждого маршрута и исполнения на устройстве проверяйте
конкретный контракт и тесты; [HTTP OpenAPI](openapi.json) описывает объявления,
а не все runtime проверки.

## 7. Audit & Logging

[Audit middleware](../backend/middleware/audit.py) обрабатывает определённые
mutating HTTP methods, исключает заданные пути и требует установленную audit
identity. Запись выполняется в отдельной сессии после ответа; ошибка записи
логируется. Это **best-effort**, а не гарантия, что каждое изменение или отказ
долговечно записаны. Не все данные доступны до установления tenant. Требования к
чтению/экспорту — [Audit investigation](operations/AUDIT-INVESTIGATION.md),
ограничения RLS — [PostgreSQL RLS](security/postgresql-rls.md).

Runtime audit policies запрещают UPDATE/DELETE в описанном tenant scope, но это
не доказательство неизменяемости журнала для владельца БД, администратора хоста
или любой внешней системы. Настройку и retention логов проверяйте в своей среде.

## 8. Secret Management

Не храните реальные `.env`, токены, ключи, credentials, дампы или сырые логи в
публичном репозитории и issue. Используйте отдельный управляемый secret store и
процедуры ротации, совместимые с конкретным компонентом. Key ring игровых
аккаунтов и VPN требуют отдельного планирования: замена или потеря ключей влияет
на чтение сохранённых данных. Примеры интеграции с Vault, облачными хранилищами
или HSM не означают, что они настроены в проекте или вашей установке.

## 9. Dependency Security

[Backend CI](../.github/workflows/ci-backend.yml) содержит Bandit и pip-audit;
[pre-commit](../.pre-commit-config.yaml) включает detect-secrets. Наличие конфигурации
не доказывает, что hooks установлены или что hosted CI выполняется и прошёл для
конкретного commit. Не заявляются фиксированные сроки обновлений и автоматическая
генерация полноценного SBOM: действующий состав checks и артефактов надо проверять
в workflows и конкретном run.

## 10. Security Checklist

Для каждого изменения проверьте его реальные контракты: границы tenant и роль БД,
серверные права и тип principal, обработку секретов, ошибки и неизвестные исходы,
путь данных, ограничение доступа и соответствующие тесты. Перед rollout отдельно
проверьте миграции, резервное восстановление, настройку ingress, credentials и
установленные версии. Успешный тест или health endpoint не доказывают отсутствие
уязвимостей или готовность production.

## 11. Vulnerability Response

Порядок приватного сообщения — в [SECURITY.md](../SECURITY.md). Проект не объявляет
фиксированные SLA ответа или исправления и не публикует вымышленный почтовый адрес
из старого шаблона. Не отправляйте секреты или воспроизводимый exploit в публичный issue.

## 12. v4.3–4.6 Security Enhancements

Прежние утверждения о версиях, времени reconnect, tunnel, числе тестов и механизмах
защиты относятся к историческим описаниям; не используйте их как текущую приёмку.
Датированные результаты и доказательства сохраняются в [архиве аудитов](audits/).
Актуальность каждого поведения проверяется по исходникам соответствующей ревизии
и конкретному записанному наблюдению, а не номеру старого документа.
