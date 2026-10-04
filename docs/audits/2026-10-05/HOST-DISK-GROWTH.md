# Постепенное заполнение C: — измерения и открытая атрибуция

**Дата пользователя:** 5 октября 2026, Asia/Yekaterinburg. Все времена ниже — UTC;
к ним прибавляются пять часов. Основное окно диска: 4 октября 18:16:45–19:25:55 UTC
/ 23:16:45 4 октября–00:25:55 5 октября по местному времени.
**Исходники сборщика:** `6180faf`; установленный API/review UI — `c1a6e79`;
Android — существующий `1.2.44-dev / 10244`. Приложения этим этапом не обновлялись.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Процедура наблюдения](../../operations/HOST-RESOURCES.md) ·
[Предыдущая инвентаризация и очистка](../2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP.md) ·
[Числа, ограничения и hashes](HOST-DISK-GROWTH-EVIDENCE.json).

## Подтверждённый результат

На первоначальном 69-минутном окне свободное место на C: **продолжало уменьшаться**. В 15 срезах за 69 минут оно
снизилось с **44 431 917 056 до 42 207 911 936 байт**, то есть на
**2 224 005 120 байт / 2,071 GiB**. Это измерение тома, а не вывод по красной полосе
Проводника. Владелец этого снижения **не установлен**; утечка Sphere не доказана.

| Проверенная область | Фактическое изменение / объём | Что следует из измерения |
|---|---:|---|
| Workspace, полные срезы 18:16:45–19:16:50 | +2 461 539 байт / 2,347 MiB | Главным образом bounded RAM reports; не объясняет 2 GiB на томе |
| npm-cache, те же полные срезы | 0 байт | Не растёт в этом интервале |
| История чатов, те же срезы | +119 989 байт | Малый наблюдаемый рост, не причина гигабайтового снижения |
| Docker VHD, 15 named-file срезов | Длина и storage API size: 234 731 077 632 байта, без изменения | Нового увеличения этого VHD здесь не обнаружено; внутренние записи возможны |
| Измеренные диски LDPlayer | Длина/storage API без изменения | Это не утверждение обо всех эмуляторах и всех служебных файлах |
| APK PH010 / PH025, данные пакета | 11 456 / 12 272 KiB | Эти два пакета не накопили гигабайты |
| APK PH010 / PH025, `sphere_logs` | 10 616 / 11 432 KiB | Найдена отдельная ошибка retention, описана ниже |
| Backend device logs, рекурсивно в 19:27:46 | 14 файлов / 8 112 062 байта | Сохраняются журналы; этот объём не объясняет падение free на 2 GiB |

Срезы каталогов и free space не атомарны и имеют разные концовки времени.
Малое значение по доступному каталогу не исключает другой путь, transient файл,
рост sparse/compressed allocation или защищённых областей NTFS.

## Повторная проверка остального C:

Повторный read-only обход прошёл **5 029 835 файлов / 814 352 каталога** за
**162,656 секунды**, 19:27:17–19:30:00 UTC. Как в предыдущем обходе, пропущены
6142 reparse points и зарегистрированы 123 ошибки доступа. Содержимое файлов
не читалось; все личные пути и подробные списки остаются только локально.

По сравнению с обходом, окончившимся в 17:45:24, доступная логическая сумма
**уменьшилась на 5 043 181 260 байт**. Между обходами была штатная очистка npm/pip,
поэтому это не idle growth window. Крупнейший положительный доступный каталог
из сравниваемых областей — история чатов, **+15 618 832 байта**. Изменения рабочих
документов, Temp, логов Windows и LDPlayer имеют мегабайтный порядок.
Вложенные области не складываются и не считаются независимыми расходами.

Таким образом, доступный logical-file inventory **не объясняет продолжающееся
снижение физического free space**. Это граница измерения, а не доказательство,
что «диск не растёт». Нельзя исключить системные данные или allocation при
неизменной длине файлов, опираясь только на этот обход.

### Защищённый слой Windows

В 19:31:04 UTC выполнены штатные команды только чтения:

- `vssadmin list shadowstorage`: exit2, Windows требует elevated administrator.
- `fsutil volume diskfree C:`: exit1, Access denied.
- `fsutil usn queryjournal C:`: exit0; настроен maximum 32 MiB / allocation delta 8 MiB,
  write-range tracking disabled. Это параметры USN, не текущий размер всех NTFS metadata.
- CIM `Win32_ShadowStorage` / `Win32_ShadowCopy` завершились ошибкой инициализации;
  это unknown, не «теневых копий нет».

