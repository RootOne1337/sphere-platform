# 03 — PostgreSQL: отказ, соединения, миграции, восстановление

**Обновлено 10 сентября 2026.** [Общий порядок](README.md) ·
[RLS/roles rollout](../security/postgresql-rls.md) · [Backend](01-backend-outage.md)

## Сначала установить причину

Используйте контейнер, database и роль именно этой установки. Старые имена
`sphere_postgres`, `sphere_user`, `sphere_db` не были текущим Compose-контрактом.
`pg_wal` — не доказательство настроенного внешнего WAL archive или backup.

```powershell
docker compose -f docker-compose.yml -f docker-compose.full.yml ps --all postgres
docker compose -f docker-compose.yml -f docker-compose.full.yml logs --since 15m --tail 200 --timestamps postgres backend
```

Сопоставьте ошибку: connection refused/reset, authentication failure, pool timeout,
statement timeout, lock wait, disk full, corruption или migration mismatch.
`backend/database/engine.py` использует settings `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
`DB_POOL_TIMEOUT`; параметры умножаются на число процессов backend. Статические
числа pool из старого runbook не являются настройкой вашей установки.

Для PostgreSQL operator session с корректными credentials доступны read-only запросы:

```sql
SELECT state, wait_event_type, count(*)
FROM pg_stat_activity
GROUP BY state, wait_event_type;

SELECT pid, state, wait_event_type, wait_event,
       now() - xact_start AS transaction_age
FROM pg_stat_activity
WHERE xact_start IS NOT NULL
ORDER BY xact_start;

SELECT version_num FROM alembic_version;
```

Не прикладывайте полный query text к инциденту без проверки содержимого. Runtime
роль может не видеть чужие sessions/tenant rows; отсутствие строк не доказывает
потерю данных. Это диагностическое различие, а не повод запускать приложение owner.

## Миграции

Head на этом срезе — `20260909_user_auth_bootstrap`. Сверьте с текущим checkout и
`alembic -c alembic/alembic.ini heads`; `current` выполняйте с migration credentials
в подготовленной среде. Failed migration и failed runtime SELECT — разные сбои.
Часть migrations намеренно запрещает небезопасный downgrade. Подробности в
[credential runbook](../security/user-auth-bootstrap.md) и [RLS guide](../security/postgresql-rls.md).

## Восстановление

- Pool/locks: найдите владельца долгой транзакции и её работу; blanket
  `pg_terminate_backend` не является стандартным лечением. Проверяйте rollback и
  повтор с тем же task/receipt identity после адресного решения.
- Disk/corruption: сохраните state/evidence, остановите новые записи согласованным
  способом; восстановление выполняется по проверенному backup procedure. Не удаляйте
  `postmaster.pid`, WAL или volumes наугад.
- Crash: restart после установленной причины, затем SQL readiness и representative
  read/write. Успешный `pg_isready` не подтверждает schema/data correctness.

Backup/restore drill должен идти в отдельную БД/volume, без перезаписи текущей.
Нужны проверка checksum, migration state, role/grants, representative tasks/receipts,
account encryption keys, VPN held intents и reconciliation с внешними эффектами.
Затем измеряется RPO/RTO и принимается план cutover. Hourly backups и 30-minute RTO
в репозитории не подтверждены; расписание и recovery target предстоит утвердить.

## После восстановления

Проверить user/device auth, создание/получение результата одной задачи, отсутствие
повторного исполнения после retry, сохранность unresolved intents и стабильный pool.
Сохранить incident timeline и isolated regression, а не только факт restart.
