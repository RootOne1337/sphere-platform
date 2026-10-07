# Ресурсы хоста: диск, Windows commit, WSL и контейнеры

**Актуальное дополнение 7 октября, 23:34 UTC+5:** прежние elevated host/ETW,
NTFS и VMDK processes отсутствуют; последние complete samples около14:03UTC,
их старое `running` не является текущим статусом. Причина остановки неизвестна.
Восстановлен limited PID29648, пять Docker/LDPlayer files плюс RAM/process/WSL
metadata,236×120s до8 октября07:13:38UTC+5,16MiB. VSS/USN/ETW в новом окне
не восстановлены: терминал не administrator. Данные реально читаются из JSONL.
[Разрыв, ограничения и порядок проверки](../audits/2026-10-07/STORAGE-COLLECTOR-INTERRUPTION.md).
Абзацы ниже — исторические срезы; они не подтверждают живые collectors сейчас.

**7 октября, текущий срез после16:40 UTC+5:** elevated kernel/VSS capture
подтвердил отдельный free-drop235 745 280B с allocation VSS+234 881 024B /99,63%.
Ранее одобренный лимит8GiB после drift19,06GiB возвращён; на C: освободилось
16,304GiB, обе проверенные restore copies удалены. Приблизительно20GiB перед
этим освободил оператор удалением постороннего файла; это не наша очистка.
Docker guest cleanup завершён в два этапа:39 owned images /11,890GiB внутри
guest; host VHD не уменьшился, все46 epochs/rollback сохранены.
[Новые измерения, screenshots и ограничения](../audits/2026-10-07/HOST-STORAGE-VSS-CURRENT.md).

Вместо limited observer реально работает elevated `host_storage_watch`:
16:27→00:27 следующего дня UTC+5,241×120s,16MiB budget; VSS уже measured.
Дополнительно [event-triggered supervisor](../../scripts/pilot/disk_writer_watch.py)
начат16:38:18, общий deadline00:27:02. Он читает последние complete samples,
запускает не более4 named memory WPR captures при free-drop/VSS-growth128MiB,
смене membership или max. Это post-trigger, не восстановление прошлых writes.
Metadata1MiB; после учёта512MiB сохранённых ETL больше нет запусков; это не
hard file cap при последнем save. Unknown capture останавливает supervisor;
чужие trace sessions не отменяются, VSS policy автоматически не меняется.
Всю систему покрывает kernel trace, а не только процессы Docker/Sphere.
Finite RAM soak, quota actor и атрибуция всей исторической потери открыты.

Приватные отчёты работающего наблюдения (не запускать второй экземпляр):

| Сборщик | Private directory | Предел / назначение |
| --- | --- | --- |
| Elevated disk/RAM/VSS/Docker/WSL | `.local-pilot/host-storage-elevated-20261007T1127` | 241×120s, до19:27:02UTC,16MiB |
| Event-triggered FileIO/DiskIO | `.local-pilot/disk-writer-watch-20261007T1142` | Общий deadline host observer, max4 attempts |
| LDPlayer six VMDKs | `.local-pilot/ldplayer-files-20261007T1141` | 97×300s,11:40:26→19:40:26UTC,8MiB |
| Whole C: USN changed-file sizes, replacement | `.local-pilot/ntfs-growth-20261007T1310` | 206×120s,13:03:12→19:53:12UTC,16MiB |
| Previous USN reader, stopped | `.local-pilot/ntfs-growth-20261007T1157` | Last sample12:16:52UTC; stopped12:18:52UTC on changed-ID budget |
| Completed initial kernel capture | `.local-pilot/disk-writer-20261007T112141-3acccbff585d4ae2a2683b3276b4ff4a` | Четыре volume samples /28,304MB ETL |

При следующем разборе читать `status.json`, complete snapshots и только затем
соответствующий named ETL. PID сам по себе не является identity: в этом запуске
Windows переиспользовала PID старого завершённого WPR collector для нового
observer. Перед остановкой своего helper нужны command line **и** creation epoch.
При перезапуске Windows сбор не продолжится сам; данные до него сохраняются.

Для нового отдельного наблюдения из elevated PowerShell, после проверки что
существующее окно завершилось, использовать НОВЫЕ direct `.local-pilot` paths:

```powershell
python -m scripts.pilot.disk_writer_watch --input-dir .local-pilot\host-storage-NEW --output-dir .local-pilot\disk-writer-watch-NEW --hours 8 --max-captures 4 --drop-mib 128
```

Input должен быть running elevated observer текущего source hash. Stale/future,
oversized/duplicate JSON и invalid counters отклоняются без новых captures.
Сборщики не пишут автозапуск, не чистят данные и не отправляют команды Android.
Suite109 passed /34 subtests; Ruff и mypy проверены для трёх production utilities.

