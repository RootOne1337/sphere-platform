# OTA: обрыв загрузки и параллельные обновления

**13 сентября 2026 · AUD-107 · High operational · native до/после, OTA на двух Android и повторный reboot приняты.**

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

Из каталога `android` (Windows: `gradlew.bat`):

```sh
./gradlew :app:testDevDebugUnitTest --tests com.sphereplatform.agent.ota.OtaUpdateServiceRecoveryTest
```

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

Оба устройства уже на **1.2.4-dev / 10204**, source **`fdd26c5`**. Размер
**8,385,905 bytes**; SHA-256
`db3f9111e3e59c2871b042e07a81bb86d123c686bd40e27e8b2ec3b5f0902add`.
V2 подпись проверена, сертификат/package совпадают с предыдущей APK. Signed dev
и enterprise проходят **по 70 selected tests**, включая все девять OTA cases.

1. Второй Android сам скачал и установил 10203 → 10204 через сервер/HTTPS/свой su.
   Команда вернулась за **10.266 s**; при старте удалились оба полных старых APK
   и файл baseline-обрыва. Каталог `ota` пуст.
2. Повторён тот же native truncated-body fault на 10204: ошибка с command_id
   видна в APK journal; **файлов после ошибки нет**, PID сохранён и оба устройства
   отвечают. Исходная конфигурация gateway восстановлена, test container удалён.
3. Следом отправлены **две OTA-команды с разными IDs**, одной версией/проверенным
   SHA. Redis receipt channels подтверждают `received` и `running` от APK для
   обеих команд; в её журнале **один** `OTA: starting update` с уникальной меткой.
   Только одна загрузка/передача установщику прошла до self-replacement; новый
   процесс отвечает через **10.453 s**, installed SHA совпадает, staging пуст.
   Это также native retry после обрыва. Ожидающая coroutine исчезла со старым
   процессом; durable exactly-once или завершённый ACK для обеих команд этим
   **не подтверждается**.
4. После canary опубликован обычный **android/dev 10204**. Первый Android сам
   обновился и вернулся за **9.844 s**, второй продолжал работу. Canary удалён;
   прежний android/dev 10203 сохранён, всего в каталоге **два release**.
5. Reboot второго уже на 10204: Android сам запускает `BootRecoveryJobService`,
   команда проходит за **21.094 s**. App-launch/UI действий нет, Windows station
   watchdog отключён на время reboot/установок и восстановлен. Device IDs,
   signed cache v9 и APK hash сохранены; новых регистраций нет.
6. Финально **12/12 команд**, оба реальных журнала, installed SHA и пустые staging
   проверены. WorkManager DB read-only: ENQUEUED, interval 6 h / backoff 30 s на
   обоих устройствах. `/latest` с 10203 предлагает 10204 на текущем HTTPS host;
   с 10204 возвращает отсутствие обновления. Девять сервисов healthy; старая
   Sphere installation сохраняет IDs/images/states/mounts.

[Полные native evidence](evidence/apk-ota-recovery-native-20260913.json) ·
[Artifact manifest](evidence/apk-fdd26c5-manifest.json).
LATEST продвинут только после этой приёмки. Коммит исходников сам по себе не
публикует обновление; полный естественный шестичасовой период не выжидался.

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

Точный source CI head [fdd26c5](evidence/ci-fdd26c5-summary.json) зелёный:
backend, Android, frontend, lint/security/RLS и image bootstrap. Последующий
commit документации проверяется отдельно; статус виден в PR.
