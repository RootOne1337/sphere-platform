# AUD-133: pipeline работает под ограниченной ролью PostgreSQL

**21 сентября 2026 · High / P0 F32-25 · исправлено в исходном коде; rollout открыт.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Lease/checkpoint recovery](PIPELINE-RECOVERY.md) · [Readiness](../../operations/READINESS.md)

## Дефект и доказательство

Pipeline запускал claim, recovery и cancellation с обычной SQL Session без
`app.current_org_id`. PostgreSQL RLS возвращал пустой результат под non-owner
ролью: сохранённое задание оставалось QUEUED, хотя poll завершался без SQL-ошибки.
Heartbeat использовал другую Session и по той же причине не находил свой run.
Проверки под владельцем таблиц обходят RLS и не обнаруживают этот отказ.

На исходном `6ebca1b` три новые проверки **упали до исправления**: startup не
принимает очередь, отмена не завершается, продление существующего lease возвращает
False. Использованы настоящие PostgreSQL, non-owner/NOBYPASSRLS роль, случайные
fixture tenants и отдельный пул с одним connection. Android-команды не отправлялись.
Историческая [F32-25 probe](evidence/pipeline_rls_probe.py) сохранена отдельно;
актуальные assertions находятся в стандартном regression-наборе.

## Исправление и его границы

Миграция добавляет `sphere_auth.pipeline_work(text)`. Узкая SECURITY DEFINER
функция с фиксированным search_path возвращает только run/tenant UUID для
`queued`, `recovery` или `cancel`, максимум 64 строки. PUBLIC лишён EXECUTE;
произвольный SQL, содержимое заданий и операции записи недоступны через функцию.
Неизвестный kind и NULL дают пустой результат.

После discovery worker создаёт отдельную Session для каждого tenant. Состояние
повторно проверяется в RLS-запросе под `FOR UPDATE SKIP LOCKED`; обнаруженный UUID
не является разрешением выполнить устаревшую запись. Claim, child admission,
heartbeat, checkpoint, cancellation и освобождение owner сохраняют один tenant.
Transaction-local context восстанавливается после commit/rollback существующим
`bind_tenant_context`, не остаётся на переиспользуемом connection.

Ограничение десять активных runs на executor сохранено. Каждая закоммиченная
tenant-группа сразу регистрируется в executor до обращения к следующей: отказ
следующего SQL commit не теряет уже занятые слоты. Generation fencing и правила
неизвестного внешнего эффекта из AUD-131 продолжают действовать.

## Проверки

**76 связанных тестов прошли**, включая 13 новых RLS regressions и проверку
миграции. Ruff изменённых файлов и mypy четырёх runtime-модулей с
`--follow-imports=silent` прошли. Проверка с анализом импортов отдельно выдаёт две
ошибки `union-attr` в неизменённом `backend/database/redis_client.py:50–51`;
они воспроизводятся и при проверке только этого файла в локальном окружении.
Это не полный зелёный mypy всего backend; точный CI проверяется после push.
Полный backend-набор: **1880 passed**, 0 failures, 0 errors; 0 skipped. Точные результаты — в [evidence](evidence/pipeline-rls.json).

| Сценарий | Проверяемый результат |
| --- | --- |
| Startup без tenant context | Разрешённый discovery находит QUEUED; tenant worker завершает его |
| Два tenants и один pooled connection | Оба выполняются; чужие строки невидимы; LOCAL context не протекает |
| Child admission, commits и heartbeat | Child сохраняется; lease обновляется минимум дважды |
| Потерянный owner | Recovery продолжает тот же Task ID, не создаёт вторую задачу |
| Настоящее завершение OS-процесса | Второй non-owner worker восстанавливает тот же child и завершает run |
| Отмена parent/nested | Собственные children отменяются; чужая строка с подставленным parent ID не меняется |
| Два worker, 32 QUEUED | Каждый принимает десять разных runs; двенадцать остаются QUEUED |
| Ошибка commit следующего tenant | Первый закоммиченный run уже зарегистрирован и не теряется |
| Чужой tenant с известными UUID/owner/generation | Нельзя усыновить run или продлить lease |
| Нет EXECUTE, затем выдан grant | Первое чтение запрещено; следующий poll того же executor работает |
| Migration upgrade/downgrade/re-upgrade | Фильтры, лимит и ACL корректны; данные runs сохраняются |

