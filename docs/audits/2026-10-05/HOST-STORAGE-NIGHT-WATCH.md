# Конечное ночное наблюдение диска и ОЗУ

**Дата:** 5 октября 2026, Asia/Yekaterinburg.<br />
**Source:** `02b5084`; API/UI остаются `c1a6e79`.<br />
**Статус:** RUNNING / HISTORICAL_ATTRIBUTION_OPEN / LONG_RAM_SOAK_OPEN.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Процедура](../../operations/HOST-RESOURCES.md) ·
[Санитизированные измерения](HOST-STORAGE-NIGHT-WATCH-EVIDENCE.json) ·
[Предыдущая ETW/VSS атрибуция](DISK-WRITER-ATTRIBUTION.md) ·
[Применённая квота VSS](VSS-RETENTION-REVIEW.md)

## Решение оператора

Разработку продолжаем без ожидания очередного падения свободного места.
Наблюдатель сохраняет ограниченные метаданные в фоне; при повторном расходе
сопоставляем независимые счётчики и затем включаем короткую трассировку writer.
Очистка не принимается как доказательство устранения постоянного роста.

## Что уже установлено

Большой `docker_data.vhdx` занимает **234 731 077 632 байта / 218,61 GiB**
по native allocated-size API. Это общий диск Docker Desktop, содержащий несколько
проектов, а не размер tracked исходников Sphere. Предыдущий `du` разделяет
containerd image/snapshot store около175GiB, volumes около7GiB и directories
контейнеров около307MiB. Текущие `docker system df` и guest `df` измерены отдельно.

В предыдущем интервале VSS allocated +1,969GiB почти совпал с C: free −2,033GiB.
Применённая с согласия оператора квота8GiB освободила17,205GiB на Windows;
это отдельное изменение retention с удалением двух прежних restore copies.
Исторические потери десятков гигабайт целиком этому механизму не приписаны.

## Дополнительная адресная очистка кэша

**4 октября23:52:00–23:54:27 UTC**: рассмотрены130 private immutable reclaimable
cache IDs с display age≥3days. Для каждого повторены native exact-ID lookup,
Reclaimable/Shared/Mutable и консервативный age guard; prune получает exact ID
и `until=48h`. Состояние всех контейнеров сверялось каждые10 кандидатов и в конце.

Фактический результат:

- cache records **795→768**; число image objects **186→186**;
- guest filesystem used **199 318 523 904→198 172 246 016 байт**;
- освобождено **1 146 277 888 байт / 1,068 GiB внутри guest**;
- все46 container IDs/images/start epochs/status и67 volume names сохранены;
- native allocated VHD **не изменился**; это не дополнительный Windows free gain.

130 рассмотренных IDs не означают130 удалённых: часть native calls вернула0B,
включая зависимости, которые BuildKit сохранил. Нет `--all`, удаления volumes,
container restart или общего `docker system prune`. Кэш восстанавливается при
следующих сборках; недавние и shared records не вошли в выбранный список.

