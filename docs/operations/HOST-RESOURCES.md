# Ресурсы хоста: диск, Windows commit, WSL и контейнеры

**Проверено:** 4 октября 2026. Источник правил сборки: `c1a6e79`.

[Текущее состояние](CURRENT-STATE.md) · [Readiness](READINESS.md) ·
[Аудит инцидента и измерения](../audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md) ·
[Предварительная проверка](../../scripts/pilot/resource_guard.py) ·
[Её регрессионные проверки](../../tests/test_pilot_resource_guard.py).

**Последняя инвентаризация C: / 4 октября, 17:50 UTC:**
[размер workspace, крупные потребители, package cleanup и allocation](../audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP.md).
Workspace 7,996 GiB / tracked22,08 MiB; shared Docker VHD218,61 GiB отдельно.
После штатной очистки npm/pip — C: free41,43 GiB; runtime сохранён.

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

## Как локализовать постепенный рост диска

[`disk_growth`](../../scripts/pilot/disk_growth.py) — отдельная утилита для
конечных metadata observations. Она не чистит файлы, не перезапускает Docker
и не отправляет команды Android. Снимок содержит C: free, длину и физическое
размещение явно указанных файлов, сравнение полных доступных сумм каталогов
и ограниченный список изменившихся крупных файлов.

```powershell
python -m scripts.pilot.disk_growth `
  --root . `
  --file "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx" `
  --output-dir .local-pilot/disk-growth-run `
  --samples 97 --interval 300 --roots-every 3 --max-total-mib 16
```

Каталог результата должен быть новым. `--root` и `--file` можно повторить для
Temp, каталога runtime logs и конкретных дисков LDPlayer. Roots не должны
перекрываться. По умолчанию 97 срезов с интервалом 5 минут — плановое окно
8 часов; directory scan выполняется каждые 15 минут, named files — каждый срез.
Один root ограничен 500 000 entries / 60 сек; не более 12 roots / 100 named files.
Сборщик останавливается при C: free ниже 512 MiB, превышении report quota или
ошибке записи. Это конечный процесс, без service/autostart.
Выход `0` — завершено плановое окно; low-disk/error остановка возвращает `2`.

JSON samples ограничены 1 MiB каждый / 16 MiB суммарно при указанной конфигурации;
atomic temporary sample может кратковременно занять ещё до 1 MiB. Status —
отдельный небольшой JSON. Output самого сборщика исключён из directory scan,
но входит в реальное потребление места тома. Самопроизвольной очистки старых
наблюдений нет: завершённые окна обслуживаются отдельно.

**Raw samples содержат частные локальные пути. Не загружать их в публичный Git.**
Содержимое наблюдаемых файлов не читается. Reparse points не обходятся;
права доступа не повышаются. Missing/access/budget failures сохраняются явно;
partial scans не вычитаются из complete scans как доказательство роста.
Windows metadata API используют extended paths для локальных и UNC-каталогов:
файл с путём длиннее 260 символов должен попадать в измерение. До десяти
первых ошибок обхода сохраняются как относительный путь и тип ошибки,
чтобы partial scope можно было расследовать без чтения содержимого файлов.
Candidate set содержит до 2000 крупнейших файлов ≥1 MiB на root, его смена
не является доказательством создания/удаления файла. Logical totals не
дедуплицируют hard links; allocation отдельных VHD измеряется отдельно.
Windows `allocatedBytes` в этой утилите — результат `GetCompressedFileSizeW`:
для sparse/compressed файлов он отличается от длины, для обычных файлов API
возвращает длину. Это не полная бухгалтерия cluster rounding, NTFS metadata
и защищённых областей тома. [Контракт Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew).

Рост Docker VHD требует следующего сравнения Linux image/cache/volume/log
sizes. Рост LDPlayer image требует следующего измерения каталогов внутри
Android через разрешённый APK RPC. Read-only metadata указывает файл,
**но не PID программы, выполнившей запись**. Счётчики process I/O также нельзя
считать уникальным расходом диска: повторные записи, сеть и device I/O отличаются
от роста размещённых байтов. Для подтверждения writer использовать конечный,
отфильтрованный OS file-I/O trace, например
[Microsoft Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon),
после локализации пути. Не оставлять глобальную трассировку без лимитов:
сам trace способен создавать большие файлы.

