# Ошибки файловой системы рабочего ПК

Последнее дополнение: **6 октября 2026, 15:23 UTC**; исходные проверки ниже датированы отдельно. Это отдельный инцидент Windows C:,
не заключение о причине расхода памяти, роста Docker VHD или сбоях Android.

## Подтверждено

При чтении старого, исключённого из Git контекста сборки Windows вернула ошибку
1392 «файл или папка повреждены». Read-only запрос журнала System с фильтром
`ProviderName=Ntfs, Id=55` подтвердил два события:

| Время UTC | Record ID | Подтверждённое сообщение |
| --- | --- | --- |
| 4 октября, 16:36:14.357 | 219586 | Повреждение структуры C:, природа неизвестна; Windows указывает на необходимость автономной проверки |
| 5 октября, 23:25:59.393 | 220528 | Повреждён индекс `$I30:$INDEX_ALLOCATION` старой временной папки тестов |

Вторая папка относительно репозитория:
`.local-pilot/script-studio-20261006/layout/context/frontend/__tests__/devices`.
File reference: `0x140000004e0a6e`. Это не текущие исходники `frontend/__tests__/devices`.
[Сокращённый receipt](evidence/host-filesystem/events.json) исключает имя пользователя
и несвязанные события других providers. Точное исходное сообщение получено из
System, а не выведено из размера папки.

Два loose Git tree объекта ранее были восстановлены с проверкой исходных SHA-1;
подробности сохранены в [отчёте Studio](STUDIO-REDESIGN.md). Последующий
`git fsck --no-dangling` **6 октября, 07:15 UTC** завершился exit 0.
Это проверка доступных Git объектов, а не всего диска или аппаратного состояния SSD.

## Что сделано и что не установлено

- Старый повреждённый контекст не используется для новых сборок; исключён его
  повторный рекурсивный обход. Новые контексты извлекаются из проверенного Git commit.
- Не выполнялись `chkdsk /f`, `chkdsk /r`, удаление повреждённого дерева,
  перезагрузка, изменение VSS или остановка Docker ради проверки.
- `fsutil dirty query C:` ранее отказал с Windows error 5. Флаг dirty остаётся
  неизвестным; отказ нельзя трактовать как «том исправен».
- NTFS events не доказывают физическую неисправность накопителя и не устанавливают
  writer, заполняющий диск. [Storage audit](../2026-10-05/HOST-DISK-GROWTH.md) остаётся отдельным.
- Новые тесты и сборки ограничиваются ресурсными воротами. Успешная сборка не
  закрывает файловый инцидент и не заменяет системную проверку в отдельном окне.

## Повреждённый generated class в Android-сборке

Отдельное наблюдение **6 октября, 12:30:32 UTC**, source `6a9f570f` / APK 1.2.46.
Первый полный EnterpriseDebug test run получил 19 `ClassFormatError` в
`WebSocketAuthenticationTest`: Java прочитала magic 4294967295 (`ffffffff`).
Это не assertion failures нового input adapter. Проверка четырёх соответствующих
файлов, а не предположение об ошибке кода, показала:

| Результат | Bytes | Magic | SHA256 |
| --- | --- | --- | --- |
| Raw Kotlin output Dev и Enterprise, transformed Dev | 1753 каждый | `cafebabe` | `bbc2ba76e9fafc358ce811c78a5c694cf4f3a47df7a3d8e31dbdeb6d02196840` |
| Единственный transformed Enterprise output | 1753 | `ffffffff` | `3d212e4aa7b626516a5554ca3ae6805da897d54578258a99e5a95456cddc1670` |

