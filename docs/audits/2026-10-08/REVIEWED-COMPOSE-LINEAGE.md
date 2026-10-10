# Reviewed delivery: ограниченная цепочка Compose

8 октября 2026, Asia/Yekaterinburg. При планировании UI source9610523 installer
отказал `Unexpected Compose inventory`: установленный e88c4db имел17 различных
файлов в `com.docker.compose.project.config_files`; старый guard допускал16.
Каждая предыдущая image-only установка добавляла ещё один override к цепочке.
Это воспроизведённый дефект дальнейшей доставки, не причина роста Docker VHDX.
Backend в том же срезе имел10 разных Compose files.

## Изменение

Оба installer сохраняют полный разрешённый Compose model в один приватный
`baseline.json`. Compose читает его повторно; строгое сравнение **всего** model
с исходным обязательно до загрузки образа и замены контейнера. Только после
этого добавляется один image/build-removal override и выполняется прежний
полный delta check. Новая установленная цепочка имеет2 файла; последующее
обновление снова использует baseline + один override, а не накапливает их.

Имена старых файлов ограничены64, должны быть непустыми/уникальными и пройти
прежние path/symlink/private-scope guards. Увеличение допуска служит чтению
существующей исторической цепочки; installed candidate снова имеет2 файла.
Приватный baseline ограничен256KiB, содержит те же resolved environment values
и не выводится в terminal/PR/report summary. Нельзя публиковать baseline:
он может содержать секреты существующей конфигурации.

Environment strings с `$` экранируются перед повторным чтением. Resolved
`command`, `entrypoint`, `healthcheck.test` в Compose JSON сохраняют собственное
`$$` escaping; его нельзя удваивать. Первый реальный roundtrip выявил именно
такую разницу в gateway entrypoint, и guard остановил операцию. После исправления
повторное чтение совпало полностью. Не сравниваются только выбранные поля;
любое отличие любого сервиса, сети, mount, env или команды блокирует установку.

Исходная цепочка сохранена для прежнего rollback. Image source/CI attempt,
independent digest admission, schema/OTA, resource checks, container inventory
и запрет restart зависимостей остаются обязательными. Baseline не является
новым deployment secret store или backup независимого диска.

## Проверки

До реализации2 новых freeze tests failed, остальные11 UI installer cases passed.
После:31 UI/backend installer tests passed; Ruff passed. Проверены literal
dollars, сохранение shell/healthcheck escaping, отказ любого model difference,
неизменённые host-volume guards, image admission/rollback/остальные контейнеры.

Read-only план source9610523 на реальном Docker прошёл:17→2 UI Compose files,
`completeBaselineRoundtripVerified=true`, resourceFindings пуст, runtimeInstalled
false. Установка и readback фиксируются в отдельной installed acceptance.

Этот operational fix не меняет приложение/APK, не запускает миграции, не удаляет
исторические images/volumes/Compose files, не закрывает storage/Git incidents.

## Installed readback, 06:55 UTC

UI and API9610523 are healthy on3015. Full reviewed install and finite PH011
native-busy/retry/READY evidence are recorded in
[installed acceptance](UI-INSPECTION-INSTALLED-ACCEPTANCE.md).
