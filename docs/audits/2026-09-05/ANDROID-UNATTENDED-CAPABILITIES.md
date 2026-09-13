# Android без локального ADB: фактическая готовность

**13 сентября 2026 · AUD-102 · High · исправлено и принято на двух Android 9/API 28.**

[Аудит](AUDIT-REPORT.md) · [Локальный стенд](../../operations/LOCAL-PILOT.md) ·
[Подключение и резервные адреса](../../operations/READINESS.md)

## Что действительно независимо от станции

APK хранит свою регистрацию, получает подписанный discovery, открывает исходящий
HTTPS/WebSocket и выполняет команды через Android `su`. Windows, LDPlayer console
и внешний ADB не входят в этот runtime-путь. Устройство может находиться в другой
сети, если оно может достичь сервера. Наличие root само по себе не означает, что
root manager разрешил `su` именно UID приложения.

Windows NAT watchdog — отдельный ремонт конкретной виртуальной сети двух локальных
LDPlayer. Он не нужен физическому телефону и не заменяет восстановление связи APK.

## AUD-102: новый Android требует ручной кнопки для стрима

**Root cause.** `CommandDispatcher` открывал `ScreenCaptureRequestActivity`, которая
сразу запускала стандартный projection intent. `RootAutoStart.grantPermissions`
не настраивал `PROJECT_MEDIA`. Ранее выданное вручную разрешение скрывало дефект.

**Воспроизведение до fix.** На втором зарегистрированном Android 9/API 28 временно
сброшен только app-op нашего пакета в `default`. Через серверный Redis publisher
отправлен `start_stream` в уже существующий WebSocket APK. Пять проверок с интервалом
секунда: системный `MediaProjectionPermissionActivity` активен, projection отсутствует,
APK не выставила `allow`. PID не менялся. В `finally` диалог отменён и прежний app-op
восстановлен. ADB применялся для внесения fault/наблюдения/cleanup; команду APK
получила от сервера, не от ADB.

[Native before](evidence/native-projection-permission-before.json).

**Affected files / fix.** Новая `RootScreenCapturePermission` запускает внутри APK
ограниченный по времени `su -c`, меняет только свой package/user `PROJECT_MEDIA`
и проверяет реальный режим через `cmd appops get`. Работа идёт на IO dispatcher;
таймаут 8 секунд, временный диагностический файл удаляется, чтение ограничено 4 KiB.
`ScreenCaptureRequestActivity` ждёт подготовку, затем получает новый projection token
обычным Android intent. При недоступном/неразрешённом root сохраняется системный
consent flow. Повторное создание Activity не запускает второй запрос.

`android/version.properties`: следующий APK имеет **10201 / 1.2.1-dev**. Это важно
для OTA: несколько разных сборок с прежним одинаковым 10200 не считались обновлением.
Само повышение версии не публикует релиз на сервере.

**Regression tests.** `RootScreenCapturePermissionTest` вызывает настоящий production
helper с контролируемым процессом и настоящими временными файлами: свой package,
отдельный Android user, ложный exit 0, deny/default/unsupported, неуспех root,
таймаут с остановкой процесса, отсутствие su, недопустимый target, ограничение чтения.
8 tests pass; полная dev JVM suite: **523 tests / 38 suites, 0 failures/errors/skips**.
[JUnit summary](evidence/root-projection-full-summary.json). Signed dev и enterprise
builds проходят по 37 тестов: 19 discovery + 10 logger + 8 root permission.

**Native после fix.** APK `ce26a9e` установлена поверх старой на обоих устройствах
по одному через ADB; self-install OTA этим не проверялся. Автоматический возврат
команд от начала установки: 7.640 s (первый), 7.813 s (второй), прежние device IDs
и signed cache v8, без ручного запуска приложения/очистки данных/новой регистрации.
На каждом снова сброшен только `PROJECT_MEDIA` в `default`, затем сервер отправил
`start_stream`. APK сама выставила `allow`: во всех 5 наблюдениях на каждом
projection активен, системный dialog отсутствует, PID тот же. После теста серверный
`stop_stream` остановил projection; оба устройства выполнили ещё 12/12 команд,
API вернул настоящие 100-строчные журналы. ADB не выдавал разрешение в проверяемом
пути: только fault, read-only inspection и восстановление исходного app-op после теста.

[После — первый](evidence/native-projection-permission-after-index0.json) ·
[После — второй](evidence/native-projection-permission-after.json) ·
[Установка и команды](evidence/apk-projection-native-rollout-20260913.json) ·
[APK manifest](evidence/apk-ce26a9e-manifest.json).

Свежая local APK: `SphereAgent-signed-discovery-ce26a9e-dev-debug.apk`, 8,380,169 bytes,
SHA-256 `24ef116ed28777b94f43715e1f5ae326d25d4d04c579d14e7937139188d7a19d`.
`LATEST-SphereAgent-pilot.apk` переключён только после приёмки обоих устройств.

**Residual risk.** Проверка Android 9 не доказывает поведение всех OEM и Android 14+.
Обычный Android требует consent и новый token для каждой projection session;
приложение не переиспользует старый token.
[Официальный контракт MediaProjection](https://developer.android.com/media/grow/media-projection).
Этот fix не подтверждает ещё передачу/декодирование кадров в браузере.

## Открытые эксплуатационные блокеры

| Приоритет | Подтверждённое состояние | Следующая приёмка |
| --- | --- | --- |
| High | Streaming REST использует process-local `ConnectionManager` при четырёх workers. На online APK keyframe дал 14 HTTP 200 и 2 HTTP 404; обычные команды до/после прошли. Frame bridge и viewer lifecycle также локальные | Доставка control и кадров между разными workers, reconnect, stop и отсутствие фонового стрима без viewer |
| High | На pilot сервере **0 OTA-релизов**. `LATEST` на Windows не является публикацией в `/updates/`. Последние установки выполнены через ADB | Реальное скачивание и self-install APK из серверного релиза, автоматическое возвращение с тем же device ID без ADB |
| High | Каталог OTA по умолчанию `/tmp/sphere_updates.json`; durability и конкурентная публикация не подтверждены | Persistent catalog/artifact, повторная проверка после container replacement, ошибки загрузки и установки |
| High | Есть подписанные discovery/cache/mirror, но pilot имеет один временный ingress | Отказ независимого пути без потери обоих каналов; текущий резерв адресов не является отдельным живым сервером |
| High | VPN manager вызывает `wg-quick`; одного root недостаточно для наличия подходящего WireGuard backend | Native VPN на целевой Android-сборке, recovery, проверка сохранения канала управления |

[Native worker routing](evidence/stream-worker-routing-before.json).
Расписание `UpdateCheckWorker` — 6 часов при доступной сети, а не немедленная доставка
каждого изменения Git. Нельзя считать OTA рабочим только по наличию класса Worker.
Нельзя считать приложение независимым от всех ограничений Android только из-за root.

## Порядок дальнейшей проверки

1. Выполнено на двух Android 9: новый root permission flow после сброса app-op, без ручной кнопки. Другие версии/OEM и recreation Activity во время задержанного su требуют отдельной проверки.
2. Исправить межпроцессный путь стрима и проверить реальные кадры в viewer.
3. Опубликовать и принять OTA от скачивания до автоматического возврата APK; отдельно проверить сбои.
4. Проверить VPN и независимый резервный ingress на целевой конфигурации.
