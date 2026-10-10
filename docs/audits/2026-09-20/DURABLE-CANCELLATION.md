# AUD-129: сохранённая отмена task и дочерних pipeline

**20 сентября 2026 · High / F32-01 · исправление исходного кода, native rollout ещё не принят.**

[Fleet32 preflight](FLEET32-PREFLIGHT.md) · [Предыдущее частичное исправление](STOP-DELIVERY-FAILURE.md) · [Протокол](../../security/task-control-protocol.md)

**Последующая установка:** [canary 21 сентября, APK 1.2.8](CANARY-20260921.md).
Ниже сохранён исходный source checkpoint; native границы и F32-26 уточнены в canary.

## Проблема и причина

После AUD-128 отрицательная публикация stop уже не давала ложный успех, но положительная
публикация всё ещё переводила SQL task в CANCELLED. Redis publish доказывает наличие
подписчика, а не окончание DAG. Запрос терялся при сбое процесса, отмена ASSIGNED могла
опередить EXECUTE_DAG, а отмена pipeline оставляла его дочернее задание выполняться.
UI скрывал такую работу из активных задач. Это эксплуатационный дефект: следующая
работа могла попасть на устройство до окончания предыдущей.

На исходном `6815879` пять изолированных PostgreSQL regressions завершились failure:
RUNNING/ASSIGNED преждевременно становились терминальными, отсутствовал сохранённый
intent, rollback допускал внешний эффект и cancelled receipt превращался в FAILED.
Исходный Fleet32 probe отдельно доказал CANCELLED pipeline с RUNNING child.
Сырые выводы хранятся приватно; итоговые счётчики — в [evidence](evidence/durable-cancellation.json).

## Новый контракт

| Событие | Состояние и доказательство |
| --- | --- |
| Отмена QUEUED под SQL row lock | CANCELLED сразу: dispatcher фиксирует ASSIGNED до сетевой отправки |
| Отмена ASSIGNED/RUNNING | `cancel_requested_at`, прежний активный status, `finished_at=null`; HTTP stop отвечает 202 |
| API transaction rollback | Нет публикации, снятия lock или сохранённого запроса |
| Нет Redis/сети/worker | Intent остаётся в PostgreSQL; новый worker подбирает его |
| Публикация / control ACK | Только доставка / принятие управления; task остаётся активным |
| Terminal DAG receipt `cancelled=true` | CANCELLED; только теперь освобождается исполнение |
| Успех успел раньше отмены | Сохраняется настоящий COMPLETED, не выдуманный CANCELLED |
| Неопределённый исход root/process interruption | Task остаётся активным, evidence сохраняется; APK result не подтверждается ACK |
| Отмена pipeline | Запрет нового child; текущему child сохраняется intent; parent ждёт terminal child и вложенные runs |

Dispatcher выбирает до 16 запросов с `FOR UPDATE SKIP LOCKED`, фиксирует время попытки
до I/O и отправляет группами максимум по восемь, с deadline две секунды на отправку.
Повтор возможен не ранее пяти секунд; target и `user_cancel_<task UUID>` неизменны,
timestamp/TTL обновляются. Это повтор **адресной идемпотентной отмены**, а не повтор
EXECUTE_DAG или произвольного изменяющего запроса. Незавершённая отмена блокирует
диспетчеризацию следующей задачи и исключается из обычного watchdog timeout.

APK сначала синхронно сохраняет отмену в существующем encrypted command journal.
Для ещё не полученного задания сохраняется terminal tombstone: поздний EXECUTE_DAG
вернёт receipt без действий Android, в том числе после restart. Для активного задания
сохраняется flag, который runner проверяет на границе действий. Control ACK и результат
самого DAG имеют разные ID. Переполнение/ошибка записи не выдаётся за принятую отмену.
При обрезке слишком большого result признак `cancelled` сохраняется.

Pipeline cancellation/reconciliation использует порядок блокировок Task → PipelineRun.
Смена child во время ожидания и некорректный tenant link дают 409 до изменения. Nested
runs обнаруживаются по сохранённому `parent_run_id`; новый executor продолжает их отмену
без повторного запуска шага. Поздний handler не перезаписывает отмену и не запускает
следующий шаг. Scheduler сохраняет тот же intent, включая PAUSED и nested runs.
Batch DELETE сохраняет прежнюю политику: RUNNING tasks продолжают работу, QUEUED
отменяются сразу, ASSIGNED ожидают отмены на APK; CANCELLED batch означает прекращение
допуска волн, а не подтверждение остановки всех уже работающих устройств.

Веб получает `cancel_requested_at` в task/run API и показывает **Cancelling — awaiting
device result**. Активная задача остаётся видимой; повторные кнопки на странице task
отключены до результата. Это не новый терминальный статус и не искусственный успех.

## Изменённые компоненты

- [Task service](../../../backend/services/task_service.py), task API/schema/model,
  batch, scheduler и heartbeat watchdog: intent, доставка и terminal reconciliation.
- [Pipeline service](../../../backend/services/orchestrator/pipeline_service.py),
  executor и handlers: admission fence, child/nested cancellation, защита поздних writes.
