# AUD-136: расписания под RLS и атомарное восстановление после сбоя

**21 сентября 2026 · High / P0 до runtime-role rollout · продолжение F32-25.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Task dispatcher](TASK-DISPATCH-RLS.md) · [Readiness](../../operations/READINESS.md) · [Порядок запуска](../../operations/STARTUP.md)

## Подтверждённые дефекты

На исходниках `57f2730` семь новых regressions упали до изменения scheduler,
без ошибок setup. Настоящая non-owner/NOBYPASSRLS роль использует пул из одного
соединения. Для проверки остальных дефектов отдельно задан tenant context:
невидимость строк не маскирует ошибки обработки.

| Дефект | Root cause | Evidence/reproduction до fix |
| --- | --- | --- |
| Расписания не исполняются под RLS | `_tick` открывает Session без tenant context | Due exhausted schedule остаётся active; SCRIPT и PIPELINE schedules не создают ни child, ни execution receipt — три failures |
| Ошибка обработчика не откатывает запуск | Общая транзакция для страницы; exception перехватывается, затем общий commit | После создания/flush дочерней работы принудительно выброшен RuntimeError; Task, execution и `total_runs=1` всё равно сохранены |
| `only_online` игнорируется при отказе Redis | При отсутствующем клиенте или ошибке presence возвращается весь список устройств | Без Redis создан запуск, хотя доступность устройства неизвестна |
| Проверка предыдущего запуска падает | `func.make_interval(secs=...)` использует неподдерживаемый keyword в SQLAlchemy | После первого запуска следующая проверка SKIP получает `Function.__init__() got an unexpected keyword argument 'secs'` |
| Пропущенный интервал остаётся просроченным | Расчёт использует старый `last_fired_at`, не пропуская уже прошедшие интервалы | При положительном результате conflict check сохранён SKIPPED receipt, но `next_fire_at` остаётся в прошлом |

Первые три RLS failures дополняют историческую
[scheduler-пробу](evidence/scheduler-rls.json). Отказ после flush — управляемая
инъекция сбоя границы транзакции, не утверждение о конкретном инциденте на pilot.
Исполнение DAG на Android для этих доказательств не требуется.

## Исправление и контракт

`sphere_auth.schedule_work(uuid)` возвращает до 50 пар schedule/tenant UUID.
Функция доступна только по отдельному grant, не возвращает параметры или DAG,
имеет фиксированный search_path. Worker обходит due schedules с keyset cursor;
необрабатываемая первая страница не скрывает следующую бесконечно.

Каждое расписание получает свою tenant-bound Session и транзакцию. Под
`FOR UPDATE SKIP LOCKED` повторно проверяются tenant, active и due time.
Создание batch/children, execution receipt, cancellation intent и изменение
счётчика/следующего времени коммитятся вместе. Любое исключение до commit
откатывает весь этот запуск; соседние расписания обрабатываются независимо.
После неизвестного результата commit следующий tick читает сохранённое состояние.
Немедленного слепого replay нет. Удаление RLS или BYPASSRLS не требуется.

Runtime tick больше не отправляет вспомогательную Redis enqueue после commit:
сохранённые Tasks подхватывает SQL-диспетчер AUD-135. Это проверено передачей
созданной scheduler задачи через настоящий TaskService под рабочей ролью, с
transport double. Отказ Redis не может превратить незакоммиченную задачу в запуск.
Legacy enqueue-ветви внутреннего helper вне `_tick` этим изменением не удаляются.

Для `only_online` presence читается через MGET порциями до 512 devices под общим
двухсекундным deadline. Нет клиента, ошибка или timeout — весь firing остаётся
pending. Успешное чтение с offline-устройствами даёт обычный SKIPPED/отфильтрованный
запуск. Ошибка presence после CANCEL_PREVIOUS откатывает и новый cancel intent.

SQL-проверка активности предыдущих Tasks использует interval arithmetic.
SKIP переводит интервальное расписание к следующему будущему слоту, сохраняя
каденцию и прежний `last_fired_at`: пропуск не записывается как реальное исполнение.
Потерянные временные слоты автоматически не проигрываются пачкой.