[Регрессии диагностики](../../tests/test_pilot_disk_growth.py) проверяют sparse growth,
unknown allocation, replacement, доступ/partial scopes, candidate semantics,
реальный Windows long-path scan/allocation и преобразование UNC-путей,
storage/low-disk stops и расчёт delta по совпадающим концам измерения.

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

### Общие download caches хоста

Сначала измерить точный каталог и проверить `npm config get cache` / `pip cache dir`.
Download cache не равен установленным `node_modules`, virtualenv или каталогу
исходников. При адресном обслуживании использовать штатный `npm cache clean`
с `--force` и явным `--cache`, либо `pip cache purge` с явным `--cache-dir`.
После очистки следующая установка может снова скачивать зависимости.
`npm cache clean` не удаляет все `_npx` installations: CLI/MCP могут исполняться
оттуда. Их нельзя считать теми же одноразовыми archives или молча удалять вместе.
Не применять рекурсивное удаление всего AppData/Temp/Users или среды инструментов.

4 октября эти операции дали наблюдаемую прибавку4,726 GiB, а все46 контейнеров
сохранили ID/image/start. Два других Next cache directories0,819 GiB остались:
их удаление отклонила автоматическая проверка. Отклонённый запуск не является
очисткой; данные и границы действия сохранены в отдельном disk follow-up.

### Operational retention

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

## Продолжение 5 октября

[Наблюдение роста диска](../audits/2026-10-05/HOST-DISK-GROWTH.md) фиксирует
-6,459 GiB C: free в17 сохранившихся старых срезах без сопоставимого роста
workspace/Docker VHD. VSS candidate и writer trace OPEN; размер файла не заменяет
размер всех областей тома. Восьмичасовые окна прерваны после перезапуска приложения.
R09: native APK logs фактически 6обычных файлов при configured 5; исправление
ротации ещё не выпущено и не объясняет гигабайтовую потерю свободного места.

### Однократный запуск системных замеров

Если фактический terminal token не administrator, запуск UI приложения от
администратора сам по себе не считается подтверждением прав инструмента.
`vssadmin` / `fsutil volume diskfree` отказали текущей сессии и после перезапуска.
Для отдельного конечного окна открыть PowerShell **от имени администратора**:

```powershell
& 'C:\Users\dimas\Documents\ChatGPT\sphere-platform\scripts\pilot\collect_storage_allocation.ps1'
```

[Сборщик](../../scripts/pilot/collect_storage_allocation.ps1) выполняет только
`vssadmin list shadowstorage /for=C:` и `fsutil volume diskfree C:` и пишет свои
JSON в новый `.local-pilot/admin-storage-*`. Нет cleanup, service/autostart,
смены прав, рестартов или операций с Android. Окно PowerShell оставить открытым;
его можно свернуть. По умолчанию 31 срез / 60s, плановое окно 30 минут.
CLI ограничен одним часом, sample128KiB / reports4MiB и early stop при free<512MiB;
native query имеет timeout10s и до2s на завершение собственного child.
Final sample может закончиться после планового времени из-за query timeout.
Unknown/nonzero exit/truncation сохраняются, не означают нулевой расход.

Синтаксис проверен Windows PowerShell; реальные отрицательные запуски
подтвердили rejection без admin и при недопустимом/избыточном окне до создания
output. Дополнительно пользовательский запуск19:45:20 UTC подтвердил положительный
путь:31 срез / 19:45:20–20:15:20 UTC, все62 native queries exit0 без truncation.
Admin окно COMPLETE. Allocated VSS display вырос13,9→14,1ГБ; free -264,719MiB.
Размеры display округлены: это не точный VSS byte delta и не полная атрибуция
предыдущего гигабайтового скачка. Отрицательные unit checks сами по себе privileged path
не доказывают; здесь есть отдельные реальные квитанции.
[Регрессии](../../tests/test_pilot_storage_allocation.py).

### Ограниченная запись процесса и файла, 5 октября

