# HTTP 500 после сохранения нового сценария

**14 сентября 2026 · AUD-115 · High operational · native HTTP + PostgreSQL regression.**

[Аудит](AUDIT-REPORT.md)

## Дефект и причина

При подготовке ночного теста POST `/api/v1/scripts` с валидным безопасным DAG
вернул HTTP 500 на новом pilot. Журнал показывает `ScriptResponse.current_version`:
`MissingGreenlet`. Транзакция уже закоммичена: сценарий существует, хотя клиент
видит ошибку. Повторный POST может создать дубликат.

`create_script` сохраняет FK текущей версии, но отношение SQLAlchemy остаётся
незагруженным. Обычный `db.refresh(script)` обновляет колонки; Pydantic затем
пытается лениво загрузить `current_version` вне async greenlet.

## Минимальный fix и regression

В `backend/api/v1/scripts/router.py` перед сериализацией create response явно
ожидается `db.refresh(script, attribute_names=["current_version"])`.
Контракты API, права, версия DAG и момент commit сохранены.

`tests/production/test_script_mutation_response.py` выполняет настоящий HTTP/ORM
цикл на отдельном PostgreSQL. До fix: **create fail, update/rollback pass**.
После: все три проходят, новый GET через отдельную сессию возвращает ту же
сохранённую версию и DAG. Вместе с `tests/test_scripts`: **42 tests pass**.
Update и rollback оставлены без изменений; их eager-loaded отношения уже работали.

## Остаточный риск

Это не idempotency key для POST: потеря ответа после commit по другой причине
по-прежнему оставляет неизвестный клиенту результат. Ночной harness не повторяет
изменяющие запросы с неизвестным исходом; останавливает нагрузку и сохраняет ID,
когда он доступен.

Backend `625741a` установлен только в новом pilot: POST вернул 201, оба APK
выполнили созданный DAG (13 подтверждённых узлов), batch завершён с 2 success.
Все CI исходной ревизии прошли: [архив](evidence/ci-625741a-summary.json).
[Native сводка и дальнейший ночной прогон](evidence/overnight-preflight-summary.json).