- Миграции [task intent](../../../alembic/versions/20260920_task_cancel_intent.py) и
  [pipeline intent](../../../alembic/versions/20260920_pipeline_cancel.py): nullable
  timestamps; новые enum values не требуются.
- [CommandJournal](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandJournal.kt),
  dispatcher и runner: durable fence и явный cancelled result.
- Task Engine/Task Detail и hooks: честное отображение ожидания результата.

## Проверка и rollout

Счётчики и границы тестов сохранены в [evidence](evidence/durable-cancellation.json):

| Набор | Результат |
| --- | --- |
| Полный backend без явно выделенных load profiles | **1802 passed**, 5 deprecation warnings |
| Связанные cancel/delivery/batch сценарии | 122 passed |
| Pipeline/orchestration и обратимость миграций | 83 passed; частично пересекаются с предыдущим набором |
| Полный frontend | **229 passed**, TypeScript без ошибок |
| Android Dev / Enterprise unit tests | Dev **586 passed**, Enterprise **585 passed + 1 skipped**; по 586 всего |
| Изменённые backend modules | Целевые Ruff и mypy прошли |

Первый общий backend-прогон не был зелёным: 1771 passed / 26 failed. Двадцать три
сбоя вызвала CP1251/UTF-8 кодировка PowerShell fixtures; отдельный `c730e10` исправил
их, все 66 проверок этих suites прошли. Ещё три сбоя — устаревшее ожидание записи
Redis-очереди и глобальная доставка старых fixture cancellation intents. Исправлены
ожидание SQL-контракта, tenant scope тестового dispatch и cleanup intent; затем
весь набор повторён успешно. Исходные результаты сохранены в evidence.

Полные локальные Ruff/mypy на Windows имеют соответственно один и 14 diagnostics
в неизменённых файлах: они независимо воспроизведены на `6815879` тем же toolchain,
списки mypy совпали. Это не зелёный global static check. Exact-commit CI проверяется
отдельно; результаты старого HEAD не переносятся на новый коммит.

**CI исходного исправления `232ddb8` полностью прошёл:** Backend (tests, lint/mypy,
security, production image bootstrap, RLS, Alembic single head), Frontend и оба
запуска Android workflow. Preview guard прошёл, deployment намеренно skipped для
draft PR. [Архив результатов с точным SHA и ссылками на runs](../2026-09-05/evidence/ci-232ddb8-summary.json).
Это CI указанного исходного коммита; последующий коммит архива меняет только документы.

Основные regressions: [task](../../../tests/production/test_durable_task_cancellation.py),
[pipeline](../../../tests/production/test_pipeline_cancel_intent.py), delivery/serialization,
scheduler/batch; Android `CommandJournalTest` и `ControlCommandTargetTest`; веб `tasks/history`.
PostgreSQL/Redis используются только изолированные; Android unit tests исполняют реальные
dispatcher/journal/runner с заменой OS/network/storage. Они не доказывают физическую
остановку shell subprocess на настоящем эмуляторе.

1. Подготовить окно приёмки с остановленным новым admission, сохранить active receipts.
2. Установить и проверить APK с durable flag/tombstone на двух canary устройствах.
3. Применить обе миграции, затем согласованно обновить все backend workers и frontend.
4. Выполнить native stop-before-execute, stop-in-action, reconnect, backend restart и
   rollback; сверить SQL, persisted APK receipt и отсутствие следующего действия.
5. Только затем расширять cohort; 32 устройства и восьмичасовой soak остаются gates.

Смешанный backend deployment не обеспечивает контракт: старый writer может объявить
отмену раньше времени. APK 1.2.7 не сохраняет новый pre-arrival fence. Установленные
backend `85fb1ea`, frontend `03b161e` и оба APK `1.2.7/10207` этим source change не менялись.

## Остаточные риски

- Отмена кооперативная. Уже начатая синхронная/root/Lua операция завершается на своей
  границе; flush root pipe не доказывает завершение дочернего OS process. Неопределённый
  исход требует разбора оператором; автоматического разблокирования такой задачи нет.
- Watchdog обычной задачи без cancel intent пока сохраняет прежний TIMEOUT-контракт;
  deadline не равен доказательству остановки. Pause/resume не получили ordering journal.
- Pipeline `action` остаётся legacy publish path без terminal native task receipt;
  отмена run не отзывает уже отправленную такую команду. В parallel разрешены только
  существующие action/delay; untrackable execute_script/sub_pipeline отвергаются заранее.
- Обычный RUNNING pipeline без отмены не получает lease/restart recovery этим fix.
  Durable batch waves, webhook after-commit, bounded decoder и VPN — отдельные F32 пункты.
- Pending journal ограничен 512 entries / 1 MiB; acknowledged receipts удерживаются
  семь дней. Это не безграничная гарантия дедупликации после очистки данных приложения.
- Rollback БД до версии без столбцов при незавершённых intent потеряет сведения об отмене;
  сначала остановить admission и согласовать незавершённую работу. Backup обязателен.

**F32-01 остаётся открытым для native/mixed-version/root-path приёмки. Успешная сборка,
unit tests и сохранённый intent сами по себе не означают готовность 32 устройств.**