Installed buildx0.32.1-desktop.1 возвращал JSON с human display age/size,
в отличие от текущего примера документации. `du --filter until=48h` отдельно
вернул весь inventory, поэтому он не использован как доказательство eligibility.
Повторный `id=<ID>` проверялся на точное совпадение, а native prune сохранял
свой age filter. Отчёт не суммирует пересекающиеся image/cache display sizes.
Механизм общей storage и native filters описан в
[Docker du](https://docs.docker.com/reference/cli/docker/buildx/du/) и
[Docker prune](https://docs.docker.com/reference/cli/docker/buildx/prune/).

## Рабочий сборщик

[`host_storage_watch.py`](../../../scripts/pilot/host_storage_watch.py)
запущен отдельным hidden elevated process. Native PID и фактический первый
полный sample проверены; source SHA-256 совпадает с конфигурацией запуска.
Обычная tool-сессия остаётся с обычным Windows token.

**Текущее окно:** 4 октября23:58:34 UTC → примерно5 октября07:58:34 UTC,
то есть **04:58→12:58 UTC+5**.241 срез с интервалом120s;
Docker/guest readback каждый8-й срез (16min), также последний.
Настройка и короткое предыдущее окно сохранены отдельно и не склеиваются
в восьмичасовую приёмку. Первый запуск с повторяющимися Windows paths отказал
до создания отчёта; исправленная конфигурация содержит97 distinct paths.

Каждый sample содержит:

- свободные байты C: и native allocated/logical размеры97 named files,
  включая Docker/LDPlayer VHD, pagefile и крупные ранее найденные файлы;
- exact VSS used/allocated/max для каждой пары volume/diff volume;
- Windows boot epoch, available/total RAM, commit/limit, paged/nonpaged pools;
- top32 process private bytes/working set с PID/start epoch;
- top16 process IO rates с явным признаком includes non-file traffic;
- отдельные Docker inventory/stats/epochs, guest `df` и Linux memory на своей cadence.

Неудачное чтение обозначается `unavailable`, неснятый Docker cycle —
`not_sampled_this_cycle`; старые значения не выдаются за свежие. Boot/VSS membership
changes отделены от comparable deltas. PID/process IO не является атрибуцией
постоянного заполнения диска. `pagefilesMiB` — usage из CIM, а allocated named-file
reading может быть недоступен из-за sharing; это разные измерения.

Ограничения:128KiB/sample, по умолчанию16MiB общий report budget с32KiB reserve
для status/temp; maximum32MiB configurable. Observation≤24h с bounded native
timeouts и deadline guard; текущий запуск8h. При C: free<512MiB — stop.
Нет directory walks, file-content reads, непрерывного ETL file logging,
автоматического удаления, service registration, autostart или команд Android.

Private directory текущего окна:
`.local-pilot/host-storage-night-20261004T235833`.
`status.json` сохраняется atomic replace; `samples.jsonl` ограничен budget.
Paths/process names/raw metadata не публиковать; JSON evidence выше содержит
только counters, scope и SHA-256 локальных квитанций.

## Проверки и дальнейшее действие

**68 диагностических tests passed**, включая реальные native Windows rejection,
WPR profile/status/VSS cases и новые window/budget/unknown-epoch/native-error
регрессии. Ruff0.15.2 для всего `scripts/pilot` и нового test file passed;
найденная старая I001 в codec probe исправлена только сортировкой imports.
[Новые tests](../../../tests/test_pilot_host_storage_watch.py).

После cache cleanup API ready, Postgres/Redis ok. Fleet срез23:56:58 UTC:
19 зарегистрированных,14 online,2×10245 /12×10244. Это конечный snapshot,
а не длительная приёмка связи/видео. APK/Tuna/backend/frontend не перераскатывались.

1. На следующем существенном drop сопоставить free delta, VSS allocation,
   allocated named-file growth, Docker guest usage и RAM/commit в одной boot epoch.
2. Если free loss остаётся необъяснённым — запускать имеющийся короткий named
   memory WPR collector и разбирать ограниченную ETL через TraceEvent;
   не создавать сотни мегабайт CSV и не повторять полный обход C:.
3. После конца окна проверить process epoch / latest sample / status. Reboot,
   отсутствие процесса или stale heartbeat означает INTERRUPTED/UNKNOWN,
   даже если последний status остался `running`; не объявлять отсутствие утечки.
4. Docker offline compaction требует отдельного сохранения persistent data и
   остановки обслуживания; в этом этапе она не выполнялась.

Heartbeat `enterprise` сохраняет прежнее расписание и продолжает разработку,
дополнительно проверяя это конечное окно. Без новых actionable фактов уведомлений
нет; завершение/отказ/новая доказанная причина сообщаются отдельно. Полная
историческая атрибуция, RAM soak, backend log global quota/idle sweeper,
VHD physical reclamation и прежние web/Fleet32 gates остаются открыты.