USN reader читает существующий журнал C:, не создаёт/не меняет его;8MiB journal
read/10s в цикл,256 resolved IDs/4096 cache/256KiB sample/16MiB reports. Overflow
resolution отмечается partial с count. При byte/time backlog следующий цикл
продолжает с фактически прочитанного cursor; endpoint не подставляется вместо
него. Всплеск более4096 identities сохраняет последние bounded observations;
eviction count не является количеством уникальных файлов и не выдаётся за полное
покрытие. Wrap/unsupported/nonadvancing journal прекращают сбор с явной ошибкой.
First file sightings baseline, PID нет в USN;
сопоставлять same-identity allocation deltas с ETW, не считать bytes written
байтами роста. [Reader](../../scripts/pilot/ntfs_growth_watch.py).

**7 октября,18:03 UTC+5 — исправление reader burst:** старый reader остановился
на обычном превышении4096 changed IDs. Последний sample12:16:52UTC, restart
13:03:12UTC: этот промежуток не объявлен покрытым NTFS-наблюдением. Остальные
host/VSS, ETW supervisor и VMDK observers продолжали работать. Replacement уже
записал baseline; metadata source SHA-256 находится в status.json, autostart
не включён, первоначальный deadline не продлён.14 pure tests, Ruff и mypy прошли.

**Исторический первый срез7 октября, Docker retention:** подтверждён основной расход в образах/слоях,
а не в сохранённых кадрах: containerd 185 725 952 KiB, Android logs 139 652 KiB,
MinIO 104 KiB. Удалены 34 старых owned images, внутри guest освобождено
2,442 GiB; все 46 container epochs и обе rollback версии сохранены. Это не
возврат места на C: и не устранение продолжающегося расхода. Исправлен read-only
planner: exact whitelist тестовых образов, общий пул последних двух тестовых
сборок; runtime rollback сохраняется отдельно для каждого repository.
18 focused tests/Ruff/mypy прошли. Cache exact-ID cleanup вернул 0 B.
[Подробный разбор и границы](../audits/2026-10-07/DOCKER-STORAGE-RETENTION.md).

**Позднейший срез 7 октября, 16:02 UTC+5:** исходный 8h observer завершён,
97/97 samples. C: free **36 431 638 528 → 27 286 896 640 B**,
потеря **8,517 GiB**; Docker VHDX logical/allocated постоянны во всех срезах.
[Полный разбор](../audits/2026-10-07/HOST-STORAGE-FOLLOWUP.md) ·
[Конечные evidence/hashes](../audits/2026-10-07/HOST-STORAGE-FOLLOWUP-EVIDENCE.json).
На момент этого среза limited RAM/commit observer был запланирован до23:56 UTC+5.
Этот observer затем остановлен после18 samples и заменён elevated окном,
описанным выше; новое состояние не выдаётся за завершённый RAM soak.

**7 октября, 15:56 UTC+5 — повторный расход диска подтверждён, причина открыта.**
Ремонт при загрузке уже выполнен; утверждение о preboot блокировке ниже —
исторический срез 6 октября, а не текущий статус.
В окне 08:02–15:52 накоплено 95 named-file samples: C: free уменьшился
на 9 097 113 600 B, при неизменных logical/allocated Docker VHDX во всех срезах.
Pagefile logical size неизменен, allocation недоступен и identity `[0,0]`
не доказывает непрерывную идентичность файла. Это не установление writer.
Текущая версия UI/API остаётся a41c4e6; backend/DB/APK не обновлялись этим этапом.

Добавлен read-only [разбор конечных samples](../../scripts/pilot/disk_growth_report.py):
лимиты 97 samples / 1 MiB на файл / 8 MiB суммарно; output не содержит исходных
путей. Он различает нулевой endpoint delta и постоянство во всех срезах,
пропуски, смену identity и отсутствие allocation; `writerAttribution` остаётся
`UNDETERMINED`. Полный 8h исходный sampler ещё заканчивается в 16:02 UTC+5.

[Host collector](../../scripts/pilot/host_storage_watch.py) теперь допускает
явный `--allow-unprivileged`: Windows RAM/commit/pools/process epochs,
Docker и WSL собираются с имеющимися правами. По умолчанию требование elevated
сохранено. Ограниченный режим не повышает права; VSS при отказе остаётся
`unavailable`, пустой список не означает нулевой размер. Process IO содержит
сетевые операции и не считается файловой атрибуцией.

Исторический limited observer начат15:56:50, остановлен16:31:31 UTC+5:
241 samples / 120 s, Docker каждые 16 min, report cap 16 MiB,
sample cap 128 KiB, без contents/root scans/cleanup/restarts/autostart.
Первый snapshot содержит реальные RAM/commit/pools/Docker/WSL counters;
VSS недоступен, administrator=false. Конечный RAM soak ещё не принят.