[`collect_disk_writer.ps1`](../../scripts/pilot/collect_disk_writer.ps1) связывает
kernel FileIO/DiskIO с samples free C:, available RAM и exact VSS byte counters.
Фактическое продолжение запущено отдельным elevated child; обычная tool-сессия
по-прежнему не administrator. Проверять права по receipt, не по запуску UI Codex.

```powershell
& 'C:\Users\dimas\Documents\ChatGPT\sphere-platform\scripts\pilot\collect_disk_writer.ps1' -DurationSeconds 600 -IntervalSeconds 10 -StopAfterDropMiB 128
```

Один custom SystemCollector: 128×1024KiB memory circular payload; maximum1800s,
metadata sample128KiB / total8MiB, disk headroom20GiB и available RAM4GiB.
WPR проверяет чужую запись до старта и работает только с собственным instance.
Stop сохраняет compressed ETL без symbol downloads. Payload bound не ограничивает
размер native rundown/temp при сохранении. Нет постоянной службы или autostart.

Не экспортировать всю ETL в CSV без оценки места: реальный 18,7MB trace породил
552MB CSV, и запись наблюдателя сама вызвала free-drop. Проверенный разбор использует
Microsoft TraceEvent3.2.8 (MIT); logical writes, DiskIO transfer, growth и VSS
allocation учитываются отдельно. EventsLost0 не доказывает полноту circular начала.
Raw ETL/process commandlines/private paths остаются локально; публикуются sanitized
числа и SHA. [Фактическая запись и observer effects](../audits/2026-10-05/DISK-WRITER-ATTRIBUTION.md).

R09 обновлён: logger source `ae90715`, версия кандидата10245; ordinary5×2MiB,
encoded queue≤4MiB и truncation/drop counter. **1680 passed /2 skipped**.
PH010 local/PH025 remote уже10245: exact installed hash/receipt и startup quota6→5
подтверждены;12 других online ещё10244. Normal OTA/stable promotion и long soak OPEN; [runtime evidence](../audits/2026-10-05/APK-LOG-RETENTION.md).
Предыдущее описание шести файлов выше — датированный defect старого APK.

Адресная очистка51 owned images дала +10,938GiB в guest, без compaction VHD.
Daemon configured GC enabled/20GB не является quota всех Docker objects;
default builder shared с другими проектами. Для следующих builds сохранять
current/rollback и все running/stopped dependencies; cleanup списка по точным IDs
и checked ownership. Volumes, dangling unknown images и общий cache не удалять
по одному имени `sphere-*`. Persistent-data backups и physical reclaim остаются
отдельным maintenance gate.

Read-only image plan теперь воспроизводится
[`plan_owned_image_retention.py`](../../scripts/pilot/plan_owned_image_retention.py),
source `c89594a`;14 tests и actual0 additional candidates после cleanup.
Только четыре explicitly owned repositories, all-tags Git proof, current source,
два rollback versions, все running/stopped dependencies; repeat epoch guard.
Нет native remove/prune/restart, ни recurring task.

Сопоставление exact VSS22:52 UTC: C: free−2,033GiB /allocation+1,969GiB;
перезаписи большого VHD могут сохранять старые блоки в VSS. Две persistent copies,
max19,057GiB. [Измерения и вариант C:→C:8GiB](../audits/2026-10-05/VSS-RETENTION-REVIEW.md).
Снижение quota может удалить restore history и требует прямого согласия;
не заменять это action отключением VSS, общим delete или live VHD compaction.
На данном ПК оператор одобрил вариант;22:58 UTC quota8GiB применена,
обе прежние copies удалены Windows, наблюдаемый free gain17,205GiB.
Native exit0/max readback и postchange API/fleet сохранены в linked evidence.

После перезапуска приложения прежние disk/RAM processes отсутствовали,
последние сохранённые срезы19:35 UTC. Восьмичасовая приёмка прервана, а не
успешно завершена. Отдельные30-минутные продолжения запущены19:41:48/19:45:11 UTC;
первые полные срезы подтверждены. Оба продолжения завершены:31 disk /16 RAM
samples; последнее RAM20:15:11 UTC. Разрыв не входит в continuous uptime/soak.