Повреждённый файл относительно проекта:
`android/app/build/intermediates/classes/enterpriseDebugUnitTest/transformEnterpriseDebugUnitTestClassesWithAsm/dirs/com/sphereplatform/agent/ws/WebSocketAuthenticationTest$http$1$1.class`.
Исходники не менялись. Перед удалением проверены resolved absolute path внутри
этого generated root и точный bad SHA256; исходные байты и failed build log
сохранены privately. Удалён **только один 1753-byte восстанавливаемый файл**, без
рекурсивного удаления дерева. Gradle повторил transform из корректного raw output.
Новый файл имеет `cafebabe` и исходный good SHA256; полный Enterprise suite затем
дал **855 passed / 1 assumption-skipped / 0 failed**. Dev suite имеет тот же итог.

[Сокращённый before/after receipt](evidence/android-focused-text-clear/generated-class-corruption.json)
сохраняет наблюдение повреждения и пересоздания; raw binary/log не публикуются.
[APK delivery](ANDROID-FOCUSED-TEXT-CLEAR.md) отдельно проверяет ZIP/DEX и signer.
Один повреждённый generated output **не устанавливает** причину: NTFS, storage
driver, RAM, внешнее изменение файла и compiler/toolchain требуют независимых
проверок. Наличие ранее записанных Ntfs55 не доказывает причинную связь.
Пересоздание файла не закрывает host incident и не устанавливает writer,
заполняющий C:. Offline filesystem repair или перезагрузка не выполнялись.

## Повторное повреждение loose Git объектов — 6 октября, 14:26–14:28 UTC

Перед публикацией нового APK/evidence исторический validator обнаружил нечитаемый
Git object; `git fsck` подтвердил **пять** повреждённых loose objects. Первые байты
каждого — `ff`, три небольших файла целиком заполнены `ff`. Это наблюдение raw
файлов, не предположение по сообщению валидатора.

| Object SHA-1 | Type | Bad compressed bytes | Отношение к проекту |
| --- | --- | --- | --- |
| `22d9c8f825cad200bf6e796b1f847f2343fceb4a` | tree | 792 | Git tree |
| `4ccd02c08142fd1373056698a6c98d8279270f90` | blob | 7901 | `DeviceWorkbench.tsx`, Git object; текущий working file не заменялся |
| `527809ac5e77e54df79aa751312d0e590e30a998` | tree | 1014 | Git tree |
| `619c2d887f32b856fc319d3b1becba47dbf30d20` | blob | 101070 | Исторический native JPEG `catalog-delivery.jpg` |
| `c8e679239c663bc36e885502ffe8d25238566e28` | blob | 110403 | Исторический native JPEG `editor-delivery.jpg` |

Повреждённые bytes и exact bad SHA256 сохранены privately. Из GitHub получены
соответствующие blobs/trees, восстановлен canonical Git object payload; **SHA-1
сверен до и после записи**. Перед atomic replacement проверены принадлежность
пяти resolved paths `.git/objects` и неизменность bad hash. Восстановлены только
эти объекты; reset исходников, удаление старых contexts или системный ремонт не
выполнялись. `git fsck --no-dangling` после восстановления дал exit 0, validator
immutable command-recording evidence снова прошёл.

[Receipt пяти объектов, before/after hashes и read-only System срез](evidence/host-filesystem/git-object-recurrence.json).
Raw corrupt binary и API credentials в Git не публикуются.

Отдельное новое **Ntfs55 / record 220639**, **6 октября 11:15:49.334 UTC**, file
reference `0x6800000002a628`, указывает на индекс `$I30:$INDEX_ALLOCATION` **вне
проекта**: `Program Files/WindowsApps/Deleted/OpenAI.Codex_26.930.7945.0/.../app/locales`.
Read-only physical disk API сообщает `ADATA LEGEND 970 PRO / Healthy / OK`;
этот общий статус не является проверкой NTFS, SSD electronics или RAM.
Причинная связь нового System события с повреждёнными Git объектами **не доказана**.
Возможные storage/driver/RAM/external-writer причины требуют независимого
расследования. Исправление пяти копий данных не закрывает повторяющийся инцидент.
Writer, заполняющий C:, по-прежнему UNKNOWN; bounded Android screenshot cache
не объявляется причиной расхода Windows/Docker.

