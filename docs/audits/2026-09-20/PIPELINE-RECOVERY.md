# AUD-131: восстановление pipeline без слепого повтора шага

**20 сентября 2026 · High / F32-02 · source fix; на pilot не установлен.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Admission AUD-130](PIPELINE-ADMISSION.md) · [Отмена AUD-129](DURABLE-CANCELLATION.md) · [Readiness](../../operations/READINESS.md)

## Проблема, причина и воспроизведение

Старый executor выбирал только QUEUED. Если процесс умирал, RUNNING оставался без
исполнителя; глобальный timeout проверялся только живой coroutine. Добавить выбор
старых RUNNING недостаточно: положение и результат шага не образовывали сохранённую
точку восстановления. После завершения Task handler очищал `current_task_id` до
записи результата; после успешного шага `current_step_id` ещё указывал на старый шаг.
Новый исполнитель мог создать вторую Android-задачу или повторить внешнее действие.

Кроме того, pause немедленно выставлял PAUSED, а resume — QUEUED, даже пока старый
handler продолжал выполняться. Завершение последнего шага во время pause оставляло
его доступным для повтора. Новый claim сбрасывал `started_at`, продлевая общий timeout.
Startup не регистрировал shutdown собственного executor.

На `7290f1e` **пять SQL regressions и один lifecycle regression провалились** до
исправления. Данные: [санитизированная сводка](evidence/pipeline-recovery.json);
tests сохранены в [recovery suite](../../../tests/production/test_pipeline_recovery.py)
и [lifecycle suite](../../../tests/test_pipeline_lifecycle.py). Сырые логи приватные.

## Контракт восстановления

Каждый SQL claim сохраняет случайный UUID владельца процесса, монотонное поколение
и lease на 30 секунд. Heartbeat продлевает его каждые пять секунд; попытка ограничена
тремя секундами. Ошибка/истечение прекращает coroutine владельца, но не выдумывает
FAILED/CANCELLED для Android. При следующем poll другой worker проверяет сохранённые
данные. Срок считается по часам PostgreSQL, после получения блокировки строки;
начало старой транзакции не продлевает истёкшее право исполнения.

| Сохранённое состояние | Поведение после потери worker |
| --- | --- |
| `ready` | Выполнить сохранённый следующий шаг; завершённый предыдущий не повторяется |
| `in_flight`, обычный delay | Учесть прошедшее время; уже истёкший delay не запускается заново |
| `in_flight`, condition | Повторно вычислить условие по сохранённому контексту |
| `in_flight`, execute_script / sub_pipeline | Продолжить ожидание того же child ID; не создавать замену существующей работе |
| Child ещё не был создан | Его создание и привязка защищены generation/row lock и одной транзакцией |
| Устаревший owner / generation | Не допускать новый child, следующий шаг или поздний checkpoint |
| Неизвестный результат action/n8n/loop/parallel/event wait | PAUSED + `execution_phase=unknown` + причина в context/step_logs; автоматического replay нет |
| Неполное внешнее действие или активный child после timeout | Сохранить child и потребовать проверки; retries не создают дубликат |
| Pause во время шага | Дождаться его границы; Resume отвечает 409, пока старый owner не освобождён |
| Pause во время последнего успешно завершённого шага | Завершить run; уже выполненный последний шаг не остаётся для Resume |

Результат, context, следующая позиция, сброс таймера шага и освобождение child ID
коммитятся вместе. Общий `started_at` сохраняется между claims/resume. Deadline
шага также сохраняется; восстановление не выдаёт ему полный новый timeout.

UI показывает причину ожидания восстановления или неопределённого результата;
Resume выключен, пока backend не подтвердил безопасную границу. Истёкшая дата lease
на часах браузера сама по себе не разблокирует кнопку. Recovery events отделены от
успешных шагов в журнале. Отмена paused run остаётся доступной через существующий
контракт отмены; остановка внешнего эффекта не следует из закрытия записи pipeline.

Shutdown закрывает admission, даёт до 30 секунд на завершение, затем отменяет
оставшиеся локальные coroutine. Внешний shutdown deadline — 35 секунд; ожидание
cleanup ограничено, оставшиеся coroutine учитываются в логе. Незавершённая работа
сохраняет identity/lease для последующего recovery.
Это не утверждение об остановке Android Task при выключении backend.

## Файлы и проверки

- [Migration](../../../alembic/versions/20260920_pipeline_lease.py),
  [model](../../../backend/models/pipeline.py): owner/generation/lease, phase,
  начало шага и ID дочернего pipeline; индекс для recovery.
