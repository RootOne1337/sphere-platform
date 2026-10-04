# Ресурсы хоста: диск, Windows commit, WSL и контейнеры

**Проверено:** 4 октября 2026. Источник правил сборки: `c1a6e79`.

[Текущее состояние](CURRENT-STATE.md) · [Readiness](READINESS.md) ·
[Аудит инцидента и измерения](../audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md) ·
[Предварительная проверка](../../scripts/pilot/resource_guard.py) ·
[Её регрессионные проверки](../../tests/test_pilot_resource_guard.py).

## Что проверять перед сборкой

Из корня проекта, имея Python 3.11+:

```powershell
python -m scripts.pilot.resource_guard --output .local-pilot/resource-preflight.json
```

На данном стенде Python доступен также через `.venv-audit/Scripts/python.exe`.
Выход `0` означает, что все измерения доступны и проходят пороги. Выход `2`
блокирует следующую тяжёлую сборку. Ошибка измерения также блокирует допуск.
Запуск самостоятельно ничего не удаляет, не перезапускает и не отправляет Android.
Его нужно явно включать в локальную процедуру сборки: универсальный перехват
всех `docker build`, IDE и сторонних сборщиков этим CLI не реализован.

| Измерение | Предварительный порог | Значение и ограничение |
|---|---|---|
| Свободное место на томе workspace | Не менее 20 GiB | Если Docker disk image расположен на другом томе, дополнительно проверять этот том |
| Доступная физическая память | Не менее 4 GiB | Не обещает, что любой размер сборки поместится |
| Windows committed / commit limit | Строго менее 85% | Это обязательства виртуальной памяти, а не процент занятой физической RAM |
| Неизвестное/некорректное измерение | Отказ | Нет подмены отсутствующего значения здоровым нулём |

Пороги — консервативный допуск этого стенда, не универсальный production SLO.
Флаги `--path`, `--min-disk-gib`, `--min-ram-gib`, `--max-commit-percent` задают
явную политику; недопустимые/нечисловые пороги отклоняются. На Linux используется
`MemAvailable`; Linux `Committed_AS` не сравнивается с Windows commit limit.
Проверка диска через `shutil.disk_usage` измеряет том переданного пути.

## Измерения без изменения состояния

```powershell
Get-PSDrive C
Get-CimInstance Win32_OperatingSystem |
  Select-Object LastBootUpTime,TotalVisibleMemorySize,FreePhysicalMemory
Get-CimInstance Win32_PerfFormattedData_PerfOS_Memory |
  Select-Object CommittedBytes,CommitLimit,PoolNonpagedBytes,PoolPagedBytes
Get-Process |
  Sort-Object PrivateMemorySize64 -Descending |
  Select-Object -First 15 ProcessName,Id,PrivateMemorySize64,WorkingSet64
docker stats --no-stream
docker system df
docker system df -v
docker buildx du
wsl.exe -d docker-desktop -- cat /proc/meminfo
```

Размеры CIM `TotalVisibleMemorySize`/`FreePhysicalMemory` имеют единицу KiB;
`CommittedBytes`, process private/working set — байты. Сохранять исходные единицы,
время UTC и `LastBootUpTime`. Один PID нельзя сравнивать через перезапуск:
для тенденции нужен PID вместе со временем создания процесса.

