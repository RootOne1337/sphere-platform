# AUD-132: batch сохраняет план и восстанавливает оставшиеся волны

**21 сентября 2026 · High / F32-03 · source fix, на pilot не установлен.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Pipeline recovery](PIPELINE-RECOVERY.md) · [Readiness](../../operations/READINESS.md)

## Дефект и воспроизведение

Раньше `start_batch` сохранял total/settings, но передавал список целей только в
`asyncio.create_task`. При падении worker между волнами оставшиеся устройства
терялись: в БД не было полного плана. Повтор исходного списка также небезопасен:
проверка дубликата Task учитывает только активные задачи, уже завершённую можно
создать повторно. Каждая волна читала текущую версию Script, поэтому публикация
версии между волнами меняла программу одной и той же пакетной операции.

Три новые проверки **провалились до исправления**: отсутствуют сохранённые цели,
отсутствует закреплённая версия, дублирующиеся device IDs принимаются и могут
создать несовпадение total с фактической программой волн. Исходный F32-03 также
воспроизвёл потерю coroutine между двумя волнами. [Сводка](evidence/batch-recovery.json).

## Контракт после изменения

До HTTP 202 одной транзакцией сохраняются полный план, постоянный Task UUID
каждого элемента, версия Script, настройки и начальный cursor. Один startup loop
на процесс выбирает до 32 ожидающих batch за poll; создаёт максимум одну волну
каждого. Отдельных фоновых задач на каждый batch больше нет.

Одна волна выполняет **только SQL**. Transaction advisory lock сериализует её с
другим producer и отменой. Task rows, отклонения, счётчики, receipts, следующий
cursor и время следующей волны коммитятся вместе. PostgreSQL освобождает lock при
rollback/смерти соединения; отдельный lease здесь не нужен. Android dispatch идёт
позже по уже сохранённым QUEUED Task через существующий dispatcher.

| Ситуация | Поведение |
| --- | --- |
| Worker потерян до начала волны | Новый loop находит сохранённый plan |
| Сбой до commit | Ни Task, ни receipts/cursor не продвигаются |
| Commit прошёл, ответ потерян | Новый worker читает уже продвинутый cursor; прошлый Task не повторяется |
| Между волнами опубликован новый Script | Продолжает закреплённую версию; tenant/script связи проверяются |
| Delay/jitter между волнами | Сохранённый `next_wave_at`, ожидание без DB connection и coroutine на batch |
| Другой producer удерживает wave lock | Poll пропускает эту запись, не создавая вторую очередь в памяти |
| Устройство отклонено при admission | Один receipt с кодом 4xx и одно увеличение failed в транзакции волны |
| SQL error/timeout | Rollback либо уже подтверждённый cursor; повтор откладывается, не выдаётся ложный успех |
| Batch отменён | Новые волны не допускаются; прежняя finish-current-work политика RUNNING Task сохранена |
| Старый batch без плана | `legacy_unknown`; недостающие цели не угадываются |

`admission_state=submitted` означает создание всех допустимых заданий, **не их
исполнение**. Финальный batch status и succeeded/failed зависят от результатов
Task. API дополнительно возвращает закреплённую версию, cursor, due time, состояние
admission; detail содержит receipts без секретов/текстов чужих ошибок.

## RLS и эксплуатационные права

Без tenant context обычная DB-роль не видит batch. Для startup loop добавлен узкий
`sphere_auth.due_batch_admissions()`: SECURITY DEFINER, фиксированный search_path,
только due batch/tenant UUID, максимум 32 строки, без произвольного SQL и без записи.
PUBLIC не получает EXECUTE. После получения ID каждый обработчик связывает
отдельную Session с tenant; RLS применяется ко всем её транзакциям.