- [Ownership](../../../backend/services/orchestrator/pipeline_ownership.py),
  [recovery runner](../../../backend/services/orchestrator/pipeline_recovery.py),
  [executor](../../../backend/services/orchestrator/pipeline_executor.py): bounded
  claim, lease renewal, generation fencing и атомарная точка восстановления.
- [Handlers](../../../backend/services/orchestrator/step_handlers.py): сохранение
  child identity, повторное ожидание, проверки владельца перед SQL-записями;
  параллельные delay/action сериализуют доступ к общей session.
- [Pipeline service](../../../backend/services/orchestrator/pipeline_service.py),
  startup/shutdown router, response schema/OpenAPI и orchestration UI.

**120 связанных backend tests прошли**, включая 31 recovery case, миграцию,
lifecycle и предыдущие admission/cancellation/SQL-wait suites. **234 frontend tests
прошли**, TypeScript без ошибок; целевые Ruff и mypy прошли. **Полный backend:
1848 passed**, пять существующих deprecation warnings; исключены только выделенные
load profiles. Финальная синхронизация OS-kill test отдельно повторена успешно.
Точные счётчики и границы — в [evidence](evidence/pipeline-recovery.json).

Проверены:

- Принудительное завершение **отдельного OS-процесса** тестового worker после
  сохранения child, затем recovery новым executor и ровно один сохранённый Task.
- Потеря coroutine после получения receipt и после checkpoint commit; старый шаг
  не повторяется, child identity сохраняется до атомарного перехода.
- Два recovery-worker, старое поколение того же process-owner, поздний результат,
  heartbeat false/exception/timeout, lock wait дольше lease, partial external failure.
- Pause/resume, shutdown/drain, неизменный общий timeout, остаток delay, nested child,
  несоответствующий tenant/device child, параллельные handlers, повторяемая миграция.
- Реальный PostgreSQL и изолированные тестовые tenants. Child receipts записывает
  fixture; тест **не запускает действие на APK**. В OS-kill сценарии lease принудительно
  истекает после подтверждённой смерти процесса для быстрого детерминированного теста;
  отдельно проверено настоящее течение времени под SQL-блокировкой.

Промежуточные failures не скрыты: первый expanded run содержал некорректную модель
delay (он уже истёк, поэтому handler не вызывался); её заменили на condition для
проверки позднего результата. Два heartbeat tests первоначально инжектировали отказ
до входа в шаг; добавлено ожидание его старта. Повторный расширенный набор прошёл.

## Rollout и остаточные ограничения

1. Миграция консервативно помечает старые RUNNING/PAUSED/WAITING и уже стартовавшие
   QUEUED как `unknown`: у них нет надёжной точки восстановления. Не запускать
   автоматический replay старых записей. Перед rollout остановить admission,
   сверить active child receipts и обновить **все** backend workers согласованно.
2. Старый backend не проверяет generation. Смешанные версии workers не обеспечивают
   этот контракт. Downgrade удаляет checkpoint/lease поля и поэтому требует остановки
   работы и сверки receipts, даже если сама миграция технически обратима.
3. **Nested capacity остаётся OPEN:** родители занимают слоты в ожидании child.
   Нужен сохраняемый WAITING с освобождением capacity. Общая/per-device квота также
   не реализована; AUD-130 ограничивает только один executor.
4. **Batch F32-03 остаётся OPEN.** Здесь восстанавливаются PipelineRun, не потерянный
   план ещё не созданных batch waves.
5. Внешний HTTP/Redis/root effect не становится exactly-once от SQL lease. При
   неизвестном результате требуется разбор; безопасный операторский reconciliation
   workflow ещё нужен. Legacy `action` publisher не подтверждает физическое выполнение.
   Произвольные плагины должны соблюдать тот же контракт identity/fencing.
6. Полная матрица длительного SQL/Redis outage, остановки сети, 32 настоящих экранов
   и восьмичасовой soak остаётся открытой. Новые heartbeat создают SQL-нагрузку;
   её влияние на 32/64 устройства ещё предстоит измерить.

Новый pilot не обновлялся: backend `85fb1ea`, frontend `03b161e`, оба APK `1.2.7/10207`.
Старые `sphere-platform` и `sphere-tunnel` не изменялись. F32-02 продвинут в исходном
коде и изолированных тестах; это **не native rollout и не GO для длительного 32-device теста**.
