# Docker storage и текущие записи на C: — измерения и адресная очистка

**Дата пользователя:** 5 октября 2026, Asia/Yekaterinburg (UTC+5).
**Измерения:** 4 октября 21:04–21:42 UTC; продолжение с 22:42 UTC отдельно. Source recorder `1402612`,
bounded CIM projection `9a9256f`; API/UI `c1a6e79`, APK10244 сохранены.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Процедура наблюдения](../../operations/HOST-RESOURCES.md) ·
[Предыдущее снижение free](HOST-DISK-GROWTH.md) ·
[R09 APK source fix](APK-LOG-RETENTION.md) ·
[Числа и hashes](DISK-WRITER-ATTRIBUTION-EVIDENCE.json).

## Что доказано по Docker

На присланном оператором screenshot218,6 GiB занимает `docker_data.vhdx`.
Проверка named file дала **234 731 077 632 байта**, без увеличения длины
в предыдущем69-минутном окне. Рост66,8GB в Microsoft PC Manager относится
к категории всех user files за21 день, а не исключительно к этому VHD.

Это shared data disk Docker Desktop, отдельный от рабочей папки Sphere.
До нового обслуживания guest filesystem сообщал **211 054 899 200 used bytes**,
то есть около196,56 GiB. Следовательно, крупный VHD содержит реальные данные,
а не только освобождённые раньше блоки.

| Docker category, до очистки | Reported size | Граница вывода |
|---|---:|---|
| Images | 237 /198,4GB | Общие layers пересекаются между images |
| Build cache | 795 records /88,34GB | Пересекается с image layers; не прибавляется к images |
| Volumes | 67 /6,993GB | Persistent data; не удалялись |
| Containers | 46, из них17 running | Все identities/image/start epochs сохранены |
| Sphere-tagged images | 119 distinct | Docker reported unique layers около64,50GB |
| Sphere без container references | 108 | Unique layers около63,08GB; это не автоматическое разрешение удаления |

Размеры Docker здесь округлены в decimal GB. Общие/уникальные/восстанавливаемые
байты и physical free — разные показатели. Tagged ownership не доказывает,
что весь shared disk принадлежит этому checkout или что любой старый image
можно удалить без проверки rollback/других приложений.

**Существенная часть расхода действительно связана с нашей разработкой:**
накапливались старые frontend/backend/test images. Папка исходников около8 GiB
сама по себе не описывает эти внешние layers. Source dependency-reuse fix
`c1a6e79` не является автоматической lifetime retention всех прошлых сборок.

## Адресная очистка и её реальный эффект

Подготовлен список51 image ID. Разрешены только три точно известные pilot/review
repositories и test repository, присутствующий в tracked evidence; все tag refs
проверены как существующие Git commits. Сохранены39 protected images, включая
все running/stopped container dependencies, две newest core версии и текущий
`c1a6e79`. Dangling images, mini-factory/другие проекты, volumes и общий cache
этой операцией не удалялись.

Перед каждым удалением повторно проверены46 container identities и epochs,
image ID и полный набор тегов. Нет `--force`, глобального `prune`, рестартов
или APK-команд.50 ID удалены напрямую.51-й с двумя тегами сначала дал native
conflict; этот отказ сохранён. После повторной проверки оба owned тега удалены
отдельной обычной командой, тоже без force.

После очистки:

- Images **237→186**, reported size198,4→182,6GB.
- Guest filesystem used **211 054 899 200→199 310 188 544 bytes**:
  освобождено **11 744 710 656 bytes /10,938 GiB** внутри Docker.
- Build cache всё ещё88,34GB; reclaimable изменилось8,138→25,39GB.
  Освободившиеся references не гарантируют немедленное удаление всех layers.
- VHD **234 731 077 632 bytes**, без физического сжатия.
- API ready, PostgreSQL/Redis ok;14 online, online APK version10244.

**10,938 GiB внутри Docker — не обещание такого же прироста C:.** На отдельном
коротком before/after cleanup срезе free C: уменьшилось на442,03 MiB.
Между последним завершённым tracer sample и следующим elevated sample allocated
VSS вырос **15 890 276 352→16 360 038 400 bytes /+448 MiB**. Это близкий по
времени и величине защищённый расход, который обычный file-size scan не видит.
Срезы не атомарны; корреляция не доказывает writer каждого нового VSS блока.
Restore points/VSS/pagefile не изменялись и не удалялись.

## Кто пишет сейчас: конкретная трасса

Установлен portable **Microsoft Process Monitor4.11**, signature Valid/Microsoft.
Постоянный driver/service/autostart этим этапом не настраивался; ProcMon capture
не запускался. Для основной записи использован встроенный Windows Performance
Recorder с собственной memory profile.
[Официальный Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon).

