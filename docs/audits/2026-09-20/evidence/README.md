# Воспроизведения F32: запуск и ограничения

Исходный код проверен на `1c93cf0a04b07e6a005627d45be511364efe111d`.
[Основной отчёт](../FLEET32-PREFLIGHT.md).

| Файл | Содержание |
| --- | --- |
| [runtime-summary.json](runtime-summary.json) | Read-only snapshot только нового pilot; без credentials, host URLs и сырых crash/log buffers |
| [reproductions.json](reproductions.json) | Семь ожидаемых failing assertions, факты и ограничения controlled reproductions |
| [sql_probes.py](sql_probes.py) | Шесть сценариев с настоящей PostgreSQL и один с временным OTA JSON; явно запускаемые диагностические tests |
| [decoder_probe.cjs](decoder_probe.cjs) | Текущий активный TypeScript decoder со stalled codec double |
| [decoder-result.json](decoder-result.json) | Очереди, timestamp replacement и ошибка codec; не browser benchmark |

## Backend

Подготовить **отдельные локальные PostgreSQL/Redis** и схему по
[инструкции integration tests](../../../../tests/production/README.md).
`POSTGRES_URL`/`REDIS_URL` должны указывать на эти сервисы, а не pilot.
Fixture дополнительно требует loopback host и слово `audit` в имени disposable БД.
Нужны backend test dependencies и обычные test environment settings из этой инструкции.
URL/пароли не добавлять в репозиторий или публичные logs.

Из корня репозитория, после безопасной настройки окружения:

```powershell
$env:SPHERE_RUN_INTEGRATION = '1'
python -m pytest -p tests.conftest -p tests.production.conftest docs/audits/2026-09-20/evidence/sql_probes.py -q --no-cov
```

Ожидаемый результат на указанном source commit: **7 failed, 0 errors**.
Failures должны быть именно финальными assertions; import/fixture/connection error
не считается воспроизведением. Один тест специально заменяет результат отправки
stop на `False`; delay probe блокирует только handler sleep; остальные SQL writes
и выборки настоящие. Poll query ограничен случайной test organization, чтобы
исторические fixtures не влияли на результаты. OTA использует только `tmp_path`.

Эти probes находятся вне стандартного `testpaths=["tests"]` и не ломают обычный CI.
При исправлении переносить соответствующий сценарий в regression suite, дополняя
проверкой безопасного recovery и гонок. Assertions описывают отсутствующий контракт;
конкретное состояние `cancelling`/durable plan после fix может потребовать уточнения
проверки. Сам факт отказа текущего кода это не меняет.

## Активный frontend decoder

После установки frontend dependencies (`npm ci` в `frontend`), из корня:

```powershell
node docs/audits/2026-09-20/evidence/decoder_probe.cjs
```

Probe компилирует настоящий `frontend/lib/h264-decoder.ts`; `VideoDecoder` заменён
только для моделирования невычитываемой очереди и ошибки. На указанном коде:
2048 pending NAL / 2 MiB, 1000 decode submissions, source timestamp заменён временем
браузера, исключение после codec error выходит наружу. Никакого реального codec
или 32-device нагрузочного теста эта проверка не изображает.

## Pipeline RLS и nested capacity, 21 сентября

[AUD-133 evidence](pipeline-rls.json) фиксирует три baseline failures и 1880
passing backend tests после исправления RLS. Отдельная
[nested capacity probe](pipeline_nested_capacity_probe.py) на source `d859a52`
проверяет следующий открытый сценарий: десять родителей держат все слоты,
их пустые children не получают executor. [Сводка](pipeline-nested-capacity.json).
Запускать только с disposable loopback PostgreSQL/Redis и теми же guards:

```powershell
python -m pytest -p tests.conftest -p tests.production.conftest docs/audits/2026-09-20/evidence/pipeline_nested_capacity_probe.py -q --no-cov
```

На указанном source ожидается **1 failed, 0 errors** на финальном assertion
`parents_completed > 0`. Это не fault на pilot, не Android automation и не
часть проходящего стандартного CI. После исправления сценарий нужно перенести
в regression suite и дополнить restart/cancel/deadline проверками.
Последующий [AUD-134](../PIPELINE-NESTED-WAIT.md) сохраняет этот сценарий и дополнительные
regressions в `tests/production/test_pipeline_nested_wait.py`. Та же историческая
проба после fix проходит; before-сводка не переписана. [After evidence](pipeline-nested-wait.json).

## Сохранность evidence

Отдельное открытое продолжение F32-25 — [scheduler RLS](scheduler-rls.json).
`scheduler_runtime_probe.py` запускается теми же `-p tests.conftest
-p tests.production.conftest` и disposable-service guards; на базе `294bd15`
ожидается один final assertion failure (due exhausted schedule остаётся active).
Эта проба не создаёт Android-задачи и не считается passing regression.
Аналогично запускается `dispatcher_runtime_probe.py`: [evidence](dispatcher-rls.json)
фиксирует QUEUED без binding и ASSIGNED с ним. Transport/presence — заглушки;
ожидается один финальный assertion failure, не отказ реального устройства.

[AUD-135](../TASK-DISPATCH-RLS.md) исправляет зарегистрированный startup dispatcher:
[сводка до/после](task-dispatch-rls.json), regressions в
`tests/production/test_task_dispatcher_runtime.py` и migration regression. Baseline
из трёх startup failures сохранён; полный suite проверяет новый worker, RLS,
Redis startup, pagination, commit/transport ambiguity и настоящий SQL timeout.
Историческая `dispatcher_runtime_probe.py` намеренно вызывает unscoped TaskService
напрямую; это прежнее доказательство причины, а не проверка нового startup contract.
Транспорт — doubles, pilot/APK не обновлялись. CI предыдущего точного head `b08a773`
[прошёл все четыре workflows](../../2026-09-05/evidence/ci-b08a773-summary.json).

Сырые pytest logs, Android meminfo/crash buffers, operator credentials и deployment
configuration оставлены приватными. `runtime-summary.json` — исторический snapshot,
не постоянный health status. Данные старого Docker проекта не используются.
`reproductions.json` сохраняет точный source SHA; актуальность после новых fixes
проверяется повторным запуском, а не редактированием прошлых результатов.