## Дальнейшая проверка

Перед автономным ремонтом нужен проверенный backup важных пользовательских данных
и проекта, согласованное окно остановки рабочих контейнеров и эмуляторов и
системная проверка Windows. Перезагрузка требует согласованного окна. После ремонта необходимы повторные
System events, проверка Git и hashes выпускаемых артефактов; отсутствие нового
события в коротком интервале само по себе не является приёмкой.

## Ремонт подготовлен: 6 октября, 15:06–15:23 UTC

Оператор запросил ремонт («фикси») и сообщил, что отдельного физического диска
для backup нет. Работа ниже не закрывает аппаратную причину, расход Docker VHD
или весь host leak audit. Веб/API/APK в этом продолжении не обновлялись.
[Сокращённое evidence](evidence/host-filesystem/repair-readiness.json).

### Что сохранено

Private recovery copy на том же C: проверена по SHA256 всех **11 файлов /
16 450 263 байт**; `source-HEAD.zip` прошёл ZIP CRC, опубликованный source HEAD
`d424e52cebacefed3d928be106d33e73293bbec3` совпал с remote. `git fsck
--no-dangling` завершился exit0. В копии есть исходники HEAD, patches, настройки
pilot, текущий Prometheus working file, Git config, debug signing key,
consistent custom PostgreSQL dump и roles, container configuration inventory.
Directory custom dump прочитан через `pg_restore -l`; полный restore не выполнен.
Пустые patches не доказывают сохранение всех untracked файлов.

**Это не независимый backup:** личные файлы, весь SSD, MinIO objects, Redis volume,
прочие application volumes, все untracked development files и все signing keys
в него не входят. Копия на C: не защищает от отказа самого SSD. Credentials,
database contents, raw logs и corrupted binaries не публикуются в Git.

### Проверка Windows и факты о повторении

| Наблюдение | Подтверждение | Ограничение |
| --- | --- | --- |
| C: NTFS, `Warning / Full Repair Needed` | `Get-Volume`, до и после Scan | Общий physical disk `Healthy` не отменяет NTFS failure |
| Dirty bit установлен | Elevated `fsutil dirty query C:`, exit0 | Это состояние тома, не диагноз SSD/RAM |
| Scan 15:08:50–15:16:24 UTC | `Repair-Volume -DriveLetter C -Scan`: `ScanErrorsFoundNeedSpotFix` | Очередь offline defects, не ремонт C: |
| Application Chkdsk event26226 /134448 | 15:16:23.712 UTC, длительность450586ms | Event содержит также проверку/моделирование на snapshot, её «исправление» не выдаётся за исправление рабочего тома |
| Две повреждённые директории | Индексы `$I30` текущего старого build context и deleted WindowsApps package | Не новые assertions или изменения исходников |
| Missing index entries | 15 в старом build context, 6 в WindowsApps directory | Содержимое файлов и аппаратная причина отдельно не проверены |
| Более ранний boot repair | Wininit1001 /133794, 4 октября16:38:26.004 UTC: 3 records в Epic Games cache corrected | Последующие Ntfs55 доказывают новые наблюдения после ремонта; его успешность не исключила повторения |

