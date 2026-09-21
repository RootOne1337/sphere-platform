# Redis: память, сохранение и приёмка

**21 сентября 2026 · AUD-139 / F32-09 · `93551e0` применён к новому pilot без restart.**

[Readiness](READINESS.md) · [Fleet32](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [Доказательства](../audits/2026-09-20/REDIS-MEMORY.md)

## Бюджет

| Настройка | Base / development / full / production / local и remote pilot |
| --- | --- |
| Redis `maxmemory` | 512 MiB, прежняя ёмкость |
| Container memory limit | 1536 MiB |
| Eviction | `allkeys-lru`, без изменения семантики |
| Persistence | AOF / `everysec` и прежние RDB schedules |

Лимит контейнера — верхняя граница, **не резервирование** 1.5 GiB при старте.
Он покрывает dataset, возможную копию изменённых страниц при fork и запас под
allocator, процесс, AOF/client buffers. Это правило проекта, а не универсальная
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

## Открытые ограничения

- Cache eviction и отказ самого Redis — разные сценарии. `allkeys-lru` по-прежнему
  допускает удаление управляющих ключей; SQL intents не делают все Redis-ключи
  восстановимыми. Нужна проверка назначения ключей и политики по их смыслу.
- Slow PubSub consumers, суммарные buffers 32 streams и reconnect storm в этом
  probe не моделируются. Их бюджеты и latency остаются gate для Fleet32.
  CI probe прошёл без OOM, но cgroup peak достиг ceiling 1536 MiB (включая cache
  и прочую charged memory); дополнительный запас для stream workload не доказан.
- Graceful restart не доказывает отсутствие потери последней секунды AOF при
  аварийном отключении питания и не является backup/restore-проверкой всего проекта.
- Отдельный preview template не входит в исправленные runtime combinations:
  его ошибку Compose render зарегистрировали как F32-27; preview не развёртывали.
