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

`20260910_device_refresh_retry` был head сентябрьского среза, а не утверждение
о текущем checkout. Определите его heads командой
`alembic -c alembic/alembic.ini heads`; `current` выполняйте с migration credentials
в подготовленной среде. Failed migration и failed runtime SELECT — разные сбои.
Часть migrations намеренно запрещает небезопасный downgrade. Подробности в
[user credential runbook](../security/user-auth-bootstrap.md),
[device refresh rollback](../security/device-refresh-recovery.md) и [RLS guide](../security/postgresql-rls.md).

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

### Что включить помимо основной базы

Состав зависит от реально выбранного Compose project, overlays и внешних сервисов.
Имена ниже — логические имена в исходниках, а не доказательство существования,
фактического местоположения или резервного копирования томов установки.

| Данные | Что проверить в выбранной установке |
| --- | --- |
| OTA catalog и APK | `SPHERE_UPDATES_PATH` указывает на catalog; managed APK лежат в соседнем `artifacts/<sha256>.apk`. В `full` используется bind mount `./backend/updates`; production и local-pilot overlays заменяют его на `ota_data`. Сохраните согласованную пару catalog/artifacts и проверьте hash каждого нужного APK; внешние HTTPS URL требуют отдельной защиты и проверки источника. Отсутствующий catalog API читает как пустой список — это не подтверждение, что релизов не было. |
| Task screenshots / object storage | Base Compose хранит данные своего MinIO в `minio_data`, но backend использует отдельно настроенный `SCREENSHOT_STORAGE_ENDPOINT` и credentials; это может быть другое S3-compatible хранилище либо отключённая функция. Сопоставьте task `screenshot_key` с объектами bucket `sphere-screenshots`; проверьте необходимые policies, версии/метаданные и восстановление доступа в зависимости от сервиса. Только дамп PostgreSQL объекты не восстанавливает. |
| Device logs | `full`, production и local-pilot указывают `SPHERE_LOGS_DIR=/var/lib/sphere/device-logs` с `device_logs`; другие запуски могут использовать другой путь. Сохранение и retention определяются требованиями установки. [Контракт](../operations/DEVICE-LOG-STORAGE.md). |
| n8n | Base Compose настраивает отдельную PostgreSQL database `n8n`, том `n8n_data` и `N8N_ENCRYPTION_KEY`; дамп одной базы приложения не включает другую базу. При необходимости восстанавливайте связанные данные и ключ с проверкой совместимости. |

Подготовьте согласованный recovery point для связанных БД и файлов/объектов с
учётом параллельных записей и незавершённых внешних операций. Обычное копирование
активного тома или успешное существование named volume само по себе не доказывает
целостный backup. Для drill используйте отдельные БД, volume и bucket/хранилище,
изолированные от действующих writers и устройств; проверьте catalog, APK hashes,
доступ к репрезентативным объектам и соответствие ссылок восстановленным данным.
Применимость, полнота и безопасный метод backup/restore MinIO или внешнего S3 в
репозитории не подтверждены: выберите и испытайте их для конкретной установки,
включая независимое хранение и защиту копий/ключей. Не выдавайте этот список за
уже выполненную проверку восстановления.

### Ограничения существующего backup-скрипта

[`scripts/backup-database.sh`](../../scripts/backup-database.sh) — не проверенная
процедура восстановления. Перед его применением нужен отдельный review и
изолированное испытание:

- Скрипт жёстко задаёт имена PostgreSQL/Redis контейнеров и базу `sphereplatform`,
  не выбирает Compose project и не читает выбранный launcher env-файл. Он может
  обратиться не к той установке или завершиться ошибкой.
- PostgreSQL dump одной базы создаётся без владельцев и привилегий; роли, grants,
  другие базы (в том числе `n8n`), ключи шифрования, OTA, объекты MinIO/S3 и
  файлы устройств не покрываются. Ошибка
  pipeline может оставить частичный выходной файл.
- Успешность `BGSAVE` игнорируется, затем скрипт ждёт фиксированные три секунды
  и копирует файл. Это не доказывает завершение нового snapshot или его
  согласованность с PostgreSQL; отсутствие обоих Redis-файлов не останавливает скрипт.
- Скрипт выполняет удаление в каталоге backup по `find`, в том числе для имён
  `redis_*`. Его выражение не применяет возрастной фильтр и `-delete` к ветке
  `pg_*.sql.gz` из-за приоритета `-o`. Сообщение о ротации не подтверждает
  ожидаемое хранение PostgreSQL backups; не запускайте его в каталоге, где
  удаление недопустимо.
- Подсказки `--dir /путь` и `--keep 14` в самом скрипте не соответствуют parser:
  он распознаёт только формы `--dir=...` и `--keep=...`, неизвестные аргументы
  молча пропускает. Если передать одновременно `--pg-only` и `--redis-only`,
  обе стадии копирования пропускаются, а ротация всё равно выполняется.

Это вывод из исходного кода, без запуска скрипта и без проверки фактических
backup-файлов. Успешный вывод не заменяет проверку содержимого и изолированный
restore с нужными ролями, ключами и версиями.

## После восстановления

Проверить user/device auth, создание/получение результата одной задачи, отсутствие
повторного исполнения после retry, сохранность unresolved intents и стабильный pool.
Сохранить incident timeline и isolated regression, а не только факт restart.
