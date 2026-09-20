# AUD-134: вложенный pipeline освобождает слот на время ожидания

**21 сентября 2026 · High / P0, остаточный F32-05 · source fix, на pilot не установлен.**

[Fleet32](FLEET32-PREFLIGHT.md) · [RLS worker](PIPELINE-RLS.md) · [Recovery](PIPELINE-RECOVERY.md) · [Readiness](../../operations/READINESS.md)

## Дефект и evidence

После ограничения admission десять родителей могли занять все десять слотов
executor, создать десять дочерних runs и ждать их, не освобождая coroutine.
Дети оставались QUEUED: для них нет свободного слота. Это операционная блокировка
даже с пустыми children, не требующими Android, Redis или внешних вызовов.

На source `d859a52` реальный executor и PostgreSQL после восьми дополнительных
poll сохранили **10 RUNNING parents / 10 QUEUED children / 0 completed parents**.
[Исходная проба](evidence/pipeline_nested_capacity_probe.py) и
[неизменённая baseline-сводка](evidence/pipeline-nested-capacity.json).
Затем пять новых regressions упали до изменения runtime: насыщение, restart,
pause/resume, отмена и deadline не могли завершить ожидание в новом контракте.

## Контракт после исправления

Для самостоятельного checkpointed шага `sub_pipeline` родитель сохраняет
абсолютный `wait_deadline_at`, рассчитанный из прежнего начала шага и общего
срока run. В одной транзакции создаются child и ссылка на него, родитель переходит
в WAITING, освобождает owner/lease и повышает generation. После commit coroutine
заканчивается без записи успешного результата шага и без удержания слота.

Ожидающий родитель не имеет heartbeat, SQL connection или отдельного таймера в
памяти. Bounded recovery discovery выбирает его только после terminal child,
истечения deadline либо отсутствия корректной child identity. Отдельная tenant
Session повторно проверяет условия под row lock; обычный bounded claim затем
продолжает тот же checkpoint. Длительное ожидание здорового child не вызывает
циклический claim родителя и не прячет за собой следующую очередь.

| Событие | Поведение |
| --- | --- |
| Все слоты заняты родителями | Родители переходят в WAITING; дети получают освободившиеся слоты |
| Child завершён | Родитель читает результат того же child и переходит к следующему шагу |
| Worker перезапущен | Ожидание, child ID и исходный deadline остаются в PostgreSQL |
| Потерян ответ на commit WAITING | Повтор читает сохранённую identity; второй child не создаётся |
| Commit до сохранения child не прошёл | Транзакция откатывается; неизвестный исход сохраняется для review |
| Отмена WAITING | Сначала согласованно отменяется child; parent не сообщает завершённую отмену раньше него |
| Пауза WAITING | Parent PAUSED; child автоматически не останавливается; результат ждёт resume |
| Resume | Возврат к тому же child и прежнему deadline, без нового срока |
| Deadline, child ещё активен | PAUSED / unknown для review; identity не стирается, child не запускается повторно |
| Неверная или чужая child reference | Возврат на проверку, не бесконечное ожидание и не чтение чужих данных |

Обычное возобновление отмечается `wait_resumed`, потеря lease — `lease_recovered`.
Длительность `sub_pipeline` в step log включает сохранённое ожидание, а не только
время последнего краткого вызова handler. UI уже показывает WAITING; API pause
теперь принимает WAITING. Контракт HTTP-ответов не расширялся.

## Дополнительно выявленный SQL timeout

Расширенный regression-набор обнаружил `PendingRollbackError`: `wait_for` мог
прервать SQL внутри handler, а runner пытался читать fence через невалидную
транзакцию. После неуспешного StepResult runner выполняет rollback и перечитывает
сохранённый run под generation fence. Доказательство дополнено настоящим
`SELECT pg_sleep(5)` с 500ms deadline: исход остаётся unknown/review, а SQL Session
восстанавливается без ложного успеха или повтора эффекта.

## Файлы и проверки

- [Model](../../../backend/models/pipeline.py),
  [migration](../../../alembic/versions/20260921_pipeline_wait.py): nullable deadline,
  индекс status/deadline и обновление discovery с сохранением ACL функции.
- [Step handlers](../../../backend/services/orchestrator/step_handlers.py),
  [runner](../../../backend/services/orchestrator/pipeline_recovery.py),
  [control flow](../../../backend/services/orchestrator/pipeline_ownership.py),
  [tenant lookup](../../../backend/services/orchestrator/pipeline_tenants.py),
  [pause/resume](../../../backend/services/orchestrator/pipeline_service.py).
