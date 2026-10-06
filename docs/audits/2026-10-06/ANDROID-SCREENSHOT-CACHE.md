# Android screenshot: подтверждение захвата и ограниченное локальное хранение

**Дата:** 6 октября 2026. **Версия исходников:** 1.2.47 / 10247.
**Область:** DAG `screenshot`, Lua `screenshot()` и command `SCREENSHOT` используют
один `AdbActionExecutor.takeScreenshot`. Доставка task artifacts не реализована
этим изменением. Установленный canary 1.2.46 сохраняется как отдельный этап.

[Подтверждённый runtime дефект](ANDROID-CLEAR-INSTALLED.md) ·
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Приоритеты](ENTERPRISE-PRIORITIES.md) · [Script Studio](../../operations/SCRIPT-STUDIO.md).

## Причина изменения

Реальный 25-node сценарий PH011 сохранил PNG на Android, но не прислал artifact key.
Старый helper создавал новый `/sdcard/sphere_screenshot_<time>.png`, отправлял root
команду без ACK и ждал 300 ms. Длительность не доказывала готовность файла.
Ни count, ни size, ни age retention не было; повторные вызовы могли накапливать PNG.

Это конкретный producer growth path на Android. Долговременная скорость его роста
не измерялась. Причина расхода Windows C:, Docker VHD и host memory остаётся UNKNOWN.
Исторические `/sdcard` файлы не удаляются этим исправлением; миграция требует
отдельного inventory и решения по сохранности.

## Новый контракт

1. PNG пишется в `cacheDir/dag-screenshots-v1/pending-<UUID>.png`. Файл заранее
   создаёт само приложение, поэтому root запись не создаёт недоступный ему owner.
   Ни разрешение, ни DPI metadata, ни пиксели не изменяются/перекодируются.
2. Screencap идёт в прежней FIFO root-сессии после ранее отправленных input команд.
   Уникальный shell marker подтверждает exit status. ACK: 5 s deadline, суммарный
   stdout/stderr drain до 256 KiB, retained tail до 128 chars; новых reader threads нет.
3. После ACK проверяются size, PNG signature, IHDR/depth/color/dimensions, chunk
   boundaries/CRC и точный IEND. Pixels не декодируются; это проверка контейнера,
   не независимое доказательство корректности deflate/pixel content или цвета.
   Проверка потоковая с 8 KiB chunk buffer. Затем файл переименовывается в
   `capture-<UUID>.png`; только после этого возвращается путь.
4. Снимки одного singleton executor сериализованы mutex. Две одновременные команды
   не публикуют один staging path и не подменяют capture другого запроса.
5. Сохраняется максимум **8 committed PNG**, каждый до **5 MiB**, то есть до
   **40 MiB committed bytes**. Перед новым захватом освобождается один slot.
   Старые файлы возрастом **30 min** и orphan staging удаляются при следующем
   захвате. Это access-triggered retention, не фоновая очистка ровно в 30 min.
6. Нативный screencap может временно записать больше 5 MiB до завершения/проверки.
   Такой output отклоняется и удаляется. 40 MiB — лимит committed cache, а не
   hard filesystem quota всего каталога во время работы стороннего producer.
7. Unknown ACK/cancellation инвалидирует root ownership без replay. Неполный,
   повреждённый или слишком большой PNG не выдаёт успешный путь. Собственный
   staging и неуспешный publication убираются в `finally`.

## Границы удаления и совместимость

Prune касается только строго UUID-shaped `pending-*.png` / `capture-*.png` в
собственном каталоге. Чужие имена сохраняются. Symlink, смена canonical directory
и каталог вместо file приводят к отказу; recursive deletion нет. Clock reversal
не отменяет count budget. Windows OS eviction cache также возможен.

`takeScreenshot(): String` и Lua return type сохраняются. Путь теперь private cache,
его нельзя считать вечным файлом `/sdcard` или обещанием веб-доставки. Старые ссылки
в переменных могут стать недоступными после eviction/30 min/следующего capture.
Для долгоживущего результата нужен отдельный task-scoped object-storage transport.
Command/DAG receipt добавляет `format=png`, `storage=android-local-cache` и
`server_artifact_available=false`; `screenshot_key` не выдумывается.

## Проверки и дальнейшая приёмка

Перед source commit focused Dev run: **110 total / 108 passed / 2 skipped**,
5 suites, 0 failures/errors. Результаты двух предыдущих локальных падений относились
к невозможности создать Windows symlink fixtures; production capture/retention
assertions не падали. После явного assumption guard и финальных PNG header checks
набор выполнен заново. Новые 16 screenshot/store cases входят в этот набор.

Focused tests охватывают count/age/size, byte preservation, CRC/truncation/trailing
payload, dimension/depth checks, clock reversal, exception/cancellation/concurrency,
FIFO ACK/nonzero/missing file и границы удаления. Windows не разрешает создание
symlink в текущей тестовой сессии: два filesystem fixtures должны выполняться в
Ubuntu Android CI; локальный skip не считается доказательством этих веток.
Нерекурсивное сохранение owned-looking directory дополнительно проверяется локально.

Для кандидата нужны оба полных debug-flavor suites, ZIP/DEX/signer checks и
реальная проверка через установленный агент. Delivery receipt добавляется отдельным
датированным разделом после исполнения; этот source contract не означает rollout.
EP-019/020 остаются открытыми по upload, artifact lifecycle, reconnect/unknown
reconciliation и agent-correlated replay. EP-016 schemas/preflight остаётся следующим
самостоятельным этапом. Общий счёт **9 принято / 41 с открытыми критериями**.
