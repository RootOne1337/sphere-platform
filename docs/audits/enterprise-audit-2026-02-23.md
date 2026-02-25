# Enterprise-аудит Sphere Platform (архитектура, безопасность, эксплуатация)

**Дата:** 2026-02-23  
**Формат:** code-centric review (backend/ws/infra/docs) + smoke-checks  
**Глубина:** enterprise-level (security, tenancy, operational resilience, governance)

---

## 1) Executive Summary

Платформа демонстрирует сильную инженерную базу (RLS-концепция, JWT+blacklist, observability-слой, структурированные middleware), но в текущем состоянии есть несколько **критических архитектурных разрывов**, которые не позволяют считать систему production-ready в enterprise-контексте без доработок.

### Общая оценка зрелости (условная)

- **Security posture:** 6.5 / 10
- **Multi-tenant isolation:** 5.5 / 10
- **Operational readiness (SRE):** 7.0 / 10
- **Documentation trustworthiness:** 5.0 / 10
- **Итог:** **Medium risk** c отдельными **High/Critical** зонами.

### Top risks (приоритет 0)

1. **Неавторизованные REST-операции управления стримом** (`/streaming/{device_id}/start|stop|keyframe|status`) — отсутствует `Depends(get_current_user)`/RBAC и tenant-safe session. Это прямой control-plane risk.  
2. **Риск обхода RLS в production-конфигурации**: в RLS SQL явно указано, что superuser обходит политики; compose-конфиг использует `POSTGRES_USER=sphere`, что типично создает суперпользователя.  
3. **Cross-tenant leakage в Fleet snapshot WS**: в коде помечено, что фильтрация по `org_id` упрощена и в реальности нужна DB-фильтрация; сейчас в snapshot может уходить общий набор device IDs/status.  
4. **Долгоживущие agent tokens без expiry-check** в WS agent auth (`type='agent'`, проверка только active/type/hash).

---

## 2) Scope и методология

Проверены:
- Backend core/auth/ws/middleware/dependencies.
- PostgreSQL RLS policy script.
- Docker Compose overlays (dev/prod).
- Security documentation consistency.

Подход:
- Статический code review по критичным путям (authN/authZ/tenanting/ws).
- Конфигурационный аудит infra/compose.
- Документационный gap-анализ (декларируемое vs фактическое).
- Базовый тестовый smoke запуск `pytest -q`.

---

## 3) Детальные findings

## F-01 (Critical): Неавторизованные streaming REST endpoints

**Наблюдение:** роуты `GET /streaming/{device_id}/status`, `POST /start`, `POST /stop`, `POST /keyframe` используют `Depends(get_db)`, но не требуют аутентификацию/авторизацию и не используют tenant-scoped dependency.  
**Риск:** любой доступ до API-layer (внутренний pivot, misrouted ingress, SSRF, compromised frontend tokenless path) может инициировать управление устройством.  
**Доказательство:** `backend/api/v1/streaming/router.py` — отсутствуют `Depends(get_current_user)`/`require_permission(...)`.  
**Рекомендация:**
- Немедленно добавить `current_user=Depends(require_permission("stream:control"))`.
- Использовать `get_tenant_db` вместо `get_db`.
- Для device lookup — обязательно `org_id == current_user.org_id`.
- Добавить audit-log event для `start/stop/keyframe`.

## F-02 (Critical): Возможный системный обход RLS через superuser DB role

**Наблюдение:** RLS script прямо указывает, что superuser обходит политики; compose-конфиги используют пользователя `sphere` как app DB user.  
**Риск:** при superuser-сессии RLS не обеспечивает tenant boundary (defense layer collapses).  
**Доказательство:** `infrastructure/postgres/rls_policies.sql` (комментарий про superuser bypass), `docker-compose.production.yml` и `docker-compose.override.yml` (`POSTGRES_USER:-sphere`).  
**Рекомендация:**
- Разделить роли: `sphere_owner` (migration/admin) и `sphere_app` (NO SUPERUSER, NO BYPASSRLS).
- Принудить backend использовать только `sphere_app`.
- Ввести startup-check: `SELECT rolsuper, rolbypassrls FROM pg_roles ...` с fail-fast.

## F-03 (High): Cross-tenant leakage risk в WS fleet snapshot

**Наблюдение:** в `get_fleet_snapshot` есть комментарий, что фильтрация по `org_id` сейчас упрощена и нужна реальная DB-фильтрация; при этом берутся все tracked ids.  
**Риск:** утечка метаданных fleet между организациями через events websocket snapshot.  
**Доказательство:** `backend/api/ws/events/router.py` (`get_all_tracked_device_ids`, комментарий о необходимости фильтрации по org).  
**Рекомендация:**
- Строить snapshot только по списку устройств org из БД (`SELECT id FROM devices WHERE org_id=:org_id`).
- Redis cache key-space сегментировать по org (`device_status:{org_id}:{device_id}`).
- Добавить integration test на tenant isolation (WS snapshot).