`docker stats` учитывает контейнерную память; `vmmemWSL` включает также ядро,
Linux page cache, Docker/containerd и сборку. Эти показатели не складываются
как независимые потребители. `Cached`/`Buffers`, `AnonPages`, `MemAvailable`
и swap следует сохранять раздельно. Docker отдельно описывает удержание
page cache после сборок в [WSL backend guidance](https://docs.docker.com/desktop/features/wsl/).

`.wslconfig` действует на все WSL2-дистрибутивы; его отсутствие не доказывает,
что reclaim отключён. В текущей документации Microsoft `autoMemoryReclaim`
по умолчанию — `dropCache`. Наличие режима по документации и фактическое поведение
установленной версии нужно различать. [Официальные настройки WSL](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

## Как отличать утечку от нагрузки

| Наблюдение | Что проверять дальше |
|---|---|
| Private bytes одного неизменного процесса растут при постоянной нагрузке | Количество объектов/подписок, managed/native heap, повторяемость и возврат после закрытия сценария |
| `vmmemWSL` растёт, но `AnonPages` почти не меняется | Page cache, buffers, сборки, reclaim, swap; не объявлять утечкой приложения |
| Windows commit растёт при доступной физической RAM | Private allocation, размер/занятость page file и memory compression |
| Browser растёт при открытых потоках | Число вкладок/декодеров, decoder queue, VideoFrame.close, canvas, освобождение Blob URL |
| Docker VHD растёт при стабильном размере данных | Image history, повторные dependency layers, build cache и container logs |
| Backend cgroup растёт | PID/start time всех worker, RSS/PSS/heap; cgroup != Python heap |

Для приёмки длительной утечки нужен фиксированный сценарий: idle → выбранное
видео → закрытие видео → повтор; количество устройств/вкладок и сборок записано.
Сравнивать одинаковые process/container epochs и хранить конечное число срезов.
Рост при новой нагрузке, пять минут и перезагрузка не доказывают отсутствие утечки.
В аудитном окне 4 октября сборщик завершался сам; постоянного фонового сборщика
или новых heartbeat-уведомлений это изменение не создаёт.

После конечного12-минутного окна в17:32:56UTC запущен отдельный read-only sampler
на8часов:241срез, интервал120s,≤256KiB/срез,≤60,25MiB суммарно; ранняя остановка,
если свободного C: менее512MiB. Он скрыт, не registered service/autostart,
не переживает reboot, Android команды не отправляет. Первый полный sample
подтверждён; завершение/долгосрочный вывод пока не получены. Private receipt и
raw files: `.local-pilot/resource-recovery-20261004/overnight-monitor-receipt.json`
и `overnight-window-bounded`. Останавливать только после сверки PID+UTC start
ticks+command identity по receipt; не массовым завершением Python/WSL/Docker.

## Политика сборочных артефактов

Frontend Dockerfile выделяет `build-deps` до `BUILD_SHA`. Зависимости меняются
при изменении package/lock/base image, а не номера коммита. `npm cache` после
установки и `.next/cache` после сборки удаляются из соответствующих слоёв;
standalone output, static files, runtime dependencies и generated types остаются.
Два номера коммита приняты только после проверки одинаковых RootFS layers/config
и `CACHED` для `npm ci`. Attestation manifest ID может отличаться.

Перед удалением накопленных локальных артефактов составлять точный план:

1. Путь разрешён и находится внутри workspace `.local-pilot`; symlink/junction
   исключены, разрешённые корни не получены из непроверенного shell-текста.
2. Для старого git-archive context список файлов подтверждён по его commit;
   текущая сборка и rollback context сохраняются.
3. Для Next удаляется только подтверждённый `.next/cache` старого snapshot;
   `.next` runtime, `node_modules`, доказательства, APK, env и credentials сохраняются.
4. Image принадлежит точному repo этого compose-проекта, имеет проверяемый
   Git revision, не моложе 48 часов и не используется ни одним running/stopped
   контейнером. Проверять повторно непосредственно перед удалением.
5. Сохранить current/rollback и новые canary images. Все другие проекты исключить,
   даже если их имя начинается с `sphere`.
6. Записать намерение, результат, изменение свободного места и неизменность
   container ID/image/start times и data volumes. Отказ проверки останавливает действие.

4 октября выполнена разовая адресная очистка по этому принципу. **Автоматическое
периодическое удаление старых images/contexts ещё не включено**. Docker build cache
имеет отдельный [механизм GC](https://docs.docker.com/build/cache/garbage-collection/);
его фактическая конфигурация на хосте не аттестована этим этапом.
Глобальный prune и volume prune не являются допустимым способом устранить эту
ошибку проекта: тома могут содержать БД, ключи и чужие приложения.

## Логи и данные

Core compose теперь задаёт `json-file`, `max-size: 20m`, `max-file: 5` на сервис.
Это потолок порядка 100 MB текущих stdout/stderr-файлов, не лимит всех данных.
Применение требует пересоздания контейнера. На 4 октября новый backend реально
принял этот LogConfig; старые БД/прочие сервисы не были массово пересозданы.
Review UI уже ограничен `5m × 3`. Prometheus сохраняет TSDB в пределах ранее
заданной политики `14d / 2GB`; это отдельная retention.

APK FileLoggingTree хранит 5 файлов по 2 MiB и ограниченные диагностические tails.
Серверные agent logs имеют 50 MiB на дневной файл и 30-дневную очистку при следующем
upload. Это **не** глобальная/per-device quota и не независимый sweeper; offline
device logs могут сохраняться дольше. Их source gap остаётся в плане работ.
Удаление текущих operational logs ради свободного места требует сохранения
нужного incident window; размер логов следует измерить до объявления их причиной.

## Docker VHD: свободное Linux-место и свободное Windows-место

Удаление image внутри ext4 освобождает место в Linux, но не обязательно уменьшает
физически размещённый Windows VHD. В текущем случае VHD был 218,61 GiB без sparse
атрибута. Image/build-cache counters содержат shared layers; складывать их размеры
как уникальные физические байты нельзя.

Offline compaction — отдельная процедура обслуживания после проверки backup,
владельца/точного пути VHD, остановки Docker и нужных WSL-дистрибутивов, detach
и проверки результата. Microsoft требует VHD detached или read-only для
[`compact vdisk`](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk).
Этот этап **не** выполнял compaction и не уменьшал pagefile/WSL лимиты.
Живой `docker_data.vhdx` нельзя удалять, подменять или compact при работающих сервисах.

## Следующие критерии приёмки

- Длительный сценарий RAM с одинаковой нагрузкой и epochs; раздельно commit,
  process private/working set, WSL anon/cache/swap, container memory.
- Host/worker metrics в защищённом мониторинге, корректные labels и alerts.
  Текущий `process_resident_memory_bytes{job="sphere-backend"}` не даёт series;
  RSS Prometheus самого себя не является RSS backend.
- Проверяемая периодическая retention только собственных build artifacts;
  rollout LogConfig прочих сервисов по очереди с сохранением данных.
- Отдельное обслуживание VHD при необходимости; измеренное физическое свободное
  место до/после, backup и восстановление API/Tuna/fleet.
- Global/per-device server log quota и sweeper; исключение роста списка labels,
  подписок и очередей при многократном подключении/отключении.
