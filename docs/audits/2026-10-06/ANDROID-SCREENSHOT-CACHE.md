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
не отменяет count budget. Android OS eviction cache также возможен.

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

## Доставка и установленный canary — 6 октября, 14:32–14:48 UTC

Source **`3493eb68d05a1f37ed704c96f6d300b9772bc8c5`**. Candidate
**1.2.47-dev / 10247**, package `com.sphereplatform.agent.pilot.debug`,
**8 484 947 B**, SHA256
`7481ca620f4cbea60807121ad5f00f1bb3e1cb9dc12098980346acfd527a8c69`.
186 tracked Android файлов сверены с Git source; APK ZIP CRC и headers/checksums
всех 15 DEX прошли. Pilot signer совпал с предыдущим установленным APK.
Сохраняются debug video probe, planar-input и отключённый GPU bridge этого pilot;
это не релизная приёмка стрима или production OTA.

| Проверка | Подтверждённый результат |
| --- | --- |
| Полные локальные suites | DevDebug и EnterpriseDebug: **872 total / 869 passed / 3 skipped** каждый; 0 failures/errors. Два skips — Windows symlink fixtures, один — прежний config assumption |
| Source CI | Backend, Frontend, Android и Preview для **3493eb6** success. Preview deployment skipped; release signing smoke использует одноразовый CI key |
| Linux JUnit | Из artifact Android run **37478519344** прочитаны XML четырёх flavors/debug-release: по **872 total / 871 passed / 1 skipped**; все 16 screenshot cases, включая обе symlink ветки, passed |
| Установка | Только local **auto-ph-011**, SDK28 / root, device ID `414ce0e9-4b93-4f96-b9ca-ee675f53835e`; одно `install -r`, **10246 → 10247**, heartbeat новой версии |
| Сохранность | UID **10082**, preference файлы до явного старта и device ID сохранены; перед обновлением stopped-package APK/data backup сохранён privately; остальные 18 version codes и каталог из 19 устройств сохранены |
| Saved-version task | Один сценарий `0b06caa1-f1fd-4942-955a-1e4b55dab288`, v1 `37d7173d-b9b1-4daa-8078-c1593dfe838f`, один task **`b1d67f65-f7b9-4859-906a-77513017acfc`**, **completed 14/14**; retry всех узлов 0 |
| Native retention | Десять последовательных screenshot узлов; после завершения **ровно 8 PNG / 1 880 304 B**. Первые два пути отсутствуют, последние восемь присутствуют, staging не найден |
| Original PNG | Последний снимок **960×540 / 235 038 B**, Android SHA256 совпал со скачанным оригиналом, пиксели не перекодированы |
| Native browser | Реальная страница task на 3015, **1280×900** и narrow screenshot; desktop document overflow отсутствует, 0 captured warnings/errors, viewport восстановлен. Задание повторно не запускалось |
| Runtime boundary | UI **1c26ffc7** / API **eb7a7c26**, backend/frontend/OTA/туннели этим этапом не обновлялись; remote PH025 остаётся на **1.2.45-dev** |

DAG SHA256:
`883c8374bb0b95c3519c170ad81809d8b66825f1a0b8d2857c6fadcaab5bb6d1`.
Original PNG SHA256:
`1e69731a96544c0508552371e84e5e0fa1cccbb1c3f0b61086d4133476f61ade`.
Handler durations десяти screenshot nodes: **279, 153, 186, 207, 176, 165, 162,
155, 155, 154 ms**. Это длительности handlers одного локального теста, **не FPS,
input-to-frame latency, p95 или удалённый SLA**. Четыре CI варианта выполняют
пересекающиеся cases; их нельзя складывать как 3488 уникальных тестов.

Ordinary `adb pull` private path отказал ожидаемо. Task уже завершился и повторно
не создавался: исходный PNG сохранён через адресную временную root-копию,
SHA256 сверён с оригиналом, только этот временный transport path удалён.
Восемь PNG в Android cache оставлены для наблюдения retention. Это **ручное
получение evidence**, а не доставка server task artifact.

Серверный manifest задания по-прежнему пуст, `screenshot_key` отсутствует;
каждый output явно указывает **`server_artifact_available=false`**. Приватный
cache path не доступен обычному веб-клиенту и может быть удалён при следующем
захвате/OS eviction. Отдельный upload/lifecycle остаётся P1. Remote rollout,
другие SDK и длительный soak также не приняты. EP-016 остаётся следующим этапом.

[Manifest receipts и assets](ANDROID-SCREENSHOT-CACHE-EVIDENCE.json) ·
[Linux JUnit summary](evidence/android-screenshot-cache/linux-junit.json) ·
[Canary DAG и reports](evidence/android-screenshot-cache/task-canary.json) ·
[Оригинальный PNG](assets/android-screenshot-cache/last-capture-original.png) ·
[Реальная карточка задания](assets/android-screenshot-cache/task-local-receipt.jpg).

Offline проверка evidence: `python -m scripts.audit.validate_android_screenshot_cache`.
Raw APK, package backup, preferences, credential файлы и полный CI artifact в Git
не публикуются. Source hashes закреплены за 3493eb6; manifest этого среза не
переносит source CI на следующий документационный head.
