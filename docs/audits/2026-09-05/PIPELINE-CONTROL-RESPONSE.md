# Pipeline control сохранялся, но возвращал HTTP 500

**14 сентября 2026 · AUD-116 · High operational · native Pause + real PostgreSQL before/after.**

[Аудит](AUDIT-REPORT.md)

## Причина и воспроизведение

Настоящий pipeline `delay → execute_script → delay` принят сервером. POST Pause
во время первой задержки сохраняет `paused`, затем отвечает 500. Журнал:
`PipelineRunResponse.updated_at`, `MissingGreenlet`. Последующий GET нужен для
установления фактического результата; повторять изменяющий запрос нельзя.

SQLAlchemy обновляет `updated_at` SQL-выражением `now()` при UPDATE, после чего
поле истекает в ORM. Ответ Pydantic читает его синхронно и запускает async lazy
load. Такая же ошибка воспроизведена для **pause, resume, cancel, update, toggle**.

## Fix и tests

`backend/api/v1/pipelines/router.py`: после commit каждого из пяти изменений
явно ожидается `db.refresh` изменённого run/pipeline перед сериализацией ответа.
Транзакции, права и семантика действий не изменены.

`tests/production/test_pipeline_mutation_response.py`: **5 baseline failures**,
после fix **5 pass** на отдельном PostgreSQL через реальные HTTP routes.
Свежий GET должен вернуть то же состояние и `updated_at`.

## Границы

Исправление ответа не доказывает остановку уже исполняющегося шага. Pipeline
pause/cancel проверяются executor между шагами; мгновенная остановка Android
требует отдельного управления DAG. Ранний resume до завершения текущего handler,
worker recovery и конкурентные изменения требуют самостоятельных проверок.
Backend `12249b1` установлен только в новом pilot; все CI исходной ревизии
прошли: [архив](evidence/ci-12249b1-summary.json). Native после fix: Pause удержал
переход к Android-шагу, Resume дал ровно `hold → native → finish` с полным DAG
result; Cancel на втором устройстве не допустил следующий native шаг.
В отдельном совместном прогоне это повторено одновременно со стримом и batch.
92 связанных теста, включая 13 проверок самого harness, прошли локально.
[Сводка](evidence/overnight-preflight-summary.json) ·
[Профиль ночного прогона](../../operations/ANDROID-OVERNIGHT-SOAK.md).