При rollout мигратор должен владеть таблицами и функцией; отдельной доверенной
runtime/worker-роли выдать права (заменить `sphere_runtime` фактической ролью):

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.due_batch_admissions() TO sphere_runtime;
```

Это право открывает worker ID ожидающей работы всех tenants, не HTTP-пользователю.
Без grant loop пишет `batch.admission.poll_failed`, но работу не выполняет; после
выдачи права следующий poll восстанавливается. Grant и первые admission receipts
обязательны в canary-проверке. Нельзя считать один HTTP readyz приёмкой фоновой работы.

## Проверки и файлы

**75 связанных тестов прошли**, Ruff и mypy изменённых runtime modules прошли.
Полный backend-набор этой итерации: **1865 passed**. Он был собран до
последнего теста и `greatest`-исправления retry delay; финальные 75 связанных
tests проверены после него. Это разграничение сохранено в [evidence](evidence/batch-recovery.json).
Batch hooks frontend: четыре теста прошли, TypeScript без ошибок; UI не расширялся.
Позже проверены все четыре GitHub workflows точного source `6ebca1b`: success;
[архив CI](../2026-09-05/evidence/ci-6ebca1b-summary.json) относится к финальному
AUD-132, а не к последующим изменениям.

- [Durable admission](../../../backend/services/batch_admission.py),
  [BatchService](../../../backend/services/batch_service.py),
  [TaskService](../../../backend/services/task_service.py),
  [model](../../../backend/models/task_batch.py), [migration](../../../alembic/versions/20260920_batch_plan.py).
- [Новые SQL regressions](../../../tests/production/test_batch_recovery.py):
  lost commit ACK, rollback, два producer, delay, pinned version, tenant mismatch,
  cancellation, legacy unknown, backoff и реальная non-owner RLS role.
- [OS worker](../../../tests/production/batch_worker_probe.py): тест завершает свой
  отдельный процесс после первой волны и запускает новый; сохраняется ровно два
  Task с прежним ID первой задачи. Due time ускоряется SQL-изменением fixture;
  terminal Task тоже записывает fixture. **Это не запуск DAG на APK.**
- [Migration](../../../tests/production/test_batch_recovery_migration.py):
  upgrade/downgrade/re-upgrade в откатываемом отдельном schema, legacy data и ACL.
- [Lifecycle](../../../tests/test_batch_lifecycle.py): один loop, защита от повторного
  startup, await cancellation при shutdown. Старые concurrency/cancellation tests
  сохранены и переведены с in-memory producer на сохранённые планы.

Промежуточный набор дал 58 passed / 2 failed: после раннего flush обновление плана
делало `updated_at` expired и ломало HTTP serialization; mock не назначал batch ID.
План теперь полностью формируется до INSERT с явным UUID; повторный HTTP regression
и все связанные tests проходят. Дополнительный failing test показал, что retry
после lost commit ACK сокращал due time до пяти секунд; `greatest` сохраняет
более поздний сохранённый срок, финальный набор включает эту регрессию.
Эти failures не скрыты за успешной сборкой.

## Rollout и residual risk

1. Обновить все producers согласованно после drain/reconciliation старых batches.
   Старые процессы не знают новый cursor; смешанный rollout не принят. Downgrade
   удаляет план/receipts, требует остановки admission и сверки результатов.
2. Legacy batch нельзя безопасно достроить из total/Task rows; недостающие цели
   неизвестны. Оператор должен сверить фактические задачи и создать новый явно
   заданный batch для действительно не начатой работы.
3. Повтор **HTTP POST** после потери ответа пока не имеет общего idempotency key;
   это другой запрос и может создать другой batch. Восстановление сохранённого
   batch не означает exactly-once любого внешнего/Android эффекта.
4. RLS bootstrap других workers, nested pipeline capacity, общая/per-device квота,
   browser decoder/preview profile, Redis budget и 32-device fault/soak остаются
   открытыми. Отдельная RLS-проба pipeline зафиксирована как **F32-25**;
   последующий [AUD-133](PIPELINE-RLS.md) исправляет pipeline отдельно от batch.
   Другие background workers и runtime-role canary всё ещё требуют проверки.
5. Нагрузка 32/64 и справедливость очереди не измерены. Poll ограничивает размер
   выборки, не заменяет performance budget; перезапуск PostgreSQL/сетевой blackhole
   на реальном fleet ещё требуют приёмки. SQL failure и lost response здесь
   контролируемо инжектировались; ОС-процесс worker действительно завершался.
6. Новое API-поле доступно для диагностики; отдельный полный экран управления
   batch/review в UI этой работой не реализован. Webhook delivery не добавлена.

Backend/APK нового pilot не обновлялись; старые проекты не затронуты. До native
canary и поэтапного 4/8/16/32 прогона F32-03 не считается закрытым в эксплуатации.