До четырёх schedules обрабатываются параллельно; discovery ограничен пятью
секундами, один firing — 15 секундами. Presence удерживает транзакцию schedule,
поэтому ограничен отдельно. Пауза между ticks — пять секунд после обработки;
это не обещание пятисекундной задержки при множественных отказах.

## Проверки и affected files

- [SchedulerEngine](../../../backend/services/scheduler/scheduler_engine.py):
  scoped discovery/claim, атомарные транзакции, bounded presence, conflict query,
  продвижение пропущенных интервалов.
- [Migration](../../../alembic/versions/20260921_schedule_work.py): UUID lookup,
  ACL, обратимое удаление функции без изменения schedule rows.
- [Runtime regressions](../../../tests/production/test_scheduler_runtime.py):
  SCRIPT/PIPELINE, max_runs, две организации/один connection, два workers и
  отдельный SQL row lock, partial writes, ошибка SQL одного расписания,
  lost commit reply, rollback до commit, grant/recovery, 51 due schedule,
  Redis exception/timeout/recovery и SQL-dispatch без Redis enqueue.
- Настоящие `pg_sleep(5)` проверяют timeout discovery и обработчика после flush.
  Отдельный тест принудительно завершает **только собственное PostgreSQL-соединение**
  из disposable audit DB после создания children: rollback и следующий tick
  сохраняют ровно один запуск. Это не остановка PostgreSQL pilot или worker OS-kill.
- [Migration regression](../../../tests/production/test_schedule_work_migration.py):
  active/due/null/future, две страницы, tenant IDs, PUBLIC ACL, search_path,
  downgrade/re-upgrade и сохранность исходных строк в rollback-only schema.
- [Санитизированное evidence](evidence/scheduler-runtime.json): before/after,
  SHA-256 и точные границы. Сырые логи/credentials оставлены приватными.

**86 связанных tests прошли. Полный backend: 1929 passed, 0 failures/errors/skips**
(542,4 s), включая 22 новых runtime/migration regressions. Ruff и scoped mypy
runtime-модуля прошли; OpenAPI export не изменил контракт. Все четыре workflows
предыдущего точного head `57f2730` прошли:
[архив CI](../2026-09-05/evidence/ci-57f2730-summary.json).

## Rollout и остаточные риски

**Source fix; backend/APK pilot не обновлялись. Массовый 32-device прогон ещё не допущен.**
Перед запуском новой версии нужна migration `20260921_schedule_work`. Мигратор
должен владеть таблицами/функцией. Доверенной рабочей роли выдать дополнительный
grant; пример имени роли необходимо заменить фактическим:

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.schedule_work(uuid) TO sphere_runtime;
```

Canary под фактической ролью: SCRIPT и PIPELINE schedule, execution receipt и
подтверждение APK, конфликт, отмена, Redis recovery и worker restart. Проверить
обе организации. Один HTTP readyz не доказывает работу scheduler. Для downgrade
сначала остановить новый worker/вернуть совместимый код, затем удалить lookup.

Watchdog RLS отдельно [воспроизведён](evidence/watchdog-rls.json): просроченный
QUEUED task остаётся QUEUED после unscoped tick и становится TIMEOUT после того же
tick с tenant binding. Это одна ожидаемо падающая diagnostic probe вне passing
suite; ни команды APK, ни timeout физически выполняемой задачи она не проверяет.
Следующий fix должен отдельно проверить ASSIGNED/RUNNING и stop/reconciliation.

Открыты watchdog и остальные background SQL-пути, cluster/per-device quotas,
большие fan-out schedules и bounded latency на 32 устройствах. Cursor даёт
продвижение при конечной очереди, но не SLA или межорганизационную квоту.
Device group targeting и legacy helper callers требуют отдельной проверки;
лог сообщения handler до commit сам по себе не является execution receipt.
Unknown физические исходы APK, native stop/reconnect, video decoder/preview,
свежесть кадров, Redis budget и длительная приёмка остаются в Fleet32.
