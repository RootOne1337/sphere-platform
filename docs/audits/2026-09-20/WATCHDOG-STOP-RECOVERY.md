# AUD-137: watchdog сохраняет остановку и не освобождает занятый APK по таймеру

**21 сентября 2026 · High / P0 · F32-01 и продолжение F32-25 · source fix.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Сохранённая отмена](DURABLE-CANCELLATION.md) · [Task dispatcher](TASK-DISPATCH-RLS.md) · [Readiness](../../operations/READINESS.md)

## Подтверждённые дефекты

На `8f37426` четыре новых regressions упали до изменения runtime, без ошибок
setup. Проверки используют настоящую non-owner/NOBYPASSRLS роль PostgreSQL.
Для доказательства timeout/stop отдельно привязан tenant, чтобы невидимость
строк под RLS не скрывала ошибку перехода состояния.

| Дефект | Причина | Доказательство до исправления |
| --- | --- | --- |
| Watchdog не видит просроченную очередь под RLS | Startup создаёт unscoped Session | Двухчасовая QUEUED задача при лимите 60 минут остаётся QUEUED |
| Timeout освобождает устройство до результата APK | ASSIGNED/RUNNING немедленно превращаются в терминальный TIMEOUT; stop отправляется позже и без сохранённого retry | После watchdog следующий TaskService dispatch отправляет EXECUTE_DAG для другой задачи на том же устройстве — два failures |
| RUNNING без `started_at` остаётся навсегда | Первый SELECT исключает NULL start, второй выбирает только QUEUED/ASSIGNED | Старый RUNNING без start не получает ни timeout, ни запрос остановки |

Для RUNNING старый worker отправлял CANCEL_DAG после terminal commit и освобождения
Redis lock. При отказе отправки следующая итерация его уже не выбирала: состояние
TIMEOUT. Для ASSIGNED stop вообще не отправлялся, хотя команда могла уже попасть
на APK без подтверждения получения. Подтверждённый дефект — преждевременная
повторная выдача работы; физическое одновременное исполнение двух DAG этой пробой
не утверждается. Android transport здесь заменён проверяемой заглушкой.

[Историческая RLS-проба](evidence/watchdog-rls.json) сохранена неизменной.
[Evidence нового fix](evidence/watchdog-stop-recovery.json) связывает before/after,
исходники и новые regressions. Старые failing diagnostics не включены в passing CI.

## Новый контракт

`timeout_requested_at` отмечает, что watchdog обнаружил истёкший срок.
Для отправленной работы одновременно сохраняется `cancel_requested_at`,
но status остаётся ASSIGNED/RUNNING, `finished_at` пуст и batch ещё не завершён.
Новая попытка на этом устройстве блокируется существующим SQL execution fence.

Task dispatcher доставляет сохранённую отмену с тем же `user_cancel_<task_id>`
и `payload.durable=true`, включая retry после восстановления Redis/сети.
Используется существующий APK journal fence из AUD-129; нового типа команды нет.
Watchdog сам больше не отправляет команды и не освобождает Redis execution locks.

| Событие | Результат |
| --- | --- |
| Просрочен QUEUED, ни разу не отправленный Task | TIMEOUT, `finished_at`, один failed в batch; локально известно, что исполнения не было |
| Просрочен ASSIGNED или RUNNING | Сохранён stop intent; устройство остаётся занятым до результата APK |
| Старый RUNNING без start | После queue deadline запрашивается остановка/сверка; исполнение не считается законченным |
| Transport не принял stop или ответ потерян | Сохранённый intent остаётся; повторяется тот же targeted durable CANCEL |
| Получен ACK команды отмены | Это не DAG result; выполнение и batch не завершаются |
| APK вернул `success=false,cancelled=true` после watchdog intent | TIMEOUT и один failed в batch; повтор этого receipt не считает его ещё раз |
| APK сообщил успешное завершение перед stop | COMPLETED; реальный итог не перезаписывается предположением watchdog |
| APK сообщил обычную ошибку выполнения | FAILED с фактическим результатом |
| APK сообщил известный `outcome_unknown` | Статус и fence сохраняются для reconciliation; ложного stop/успеха нет |
| Пользователь запросил отмену раньше watchdog | Сохраняется пользовательская отмена; её причина не переписывается в timeout |
| Потерян ответ на commit | Следующий poll перечитывает SQL; повторного внешнего действия в watchdog нет |

Очередь и runtime-пороги по-прежнему задаются `TASK_QUEUED_STALE_MINUTES` и
`TASK_STALE_BUFFER_SECONDS`. Для RUNNING с start учитывается его начало плюс
`timeout_seconds` и буфер. Для ASSIGNED, QUEUED и RUNNING без start используется
возраст создания. Невалидные отрицательные пороги не разрешают обработку.

## RLS, ограничение нагрузки и наблюдаемость

Новая явно разрешаемая функция `sphere_auth.watchdog_work(integer,integer,uuid)`
возвращает до 64 пар task/tenant UUID. Она выбирает due work до ограничения
страницы, исключает уже запрошенные отмены и терминальные задачи. Fixed search_path,
никакого PUBLIC execute и никаких DAG/credentials в результате.

