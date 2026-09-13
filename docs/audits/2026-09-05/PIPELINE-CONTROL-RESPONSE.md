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
Native повторная приёмка оформляется после deployment; ночной прогон не получает
автоматически статус passed из-за успешной сборки.
