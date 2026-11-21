# C: — подтверждённые дефекты и подготовка ремонта, 11 октября

**Ремонт ещё не выполнен. Новые UI/API/APK не установлены.** Windows подтвердила
дефекты NTFS, а Git — повреждение объектов. Проверенная копия проекта и PostgreSQL
готова. Проверка `chkdsk.exe C: /f` подтверждена в BootExecute на следующую загрузку;
перезагрузка и остановка приложений этой работой не выполнялись.
[Неизменяемая квитанция](HOST-REPAIR-1216.json).

## Что подтверждено

Elevated `Repair-Volume -DriveLetter C -Scan` выполнялся11:47:48→11:55:15 UTC
(16:47→16:55 UTC+5). Результат `ScanErrorsFoundNeedSpotFix`; после сканирования
volume `Warning / Spot Fix Needed`. Позднейший обычный preflight снова показывает
`Warning / Full Repair Needed`. Нельзя подменять эти разные срезы одной строкой
или трактовать завершение scan как исправление.

Microsoft описывает Scan как поиск и постановку дефектов в очередь без ремонта.
`/f` исправляет файловую систему; занятый системный C: проверяется при следующей
загрузке. Это не восстановление старой версии проекта или базы.
[Repair-Volume](https://learn.microsoft.com/en-us/powershell/module/storage/repair-volume?view=windowsserver2025-ps),
[CHKDSK](https://learn.microsoft.com/en-us/windows-server/administration/windows-commands/chkdsk).

`git fsck --no-dangling` завершился exit3:10 повреждённых объектов, четыре из них
относятся к файлам текущего pushed head. Локальный `git archive HEAD` также отказал
из-за повреждённого blob. Объекты не удалялись, Git не объявлен исправленным.
Причина повторного повреждения не установлена; «Healthy» физического NVMe не
доказывает исправность всего пути хранения. Часть hardware error counters недоступна.

**Дополнение12:36 UTC:** подготовлены правильные replacements всех10 объектов
из authenticated GitHub blob API. Каждый проверен по точному Git SHA и local zlib
readback; суммарно221 979B. У всех10 повреждённых объектов первые8 bytes `FF`,
три целиком состоят из `FF`. Это описание прочитанных данных, не установленная
аппаратная причина. Локальные объекты ещё не заменялись, working files не
перезаписывались. Recovery ZIP дополнительно сохранён в локальной копии; позднее
дополнение увеличило её до27 файлов. [Новая квитанция](GIT-RECOVERY-1236.json).
Исходная квитанция HOST-REPAIR-1216.json сохраняет прежний26-file срез.

## Проверенная копия

Каталог локальной копии: `.local-pilot/host-repair-20261011T121248Z-ec3fe5cb`.
На момент квитанции26 файлов /24 026 089B. Она находится на том же SSD:
независимой копии PostgreSQL и личных файлов нет.

Из-за повреждённого object store исходники получены независимо из authenticated
GitHub archive pushed head `b47d4882ee4cf3b870a2ee79a0aea71243a148c3`. Все3089
файлов проверены по Git blob SHA и ZIP CRC. Canonical tree
`f7cbe1783f0850eab822507f5c2abcf4c1898bf2` получен из commit object и дополнительно
сверен; tree endpoint через commit alias не выдаётся за canonical tree SHA.
Failed local fsck сохраняется явно; он не превращается в success после такой проверки.

В копии есть локальные binary patches, выбранные untracked Markdown/uv.lock,
критические private настройки, pilot debug signing/discovery keys и конфигурации
контейнеров. Последний полный patch `full-unstaged-before-reboot.patch` заменяет
предыдущие полные patches; применять их последовательно нельзя.

PostgreSQL: consistent custom dump782 401B, база до dump17 456 487B. Содержание
архива полностью декодировано через `pg_restore --file=/dev/null`; каталог и
TABLE DATA прочитаны. Восстановление в отдельную базу не тестировалось, SQL
в рабочую базу не применялся. Redis/MinIO volumes, полный SSD, личные файлы,
все untracked файлы и все локальные Git reflogs этой копией не покрыты.
Private содержимое и сырые диагностические отчёты в Git не публикуются.

## Подтверждение следующей загрузки

Проверены hashes всех recovery files; reviewed preparer запущен elevated.
Request завершился12:16:08 UTC, native exit3. Сам exit code не подтверждает
ремонт: независимый readback BootExecute содержит `autocheck autochk /p \??\C:`.
Состояние `boot-check-confirmed; repair-pending-restart`, repairCompleted=false.
Нет `/r`, принудительного dismount, rollback, service stop или автоматического reboot.
[Preparer](../../../scripts/pilot/prepare_host_boot_repair.ps1) и
[регрессии](../../../tests/test_pilot_host_boot_repair.py).

Перед ручным перезапуском нужно сохранить открытые личные файлы и штатно закрыть
эмуляторы/Docker Desktop. При загрузке не пропускать проверку диска.
После загрузки: новые Wininit/CHKDSK logs, dirty bit и fresh volume scan/preflight;
затем восстановление повреждённых Git объектов из проверенных источников и полный
fsck. Успех прошлого ремонта или прежний `running` не заменяет эти измерения.

## Реальный сбор ресурсов

Прежний limited PID43984 отсутствует. Последний сохранённый sample11:35:33 UTC,
241 срез; старый status ещё содержит `running`. Между ним и новым полным worker
есть непокрытый разрыв. Причина остановки неизвестна; статус не переписан в success.

Новый elevated worker PID13708, launcher37352, начат12:24:25 UTC;721×120s,
deadline12октября12:24:25 UTC,24 named files и16MiB report budget. Реальный первый
sample содержит RAM/commit,32 process readings и exact VSS counters. Отдельный
native VSS worker13732 работает с12:02 UTC до13:02 UTC,31×120s/4MiB.
Ни один процесс не имеет autostart после reboot. Количество проверенных samples
и timestamp фиксируются в JSON,24h completion/soak не объявляется.

VSS теперь имеет отдельный owned subprocess с timeout10s. Его зависание не удаляет
успешно измеренные RAM/commit/process данные; отдельный VSS срез сохраняется даже
при отказе основного host query. Deadline и unknown-состояния покрыты регрессиями.
[Collector](../../../scripts/pilot/host_storage_watch.py) и
[тесты](../../../tests/test_pilot_host_storage_watch.py).

Первый exact VSS срез: used19 717 046 272B, allocated20 246 953 984B,
max20 461 912 064B (~19.057GiB). Это отличается от ранее одобренных8GiB.
Кто вернул лимит — UNKNOWN; лимит и restore history этой работой не менялись.
Текущий размер VSS не является атрибуцией всех предыдущих потерь C:.
[Предыдущее согласование](../2026-10-05/VSS-RETENTION-REVIEW.md).

## Что подготовлено для обновления

Backend installer допускает именно `backend/websocket/direct_probe_telemetry.py`;
соседние неизвестные файлы, RBAC, requirements и migrations продолжают отвергаться.
61 tests +69 subtests прошли; collector/repair scope —41 tests, scoped Ruff passed.
Ни volume gate, ни защита остальных контейнеров не ослаблены.

Source `4ce2c6d6` прошёл три CI workflows. Source-pinned pilot APK55 build helper
подготовлен; APK ещё не собран/подписан/опубликован. Actual UI/API остаются `6ee80c1f`
на3015 и публичном origin. Следующий порядок: здоровый volume и проверенный Git,
pilot signing, reviewed API/UI install, canary PH010, native session journal и
подтверждённый direct input/reconnect; затем PH025 и проверенный fleet rollout.
PH030 выключен и не входит в текущую проверку. Localhost/LAN/WAN/TURN и stable1.3
остаются открытыми; новый source не объявляется реальной доставкой.
[CI/protocol](NATIVE-DIRECT-DIAGNOSTICS-SOURCE.md) ·
[Текущая установка](CURRENT-STREAM-DELIVERY.json) ·
[Актуальный реестр](../../operations/STATUS-REGISTRY.json).