Каждый Task повторно проверяется и блокируется в отдельной tenant-bound Session.
До четырёх задач обрабатываются параллельно; discovery ограничен пятью секундами,
одна транзакция — десятью. Cursor позволяет пройти следующую страницу; ожидающие
физического результата stop intents её не занимают. Цикл сохраняет паузу 60 секунд
после обработки: это не обещание мгновенной реакции на deadline.

SQL фильтрует здоровые RUNNING до row lock, поэтому watchdog не блокирует их
обычные receipts. После commit пишется `task.watchdog.intent_committed` с Task ID
и признаками stop/локального expiry. Ошибка даёт `task.watchdog.retry_pending`.

Task API возвращает дополнительное nullable `timeout_requested_at`. Веб показывает
`Deadline exceeded — awaiting device result` для ожидающей остановки задачи,
а после terminal receipt — её фактический status. Кнопки используют прежний
pending-cancellation guard. Обновлены OpenAPI и TypeScript task type.

## Файлы и проверки

- [Watchdog](../../../backend/tasks/task_heartbeat_watchdog.py),
  [TaskService](../../../backend/services/task_service.py),
  [Task model](../../../backend/models/task.py), [schema](../../../backend/schemas/task.py),
  [migration](../../../alembic/versions/20260921_watchdog_stop.py).
- [Runtime regressions](../../../tests/production/test_watchdog_stop_recovery.py):
  RLS, реальный повторный dispatch, terminal/unknown/success outcomes,
  два tenants, конкурентные ticks, lost commit reply, row-lock race с result handler,
  65 due tasks, grant/recovery, API и отсутствие блокировки здоровой задачи.
- Реальный `SELECT pg_sleep(5)` прерывается deadline в discovery и после записи
  intent/flush; rollback и следующая попытка проверяются на том же runtime pool.
- [Migration regression](../../../tests/production/test_watchdog_stop_migration.py):
  due/healthy/null-start/terminal/pending-cancel, границы времени, ACL/search_path,
  две страницы, nullable marker и сохранность rows/cancel intent при down/up.
- Существующие [UTC/rollback/accounting tests](../../../tests/production/test_watchdog_runtime.py)
  и [control receipt tests](../../../tests/production/test_cancellation_commands.py)
  обновлены под подтверждённый контракт. Просроченный RUNNING теперь не должен
  увеличивать failed до DAG receipt; успешная сборка это не проверяет.
- [Frontend status tests](../../../frontend/__tests__/tasks/cancellation-status.test.ts)
  сохраняют различие между pending timeout и терминальным исходом.

86 связанных tests и заключительные 22 runtime/migration tests прошли.
Итог повторного полного backend: **1952 passed, 0 failed/errors/skipped**, 536,49 с,
пять предупреждений; `tests/load` исключены. Все 239 frontend tests и TypeScript
type-check прошли. Ruff, scoped mypy четырёх backend-модулей и OpenAPI export прошли.
Точные счётчики и хеши исходников сохранены в evidence.

Первый общий прогон дал 1950 passed и один failure в scheduler SQL-disconnect
test. [Разбор тестового пула](RUNTIME-POOL-HARNESS.md): fixture не включала уже
действующий в production `pool_pre_ping`. Добавлен отдельный before/after regression,
22 связанных scheduler/pool tests прошли; failure не скрыт повторным запуском.

## Установка и остаточные риски

**На pilot не установлен; APK и старые Docker-проекты не изменялись. GO для
массового 32-device теста не выдан.** Нужна согласованная установка всей цепочки
AUD-129/135/137 и актуального APK с durable cancellation journal; текущая
двухэмуляторная версия сама по себе этой приёмкой не подтверждена.

До запуска backend применить migration `20260921_watchdog_stop`. Мигратор должен
владеть таблицами и lookup. Выдать дополнительный grant доверенной runtime-роли;
`sphere_runtime` ниже — пример, не автоматически созданная роль:

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.watchdog_work(integer,integer,uuid) TO sphere_runtime;
```

Canary должен проверить deadline при недоступном APK, появление durable stop после
reconnect, отсутствие выдачи следующего DAG до terminal receipt, поздний EXECUTE_DAG
и unknown root outcome. Mock transport не доказывает физическую остановку Android.
Устройство без terminal receipt может остаться занятым: нужен разбор исхода,
а не автоматическое объявление его остановленным по ещё одному таймеру.

Старые TIMEOUT rows не переоткрываются и не считаются автоматически согласованными
с APK. Перед rollout нужно сверить их с агентами. Старые workers необходимо
остановить: они не соблюдают новый stop fence. Downgrade сначала требует остановки
новых workers и согласования ожидающих stop intents; удаление nullable marker
сохраняет cancel request, но теряет различие причины timeout/user cancellation.

Legacy Redis queue metadata здесь не очищается; SQL dispatcher его не читает.
Legacy helper callers/retention, остальные background SQL workers, общие квоты,
bounded video decoder/preview, свежесть кадров, Redis budgets и native fault soak
на 32 остаются отдельными пунктами Fleet32. Exactly-once физического действия и
совместимости со всеми Android это исправление не обещает.