Это не новый запуск `chkdsk /r`, `/b`, `/perf`, `/x` или повторный full scan.
Согласно [Microsoft Repair-Volume](https://learn.microsoft.com/en-us/powershell/module/storage/repair-volume),
Scan сообщает дефекты и ставит их в `$corrupt` для offline repair. После Scan
рабочий том остался `Full Repair Needed`. Успех Git fsck не закрывает это состояние.

NVMe **ADATA LEGEND 970 PRO** возвращает generic Healthy/OK, temperature54°C,
Wear0. PowerOnHours и четыре error counters **null / недоступны**, а не0.
Проверенный SMBIOS RAM inventory: 2×24GiB, Speed4800 /ConfiguredClockSpeed6800.
Это основание отдельно проверить профиль/стабильность памяти, **не доказательство**
виновности RAM, SSD, драйвера, Ultra mode или агента. BIOS settings не менялись.

### Расход RAM во время Scan

COM surrogate PID300 создан15:08:51.175UTC; elevated registration AppID
`{82D94FB3-7FE6-4797-BB72-9A886C66073B}` = `CFmIfsEngine host`.
В измеренном срезе его private bytes **12 267 302 912**, working set
**12 221 792 256**. Одновременный host commit приближался к limit; после завершения
Scan этот PID исчез, available RAM выросла примерно до20GiB. Срез15:22:
available19 296MiB, committed78 272 397 312 /limit95 153 381 376bytes.
Это привязанный к проверке процесс/epoch, а не долгосрочный leak proof APK/backend.
Рабочие Docker/эмуляторы не убивались для получения этого результата.

### Что уже запланировано

[`prepare_host_boot_repair.ps1`](../../../scripts/pilot/prepare_host_boot_repair.ps1)
проверил hashes recovery copy и завершённый elevated Scan. Только с явным флагом
`-ScheduleAtNextBoot` в elevated процессе вызвана точная команда **`chkdsk C: /f`**.
Windows отказала в lock работающего system volume, приняла `Y` для next boot;
native exit3 означает, что online repair не выполнен. Прочитанный **BootExecute**
содержит новый `autocheck autochk /p \??\C:`, исходный `autocheck autochk *`
сохранён. Поэтому очередь подтверждается отдельно от native exit и языка stdout.
Raw native stdout сохранён privately с default process decoding; текст не служит
единственным доказательством scheduling. Registry напрямую не переписывался.

**Состояние: repair-pending-restart.** Скрипт не выключает/не перезагружает ПК,
не останавливает службы/контейнеры, не принудительно dismount C:, не удаляет VSS,
не запускает surface scan. [Microsoft chkdsk](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/chkdsk)
описывает `/f` и scheduling system volume. При следующей загрузке проверку не
пропускать. Окно graceful shutdown контейнеров, эмуляторов и личных приложений
нужно согласовать с оператором; автоматического reboot без этого окна нет.

### Guard, ограничение сборок и проверки

[`resource_guard.py`](../../../scripts/pilot/resource_guard.py) теперь требует
доступные Windows volume `Healthy` и operational statuses ровно `["OK"]`.
Отсутствие API, пустые/неверные поля и contradictory Warning/OK блокируют
сборку. Volume определяется через путь workspace в environment variable, без
интерполяции произвольного пути в PowerShell command. Linux правила не менялись.
Guard блокирует только процедуры, которые действительно его вызывают.

**37 tests passed**, `pytest --noconftest` для двух CLI suites; Ruff и PowerShell
AST parse прошли. Реальные tests подтверждают readonly readiness, hash/size
failures, path escape и junction rejection. Tests никогда не schedule repair.
Первый readiness test нашёл отсутствие Get-FileHash в child PowerShell environment;
hash verification переведён на .NET SHA256, повторный test положительного пути
успешен. Полные frontend/Android builds на повреждённом C: не выполнялись.

[`collect_host_repair.ps1`](../../../scripts/pilot/collect_host_repair.ps1) хранит
ограниченный private report: максимум256KiB, bounded native reads15s. Scan
специально не прерывается по query deadline. Отдельный exact VSS WMI query в
первом secondary snapshot не завершил report; финальный readback изолирует его
в owned child с deadline и честно сохраняет unavailable вместо нуля. Native
VSS query успешен; exact counters этого продолжения не получены.

### VSS — актуальное расхождение, не новый cleanup

До Scan native readback: used18,2 /allocated18,5 /max19,1ГБ; после:
used16,8 /allocated17,2 /max19,1ГБ. Это округлённые display values, не exact deltas.
Они **расходятся** с verified8GiB after resize4 октября22:58UTC в
[VSS retention](../2026-10-05/VSS-RETENTION-REVIEW.md). Изменение лимита/причина
не установлены; исторический receipt не переписывается. До ремонта рабочего C:
копии повторно не удаляются. Размер Docker VHD и уменьшение свободного места
не объявляются исправленными этим filesystem этапом.

### Приёмка после перезагрузки

1. Прочитать **новый** Wininit/Chkdsk report, boot epoch, dirty bit и `Get-Volume`.
   Для продолжения сборок требуется `Healthy / OK`, completed repair, отсутствие
   reported unresolved defects. Queue сама по себе не является приёмкой.
2. Повторить `git fsck --no-dangling`, hashes source/artifacts и проверку исходного
   backup. Не удалять bad raw evidence и не делать blind Git gc/prune.
3. Штатно восстановить прежние runtime containers/UI/API/tunnel и подтвердить
   image/identity, readiness и heartbeat; отсутствие рабочего stream не подменять
   фактом доступности `/metrics`. APK автоматически не переустанавливать.
4. Проверить свежие Ntfs/disk/WHEA events. При повторении — оставить NO-GO,
   независимая проверка SSD/driver/RAM; успешная одна загрузка не аппаратный SLA.
5. Повторно получить VSS retention, bounded disk/RAM recorder, pool/epoch и writer
   measurements. Не склеивать прерванные окна в continuous soak.

### Дополнительный source-файл Python вне репозитория

**6 октября, 22:50:12 UTC+5:** scoped mypy остановился на global Python313,
`Lib/site-packages/sqlalchemy/orm/sync.py`, SQLAlchemy2.0.32. Read-only проверка
прочитала5779bytes: UTF-8 invalid byte `FF` на offset4096, следующие прочитанные
bytes также `FF`. SHA256 не совпал с записью этого файла в установленном RECORD:

- Expected base64url: `g7iZfSge1HgxMk9SKRgUgtHEbpbZ1kP_CBqOIdTOXqc`.
- Observed base64url: `gfbbFlHuGNvUQSvzJRBAXy8hHs6XvCE3T8O4LwbF4_Y`.

Private receipt: `.local-pilot/studio-followup-20261006/python-library-corruption.json`.
Файл не изменялся и пакет не переустанавливался. Это обнаружение повреждённого
файла за пределами проекта, а не установленная причина/момент его повреждения,
диагноз SSD/RAM или доказательство причастности subagents. C: сохраняет Warning /
Full Repair Needed; состояние свободного места отдельно:41 493 204 992bytes.
`git fsck --no-dangling` прошёл; Windows boot repair не выполнен.

Существующая pinned `.local-pilot/openapi-venv` с FastAPI0.136.3, Pydantic2.9.2,
SQLAlchemy2.0.28 выполнила140 scoped tests и API exporter без запуска lifespan.
Её mypy сообщает Requests import-untyped; полный CI в чистой среде остаётся gate.
Isolated mypy только нового pure parameter validator прошёл. Не выдавать эти
результаты за ремонт тома, проверку всех Python packages или полный backend CI.

## 7 октября: завершённый ремонт и возобновление

Новый boot00:42UTC+5, completed Wininit repair, Healthy/OK и повторный Git fsck
приняты. Source файлы не откатывались; queued repair gate снят.
UI-only installs99af20d и439f910 завершены с сохранением остальных45 контейнеров.
[Postboot handoff, Git recovery, runtime identities и ограничения](../2026-10-07/POSTBOOT-RECOVERY.md).
Причина повреждений, global Python package integrity и storage/RAM growth
остаются отдельными открытыми вопросами. Прежние Warning/NO-GO утверждения
выше относятся к preboot измерениям и не описывают новый том.
