# Возобновление ограниченного наблюдения за диском и RAM

Срез: 2026-10-09T12:51:26.507214+00:00. [Машинные измерения](STORAGE-OBSERVER-RESTART.json).
EP-033/047 и CHAT-12 остаются OPEN; это восстановление измерений, не устранение утечки.

Прежний observer завершил 241/241 samples 8 октября в09:01UTC.
Новое окно началось **9 октября12:42:57UTC /17:42:57UTC+5** и ограничено
**10 октября12:42:57UTC /17:42:57UTC+5**: 721×120сек, общий отчёт16MiB,
один sample128KiB. PID26192 сверён с python.exe, command binding и creation epoch.
До начала этого окна был разрыв; новые данные не восстанавливают прошлые writes.

Реально проверены 5 законченных JSONL samples: индексы, timestamps и source SHA.
Последний sample 2026-10-09T12:50:57.052463+00:00; свободно 47609090048B.
От baseline изменение C: -17375232B. Такой короткий
срез не является оценкой суточной скорости или доказательством утечки.

## Что собирается

- Allocation/length/identity 24 известных файлов: Docker VHDX, шесть LDPlayer VMDK,
  размеры верхнеуровневых SQLite/WAL/SHM Codex. Содержимое баз не читается.
- Windows RAM, commit/limit, paged/nonpaged pool, pagefile; top32 процессов
  с creation epoch/private/working set и top16 IO rates.
- Каждые16минут Docker df/stats/container epochs и WSL df/meminfo.
- Allocation deltas только для same-identity файлов. Process IO включает сеть
  и само по себе не является атрибуцией persistent writes.

Docker VHDX baseline allocation 234731077632B: большой файл подтверждён,
его размер сам по себе не определяет источник текущего уменьшения свободного места.
Build cache/images могут разделять слои; категории Docker df нельзя просто сложить.

## Границы и следующий разбор

Терминал не administrator. VSS имеет состояние unavailable/CimException;
USN/ETW не запущены. Это limited metadata observation известных файлов,
а не полное доказательство writer любого файла C:. Unknown не заменён нулём.
Новый helper не удаляет файлы, не отправляет input Android, не перезапускает
контейнеры, не меняет Windows policies и не добавляет autostart.

После reboot/deadline сбор сам не продолжится. Проверять status.json вместе
с PID/command/creation epoch, source hash и свежестью законченных samples.
Private report `.local-pilot/host-storage-limited-20261009T124256Z`; baseline prefix сохранён
отдельно с SHA-256, исходный growing JSONL не публикуется. После окончания окна
сравнить C: delta, named allocations, guest data и RAM в пределах одного boot.
Не объявлять disk/RAM leak исправленным по успешному запуску observer.
Краткие замеры не закрывают long soak/retention, privileged correlation или
resource gates500/1000. [Текущий runbook](../../operations/HOST-RESOURCES.md).
