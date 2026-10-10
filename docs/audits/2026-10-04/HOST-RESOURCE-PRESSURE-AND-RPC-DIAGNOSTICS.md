# Диск и ОЗУ хоста: инцидент, исправление сборки и диагностические доказательства

**Дата:** 4 октября 2026, Asia/Yekaterinburg (UTC+5); времена ниже — UTC.
**Установленные API и review UI:** `c1a6e79a75221c45a71160a21bc91c48b22ef5ae`.
**Коммиты:** `5e83e1c` — RPC/capture diagnostics; `c1a6e79` — cache reuse/resource guard.
**APK:** прежний `1.2.44-dev / 10244`, 14 доступных Android; пять offline вне приёмки.
**PC LastBoot:** `2026-10-04T16:39:32.500000Z`; прежний uptime не переносится через reboot.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Эксплуатационная процедура ресурсов](../../operations/HOST-RESOURCES.md) ·
[Машинные доказательства](HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS-EVIDENCE.json) ·
[Контракт native PNG и прошлые отказы](DEVICE-CONTROL-AND-NATIVE-CAPTURE.md) ·
[Readiness](../../operations/READINESS.md) ·
[PR19](https://github.com/RootOne1337/sphere-platform/pull/19).

**Позднейший disk follow-up / 17:50 UTC:** отдельно измерена вся рабочая папка
Sphere (7,996 GiB), доступная область C: и выполнена штатная очистка npm/pip.
[Карта потребителей, +4,726 GiB и сохранность runtime](HOST-DISK-INVENTORY-AND-CLEANUP.md).
Числа предыдущего инцидента ниже сохраняют собственные времена измерений.

**Последующее наблюдение, 5 октября:** [фактическое снижение C: free, ограниченный watcher и protected scopes](../2026-10-05/HOST-DISK-GROWTH.md).
Long-term attribution остаётся OPEN; источник2GiB не объявлен найденным.

## Вывод и предел доказательства

Установлен сильный дефицит **диска Windows** и накопление **build artifacts**:
на C: оставалось 41 000 960 байт. Docker VHD занимает 234 731 077 632 байта,
а отдельно старые Next caches занимали 8 812 332 358 байт. Найден конкретный
source defect: `BUILD_SHA` раньше менял stage до `npm ci`, заново создавая
dependency install layer при каждом коммите. Он исправлен и cache reuse проверен
двумя сборками с разными SHA.

Переполнение пользовательской RAM отдельно **не объявлено доказанной heap leak**.
До reboot Windows сообщала мало свободной виртуальной памяти; WSL private bytes
существенно превосходили working set. После reboot короткий замер показал
уменьшение WSL working set. Новый конечный замер сохраняет Windows private/commit,
контейнеры и Linux anon/cache/swap. Длительный одинаковый workload и heap profile
ещё не выполнены. Починка build-cache не доказывает устранение всех RAM-проблем.

Параллельное совпадение disk shortage, Docker build export stall и API timeout
сохранено. Прямой kernel trace `ENOSPC` не получен, поэтому не заявляется, что
каждый исторический обрыв удалённого видео вызван этим дефицитом.

## Разделение наблюдений

| Код | Найдено | Статус и предел |
|---|---|---|
| R01 | `BUILD_SHA` инвалидировал frontend dependency stage | SOURCE_FIXED / DEPLOYED; одинаковые RootFS/config и cached npm ci доказаны |
| R02 | 19 старых contexts и 31 Next cache | SCOPED_CLEANUP; нужные runtime/доказательства сохранены |
| R03 | Unbounded Docker logs у core containers | PARTIAL: source defaults исправлены, новый API LogConfig принят; прочие старые контейнеры не пересозданы |
| R04 | Предшествующая высокая виртуальная memory pressure | OPEN: виновный heap/процесс и длительная тенденция не доказаны |
| R05 | Большой несжатый Docker VHD | OPEN: измерен, compaction не выполнен; image cleanup не равен уменьшению VHD |
| R06 | Нет backend process RSS series в текущем Prometheus | OPEN: Docker stats использованы честно, чужой RSS не выдан за backend |
| R07 | Agent log retention не является global quota/sweeper | OPEN: код и фактический размер просмотрены; массовое удаление логов не делалось |
| R08 | Legacy decoder имеет unbounded pre-config list | SOURCE_RISK: текущие routes используют другой ограниченный decoder; причиной текущего хоста не доказан |

Эти эксплуатационные findings не переименовывают исходные 41 веб-пункта:
**34 source-fixed / 7 незакрытых**, включая F32/F33/F39 PARTIAL, остаются прежними.
Новый native capture не закрывает N01 durable artifact-upload pipeline.

## Временная шкала инцидента

| UTC | Факт |
|---|---|
| 14:27 | Старая установка API/UI9716348; 19 catalog, 14online APK10244; новый deploy ещё не запускался |
| Около 14:50 | C: 41 000 960 байт; build export/unpack завис, Docker/WSL команды не отвечали, API18080 и UI3015 timeout |
| 14:57:23 | 50 668 236 800 RAM, free 10 095 448 064; OS TotalVirtual102 267 379 712/free5 070 413 824 |
| До reboot | Адресная очистка 19 contexts дала free559 923 200; 31 Next cache — free9 162 141 696 |
| До reboot | `docker desktop restart --timeout55` не завершил восстановление; завершён только docker-desktop distro, не Ubuntu |
| 16:39:32.5 | Перезагрузка ПК пользователем; новый LastBoot подтверждён CIM |
| 16:55:53 | Docker здоров, C:43 978 809 344, freeRAM20 599 902 208, actual commit45 958 873 088/95 153 381 376 |
| 16:59–17:04 | 21 sample; WSL working set снизился примерно на 1,53 GiB |
| 17:01:29 | Удалены 53 старых unused images только точных repos проекта, 46 container identities/images/epochs сохранены |
| 17:07–17:11 | Новые immutable API/UI образы построены после resource preflight; packaged gates прошли |
| 17:14:30 | API c1a6e79 healthy; 16 соседних сервисов и volumes/mounts сохранены; logs20m×5 подтверждены inspect |
| 17:14:45 | UI c1a6e79 healthy на3015; замена только image/build arg, 16 соседей сохранены |
| 17:14:53 | PH025 native PNG504 на первом `display_before`; полный correlated trace сохранён |
| 17:15:09 | PH010 native PNG200, полный decode и hash chain подтверждены |
| 17:16:24–17:17:24 | Первый fleet gate FAILED:11→14, смена remote connection epochs; не скрыт |
| 17:20:13 | Отдельный диагностический recovery trial PH025 PNG200/3,817s; прежний504 не перезаписан |

Pre-reboot OS TotalVirtual/free — приближение virtual pressure, **не** точное
измерение Windows `CommittedBytes/CommitLimit`: actual PerfOS counter тогда
не был сохранён. После reboot это уже прямой счётчик. Старый memory compression
working set10 860 617 728 и vmmemWSL working set8 992 907 264/private24 907 317 248
не складываются в независимый итог RAM.

## Размеры диска и безопасное восстановление

Единицы исходных JSON — байты; GiB здесь означает 2^30 байт.

| Объект | Измерено | Как интерпретировать |
|---|---:|---|
| Docker VHD logical/allocated | 234 731 077 632 B /218,61 GiB | GetCompressedFileSize, sparse attribute отсутствует; размер хостового файла |
| Docker ext4 used | Около194,2 GiB | Linux filesystem; доступно около761,4 GiB, что не означает столько свободного C: |
| Images до очистки | Docker199GB | Docker shared accounting, включает чужие проекты |
| Build cache records | 86 935 621 017 B | Shared81 467 565 691; первоначально private5 468 055 326, не складывать с images |
| Все Docker volumes | Docker7,052GB | Не удалены, включая чужие проекты/ключи/БД |
| Старые Next caches | 8 812 332 358 B /8,21 GiB | Удалены только31 owned `.next/cache` |
| Старые git-archive contexts | 436 241 289 B | 19 owned trees, список подтверждён commit, текущие contexts сохранены |
| `.local-pilot` после очистки | 3 978 829 989 B | Read-only walker не следует junctions/symlinks; node_modules/APK/evidence сохранены |
| Все container log directories | 316 236 KiB /около309 MiB | Не главный подтверждённый источник сотен GiB |
| Новый API `/var/lib/sphere` | 197 728 KiB /около193 MiB | Реальные app logs/profile data, не удалены |
| Pilot PostgreSQL volume | Docker82,3MB | Только один том, не RAM и не весь Docker disk |
| Prometheus volume | Docker89,35MB | TSDB, отдельный retention14d/2GB |

Удаление 53 images отобрано по точному repo, Git revision, возрасту >48h и отсутствию
ссылок всех 46 running/stopped контейнеров. Размер selected images10 574 108 359 B
логический, с shared layers; **это не количество освобождённых Windows-байт**.
Docker после очистки показывал images195,9GB; VHD не уменьшился, freeC почти
не изменился. Никакого `system prune -a --volumes` не выполнялось.

Рост C: free после reboot не приписан только очистке: сравнение через reboot,
возможные изменения pagefile/других процессов не позволяют такое заключение.
После reboot pagefile allocated44 484 788 224 B; прежний allocated не измерен.
Сам pagefile, пользовательские Downloads, APK, базы, ключи, чужие приложения
и другие WSL-дистрибутивы не удалялись/не перенастраивались.

Динамический VHD не обязан уменьшаться после удаления Linux-файлов;
offline compaction требует отдельной процедуры. [Microsoft compact vdisk](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/compact-vdisk).

## ОЗУ: что подтверждено измерениями

После reboot Docker Desktop4.65.0, Engine29.2.1, WSL2.4.13.0/kernel5.15.167.4.
`.wslconfig` отсутствует. Это не означает отключённый memory reclaim: текущая
[документация Microsoft](https://learn.microsoft.com/en-us/windows/wsl/wsl-config)
задаёт default `dropCache`; собственные settings и actual behaviour различаются.
В Linux snapshot: MemTotal24 193 352 KiB, MemAvailable21 277 780 KiB,
Cached2 098 392 KiB, Buffers1 016 888 KiB, AnonPages1 908 512 KiB,
swap used38 116 KiB. Это позволяет отличать anon heap от reclaimable cache.

В 21 sample16:59:26–17:04:34 Windows commit вырос примерно521 MiB,
freeRAM выросла примерно326 MiB. Один и тот же vmmemWSL PID: private+201 502 720 B,
working set−1 639 366 656 B. Browser private+245 145 600 B за тот же интервал;
это наблюдение, не доказательство leak и не принадлежность конкретной вкладке.
Docker описывает удержание Linux page cache после сборки как отдельный механизм:
[официальный WSL backend guide](https://docs.docker.com/desktop/features/wsl/).

Новый 25-sample замер связывает process PID/start time, Windows commit/RAM/pools,
C: free, Docker stats и Linux anon/cache/swap. Его сводка публикуется отдельно
в [evidence](HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS-EVIDENCE.json).
Эта конечная проверка не заменяет overnight soak и управляемый повтор workload.
`process_resident_memory_bytes{job="sphere-backend"}` не имеет series в текущем
Prometheus; series с jobPrometheus относится к самому Prometheus, не к API.
Полное отсутствие backend memory leak ни одним из этих фактов не доказано.

Фактическое окно: **17:16:06–17:28:06 UTC, 25 срезов / 12 минут**, без смены
host boot и IDs всех 17 наблюдаемых контейнеров. Проверки ресурсов прошли во всех
срезах. Сам monitoring не отправлял Android команды; отдельно в этом окне выполнен
один remote native capture. Количество browser tabs/приложений не фиксировалось,
поэтому это наблюдение, а не строго управляемый одинаковый workload.

| Счётчик | Начало → конец | Изменение и предел |
|---|---|---|
| Доступная RAM | 18 526 568 448 → 20 745 273 344 B | +2 218 704 896 B, около2,07GiB |
| Windows commit | 50 915 508 224 → 51 389 882 368 B | +474 374 144 B, около452MiB; limit95 153 381 376 B |
| C: free | 43 639 865 344 → 43 634 450 432 B | −5 414 912 B, около5,16MiB |
| Nonpaged pool | 2 047 832 064 → 2 078 081 024 B | +30 248 960 B; kernel pool attribution не сделана |
| Linux anon | 2 073 563 136 → 2 124 996 608 B | +51 433 472 B |
| Linux cache | 4 941 991 936 → 4 924 841 984 B | −17 149 952 B |
| Linux swap used | 39 030 784 → 44 273 664 B | +5 242 880 B |
| Backend cgroup | Около571,2 →588,6MiB | +17,4MiB, тот же containerID; startup/request/cache effects не отделены от heap |
| Review UI cgroup | Около62,84 →67,4MiB | +4,56MiB, максимум88,17MiB |
| Grafana cgroup | Около352,3 →372,4MiB | +20,1MiB, ограничение512MiB |
| vmmemWSL private | 10 589 396 992 →10 905 628 672 B | +316 231 680 B; PID тот же, Windows не раскрыла start time |
| vmmemWSL working set | 7 214 428 160 →7 429 963 776 B | +215 535 616 B; same process epoch формально не принят |
| Memory Compression working set | 2 386 620 416 →3 387 838 464 B | +1 001 218 048 B; start time недоступен, это не отдельный application heap |

Browser-процессы с подтверждёнными PID/start time: суммарно private+13 053 952 B,
working set−361 201 664 B. Новые/исчезнувшие процессы не входят в такой same-epoch
delta, а входят в общие Windows memory counters. Эти различия нельзя скрывать
обобщённым выводом «WSL/браузер больше не растут». Быстрое исчерпание RAM в этом
окне не воспроизведено; долгосрочный механизм остаётся UNDETERMINED.

В17:32:56UTC запущен **отдельный ограниченный read-only сборщик на8часов**:
241 sample с интервалом120s,≤256KiB на JSON,≤63 176 704 B суммарно, остановка
при C: free<512MiB. Процесс hidden, не автозапуск/служба, без Android команд,
без host config changes. Первый полный sample получен, stderr пуст. Его долгий
результат ещё **не** принят. Первый менее строго ограниченный sampler остановлен
после проверки PID/start ticks/command identity; его короткий срез сохранён.
Сравнение даты как строки первоначально отказало из-за PowerShell DateTime
десериализации; проверка по UTC ticks затем подтвердила владельца процесса.
Длительный сборщик остановится сам; при PC reboot он не восстанавливается.
Private raw process inventory хранится в `.local-pilot`, не публикуется на GitHub.

Read-only preflight17:28:07UTC: freeC43 634 319 360 B, availableRAM20 676 620 288 B,
commit51 481 571 328/95 153 381 376 B, все пороги пройдены.

## Исправленная сборка и защита ресурсов

В `frontend/Dockerfile` прежние `ARG BUILD_SHA`/`ENV NEXT_PUBLIC_BUILD_SHA` находились
перед `npm ci`. При каждом commit зависимый слой становился новым. Теперь отдельный
`build-deps` stage содержит только package/lock/install; metadata задаётся после
копирования source в builder. npm cache удаляется после install; `.next/cache`
удаляется после успешного build. Runtime assets и generated types сохраняются.

Фактические trial BUILD_SHA c1a6e79 и5e83e1c: RootFS layers и Config одинаковы,
`npm ci` во втором trial — `CACHED`. Manifest image IDs отличаются из-за новых
attestations; ранний неверный harness с проверкой равенства этих IDs сохранён,
затем исправлен на содержательную проверку. Builder `docker inspect.Size` изменился
с551 398 636 до303 371 224 B; это image-accounting, **не физически освобождённый C:**.

`scripts/pilot/resource_guard.py` читает доступный диск/RAM и Windows commit,
отказывает при неизвестном счётчике, free disk<20GiB, availableRAM<4GiB,
commit≥85%. Linux uses MemAvailable. Нет очистки/kill/restart/Android-команд.
18 cases проверяют границы, отрицательные/bool/missing значения и ошибку collector.
Оба новых локальных image build прошли guard; gate не обещает любой размер build.
Standalone CLI не перехватывает все сторонние сборки автоматически.

Core compose добавляет logs20m×5. Реальный новый API inspect принял точно этот
LogConfig. Тома/БД/прочие старые контейнеры не пересоздавались; rollout остальных
caps остаётся отдельной работой. Review UI сохраняет прежний cap5m×3.

## Аудит активных буферов и хранения

| Путь | Найденный предел/cleanup | Остаточная работа |
|---|---|---|
| Активный `frontend/lib/h264-decoder.ts` | Frame≤1MiB, decode8frames/2MiB/500ms, no pre-config buffer; VideoFrame закрывается в finally, destroy/reset очищают state | Browser heap/GPU profile и многократные open/close ещё не измерены |
| Legacy `src/lib/streaming/H264Decoder.ts` | Есть unbounded pendingFrames до SPS/PPS | Текущие routes его не импортируют; retained legacy component/test существует, не объявлен причиной |
| Backend VideoStreamQueue | 50 frames,8MiB,200ms; per-viewer backpressure, shared frame bytes | Global admission и ресурсный SLO для сотен viewers не приняты |
| Backend stream bridge | Weak device locks; idle publisher exits10s, owned tasks cancellation/close | Длительный reconnect/fault memory soak OPEN |
| Native PNG | Max5MiB,128KiB chunks, overall80s,8s RPC; UUID paths + finally cleanup | Root required; cleanup может не подтвердиться при потере связи |
| APK FileLoggingTree | 5×2MiB, bounded recent lifecycle tails | Это app logs, не вся системная история Android |
| Серверные agent logs | Дневные50MiB, upload512KiB, cleanup30d при upload | Нет global quota/independent sweeper; body limit проверяется после request.body allocation |
| Docker stdout/stderr | Новый API20m×5, review UI5m×3 | Прежние containers ждут адресного пересоздания |

Таблица — source audit и отдельные runtime measurements, не heap attestation.
Нет утверждения, что все старые пути удалены или уже достигается любой fleet size.

## Корреляция RPC и native capture

Исправлен отдельный доказанный дефект: Redis PubSub close мог заменить уже
полученный completed result или исходную 503/504 своей exception. На старом
packaged API9716348 три targeted regressions упали; на новом проходят.
`aclose` ограничен2s, cleanup failure не заменяет outcome, cancellation передаётся.

Для `interactive_<UUID>` записываются metadata-only:

- `interactive_rpc.forwarded`: command ID, worker socket write completion и timing.
- `interactive_rpc.finished`: publish/subscribe/await_result, outcome,
  progress count/first progress, live_only и subscription cleanup.
- `native_screenshot.finished`: snapshot ID, phase durations, first failed
  phase/index, RPC/completed counters, HTTP status и cleanup confirmation.

Нет raw shell/output, pixels, JWT, полных endpoints или бесконечного trace history.
HTTP ошибки502/503/504 содержат `X-Screenshot-Id`, `X-Screenshot-Elapsed-Ms`,
при наличии `X-Screenshot-Failed-Phase`, `X-Screenshot-Cleanup-Confirmed`.
UI декодирует bounded≤16KiB binary JSON error, показывает только проверенные
поля; автоматического retry root-команды нет.

| Actual trial | Ответ | Коррелированные этапы |
|---|---|---|
| PH02517:14:53, remote | 504/16,045s | display_before8,005s, cleanup8,004s;2 live RPC published/socket write completed,0progress/0completed; failedRPC1, subscription closed |
| PH01017:15:09, local | 200/6,208s | 10/10 completed RPC,10 socket writes;230885B,960×540; cleanuptrue |
| PH02517:20:13, recovery | 200/3,817s | 10/10 completed RPC,10 socket writes;217083B,960×540; cleanuptrue |

Оба PNG полностью декодированы Pillow; Android SHA-256 = server header = file.
First failed request и последующий успех имеют разные snapshot IDs/evidence.
Первый PH025 отказ находится **до screencap**, а не в PNG compression/browser decode;
socket-write completion не является APK acknowledgement. Почему ответ отсутствовал,
надёжно установить этим trace нельзя. API restart, поздние reconnects и предыдущие
TLS failures сохраняются как контекст, не доказанный единственный root cause.

Первый fleet gate17:16:24–17:17:24 FAILED11→14/epochs после API restart.
Remote reconnects закончились около17:16:28, baseline17:14:36 был взят раньше.
Следующее окно использует отдельный новый baseline, а не переписывает неуспех.
Это не continuous uptime и не оправдание произвольного исторического flapping.

Recovery fleet gate17:20:31–17:21:31UTC: 7 срезов, тот же cohort14 и серверные
даты подключения, heartbeat<60s;16 соседей/API/Tuna/OTA сохранены. Этот краткий
успех не меняет FAILED первого окна и не закрывает remote stability acceptance.

## Проверки и установка

| Gate | Проверенный scope |
|---|---|
| API exact production image | 186 PostgreSQL/Redis/service/RPC/native endpoint cases,0fail/errors/skips |
| API static contracts | Ruff passed, mypy229 files, OpenAPI178 operations/140paths |
| Full frontend exact Node24 builder | 113 suites/1122tests,types и production build30routes passed |
| Resource guard | 18 cases; отдельный pure-host test запуск |
| Old-image regression | 3/3 ожидаемых failures на старом Redis cleanup behaviour |
| Build cache reuse | Два SHA, identical dependency RootFS/config, second npm ci CACHED |
| API rollout | exact revision/digest/ready, logging20m×5, mounts/16neighbors/Tuna/OTA preserved |
| UI rollout | exact runner image/healthy/login200, onlyimage+buildarg,16neighbors preserved |
| Native PNG | Один local success, один remote failure и отдельный remote recovery success; все outcomes сохранены |

Образы построены из `git archive c1a6e79`; app source bind mount отсутствует.
Тестовые PostgreSQL/Redis отдельно от pilot. Пользовательские устройства не
перезагружались, новый APK/OTA не публиковался, ввод/скрипты/VPN не запускались.
GitHub CI exact source и финальные ресурсы записаны в evidence.
Browser3015 ранее отказал OPEN_URL_POLICY_BLOCKED; альтернативным каналом
ограничение не обходилось. Текущий native download/layout/wheel визуально не приняты.

## Открытые критерии завершения

1. Длительный host/worker/browser/APK memory workload с повторными open/close,
   измеренными process epochs, heap/GPU и idle recovery.
2. Ownership-based scheduled build retention, actual GC policy и отдельная VHD
   maintenance при необходимости; никаких удалений data volumes.
3. Применение LogConfig старых сервисов по очереди; server agent-log quota/sweeper.
4. Полные host и backend-worker метрики/alerts в мониторинге, без ложных series.
5. Устранение root cause remote response loss, measured browser FPS/input latency,
   visual acceptance и stream+scripts/fault20–30/32devices. Fleet32 остаётся NO-GO.