На этом первоначальном срезе размер теневого хранилища не был измерен. Последующие
успешные системные замеры описаны ниже. Shadow copies, USN, pagefile, hibernation
и restore points не удалялись и не перенастраивались. Наличие shadow storage само
по себе не доказывает причину снижения free space.

## Ограниченный сборщик продолжает работу

Коммиты `2a2c665` и `6180faf` добавляют metadata CLI и исправление Windows long paths.
Первый запуск обнаружил две ошибки обхода workspace; его два среза сохранены.
Повторная проверка исправленного scanner прошла 288 844 entries без ошибок.
Завершён только принадлежащий сборщику процесс после сверки PID/UTC start/module;
RAM sampler, Docker, приложения и Android продолжили работу.

Исправленный watcher запущен **18:15:55 UTC**; первый завершённый срез подтверждён
в 18:16:45. На проверке 19:27:46 процесс использовал **15 196 160 private bytes /
22 421 504 working-set bytes**. Это наблюдение одного момента, не heap soak.

| Ограничение | Конфигурация |
|---|---|
| Продолжительность | Плановое окно 8h, 97 samples / 300s; последний scan может окончиться позже |
| Named files | 100 путей, каждый срез; 97 доступны, storage API успешен для95 |
| Unknown | 3 отсутствующих пути; 2 sharing violations при allocation; не подменяются нулями |
| Directory roots | Workspace, Temp, session logs, npm-cache каждые900s |
| Budget обхода | 500 000 entries / 60s на root; не более2000 candidates ≥1 MiB/root |
| Quota отчётов | ≤1MiB/sample, ≤16MiB всех samples; временный JSON ещё≤1MiB, небольшой status отдельно |
| Остановка | Low disk<512MiB, quota/error или конец окна; нет service/autostart |
| Изменения | Только собственные отчёты; нет cleanup, рестартов, Android-команд от watcher |