- [Новые regressions](../../../tests/production/test_pipeline_nested_wait.py):
  non-owner RLS, насыщение десятью родителями, три уровня с одним слотом,
  worker replacement, cancel/pause/deadline, global/scoped discovery, commit
  rollback/lost ACK и реальный SQL timeout.
- [Migration regression](../../../tests/production/test_pipeline_wait_migration.py):
  legacy WAITING, активный/terminal/чужой child, deadline, ACL, индекс,
  downgrade/re-upgrade с сохранением runs в изолированном schema.
- [SQL connection regression](../../../tests/production/test_pipeline_wait_connections.py)
  сохраняет проверку пула из одного соединения и idle-timeout 900ms; для nested
  ожидает WAITING и возобновление новым poll. Ровно один результат шага плюс
  отдельное событие `wait_resumed`; длительность включает время ожидания.

**Полный backend: 1892 passed, 0 failures/errors/skips.** 87 связанных
tests прошли на финальном коде, включая missing-identity guard и сохранённый
deadline. Ruff и scoped mypy пяти модулей прошли.
Точные результаты и повтор исходной пробы:
[sanitized evidence](evidence/pipeline-nested-wait.json). Промежуточные failures
сохранены: 60 passed / 2 failed (SQL timeout и прежнее ожидание RUNNING), затем
43 passed / 1 failed (старый assertion считал все log entries результатами шага).
Assertion уточнён под новый event-контракт, проверка ровно одного успешного шага
и освобождения connection сохранена. Сырые логи остаются приватными.
Дополнительная проверка усилена: deadline уже истёк, но срок в шаблоне изменён
на более поздний. Первый вариант fix циклически возвращал parent в WAITING,
поскольку discovery использовал сохранённый срок, а runner — пересчитанный.
Один failing regression предшествует исправлению: runner также ограничивает
remaining time сохранённым абсолютным deadline. Успех отдельных исходных tests
не скрыл эту найденную в процессе проблему.

## Rollout и residual risk

1. Обновить workers согласованно после установки миграции. Старая версия не знает
   deadline и воспринимает WAITING как потерянный lease; смешанный rollout не принят.
   Права `sphere_auth.pipeline_work(text)` из AUD-133 сохраняются при CREATE OR REPLACE.
2. Downgrade удаляет wait deadline, но сохраняет runs и child IDs; исходные сроки
   шагов/начала остаются. Перед откатом остановить workers и сверить ожидающую
   работу; старый код снова подвержен блокировке слотов. Не делать blind replay.
3. Освобождение слота реализовано для checkpointed `sub_pipeline` как шага run.
   Вызов `sub_pipeline` внутри `loop` пока не имеет durable checkpoint каждой
   итерации и не получает эту гарантию. `parallel` сейчас принимает только
   action/delay и явно отклоняет stateful children. Вложенный граф не имеет общего лимита
   глубины/циклов, кластерной/per-device квоты и доказанной fairness.
4. Deadline активного child ведёт в review, а не обещает физически остановить
   Android. Родительская пауза также не равна stop ребёнка. Recovery неизвестных
   внешних эффектов остаётся консервативным.
5. Задержка возобновления включает интервал polling и ожидание admission;
   это не контур управления игрой в реальном времени. Будущий AI-контур и
   низкая задержка кадров требуют отдельного контракта.
6. Эти tests работают с настоящим PostgreSQL и тестовыми runs, без APK-команд.
   Замена executor в новой проверке — новый объект; OS-kill lease/child recovery
   отдельно проверен AUD-131/133. Native rollout, остальные RLS workers,
   decoder/preview/Redis budgets и смешанный 32-device fault/soak остаются открытыми.
   Scheduler RLS отдельно [воспроизведён](evidence/scheduler-rls.json) и остаётся P0;
   исправление nested waiting не делает этот worker работоспособным под RLS.
   [Task dispatcher](evidence/dispatcher-rls.json) также воспроизведён: QUEUED без
   tenant binding, ASSIGNED с ним под той же ролью; transport — тестовая заглушка.

Backend/APK pilot и старые Docker проекты не менялись. Это source fix с
воспроизводимыми проверками, **не допуск к длительному тесту 32 эмуляторов**.
