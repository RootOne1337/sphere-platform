# SQL fault tests: восстановление тестового пула как в production

**21 сентября 2026 · исправление тестового окружения, не новый runtime-дефект.**

При общей проверке watchdog прошли 1950 backend tests, но один scheduler fault
test упал на следующем discovery после принудительного разрыва SQL-соединения.
Отдельный повтор прошёл; исходный failure не отброшен как случайный.

Причина: [runtime-role fixture](../../../tests/production/conftest.py) создавала
пул без `pool_pre_ping`, тогда как [рабочий engine](../../../backend/database/engine.py)
уже использует `pool_pre_ping=True`. После разрыва соединение иногда возвращалось
в тестовый пул до обнаружения disconnect. Следующий checkout получал
`InterfaceError: connection is closed`. Это не воспроизведение отказа рабочего
engine с той же настройкой — его конфигурация отличается.

## Воспроизведение и fix

Новый [regression](../../../tests/production/test_runtime_pool_recovery.py)
возвращает tenant-bound соединение в пул и завершает только его точный
`pg_backend_pid()` через независимое соединение disposable audit PostgreSQL.
До исправления: **1 failed, 0 errors** на следующем SQL-запросе.

Fixture теперь включает такую же предварительную проверку, как production.
Повтор получает новое соединение, не видит строки без tenant context, затем
видит только вторую организацию; context не остаётся после возврата в пул.
Дополнительно [scheduler fault test](../../../tests/production/test_scheduler_runtime.py)
ожидает подтверждённого завершения SQL-процесса до recovery. Положительный timeout
`pg_terminate_backend(pid, 2000)` ждёт завершения, тогда как значение по умолчанию
подтверждает только отправку сигнала. [Контракт PostgreSQL](https://www.postgresql.org/docs/17/functions-admin.html#FUNCTIONS-ADMIN-SIGNAL).

После изменений: **22 related tests passed**, включая весь scheduler runtime
suite и новый idle-disconnect regression; Ruff прошёл. Сырые XML/logs остаются
приватными: `.local-pilot/runtime-pool-recovery-before.xml`,
`runtime-pool-recovery-after.xml`, `watchdog-stop-full.xml`.

Никаких runtime-настроек, production-запросов, pilot/APK или старых Docker-проектов
это изменение не затрагивает. Проверка разрыва одного audit-соединения не заменяет
отключение всего PostgreSQL/сети или приёмку на 32 Android.
