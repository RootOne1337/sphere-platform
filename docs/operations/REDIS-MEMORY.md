# Redis: память, сохранение и приёмка

**Обновлено 23 сентября 2026 · AUD-139 / AUD-143 · live pilot остаётся на 1536 MiB.**

[Readiness](READINESS.md) · [Fleet32](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [Доказательства](../audits/2026-09-20/REDIS-MEMORY.md)

## Бюджет

| Настройка | Source Compose profiles (не фактический runtime limit уже работающих контейнеров) |
| --- | --- |
| Redis `maxmemory` | 512 MiB, прежняя ёмкость |
| Compose container memory limit | 2048 MiB |
| Eviction | `allkeys-lru`, без изменения семантики |
| Persistence | AOF / `everysec` и прежние RDB schedules |

Лимит контейнера — верхняя граница, **не резервирование** 2 GiB при старте.
Он покрывает dataset, возможную копию изменённых страниц при fork и запас под
allocator, процесс, AOF/client buffers и charged filesystem cache. Это правило проекта, а не универсальная
гарантия для любого числа clients/подписок. Проверяйте общий бюджет Docker VM и
станции вместе с PostgreSQL, backend, браузером и эмуляторами.

`maxmemory` не ограничивает весь RSS/cgroup. Redis отдельно описывает память
буферов, исключённую из eviction accounting: [Redis eviction](https://redis.io/docs/latest/develop/reference/eviction/).
Fork, fragmentation и объём записей требуют дополнительного запаса:
[Redis administration](https://redis.io/docs/latest/operate/oss_and_stack/management/admin/).

## Проверка и изменение установленного экземпляра

Сначала сверьте Compose project/service labels, текущие image/container ID,
`HostConfig.Memory`, `MemorySwap`, `INFO memory` и сохранённую конфигурацию.
При изменении только верхнего лимита Docker допускает `docker update --memory`
с согласованным `--memory-swap`: Redis перезапускать не требуется. Используйте
конкретный проверенный ID нужной установки; изменение файла Compose обязательно
для сохранения бюджета при будущем recreate. Runtime update сам файл не меняет.

После изменения независимо проверьте actual limit, неизменность Redis PID/start
time, `PING`, API readiness и связь APK. Пароль передавайте внутри контейнера
через `REDISCLI_AUTH`; не помещайте настоящий пароль в логи/командные аргументы.

Уменьшение лимита требует отдельной оценки текущей памяти: возврат к прежним
128 MiB под заполненной БД способен немедленно вызвать OOM. Откат config commit
не означает, что такой runtime downgrade безопасен.

## Повторяемая изолированная проверка

После установки backend test dependencies:

```text
python -m pytest tests/deployment/test_redis_memory_budget.py -q
python tests/containers/run_redis_memory_probe.py --evidence-dir redis-memory-evidence
```

Первой команде нужны обычные синтетические test Settings, включая `JWT_SECRET_KEY`.
Runtime probe создаёт собственный контейнер `sphere-redis-budget-*`, сеть `none`,
без host ports, существующих volumes и swap. Синтетические credentials берутся
из Compose renderer. Он записывает 14 000 SET по 64 KiB, затем две такие же серии
одновременно с BGREWRITEAOF/BGSAVE, проверяет AOF/RDB status и restart. Сохранённый
marker и число оставшихся ключей должны совпасть. Оставшиеся — потому что нагрузка
намеренно превышает cache limit и вызывает eviction.

Probe удаляет только созданный container/anonymous volume после проверки уникальной
метки. Каталог evidence должен быть новым; повтор не перетирает предыдущий результат.
Отсутствующий kernel peak counter отмечается `null`, а не нулевым потреблением.
CI запускает эту проверку и сохраняет артефакты.

## Текущая CI-проверка и live граница

На PR head `e635de8` unit/real-service suite завершился: **1 996 tests, 0 failures,
0 errors, 15 skipped**. Последующий isolated Redis probe при лимите 1536 MiB
завершился `ExitCode=137`, `OOMKilled=true` во время AOF persistence с параллельными
14 000 SET по 64 KiB. Перед persistence в сохранённом результате было около
704 MiB `used_memory`, включая около 192 MiB AOF buffer; сам контейнер был удалён
probe. Это подтверждённая нехватка headroom в этой нагрузочной точке, не live outage.

Source Compose budget повышен до **2048 MiB**, при прежних 512 MiB dataset.
`test_redis_memory_budget.py` требует минимум 4× dataset для всех семи runtime
profiles; восемь regressions прошли. На PR head `bee9bc0` повторная isolated probe
прошла: AOF rewrite, BGSAVE и restart successful, `OOMKilled=false`, 6,531 ключ
сохранён. Однако kernel peak был ровно **2048 MiB**, то есть дошёл до лимита.
Подтверждён именно этот bounded persistence сценарий; spare memory и 32 stream
capacity не доказаны. Сохранённый live pilot остаётся на 1536 MiB до отдельного
проверенного rollout; Compose-файлы не меняют запущенный контейнер.

## Открытые ограничения

- Cache eviction и отказ самого Redis — разные сценарии. `allkeys-lru` по-прежнему
  допускает удаление управляющих ключей; SQL intents не делают все Redis-ключи
  восстановимыми. Нужна проверка назначения ключей и политики по их смыслу.
- Slow PubSub consumers, суммарные buffers 32 streams и reconnect storm в этом
  probe не моделируются. Их budgets и latency остаются gate для Fleet32; новый
  2048 MiB probe прошёл, но measured peak достиг лимита.
- Graceful restart не доказывает отсутствие потери последней секунды AOF при
  аварийном отключении питания и не является backup/restore-проверкой всего проекта.
- Отдельный preview template не входит в исправленные runtime combinations:
  его ошибку Compose render зарегистрировали как F32-27; preview не развёртывали.
