# AUD-139: OOM Redis до прикладного лимита

**21 сентября 2026 · F32-09 · P0 / High · source fix и изолированная runtime-приёмка.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Эксплуатационный контракт](../../operations/REDIS-MEMORY.md) · [Evidence](evidence/redis-memory.json)

## Root cause и affected files

[Base Compose](../../../docker-compose.yml) передавал `--maxmemory 512mb`, но
ограничивал процесс вместе с дочерними процессами и остальной памятью контейнера
до 128 MiB. Full/dev/local/remote pilot наследовали эту комбинацию. Production
overlay увеличивал container limit до 512 MiB — без запаса сверх dataset.

Read-only проверка нового pilot подтвердила 134 217 728 bytes container против
536 870 912 bytes Redis. На момент проверки used memory 1 784 960 bytes, RSS
13 463 552 bytes: **действующий pilot не был под OOM**, это будущий риск нагрузки.

## Evidence / reproduction

Baseline `071d47c`. Семь Compose combinations нарушили budget assertion;
отдельная восьмая ошибка — невалидный preview template (F32-27 ниже). Проверка
прежней dataset capacity прошла. Итого исходного расширенного набора: 8 failed,
1 passed; это не восемь OOM воспроизведений.

[`run_redis_memory_probe.py`](../../../tests/containers/run_redis_memory_probe.py)
запускает rendered pilot Redis в **собственном network-none container** без swap,
host ports и подключений к существующим сервисам. SET pressure 14 000 × 64 KiB
превышает dataset cap. До fix: **exit 137, OOMKilled=true**, benchmark прерван.
Контейнер удалён после сохранения evidence. Действующий Redis не нагружали.

Первый запуск harness завершился NOAUTH: redis-benchmark не использует
REDISCLI_AUTH. Его не считаем доказательством дефекта. После явного синтетического
пароля получено указанное OOM воспроизведение. Первая after-проба прошла pressure,
но остановилась на недоступном v2 memory.peak; после добавления v1 fallback
повторена целиком, включая restart. Эти границы сохранены в evidence.

## Минимальное исправление

Container limit base и production стал **1536 MiB** при прежних 512 MiB dataset,
LRU policy, AOF и RDB. Увеличена только верхняя граница, не reservation и не
фактическое потребление. [Regression renderer](../../../tests/deployment/test_redis_memory_budget.py)
проверяет семь настоящих Compose merges и сохранение исходной ёмкости/persistence.
Runtime probe добавлен в [backend CI](../../../.github/workflows/ci-backend.yml).

## Результат

- Восемь итоговых budget/capacity regressions passed. В более широком deployment
  запуске 110 passed и один подтверждённый preview render failure; preview затем
  вынесен из runtime-budget scope, а не замаскирован успешной проверкой.
- Fill и две серии записи по 14 000 × 64 KiB прошли. После первой серии — 7380
  evictions: фактический maxmemory достигнут. BGREWRITEAOF/BGSAVE и AOF write
  status — `ok` после записи во время persistence.
- Peak cgroup: **1 439 367 168 bytes** (включает память cgroup, не только Redis
  dataset); final sampled Redis RSS: **517 607 424 bytes**. Это результат данной
  нагрузки и kernel, не универсальный upper bound.
- Graceful stop/start сохранил marker и **6531** оставшийся ключ. OOM=false,
  не было автоматических restart; собственный тестовый контейнер удалён.

## Rollout и residual risk

Source fix подготовлен для нового pilot. Для применения достаточно поднять
container ceiling без перезапуска Redis; после применения будет сохранён
отдельный runtime receipt. Backend/frontend/APK менять для этого не требуется.

**F32-09 продвинут, но весь gate не закрыт:** бюджет buffers/slow subscribers,
семантика eviction управляющих ключей и 32-device Redis fault/reconnect ещё
не приняты. Этот fix предотвращает воспроизведённый OOM при данной нагрузке;
произвольную перегрузку и потерю последней секунды AOF при power loss не исключает.

## Дополнительно: F32-27 / P1 preview / Medium

Реальный `docker compose ... config --format json` отказывается читать
`docker-compose.preview.yml`: top-level volume key `preview-${PR_NUMBER}-pgdata`
невалиден. Переменные также используются в network/Traefik label keys.
Workflow копирует файл и вызывает Compose напрямую, без pre-render. Поэтому
успешный workflow guard при выключенном preview не является его runtime-приёмкой.

Дефект записан, template в этом fix не менялся и внешние preview hosts не
затрагивались. Он не блокирует текущий pilot; исправление preview требует
отдельного изменения и проверки фактического deployment path. Redis preview
также не имеет maxmemory; этот путь не входит в текущую приёмку.