Builtin FileIO/DiskIO profile на этом хосте запрашивает около2,8 GiB buffers.
Вместо него проверен custom **128×1024 KiB /128 MiB** circular payload,
единственный SystemCollector, без file logging mode/per-CPU multiplier.
Native `wpr -profiledetails` принял профиль. Collector не прекращает чужую
recording session: start/status/stop/cancel адресуют только его unique instance.
[Memory/file logging](https://learn.microsoft.com/en-us/windows-hardware/test/wpt/logging-mode).

### Сохранённые попытки и загрязнение измерения

1.21:04:35: старт ETW успешен, но Windows PowerShell5.1 отверг `File.Replace`
с empty backup argument. Collector failed; собственная трасса18 695 261bytes
успешно сохранена в finally. Ошибка и stale starting status не скрыты.
Production Save-Status исправлен; filesystem regression проверяет три replacements.
2.21:07:33–21:08:17: успешная запись, drop trigger555 864 064bytes.
В это время **наш `tracerpt` экспортировал552 337 158bytes CSV**. Native TraceEvent
подтвердил записи именно `initial-trace.csv` через tracerpt и System/cache flush.
Это observer-induced расход; его нельзя выдавать за неизвестную утечку приложения.
3.21:15:33–21:25:47: finite600s запись,60 samples, duration_limit,
compressed ETL **39 255 867bytes**. Нет APK/Docker builds или крупных CSV exports.
Небольшая установка parser и metadata reports относятся к workload наблюдателя,
а остальные desktop приложения, включая PC Manager, продолжали работать.

Первый CSV удалён после SHA/size проверки только своего literal path;
ETL и compact analysis сохранены. Volume before/after дал+552 337 408free bytes;
это наш собственный reconstructable intermediate, а не очистка данных пользователя.
Новый разбор читает ETL непосредственно через **Microsoft TraceEvent3.2.8 (MIT)**,
без раздувания всех rundown events в CSV.
[Library, автор Microsoft](https://github.com/microsoft/perfview/releases/tag/v3.2.8).

Черновой CSV parser перепутал IoFlags/IoSize column; его numerical attribution
помечена INVALIDATED в частной квитанции и не используется в этом отчёте.
Проверенный разбор использует native typed parser, temporal filename resolution
и отдельные FileIO/DiskIO counters. Raw commands/личные пути остаются локально.

### Результат600s записи

Volume samples21:15:34.969–21:25:24.659UTC:

| Метрика | Изменение |
|---|---:|
| Free C: | 47 749 308 416→47 713 853 440bytes; **−35 454 976bytes /33,813 MiB** |
| VSS UsedSpace | **+117 325 824bytes /111,891 MiB** |
| VSS AllocatedSpace | Без изменения:15 890 276 352bytes |
| Available physical RAM | 16 436 326 400→16 173 449 216bytes; короткий срез, не heap soak |
| FileIO write events | 70 414 /320 300 099logical write bytes |
| DiskIO write events | 10 188 /270 414 336transfer bytes; не складываются с FileIO |
| ETW EventsLost | 0; это не гарантия полного прошлого circular buffer |

Retained FileIO write timestamps21:15:49.238–21:25:34.513UTC. Они не совпадают
строго с60 volume samples. Trace save/rundown пишет собственные временные ETL:
около142,6MB FileIO входит в общие320,3MB и отделено от workload.
Memory mode не означает zero disk writes при сохранении результата.

По разрешённым filename categories видны:

| Путь / класс | FileIO logical writes | DiskIO transfer | Вывод |
|---|---:|---:|---|
| Docker VHD | 3 043 328bytes | 3 010 560bytes | Записи есть; этот короткий срез не показывает hundreds-of-MB VHD growth |
| PC Manager database/journal | 30 279 192bytes | 13 090 816bytes | Сам storage analyser тоже пишет собственную базу |
| Yandex browser paths | 66 033 547bytes | 28 495 872bytes | Cache activity, не равна приросту всех файлов |
| Windows RDP AutoTrace | 15 204 352bytes | 15 204 352bytes | Реальный writer, долгий retention/rotation пока не проверен |
| VSS/System Volume Information | Не отдельный FileIO итог | 18 235 392bytes | Защищённые writes; allocation берётся отдельно из CIM |

Это path-matched scopes, а не полная ownership карта всех приложений.
Одно содержимое может попасть в logical write и в последующий cache flush.
Unknown paths/PID−1 не приписываются произвольному процессу. Bytes rewritten
не равны bytes appended/allocated; каждый такой writer не объявляется «утечкой».

## Проверки и следующий рубеж

**8 Windows regressions passed**: invalid windows/threshold, refusal без admin,
native128MiB profile acceptance, actual PS5.1 status replacement, bounded VSS
projection и отказ подменять missing counter нулём. Elevated live projection
с `9a9256f` получила exact counters в368bytes JSON; прежняя CIM graph сериализация
раздувала sample до примерно71KiB. Это исправление собственных diagnostic reports.

Дополнительное окно с пределом 1800s / шагом 30s завершилось раньше по
`free_drop_trigger`: 21:30:59–21:38:44 UTC, 16 samples, compressed ETL
42 889 463 bytes. Free между первым и последним sample снизилось на
159 420 416 bytes; VSS AllocatedSpace в этих samples не изменился.
Два тега последнего image удалялись 21:33:42, **внутри** этого follow-up;
он не маркируется полностью idle/no-cleanup или полным 1800s soak.
Этот процесс использовал launch-time `1402612`.

### Пойманный скачок браузерного обновления

В 21:38:25–21:38:29 UTC `browser.exe` скачивал и распаковывал Chromium CRX:
`delta_patch_out`, `Unpacker_BeginUnzipping`, `CRX_INSTALL` и
`filters/declarative/ruleset_*`. Typed parser до последнего volume sample
показал 231 548 829 logical write bytes в этом scope. Manifest **AdGuard
AdBlocker 5.5.2.64** изменён в 21:38:28.223 UTC, в том же интервале.
Повторная read-only проверка в 21:42:23: все 12 проверенных временных файлов
уже отсутствовали; мы их не удаляли и расширение не выключали.

Это конкретный writer и совпадающее событие для короткого скачка, а не доказанная
утечка Sphere или атрибуция всех исторических потерь. Общие FileIO writes до
sample cutoff — 429 511 985 bytes; DiskIO transfers — 172 638 208 bytes,
пересекаются и не складываются. EventsLost=0; retained trace начинается позже
первого volume sample. Stop/rundown после cutoff исключён из этого итога.
Logical writes CRX не равны net allocated growth расширения.

Продолжение с `9a9256f` запущено 22:42:19 UTC с пределом 600s / шагом 10s;
реальный status подтверждает administrator=true и traceStarted=true. Его
результат публикуется после завершения, а не принимается по факту запуска.

### Проверка действующих ограничений

Read-only daemon config содержит `builder.gc.enabled=true`,
`defaultKeepStorage=20GB`. Buildx driver — `docker`, BuildKit v0.27.1.
После очистки всё ещё 795 cache records / 88,34GB, из них 25,39GB reclaimable;
этот storage не прибавляется к images. Configured GC budget не является
глобальным quota всех images/volumes/VHD и не доказывает фактический sweep.
[Docker GC policies](https://docs.docker.com/build/cache/garbage-collection/) ·
[Shared cache semantics](https://docs.docker.com/reference/cli/docker/buildx/du/).

Короткий WSL memory срез: MemAvailable около 20 GiB при MemTotal около 23 GiB.
Это не подтверждение долгого RAM soak и не расход всего Windows.

`du -x -k -d 2` дополнительно проверил физические Linux directory blocks:
`desktop-containerd` 183 690 040KiB (около175,18GiB), `docker/containers`
314 048KiB (около306,69MiB), `docker/volumes` 7 286 644KiB (около6,95GiB),
BuildKit metadata directory 211 584KiB. Основной расход — image/snapshot store,
не сотни гигабайт container logs. Cache layers находятся в shared store;
маленький metadata directory не означает маленький build cache. Сумма всех
directory blocks не равна reported Docker logical sizes или Windows VHD length.

Для физического возврата C: подготовить отдельное VHD maintenance window:
проверенные backups persistent data, точный VHD path/identity, graceful stop
Docker, фактический detach, штатный compact, restart и сверка46 identities,
API/UI/Tuna/fleet. Сжатие нельзя выполнять на mounted/writable VHD.
[Microsoft compact vdisk](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk).

Дальнейшая prevention: ограничить retained core versions/owned test builders
в процессе разработки, отдельно принять BuildKit GC budget для shared builder,
контролировать actual image/cache usage до build. Общий prune и удаление volumes
не являются production retention policy. Нет обещания вернуть218,6 GiB целиком.

R04 long RAM soak, R05 offline VHD compaction, R06 backend RSS series,
R07 server global log quota/sweeper и R09 installed APK canary открыты.
Прошлые−6,459 GiB free и21-day+66,8GB не полностью атрибутированы этой трассой.
**Fleet32 NO-GO /34 source-fixed,7 unclosed web gates** остаются без изменения.