OS-kill тест действительно завершает свой дочерний процесс. Время lease ускоряет
fixture, а завершение child Task записывает тест: **это не запуск DAG на APK**.
В обычных regressions global discovery выполняется реально, после чего IDs
фильтруются по fixture tenants для защиты других данных изолированной тестовой БД.
OS-процесс ограничен одним fixture tenant; это не benchmark глобальной очереди.

Промежуточный набор дал 75 passed / 1 failed: migration fixture передавала строку
в параметр PostgreSQL interval, для которого asyncpg требует `timedelta`.
Исправлена fixture; повтор всех 76 tests прошёл. Это не скрытый runtime failure.
Сырые логи и временные credentials остаются в приватной `.local-pilot`.

## Затронутые файлы

- [Discovery migration](../../../alembic/versions/20260921_pipeline_discovery.py) и
  [tenant sessions / discovery](../../../backend/services/orchestrator/pipeline_tenants.py).
- [Executor](../../../backend/services/orchestrator/pipeline_executor.py),
  [recovery](../../../backend/services/orchestrator/pipeline_recovery.py),
  [ownership context](../../../backend/services/orchestrator/pipeline_ownership.py).
- [RLS regressions](../../../tests/production/test_pipeline_rls.py),
  [migration regression](../../../tests/production/test_pipeline_discovery_migration.py),
  [OS-worker helper](../../../tests/production/pipeline_worker_probe.py).
- Прежние [admission](../../../tests/production/test_pipeline_admission.py) и
  [recovery](../../../tests/production/test_pipeline_recovery.py) tests сохранены;
  poll ограничен tenant своей fixture, чтобы не обрабатывать чужие тестовые runs.

## Rollout и residual risk

Мигратор должен владеть таблицами и функцией, чтобы RLS discovery был возможен.
Только доверенной worker-роли выдать права (имя `sphere_runtime` — пример):

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO sphere_runtime;
```

Не выдавать это право HTTP-пользователям. Без grant poll выдаёт ошибку и не
обрабатывает работу; один HTTP readyz не доказывает здоровье фонового worker.
Canary должен создать задание под фактической runtime-ролью, проверить start,
несколько lease renewals, отмену и recovery после перезапуска. Новая миграция
обязательна и для dev/owner startup. Downgrade удаляет только функцию, поэтому
сначала нужно остановить новые workers или вернуть совместимый код.

Остаются открытыми:

1. Аналогичные RLS startup-пути scheduler, task dispatcher и watchdog требуют
   отдельного воспроизведения и проверки; этот fix распространяется на pipeline.
2. Nested WAITING всё ещё занимает executor capacity; родители могут не оставить
   места детям. Общая/per-device квота и справедливость между tenants не реализованы.
   Лимит discovery 64 ограничивает poll, но не гарантирует отсутствие starvation.
3. SQL/Redis/network fault matrix, время восстановления и SQL-нагрузка heartbeat
   на 32/64 не приняты. Scoped child fixture не доказывает delivery на Android.
4. При неизвестном внешнем эффекте сохраняется review, не автоматический replay.
   exactly-once внешних действий этим изменением не обещается.
5. Browser decoder, preview profile, transport freshness, Redis budget,
   наблюдаемость и полный длительный fleet-прогон остаются gates из Fleet32.

Backend/APK pilot не обновлялись; старые проекты не затронуты. F32-25 продвинут
до проверенного source fix. **GO для смешанного 32-device теста не выдан.**
