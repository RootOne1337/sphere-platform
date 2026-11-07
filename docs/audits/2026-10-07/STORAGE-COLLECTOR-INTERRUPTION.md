# Разрыв наблюдения за диском и восстановленное ограниченное окно

Срез: **7 октября 2026, 18:34 UTC / 23:34 UTC+5**. Дополнение к
[HOST-RESOURCES](../../operations/HOST-RESOURCES.md). Исторические отчёты
не изменены; состояние `running` в файле не доказывает работающий процесс.

## Подтверждённый разрыв

При проверке в 18:11 UTC четыре прежних PID отсутствовали. Их status files
содержали устаревшее `running`. Причина остановки не установлена. Данные
после последних complete samples не восстанавливаются из этого статуса.

| Сборщик | PID старого окна | Последний complete sample UTC | Сохранённые данные |
| --- | ---: | --- | --- |
| Elevated host/VSS/RAM/Docker | 36900 | 14:03:02 | 79 samples, 699189 B |
| Event-triggered kernel writer | 3648 | 14:01:02 | 3 complete ETL, 101482688 B суммарно |
| Whole-C: NTFS growth | 9008 | 14:03:12 | 31 samples, 3349931 B |
| LDPlayer VMDK observer | 35848 | 14:00:26 | 29 samples, 70547 B |

Это разрыв наблюдения, **не доказательство утечки и не атрибуция writer**.
Windows boot time в доступном WMI срезе — 6 октября 19:42:12.5 UTC;
эта дата не подтверждает reboot около 14:03 UTC. Причина потери процессов
требует отдельной проверки. Старые отчёты сохранены для разбора трёх traces.

## Восстановленная доступная часть

Терминал агента сейчас **не administrator**. VSS, USN и kernel ETW в этом
окне не объявлены восстановленными. Доступен host/file observer с явным
`--allow-unprivileged`; отсутствие VSS записывается как `unavailable`.

Первый limited replacement PID30104 работал 18:13:41–18:21:41 UTC и сохранил
5 samples /49008 B. Он остановлен после проверки command line/creation epoch
только для добавления двух sdcard VMDK в список наблюдения. Его старый status
также не переписан в искусственно «успешно завершённый».

Текущий replacement PID**29648** стартовал **18:23:38 UTC** и завершает
конечное окно **8 октября 02:13:38 UTC / 07:13:38 UTC+5**. Предел: 236 samples
по120s, 16MiB report,128KiB sample; Docker metadata каждые8 циклов. Никакого
autostart, удаления, изменений лимита VSS или Android commands нет.

Наблюдаются ровно пять файлов: Docker `docker_data.vhdx`, `data.vmdk` и
`sdcard.vmdk` двух локальных LDPlayer. Дополнительно сохраняются RAM,
Windows commit/pools, top process memory и process IO rates, Docker/WSL metadata.
IO включает иной трафик и **не доказывает, в какой файл пишет процесс**.

Private directory: `.local-pilot/host-storage-limited-20261007T1824`.
В 18:33:38 UTC подтверждены живой process и6 complete JSONL rows /58516B,
пять file observations, host `measured`, VSS `unavailable`. Прямое чтение
JSONL проверено: данные существуют, а не только счётчик status. Срез C: free
пока не даёт оснований объявлять продолжающийся расход устранённым.

## Разбор следующего эпизода

1. Проверить возраст последнего complete sample и PID **вместе** с creation
   epoch/command line; не доверять одному `running` или повторно используемому PID.
2. Сопоставить free-disk delta с logical/allocated file sizes, Docker guest usage,
   RAM/commit и доступным VSS. Отсутствие измерения оставлять неизвестным.
3. Для прежнего окна отдельно разобрать сохранённые ETL. Текущий limited observer
   не обеспечивает новую file-to-PID attribution, USN coverage или VSS counters.
4. Не запускать второй collector поверх работающего. После OS/app restart или
   окончания окна следующий запуск требует нового bounded report directory.

Все 50 продуктовых пунктов прежнего audit ledger сохраняют статусы **9/41**.
Этот отчёт уточняет эксплуатационное покрытие; он не закрывает storage/RAM soak.