## F-04 (High): Agent token auth без проверки срока действия

**Наблюдение:** `authenticate_agent_token` проверяет только hash/active/type=agent; `expires_at` не проверяется.  
**Риск:** долгоживущие/утекшие токены сохраняют доступ к WS control-plane значительно дольше ожидаемого enterprise-периода.  
**Доказательство:** `backend/api/ws/agent/router.py` (select по `key_hash`, `is_active`, `type`).  
**Рекомендация:**
- Добавить проверку `expires_at IS NULL OR expires_at > now()`.
- Ввести обязательную ротацию (например 30/60/90 дней).
- Поддержать key fingerprinting и scoped permissions для agent-операций.

## F-05 (Medium): Небезопасное default значение JWT secret допускается валидатором

**Наблюдение:** дефолт `JWT_SECRET_KEY = "changeme_jwt_secret_key_at_least_32_chars"`; валидатор блокирует только значения c префиксом `CHANGE_ME` (uppercase) или длиной < 32.  
**Риск:** в misconfigured окружениях система может стартовать с предсказуемым secret.  
**Доказательство:** `backend/core/config.py` (default + validator).  
**Рекомендация:**
- Убрать небезопасный default (обязательная env переменная).
- Проверять case-insensitive шаблоны (`changeme`, `default`, `example`).
- Fail-fast на startup при небезопасном секрете.

## F-06 (Medium): Расхождение security-документации и фактической реализации

**Наблюдение:** security docs декларируют механизмы (например lockout policy/форматы ключей/strict patterns), которые частично не совпадают с текущим кодом.  
**Риск:** governance-risk: ложное чувство защищенности, некорректные аудиторские артефакты.  
**Доказательство:** `docs/security.md` vs `backend/services/auth_service.py`, `backend/services/api_key_service.py`, `backend/core/security.py`, `backend/core/cors.py`.  
**Рекомендация:**
- Ввести policy-as-code checklist для release gate.
- Обновлять security.md только из проверяемых source-of-truth (automated docs extraction или ADR-linking).

---

## 4) Архитектурная оценка по доменам

### 4.1 Identity & Access

**Сильные стороны:**
- JWT с `jti`, blacklist check, refresh rotation.
- MFA step-up flow для login.

**Пробелы enterprise-уровня:**
- Неравномерное применение authZ across routers.
- Нет централизованного enforcement policy (например, route linter на обязательный auth dependency).

### 4.2 Multi-tenancy

**Сильные стороны:**
- Есть `SET LOCAL app.current_org_id` паттерн.
- Есть RLS policy layer на набор критичных таблиц.

**Пробелы:**
- Надежность слоя зависит от DB role hardening.
- Не все runtime paths строго tenant-scoped (особенно ws snapshot/часть service-контуров).

### 4.3 WebSocket security

**Сильные стороны:**
- first-message auth (не query-param token).
- timeout на auth handshake.

**Пробелы:**
- Token lifecycle для agents не enterprise-hard.
- Частично отсутствует полноценный authorization matrix для message types.

### 4.4 Operations / SRE

**Сильные стороны:**
- Prometheus middleware, readiness checks, logging context.

**Пробелы:**
- Нет явных startup guards на security invariants (JWT secret, DB role attributes, required secrets).
- Test pipeline неустойчив (pytest collection ловит бинарный `test_results.txt`).

---

## 5) Рекомендуемый remediation roadmap (30/60/90)

### 0–30 дней (P0)
1. Закрыть streaming REST endpoints authZ + tenant checks.
2. Разделить DB роли; backend user без superuser/bypassrls.
3. Исправить fleet snapshot org filtering.
4. Добавить expiry/rotation для agent tokens.
5. Включить startup fail-fast checks по security baseline.

### 31–60 дней (P1)
1. Ввести contract tests на authN/authZ для каждого router.
2. Security regression suite (tenant isolation, WS auth, token revocation).
3. SAST/secret scanning в CI (bandit/semgrep/trufflehog/gitleaks).

### 61–90 дней (P2)
1. Формальный threat-model refresh и tabletop exercises.
2. Centralized policy engine (OPA/Cedar-style) для route/message authorization.
3. Compliance evidence automation (SOC2/ISO27001 ready artifacts).

---

## 6) Быстрые KPI для контроля исправлений

- % API routes with explicit auth dependency: **target 100%**.
- # cross-tenant leak tests passed: **target 100%**.
- Mean age of active agent keys: **target < 45 days**.
- Security-doc drift SLA: **target < 7 дней** между изменением кода и docs.

---

## 7) Приложение: выполненные проверки

- `pytest -q` → завершился с ошибкой коллекции из-за бинарного `test_results.txt`.
- Просмотрены критичные файлы: `backend/api/v1/streaming/router.py`, `backend/api/ws/events/router.py`, `backend/api/ws/agent/router.py`, `backend/core/config.py`, `infrastructure/postgres/rls_policies.sql`, `docker-compose.production.yml`, `docker-compose.override.yml`, `docs/security.md`.

