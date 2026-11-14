# F37: поиск всего журнала и подтверждённый CSV

**Срез:** 2 октября 2026,17:12 UTC+5.<br />
**Установлено:** UI `67b6bef`, API `39baa13`, [review3015/audit](http://127.0.0.1:3015/audit).<br />
**Исходный аудит:** `1354d66`, commit документа `80fb365`; исторический аудит не переписан.

[Операторский контракт](../../operations/AUDIT-INVESTIGATION.md) ·
[Evidence JSON](AUDIT-INVESTIGATION-EVIDENCE.json) ·
[Реестр F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Текущее состояние](../../operations/CURRENT-STATE.md)

## Что было неправильно

Веб передавал только page/per_page. Статус, действие, пользователь и DSL фильтровали
уже загруженные100 событий; CSV сериализовал только видимые строки. Оператор мог
получить пустой результат при наличии нужного события на следующей странице.
Cached rows также могли оставлять экспорт доступным после отказа свежего чтения.

На предыдущем source `5d27624`11 новых UI assertions failed,0 control passes,
0 runtime-error suites. На настоящем PostgreSQL/RLS18 из первоначальных24
проверок failed,6 controls passed. Первые черновые запуски UI имели ошибку data
fixture и затем проблемы разрешения config/React; они не используются как доказательство.
Финальная before-проверка использовала immutable old page и тот же frontend runtime.

## Реализовано

- Одна серверная валидация/построитель для списка и CSV: status, literal action,
  resource type, actor UUID, диапазон aware timestamps и AND DSL/free text.
- Фильтры проверяются по всей текущей организации; права `audit:read` и runtime RLS
  сохраняются. Ограничены page size, длина/число поисковых условий и объём экспорта.
- Веб отделяет черновик от применённого запроса, сбрасывает page1 и сохраняет
  условия при paging. UTC ввод не зависит от часового пояса ПК.
- CSV делает один projection SELECT, до5000 строк, исключает произвольные payloads,
  нейтрализует spreadsheet formulas, сообщает rows/limit/truncation/observed time.
- Отмена, ошибка, malformed receipt и смена session не становятся скачанным файлом.
  Состав CSV подтверждается backend headers; cap и дальнейшие действия видны оператору.

Коммиты:

1. `39baa13`: API,37 PostgreSQL cases, generated OpenAPI172 operations/135 paths.
2. `67b6bef`: интерфейс,29 новых UI/validation cases и операторская документация.
3. Отдельный documentation commit сохраняет эту установленную приёмку и новый ledger.

## Проверки

| Уровень | Фактический результат |
| --- | --- |
| Frontend focused | 36 cases,0 failures |
| Frontend полный | 98 suites /806 tests,0 failed /0 skipped;224 regressions сверх исходных582 |
| PostgreSQL новые | 37 cases: поиск за page1, даты/границы, actor/RLS, CSV cap/формулы, status parity |
| PostgreSQL вместе с предыдущими audit/hierarchy | 61 cases passed |
| Те же61 внутри новой production image | Passed,0 failures;1 существующий deprecation warning |
| TypeScript | `tsc --noEmit` passed |
| Backend static | mypy223 files passed; production Ruff0.15.2 passed |
| Lint/compile |44 существующих frontend warnings; обе immutable Linux Docker сборки passed |
| Generated contract | Actual backend image `export_api_docs --check` passed |

Локальный старый Ruff0.3.0 отметил две существующие E721 строки других модулей;
повтор с закреплённым production Ruff0.15.2 прошёл. Проверка generated API также
выполнена с production dependencies, а не старой локальной Pydantic/FastAPI средой.

## Живая конечная проверка

В12:10:44 UTC /17:10:44 UTC+5 сервер вернул5386 audit events. Выбрано событие
со второй страницы, отсутствующее в первых100. По его ID вместе с actor/action/
status/resource и равными границами времени сервер нашёл ровно одну запись;
CSV содержал ту же запись и нормализованный результат,7 разрешённых столбцов.
Неверный page size, naive/reversed date, invalid DSL и cap5001 дали422;
неавторизованный экспорт401; пустой экспорт корректно вернул0 rows.

В12:12:17 UTC полный ограниченный экспорт вернул **5000 уникальных событий**,
`X-Audit-Truncated:true`,995229 bytes. Оставшиеся события не включены и не объявлены
выгруженными. Конечный запрос занял0.090s; это один trial текущего небольшого журнала,
не SLO и не нагрузочная приёмка. Raw CSV/строки и credentials не опубликованы.

Backend установлен12:09:08 UTC; UI12:11:15 UTC, gateway12:11:21 UTC. В12:12:04 UTC
login/same-origin API, compiled stamp/static asset, unauthorized observability401,
Prometheus backend UP, Grafana scoped session/health и events WS snapshot/pong passed.
Каталог19,online14/offline5 после backend replacement — конечный срез восстановления,
не новая soak-приёмка. Все43 прочих контейнера (13running) сохранили IDs/images/
StartedAt/running; APK, OTA, Tuna и public frontend не изменены.

**CI:** предыдущий published `5d27624` полностью завершил backend/frontend/Android
success. Source `67b6bef`: [frontend37004977091](https://github.com/RootOne1337/sphere-platform/actions/runs/37004977091)
success; [backend37004977150](https://github.com/RootOne1337/sphere-platform/actions/runs/37004977150)
и [Android37004977161](https://github.com/RootOne1337/sphere-platform/actions/runs/37004977161)
ещё выполнялись на срезе документа. Следующий docs head требует своих checks.

## Что не принято

F37 source и конечный API/CSV путь исправлены. **30 из41 source findings fixed,
11 исходных OPEN.** Свежая визуальная проверка браузера/сохранения файла, F40/F41,
mass OTA, remote FPS/input latency и20–30-device stream+script trial остаются OPEN.
URL policy браузера не обходилась. Обновление backend/UI не изображается APK fix.

Экспорт ограничен5000; нет автоматического cursor continuation или неограниченного
архива. Список остаётся живым offset view; count/page могут сдвигаться при новых
INSERT. ILIKE на миллионах событий требует отдельной индексации/нагрузочного анализа.
Audit background writer всё ещё best effort при DB/process crash; durable outbox
не закрыт этим batch. N01 Android artifact upload и N03 legacy RPC errors OPEN.
