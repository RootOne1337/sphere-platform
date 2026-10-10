# Повторная потеря места на C: и сбор данных для атрибуции

Дата пользователя: **7 октября 2026, Asia/Yekaterinburg (UTC+5)**.
Диагностический source: **ecc82211ba6b19be2ef04f2ec7af987423db1dbf**.
Установленные UI/API: **a41c4e6**, APK не обновлялся.
Статус исходного 8h окна: **потеря подтверждена; writer всего окна не установлен**.

**Последующий срез 7 октября:** elevated trace поймал отдельное падение C:
235 745 280 B с ростом VSS allocation 234 881 024 B / 99,63%. Подтверждён
drift ранее одобренного лимита; возвращён max8 GiB, освободилось16,304 GiB
на C:, две проверенные restore copies удалены. Дополнительные~20 GiB до этой
команды освободил сам оператор удалением постороннего файла. Actual elevated
RAM/VSS observer и event-triggered FileIO supervisor работают; actor смены
квоты, attribution всего 8h и RAM soak остаются OPEN.
[Новые evidence и границы](HOST-STORAGE-VSS-CURRENT.md).

[Проверяемые числа и hashes](HOST-STORAGE-FOLLOWUP-EVIDENCE.json) ·
[Операционная инструкция](../../operations/HOST-RESOURCES.md) ·
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Предыдущая атрибуция](../2026-10-05/DISK-WRITER-ATTRIBUTION.md).

## Конечное окно наблюдения

Исходный metadata-only sampler завершил **97/97 samples за восемь часов**:
08:02:46–16:02:46 по местному времени / 03:02:46–11:02:46 UTC.
Он читает free C:, logical/allocated size Docker VHDX и metadata pagefile;
файловые contents, VSS, процессы и RAM в этом окне не собирались.
Предел отчёта — 8 MiB; исходные samples остаются private в `.local-pilot`.

| Измерение | Результат | Что доказано |
| --- | --- | --- |
| C: free до | 36 431 638 528 B | Измерение свободного места тома |
| C: free после | 27 286 896 640 B | Тот же том, без пропуска sequence |
| Изменение C: free | -9 144 741 888 B / 8.517 GiB потери | Наблюдение пользователя подтверждено измерениями |
| Docker VHDX logical / allocated | 234 731 077 632 B, постоянно во всех 97 samples | Этот файл не увеличился в sampled endpoints; записи внутри возможны |
| Pagefile logical | 50 668 236 800 B во всех 97 samples | Измеренная длина постоянна |
| Pagefile allocation / identity | allocation недоступен (`win32_32`); identity `[0,0]` | Размер allocation и непрерывная идентичность неизвестны; delta не подменяется нулём |

Падение free не равномерно. Уже в промежуточных срезах были падения
3 039 281 152 B в 09:52, 2 247 753 728 B в 11:12 и 719 405 056 B в 15:52.
Это разности между пятиминутными срезами, не точные времена отдельных writes.
Положительные изменения между ними не выбрасываются из конечного net delta.

**Постоянный размер VHDX не исключает записи Docker.** Записи в уже выделенные
блоки могут иметь отдельные эффекты в защищённых слоях Windows. Для объяснения
падения free нужны VSS/volume counters и scoped FileIO trace; совпадение по
размеру или времени само по себе не устанавливает writer.

## Docker: объём, логи и расхождение конфигурации

Read-only срез около 15:48: 46 контейнеров, 14 запущены. Каталоги контейнеров,
включая Docker stdout/stderr files и metadata, занимают **329 088 KiB**.
Это общий текущий объём около 321 MiB, который сам по себе не объясняет
многогигабайтовую потерю free. Содержимое журналов не читалось этим `du`.

Docker сообщает 222 images / 186,7 GB, 767 build-cache records / 84,42 GB,
68 volumes / 7,247 GB. **Эти категории нельзя складывать:** у них есть shared
layers и другая семантика учёта. Они не являются размером исходников Sphere.
VHDX около 218,6 GiB включает накопленные images/cache/data и отдельно измерен.
Штатная очистка внутри guest не гарантирует возврата этого места Windows;
compaction не выполнялся в данном этапе.

Обнаружен runtime drift: работающие PostgreSQL, Redis, MinIO и n8n имеют
`json-file` без `max-size`/`max-file`. В актуальном `docker-compose.yml`
для них уже заданы 20m × 5. Новые review API/UI и observability имеют лимиты;
исправление compose не изменяет конфигурацию ранее созданного контейнера.
Это отдельный риск роста логов, **не доказанная причина текущего расхода**.
Legacy services не пересоздавались; Docker prune, volumes и журналы не удалялись.

