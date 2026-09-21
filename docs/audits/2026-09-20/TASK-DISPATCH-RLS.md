# AUD-135: доставка и отмена задач под рабочей ролью PostgreSQL

**21 сентября 2026 · High / P0 перед runtime-role rollout · продолжение F32-25.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Pipeline RLS](PIPELINE-RLS.md) · [Отмена](DURABLE-CANCELLATION.md) · [Readiness](../../operations/READINESS.md)

## Дефект и воспроизведение

Startup-диспетчер создавал PostgreSQL Session без `app.current_org_id`. Под
настоящей non-owner/NOBYPASSRLS ролью SELECT возвращал пустой результат: сохранённая
задача оставалась QUEUED, сохранённая отмена RUNNING не отправлялась. Исключения SQL
не было. Проверка под владельцем таблиц скрывала этот операционный дефект.

Вторая причина отказа после восстановления: при `redis is None` startup возвращался
без регистрации цикла. При последующем появлении Redis доставку некому возобновлять.
Кроме того, прежний callback удерживал ссылку на binary Redis, полученную на старте.

На `b08a773` **три regressions упали до изменения runtime, без ошибок setup**:
зарегистрированный tick не отправил EXECUTE_DAG, не отправил CANCEL_DAG и не был
зарегистрирован при отсутствующем Redis. Это продолжение прежней
[контрольной SQL-пробы](evidence/dispatcher-rls.json), где ручное tenant binding
позволяло той же роли доставить ту же задачу.

## Исправление

Новая функция `sphere_auth.task_dispatch_work(text,uuid)` возвращает только пары
device/tenant UUID, до 64 на страницу. Она требует отдельного grant, не доступна
PUBLIC, использует фиксированный search_path и не возвращает DAG, credentials
или account data. Assignment выбирает активные устройства с QUEUED либо достаточно
старой ASSIGNED задачей; cancellation — due intent у ASSIGNED/RUNNING, включая
неактивные устройства. Связь device/tenant проверяется в lookup.

Рабочий цикл всегда регистрируется. Каждый tick получает актуальные зависимости,
сначала обрабатывает отмену независимо от presence, затем читает presence одним
MGET для страницы. Каждое устройство получает отдельную Session с tenant context,
сохраняемым после commit/rollback. SQL заново проверяет состояние под существующими
row locks: discovery не является claim или разрешением отправить задачу.

| Событие | Поведение |
| --- | --- |
| Redis отсутствует при startup | Цикл остаётся зарегистрирован; после появления клиента следующий tick продолжает работу |
| Ошибка presence | Отмена уже обработана; assignment-страница не продвигается до чтения presence |
| Первые 64 устройства offline | Cursor переходит дальше; следующее online устройство не скрыто навсегда |
| Два workers | Device lock и сохранённый ASSIGNED/cancel timestamp ограничивают повторную отправку |
| Потерян ответ на SQL commit | Сначала перечитывается сохранённое состояние; немедленного replay нет |
| Потерян ответ transport | Повтор использует прежний Task ID и прежний CANCEL command ID |
| Зависший transport | Отправка assignment ограничена двумя секундами; SQL connection уже освобождён |
| SQL discovery завис | Операция прерывается по пятисекундному deadline; следующий tick повторяет чтение |
| Пришёл CANCEL, затем очередной task | Существующий execution fence удерживает следующую задачу в QUEUED до terminal receipt |

Два независимых keyset cursor — для assignment и отмены. После конца диапазона
lookup возвращается к началу. До восьми устройств обрабатываются параллельно;
одна обработка ограничена 15 секундами, без фоновых detached send tasks. Существующая
порция отмены ограничена 16 tasks на устройство и восемью отправками внутри порции.
Предел discovery не является SLA: при отказах нескольких групп poll может занять
больше пяти секунд; пять секунд — пауза между завершёнными ticks.

Удалён startup `KEYS task_running:*` и перенос старых Redis locks обратно в очередь:
SQL уже владеет dispatch intent. Regression с существующим Redis lock подтверждает,
что такой ключ не препятствует доставке; startup больше не обходит все ключи.
Legacy queue API в остальных путях этим изменением не удаляется.

## Проверки и affected files

- [Startup](../../../backend/api/v1/tasks/router.py),
  [worker](../../../backend/services/task_dispatcher.py),
  [TaskService](../../../backend/services/task_service.py): tenant scope,
  повторная проверка состояния, bounded I/O и актуальные зависимости.
- [Migration](../../../alembic/versions/20260921_task_dispatch.py): UUID discovery,
  ACL и down/up без изменения tasks.
- [Runtime regressions](../../../tests/production/test_task_dispatcher_runtime.py):
  настоящий login с RLS, один connection в пуле, две организации, два workers,
  потеря transport/commit ACK, restart, 65 устройств с 64 offline,
  зависшая отправка, cancel fence, отсутствие grant и его восстановление.
  SQL timeout воспроизведён настоящим `SELECT pg_sleep(5)`; Session/пул после отмены
  запроса снова доставляют работу. Android transport/presence — doubles.
- [Migration regression](../../../tests/production/test_task_dispatch_migration.py):
  фильтры состояния/времени, неактивное устройство, чужая tenant-связь,
  дедупликация device, две страницы, отсутствие PUBLIC grant, search_path и rollback.
- [Санитизированная сводка](evidence/task-dispatch-rls.json) содержит счётчики,
  SHA-256 исходников и ограничения. Сырые логи и credentials остаются приватными.

101 связанный тест прошёл. **Заключительный backend: 1907 passed, 0 failures/errors/skips**
(539.5 s); включает все 15 новых runtime/migration regressions.
Ruff и scoped mypy трёх runtime-модулей прошли. OpenAPI export не изменил контракт.
Все четыре workflows предыдущего head `b08a773` прошли:
[архив точного SHA](../2026-09-05/evidence/ci-b08a773-summary.json).

## Rollout и остаточные риски

**Source fix; backend/APK pilot не обновлялись. GO для 32 устройств не выдан.**
Миграция `20260921_task_dispatch` обязательна перед запуском нового dispatcher,
в том числе в owner/dev окружении. Мигратор должен владеть таблицами и функцией.
Доверенной worker-роли выдать права; `sphere_runtime` ниже — пример имени:

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.task_dispatch_work(text,uuid) TO sphere_runtime;
```

Без grant ошибка poll видна в журнале, но HTTP readyz сам по себе не подтверждает
работу dispatcher. Canary: под фактической runtime-ролью создать task, дождаться
APK receipt, запросить отмену, получить terminal receipt, повторить после Redis
и worker restart. Проверить разные организации и отсутствие повторного эффекта.
Для downgrade сначала остановить новый worker/вернуть совместимый код, затем
удалить функцию миграцией; task rows миграция не меняет.

Последующий [AUD-136](SCHEDULER-RUNTIME.md) исправляет подтверждённый
[scheduler RLS](evidence/scheduler-rls.json) и атомарность firing; watchdog и
другие background SQL-пути требуют отдельной проверки. Также открыты decoder queue,
APK preview profile, свежесть кадров, Redis budget, смешанный native-прогон и
SQL-нагрузка/latency на 32 устройствах. 65 SQL-fixture devices не являются тестом
65 Android. Отправка/ACK transport не доказывает физический stop или exactly-once
внешнего действия. Для массового rollout нужны согласованные backend/APK fixes
и отдельная native-приёмка из Fleet32.
