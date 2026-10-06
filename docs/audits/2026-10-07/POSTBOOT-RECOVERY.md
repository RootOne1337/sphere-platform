# Возобновление разработки после ремонта C:

Дата: 7 октября 2026, Asia/Yekaterinburg. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Source baseline: `c6339b2897b60d2b4cf7a7d1f8ea2ac6bdbc1832`.

## Подтверждённое состояние

Windows загрузилась 7 октября в 00:42:12 UTC+5. Wininit event 1001,
record 134625, от 00:42:49 содержит завершённый ремонт: исправлены повреждённые
заголовки/bitmap индексов `$I30`, 21 файл возвращён в исходные каталоги.
Итог отчёта: исправления выполнены, дальнейшие действия не требуются.
`Get-Volume C:` после загрузки — **Healthy / OK**; повторный `git fsck --full
--no-dangling` прошёл. Прежний build/deploy gate `Full Repair Needed` снят.

Recovery-проверка сравнила 2707 отслеживаемых файлов HEAD: отсутствующих и
изменённых нет. Повреждённый blob `b687d557e4e8781ad7db9b5d6066c10c960517c9`
восстановлен из отдельно проверенного GitHub mirror; исходные плохие bytes
сохранены приватно. Файлы рабочего дерева этим не переписывались. Дата папки
в Проводнике не является свидетельством отката ветки.

Нулевой счётчик bad sectors в CHKDSK не доказывает исправность SSD/RAM.
Причина повторных повреждений и расхода диска **не установлена**. Результат
одного ремонта не закрывает [инцидент](../2026-10-06/HOST-FILESYSTEM-INCIDENT.md)
или storage-growth investigation. Global Python library ранее была повреждена;
ремонт NTFS сам по себе не подтверждает восстановление содержимого пакетов.

## Уже установленный веб

На `http://127.0.0.1:3015` установлен source
`99af20d9933e4f4f5f227595e19d2f47d5be7e94`, CI run
[37517925456](https://github.com/RootOne1337/sphere-platform/actions/runs/37517925456).
UI container стартовал 6 октября в 20:16:39 UTC / 7 октября в 01:16:39 UTC+5.
Подтверждены health, login200, exact Compose delta и сохранение всех остальных
**45 контейнеров**: ID, image, start epoch, status. OTA catalog SHA256 сохранён.
API остаётся `eb7a7c26`; APK не обновлялся этим действием.

| Идентичность | Значение |
| --- | --- |
| Config ID из проверенного CI | `sha256:0cacff12806aed75a5b40a77b2bc59598f1b585a25d5a9e44e99b5c5f39986f9` |
| Runtime manifest ID containerd | `sha256:f557f72ecf1347497dacd1c4e7a5baa074352042d74fea1109a33114edfb1d7b` |
| Архив gzip | 120839622 bytes |
| Остальные контейнеры | 45 сохранены |

Разные config/manifest IDs не допускаются простым отключением проверки.
Installer читает descriptor Docker, находит manifest в уже admitted archive,
проверяет SHA256 его фактических bytes и `config.digest`, равный независимому
CI config ID. Неизвестный descriptor, отсутствующий/подменённый manifest,
неверный config и некорректные JSON shapes отклоняются. Classic config ID
также поддержан. Subprocess output явно декодируется UTF-8 на Windows.
Основание формата: [OCI manifest/config descriptor](https://github.com/opencontainers/image-spec/blob/main/manifest.md)
и [Docker containerd store](https://docs.docker.com/desktop/features/containerd/).

Private receipts: `.local-pilot/reboot-recovery-20261007/` и
`.local-pilot/reviewed-web-install-99af20d9933e-358eb30c/installed.json`.
В репозиторий не включаются raw host events, credentials или Codex history.

## Проверки возобновления

Exact baseline `c6339b2`: Frontend run37519311772, Backend37519311710,
Android37519311735 завершились success. Preview37519311722 success не означает
production deploy. CI выводы относятся именно к этому SHA.

Installer/archive suite: **22 unittest methods passed**, scoped Ruff passed.
Это реальные новые negative boundaries, а не тесты строк CSS.
В установленном authenticated UI проверены отдельный sleep-узел, переназначение
цели существующей связи, разрыв и Undo: счётчики графа и JSON сохраняют результат.
Обнаружен новый visual defect: при ширине 637 поле названия сжимается до 68px.
Исправление компоновки проходит отдельную сборку и responsive browser acceptance.
Recorder/continuous input/frame correlation не объявляются принятыми этими
операциями; общий product ledger **9 accepted / 41 open** пока сохранён.