## Доступные каталоги и границы обхода

Один конечный read-only workspace scan завершён: **20 303 654 380 logical B**,
27,601 s, без access errors; hard links не дедуплицированы. Из них
**10 268 212 000 B** — каталог подготовки восстановления перед boot repair.
Зависимости, Next outputs, проверенные архивы CI и recovery evidence включены
в сумму. Recovery copy остаётся на том же SSD; это не независимый backup.

AppData Local scan достиг 30s budget и имеет `partial_budget`; ProgramData
имеет `partial_access`. Их неполные суммы не используются как доказательство
отсутствия расхода или для вычитания из free тома. Отдельные app/session
metadata scopes проверены без чтения contents. Исторические и сегодняшние
срезы не являются одним контролируемым восьмичасовым интервалом.
Private пути и файловые списки не публикуются.

## Что изменено в диагностике

[disk_growth_report](../../../scripts/pilot/disk_growth_report.py) читает только
конечные samples: максимум 97 файлов / 1 MiB каждый / 8 MiB суммарно и 256
entries в report directory. Никакого рекурсивного обхода или записи в input.
Он отклоняет duplicate JSON keys, malformed timestamps/counters и filename/index
mismatch. Сохраняет gaps, неизвестную allocation, смену/неизвестность identity.
Нулевой endpoint delta не выдаётся за постоянство во всех промежуточных срезах.
Raw paths заменены watch IDs; `writerAttribution` всегда `UNDETERMINED`.

[Host observer](../../../scripts/pilot/host_storage_watch.py) получил явный
`--allow-unprivileged`. Elevated default сохранён; повышения прав нет.
Этот режим собирает доступные Windows RAM/commit/pools/process epochs,
pagefile usage и Docker/WSL. Отказ VSS сохраняется как `unavailable`,
пустые rows при отказе не означают ноль. Process IO может быть сетевым,
поэтому top IO не считается доказательством записи persistent data.

Новый observer действительно запущен **15:56:50 UTC+5** до планового
**23:56:50 UTC+5**: 241 samples каждые 120s, Docker каждые 16min,
report cap 16 MiB / sample cap 128 KiB. Первый snapshot содержит реальные
host/Docker/WSL counters, administrator=false, VSS unavailable. В ранних
срезах RAM и commit меняются; полноценный heap/resource soak ещё не закончен.
Collector не является service/autostart и не читает full-directory contents.

Проверено **67 targeted tests / 16 subtests**, Ruff и mypy двух utilities,
24 local operator links, diff check и Git fsck. Для metadata tests использован
`pytest --noconftest`, чтобы не загружать посторонние application fixtures.
Это не полный backend CI; runtime/CI receipt установленного a41 сохраняется
отдельно. C: в повторном запросе `Healthy / OK`; это не доказательство причины
предыдущих повреждений SSD/NTFS или отсутствия RAM leak.

## Следующее необходимое доказательство

Текущая сессия не administrator. `vssadmin list shadowstorage /for=C:` и
`fsutil volume diskfree C:` вернули access denied, CIM VSS — failure.
Системный слой остаётся UNKNOWN; прежний VSS limit от 5 октября не считается
сегодняшним размером или доказательством расхода после reboot.

У оператора запрошен один запуск существующего
[collect_disk_writer.ps1](../../../scripts/pilot/collect_disk_writer.ps1)
на 600s / 10s samples / stop-after-drop 128MiB. Он использует отдельную
bounded memory ETW session и VSS counters; не очищает и не перезапускает services.
Новый запуск ещё не подтверждён. Процедура отказывается трогать другую WPR
session и сохраняет trace только собственного instance.

После получения counters нужно сопоставить allocated VSS/free C: и trace
конкретного пути/процесса. Историческую потерю всех восьми часов короткая
последующая trace автоматически не объяснит. Если расход окажется внутри
Docker, следующий слой — guest path/volume/retention; если в защищённом Windows
слое — отдельная host policy с сохранением её рисков и исходных evidence.

Backend/SQL/APK/пользовательские данные не менялись. Статус storage/RAM leak —
**OPEN**; общий product ledger **9 accepted / 41 open** остаётся прежним.
Continuous touch, rich recorder, task artifacts и fleet soak не объявляются
завершёнными этим диагностическим этапом.
