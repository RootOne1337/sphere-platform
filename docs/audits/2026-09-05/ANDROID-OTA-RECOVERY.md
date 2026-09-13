# OTA: обрыв загрузки и параллельные обновления

**13 сентября 2026 · AUD-107 · High operational · source fix и JVM regression приняты; новая APK проходит native-приёмку.**

[Аудит](AUDIT-REPORT.md) · [Доставка OTA](ANDROID-OTA-DELIVERY.md) · [Текущая APK](../../operations/LOCAL-PILOT.md#apk-именно-для-нового-стенда)

## Подтверждённые причины

| Severity | Trigger и результат до исправления | Root cause |
|---|---|---|
| High operational | Periodic worker и WS-команда обновляют одну версию одновременно. Вторая попытка пишет/удаляет входной файл первой установки; тест получает FileNotFoundException. | Один `update_<version>.apk`, нет взаимного исключения между двумя production callers. |
| Medium operational | Сеть обрывается после начала ответа: staging-файл остаётся. | `downloadApk()` выполняется до try/finally; исключение обходит удаление. |
| Medium operational | Coroutine отменена, а HTTP body продолжает загружаться. | Блокирующий OkHttp Call не связан с отменой; тест не может завершить job за 1.5 s. |
| Medium operational | Успешная самообнова оставляет предыдущий APK. | Android заменяет процесс до выполнения finally; нет очистки при следующем старте. |

Перед исправлением оба настоящих Android содержали `update_1.2.3-dev.apk`
по **8,383,485 bytes**. Дополнительный native fault на втором устройстве: APK
через свой текущий HTTPS ingress получил ответ от изолированного тестового
сервиса, который объявил 1 MiB, отправил 64 KiB и закрыл соединение. Ошибка
записана с command_id, процесс и команды обоих устройств сохранились. Остался
`update_AUD107-before.apk` размером **0 bytes**: данные не дошли до записи файла
через реальную цепочку прокси, но staging был создан и не удалён. Полный старый
APK также остался. Тестовый URL и контейнер удалены, исходный gateway config
восстановлен с проверкой SHA и `nginx -t`/reload. Старый Docker не изменялся.

## Минимальный fix

`OtaUpdateService` остаётся Hilt singleton в единственном процессе агента.
Mutex сериализует download → checksum → передачу установщику → cleanup.
Каждая попытка получает локально созданный уникальный staging-файл; строка
версии больше не формирует путь. Try/finally охватывает и загрузку. Весь
путь выполняется на IO dispatcher; дочерняя coroutine отменяет OkHttp Call,
чтобы закрыть socket и дождаться закрытия writer до удаления файла. Проверки
отмены также выполняются при чтении/hash и перед вызовом установщика.

При создании сервиса удаляются только его `ota/update_*.apk`, без обхода других
каталогов. Это убирает файлы, оставшиеся после SIGKILL/self-replacement, когда
finally выполнить невозможно. Ошибка startup cleanup журналируется и не мешает
поднять управление устройством. Root/PackageInstaller механизмы не менялись.

Affected files:

- `android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt`
- `android/app/src/test/kotlin/com/sphereplatform/agent/ota/OtaUpdateServiceRecoveryTest.kt`
- `android/version.properties`: кандидат **10204 / 1.2.4**.

## Regression и воспроизведение

`cd android`, затем `./gradlew :app:testDevDebugUnitTest --tests
com.sphereplatform.agent.ota.OtaUpdateServiceRecoveryTest` (Windows: `gradlew.bat`).
Тест вызывает production service, настоящий OkHttp, чтение/запись файлов и
SHA-256. Подменена только граница Android installer. Cancellation использует
настоящий loopback TCP server с медленным body; другие fixtures — OkHttp
responses и источник, выбрасывающий IOException после первого блока.

До fix: **9 cases, 5 failures** — четыре эксплуатационных сценария и отдельный
новый контракт «version label не выбирает имя файла». Последний не считается
дополнительной уязвимостью. После: **9/9**, полный dev JVM suite **556 tests /
41 suites / zero failures, errors, skips**. Дополнительно проходят checksum
mismatch, HTTP 503, oversized Content-Length и retry после installer failure.
[Машиночитаемые evidence](evidence/android-ota-recovery-summary.json).

## Текущая приёмка и границы

Работающие устройства пока остаются на принятой 1.2.3; LATEST не меняется до
проверки нового подписанного кандидата, доставки с сервера и повторения native
fault. Коммит исходников сам по себе не публикует обновление.

- Mutex охватывает передачу APK установщику. Асинхронный PackageInstaller
  fallback после commit всё ещё требует отдельного persistent session tracking;
  эти тесты не доказывают единственную завершённую установку на любом non-root ROM.
- Serial execution не является durable dedup/replay policy между перезапусками.
  Pending command IDs, package/signing/version compatibility и fleet rollout
  остаются отдельными gates. Во время уже начатого `pm install` отмена не означает
  rollback; прежний 120 s timeout остаётся.
- Очистка после падения выполняется при следующем создании сервиса. Невозможность
  освободить файл из-за ошибки файловой системы видна в журнале; гарантии удаления
  при мёртвом процессе или неисправном storage нет.
- Два rooted Android 9 не заменяют нагрузку сотен устройств, проверку иных Android
  и полный естественный шестичасовой цикл WorkManager.

Предыдущий точный CI head [5c6d3af](evidence/ci-5c6d3af-summary.json) зелёный.
Он не заменяет отдельную проверку нового commit.