Workspace, session logs и npm-cache дают complete scopes. Temp имеет одну
PermissionError и остаётся **PARTIAL**; его суммы не используются для вычитания
как доказательство роста. Вопрос о writer PID не решается размером файла:
после обнаружения пути потребуется конечная, отфильтрованная file-I/O трассировка.
[Microsoft Process Monitor](https://learn.microsoft.com/en-us/sysinternals/downloads/procmon).

Windows storage API здесь — `GetCompressedFileSizeW`; он учитывает sparse/compressed
size, но для обычных файлов возвращает длину. Cluster rounding и закрытые данные
тома этим числом не покрываются. [Контракт Microsoft](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getcompressedfilesizew).

## ОЗУ: раздельные факты

За **57 срезов / 17:32:56–19:24:56 UTC**, при одинаковой Windows boot epoch:

| Метрика | До | После | Ограничение |
|---|---:|---:|---|
| Доступная физическая RAM | 20 114 542 592 | 21 179 318 272 байта | Увеличилась примерно на 0,99 GiB |
| Windows commit | 51 696 529 408 | 55 944 769 536 байт | +3,957 GiB, не равен физической RAM и heap одного процесса |
| API container memory | 589,3 | 595,3 MiB |  +6 MiB, тот же container ID; округлённые Docker display values |
| Review UI container memory | 70,55 | 76,45 MiB | +5,9 MiB, тот же container ID |
| WSL AnonPages | 2 137 395 200 | 2 215 657 472 байт | +74,6 MiB; cache/buffers/swap записаны отдельно |

В неизменных PID+start epochs отдельные Telegram/ChatGPT/Docker host processes
выросли; нагрузка и новые processes не фиксированы как контролируемый эксперимент.
Это не основание объявить приложение виновником утечки. Container memory не равен
worker RSS; R04/R06 и browser/heap/GPU soak остаются открыты.

## APK: конкретная недоработка ротации

С помощью авторизованного APK shell RPC получены metadata двух пакетов и списки
файлов. На каждом есть **шесть `sphere_*.log` при `MAX_FILE_COUNT=5`**, плюс отдельный
bounded `ws_lifecycle.log`. Несколько обычных файлов слегка превышают 2 MiB.

В [FileLoggingTree](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt)
`rotate()` выбирает новый `File`, вызывает prune до первого append/создания файла,
а `writeEntry()` проверяет размер до добавления очередной записи. Это объясняет
наблюдаемые шестой файл и превышение порога на запись. **R09 — OPEN:** лимит
обычных файлов не соответствует контракту; нужна regression + source fix + canary,
но этот мегабайтный дефект не объявляется причиной гигабайтового роста C:.

`/data/local/tmp` локального устройства занимает 285 624 KiB, удалённого — 52 KiB.
В локальном каталоге присутствуют старые сторонние инструменты 2025 г.; собственные
Sphere startup/diagnostic files малы. Чужие инструменты не удалялись. Это точечный
срез, не полный аудит guest disk. Первый shell запрос с метасимволами был отклонён
guard; затем отправлены отдельные разрешённые metadata commands, без изменения данных.
Первый backend probe просмотрел только верхний уровень и вернул 0 files; корректный
рекурсивный замер выше заменяет этот неполный scope, исходная квитанция сохранена.

## Проверки и следующий шаг

**44 pytest cases**, включая реальный файл с Windows path >260, UNC, partial/access,
sparse-size growth, replacement, quotas и low-disk stops; Ruff/diff проходят.
Первичная collection без обязательного test JWT не стартовала; после тестовой
переменной окружения 44 cases прошли. Runtime credentials не менялись.
Тяжёлая пересборка API/UI/APK для CLI диагностики не требуется и не выполнялась.

На первоначальном срезе восьмичасовые окна были **RUNNING**. После перезапуска
приложения процессы отсутствовали; сохранённые срезы заканчиваются в 19:34:56
(RAM) / 19:35:55 (disk). Окна **INTERRUPTED**, не completed/accepted. Raw reports содержат
частные пути и не публикуются; public evidence содержит агрегаты, ограничения и
SHA-256 датированных файлов. Hash активного status не выдаётся за неизменную квитанцию.

## Системный readback после запуска пользователем

**Итоговый срез 20:15:59 UTC:** пользователь запустил
[read-only сборщик](../../../scripts/pilot/collect_storage_allocation.ps1) в своей
PowerShell администратора. Его `administrator=true`; token инструментального
терминала остаётся `false`. Это разные фактически проверенные процессы.
Положительный путь подтверждён реальными отчётами, а не только синтаксисом/tests.
Системное окно **COMPLETE: 31 срез / 19:45:20–20:15:20 UTC**. Все 62 native
queries завершились exit0 без truncation. Сборщик сохранил 85 612 байт отчётов
и завершился самостоятельно. Это завершение конечного окна, не eight-hour acceptance.

| Системная величина | Фактическое наблюдение | Ограничение |
|---|---:|---|
| Размер C: | 1 023 141 736 448 байт | Exact `fsutil` result |
| Всего reserved | 3 600 093 184 байта | Не приплюсовывать к VSS как доказанно независимый расход |
| Reserved storage для тома | 3 560 218 624 байта | Часть предыдущего значения, не дополнительный расход |
| Free первого / последнего sample | 37 504 024 576 / 37 226 446 848 байт | -277 577 728 байт / 264,719 MiB за 30 минут |
| VSS used display | 13,5 → 13,7 ГБ | Округлённый вывод, не exact delta в байтах |
| VSS allocated display | 13,9 → 14,1 ГБ | Рост подтверждён; точный byte delta не измерен |
| VSS maximum display | 19,1 ГБ | Настроенный максимум, не текущий занятый объём |

Во всех прочитанных `fsutil` samples соблюдается **total = used + free + reserved**.
Точные VSS `UsedSpace/AllocatedSpace` в байтах пока не получены: CIM по-прежнему
возвращает initialization failure в инструментальном процессе. Контракт этих
счётчиков описан в [Win32_ShadowStorage](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/vsswmi/win32-shadowstorage).

### Предыдущий резкий скачок и событие VSS

Полное сохранившееся старое disk window содержит **17 samples / 18:16:45–19:35:55**:
free44 431 917 056 → 37 496 315 904 байта, **-6 935 601 152 байта / 6,459 GiB**.
Между samples14/15, **19:25:55–19:31:45**, потеря составила **4 706 394 112 байт /
4,383 GiB**. В complete root scans18:16:45–19:31:45 workspace вырос лишь на
3 499 811 байт, session logs на617 833, npm-cache не вырос. Temp PARTIAL не используется
для subtraction. Длина/storage API наблюдаемых Docker/LDPlayer VHD не выросла;
mtime свидетельствует о записях, не даёт их block allocation или writer attribution.

Windows Application содержит **VSS event8231 / 18:28:06.5657675UTC**: инициировано
создание shadow-copy set, requester `taskhostw.exe`. **Event8224 / 18:31:09UTC** —
остановка VSS по idle timeout. Event8231 не является отдельным доказательством
успешного создания или размера snapshot. Запросы volsnap/System Restore за17:30–19:40
не вернули matching events; это ограниченный запрос, не отсутствие VSS.

**Рост allocated VSS подтверждён, writer UNDETERMINED.** В последующем интервале
**20:00:20–20:01:20 UTC** display allocated вырос13,9→14,1ГБ одновременно с падением
free на236 511 232байта. Это реальный дополнительный потребитель места, а не вывод
только из наличия shadow copies. Exact VSS delta не получена; атрибуция всего
предыдущего снижения6,459GiB остаётся открытой.

Его copy-on-write механизм сохраняет
старые блоки при перезаписи исходного тома: размер исходного VHD может оставаться
тем же, а shadow storage расти. Это объясняет возможное расхождение logical-file
inventory и free space, но baseline VSS до гигабайтового скачка отсутствует.
Причина этого конкретного скачка **не доказана**.
[Механизм Microsoft](https://learn.microsoft.com/en-us/windows-server/storage/file-server/volume-shadow-copy-service).

### RAM: kernel pools и диагностическая нагрузка

Все62 сохранившихся старых RAM samples17:32:56–19:34:56 относятся к одной boot epoch.
Commit вырос на4 628 553 728байт, paged pool на1 759 911 936, nonpaged pool на724 037 632.
Available RAM при этом выросла на976 785 408байт. Backend в том же container epoch:
589,3 → 596,8MiB (+7,5MiB по округлённому display).

Крупный pool growth совпадает с полными обходами5млн файлов. Между19:26:56 и19:30:56,
во время второго обхода19:27–19:30, paged pool вырос на219 389 952байта. Нагрузка
не idle/controlled; нет pool-tag/driver attribution, поэтому ни Windows driver,
ни APK/backend не объявлены источником RAM leak. Новые полные обходы C: в этом
продолжении не запускались. Для доказательства kernel leak требуются tag/epoch
измерения и проверка освобождения, как описывает
[Microsoft](https://learn.microsoft.com/en-us/windows-hardware/drivers/debugger/finding-a-kernel-mode-memory-leak).

Отдельные конечные продолжения: disk31samples/60s запущен19:41:48, первый complete
root sample19:42:37; RAM16samples/120s — первый подтверждён19:45:11. Они не склеиваются
со старым окном в continuous eight-hour acceptance. Первый RAM запуск не нашёл
`scripts` module; ошибка сохранена, запуск исправлен явным workspace PYTHONPATH,
после чего реальные process/container/memory samples появились.

Оба коротких продолжения завершены: disk **31 срез / 19:42:37–20:12:37**,
RAM **16 срезов / 19:45:11–20:15:11**. Полные root scans показывают workspace
+1 335 206 байт, chat sessions +13 976 105 байт, npm-cache 0; Temp остаётся PARTIAL.
В 31 named-file срезе длина наблюдаемых Docker/LDPlayer дисков не менялась;
pagefile/hiberfile storage API по-прежнему unknown из-за sharing violation.

За короткое RAM окно available -96 325 632 байта, commit +62 607 360, paged pool
+25 624 576, nonpaged +8 187 904. В конце доступно **20 420 149 248 байт / 19,018 GiB**
RAM; free C: **37 226 446 848 байт / 34,670 GiB** на последнем native sample.
Backend container display 597,1 → 597,7 MiB; review UI 76,86 → 76,95 MiB в тех же
container epochs. Это observational window, не proof отсутствия долгосрочной утечки.

Runtime readback20:05:15 подтвердил healthy API/review UI `c1a6e79`, прежние ID/start
и ограниченные LogConfig. Первый probe использовал неверное имя UI container;
отказ сохранён, точное имя затем получено из Docker inventory. Runtime не менялся.

**48 локальных diagnostic tests**: прежние44 +4 реальных PowerShell rejection cases.
CI для533756f прошёл backend/frontend/Android/preview; deploy skipped. Это исходники
и build checks, не host leak/Fleet32 приёмка. Source системного сборщика `a305076`
опубликован; его backend/frontend/Android/preview workflows также SUCCESS
на readback20:13:09. Installed API/UI `c1a6e79` и APK10244 сохранены.

Продолжение ничего не удаляет и не меняет VSS/драйверы/pagefile/сервисы. Следующий
критерий — получить точные VSS byte counters и при повторном росте сопоставить
их с ограниченной writer/pool-tag трассировкой. Native allocated VSS growth уже
подтверждён, но прежние 6,459 GiB не приписаны ему целиком. Изменение VSS retention
или offline VHD compaction — отдельное обслуживание с проверкой сохраняемых данных. Прежние34 source-fixed /
7 unclosed web gates, R04/R05/R06/R07/R09 и Fleet32 NO-GO сохраняются.
