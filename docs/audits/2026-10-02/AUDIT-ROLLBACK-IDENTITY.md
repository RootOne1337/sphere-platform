# N05: сохранение идентичности аудита после отказа API

**Дата:** 2 октября 2026, Asia/Yekaterinburg.<br />
**Обнаружение:** backend `a9240a7`, реальные запросы через review3015.

[Текущее состояние](../../operations/CURRENT-STATE.md) · [Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Иерархия групп](../../operations/GROUP-HIERARCHY.md)

## Доказательство проблемы

После установки N04 за конечное окно логов от01:29:03 UTC найдено3 события
`audit_log_write_failed`, `badly formed hexadecimal UUID string`: rejected legacy
discovery POST422, group PUT400 и PUT409. Отказ операции был корректным, но его audit
entry терялся. Три события относятся к контрольным запросам, не доказывают потерю
всех production logs. Полные private logs не публикуются.

`get_db` выполняет rollback при исключении. SQLAlchemy очищает загруженные атрибуты
ORM principal; middleware читал `vars(principal)` после request cleanup. Получалось
`org_id=None`, а background writer пытался привязать tenant `str(None)`.

4 новых PostgreSQL/ASGI regressions на `a9240a7` воспроизвели потерю строки при400,
403,404 и409. Request session использует фактическую production rollback семантику;
audit session — отдельное соединение с реальным non-owner/NOBYPASSRLS login.
JWT authentication и RBAC выполняются реально; token revocation transport в новых
тестах заменён `false`, чтобы тест не зависел от Redis-сети.

## Исправление

После успешной серверной аутентификации зависимости копируют immutable
`AuditIdentity(org_id, user_id)` в request state. Для API key user_id остаётся null;
значения не извлекаются из непроверенных headers/body/token claims. Snapshot содержит
только UUID, не пароль, токен или ORM object. Dev bypass сохраняет тот же путь.

Middleware использует snapshot после завершения запроса. Отдельная audit session
по-прежнему привязывается к tenant до INSERT, status/duration/HTTP code сохраняются.
Неаутентифицированный запрос не создаёт tenant audit. Если custom authentication
provider выставил principal без snapshot, возникает `audit_identity_missing`, а не
тихая подмена пользователя или обращение к expired ORM attributes.

Source:
[identity](../../../backend/core/audit_identity.py),
[authentication](../../../backend/core/dependencies.py),
[middleware](../../../backend/middleware/audit.py),
[новые regressions](../../../tests/production/test_audit_rollback_identity.py).

## Проверки и границы

- Before:4 assertion failures, не fixture/runtime errors. После:24 PostgreSQL tests
  passed:4 новых rollback cases,6 существующих audit tenant/failure cases,4 Host/path
  integrity cases,10 group hierarchy cases.
- Проверка отказа SQL writer сохранена: failure reported, следующий tenant writer
  восстанавливается. Existing unauthenticated and concurrent tenant cases passed.
- Ruff и mypy трёх изменённых backend modules passed.
- API-key branch snapshot реализован, но HTTP endpoint acceptance для него этим
  batch не заявляется: текущие REST routers используют user authentication.
- Background audit всё ещё best effort: авария процесса/DB после business commit
  может потерять запись. Durable outbox/transactional recording — отдельная открытая
  архитектурная работа; этот фикс не обещает exactly-once/durable audit.
- Browser visual, полная матрица permissions и приёмка20–30 Android не заменяются
  ASGI tests. Установка и live audit readback фиксируются отдельным evidence.