```powershell
python -m scripts.pilot.disk_growth_report --input-dir .local-pilot\storage-followup-20261007T0303
# Для НОВОГО конечного наблюдения; существующий collector повторно не запускать:
python -m scripts.pilot.host_storage_watch --allow-unprivileged --output-dir .local-pilot\host-storage-unique-name --samples 241 --interval 120 --docker-every 8 --max-report-mib 16 --watch-file C:\pagefile.sys
```

Проверки: **67 passed / 16 subtests**, targeted `pytest --noconftest` для четырёх
diagnostic modules; Ruff и mypy двух production utilities passed. Это проверки
сборщика/reader, не всего backend или исправности SSD. Для VSS/kernel FileIO
остаётся отдельный elevated [конечный ETW collector](../../scripts/pilot/collect_disk_writer.ps1).
На момент этого исторического среза запуск ещё не был подтверждён; последующее
реальное elevated recording и его counters приведены в начале документа.

**6 октября, 20:23 UTC+5 — допуск сборок закрыт из-за NTFS:** том workspace C:
имеет `Warning / Full Repair Needed`; elevated Scan завершён с
`ScanErrorsFoundNeedSpotFix`. Подтверждён запрос `chkdsk C: /f` на следующую
загрузку, **ремонт и перезагрузка ещё не выполнены**. Ресурсный guard теперь
отказывает при нездоровом или неизвестном Windows volume health, даже если
свободных GiB достаточно. Это не универсальная блокировка сторонних IDE.
[Инцидент и процедура](../audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

**5 октября, 19:55 UTC+5 — EP-009 принят на живом 3015:** API/UI **`cb5b3f91`**,
gateway config **`993d9eac`** сохранён. Реальная история CPU в использованных ядрах
и памяти в GiB cgroup контейнера: окна 1/6/24 h, сбор/обновление 15 с, среднее CPU за 1 минуту.
Лимит памяти 2 GiB подтверждён; CPU quota не подменяется нулём. Host/RSS сюда не
смешиваются. 1275 frontend tests/120 suites, production Node24 build/types и 27
tests в exact API image, mypy 231/Ruff, promtool и живые queries прошли. Браузер
1600/390 px, обе темы и автоматическое обновление проверены. При замене каждого
API/UI сохранены 45 соседей; Prometheus reload без replacement всех 46.
Сохранена временная потеря 14→12→13 online; последующее конечное окно 6×3с:
14 online /5 offline из19. Это не непрерывный SLA или устранение утечки.
**9 закрыто / 41 открыто из 50**; следующий EP-010, host leak attribution, Studio
и stream+script load/soak открыты.
[Ресурсная история и границы](../audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md).

**Проверено:** 4 октября 2026. Источник правил сборки: `c1a6e79`.

**Дополнение5 октября, итог12:58 UTC+5:** finite8h recorder `02b5084` завершился
241/241 срезами. C:−2,154GiB; Docker VHD allocated/pagefile logical стабильны,
exact VSS allocated0. Physical RAM/Windows commit измерены отдельно; writer
UNDETERMINED, утечка не объявляется исправленной. [Конечный отчёт](../audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md).

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
| Windows volume workspace | `Healthy`, только `OK` | `Full Repair Needed`, другие состояния или недоступность health API блокируют сборку |
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

### Лёгкое конечное ночное наблюдение, 5 октября

[`host_storage_watch.py`](../../scripts/pilot/host_storage_watch.py) source `02b5084`
добавляет8h/241samples/120s exact C:/VSS/allocated named-file/RAM/commit/pools.
Docker guest/stats/container epochs измеряются каждые16min и в последнем sample.
Report budget16MiB, sample128KiB; нет directory walks, automatic cleanup или
autostart. Требуется отдельный elevated Windows process; запуск с обычным token
отказывает до создания output. Watched paths должны быть absolute и distinct.

```powershell
# Из корня workspace, в elevated shell; новый direct child .local-pilot обязателен.
& '.venv-audit\Scripts\python.exe' -X utf8 -m scripts.pilot.host_storage_watch --output-dir '.local-pilot\host-storage-night-unique' --watch-file 'C:\Users\dimas\AppData\Local\Docker\wsl\disk\docker_data.vhdx'
```

На этом ПК процесс уже запущен04:58 UTC+5, due примерно12:58. Не создавать дубликат
до завершения/проверенного отказа. Точный каталог, SHA/acceptance и результаты
дополнительного cache cleanup сохранены в
[ночном отчёте](../audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md).
`unavailable` не считать нулём, отсутствие Docker cycle — не stale success;
RAM deltas сопоставлять только при той же известной boot epoch. После reboot
или missing PID `running` в последнем status не означает живой recorder.

Завершение наблюдения само по себе не разрешает compaction/delete/restart.
При новом необъяснённом free-drop короткая ETW ниже даёт file/PID evidence;
process IO rates ночного recorder включают network/non-file и не заменяют её.

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
