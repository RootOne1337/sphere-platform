# Самостоятельный запуск APK после загрузки Android

**13 сентября 2026 · AUD-103 · Critical operational · исправлено и принято
на двух Android 9/API 28.**

[Аудит](AUDIT-REPORT.md) · [Автономность APK](ANDROID-UNATTENDED-CAPABILITIES.md) ·
[Стенд](../../operations/LOCAL-PILOT.md)

## Реальный отказ

Уже зарегистрированная APK `ce26a9e` / 1.2.1-dev была перезагружена вместе с Android
второго эмулятора. Windows NAT watchdog временно отключён и остановлен только на
время проверки; никаких `am start`, LDPlayer runapp или ручных нажатий в проверяемом
интервале не выполнялось. Первый Android продолжал отвечать на каждую команду.

Новый Linux boot ID и `sys.boot_completed=1` появились через 16.968 s. Однако
весь 240-секундный интервал APK не имела процесса и возвращала HTTP 503 на команды.
В конце теста Windows watchdog восстановлен. Только **после завершения отрицательной
приёмки** приложение запущено одной адресной ADB/root-командой для восстановления
рабочего состояния. Это не считается успешным автозапуском.

[Native before](evidence/android-boot-before-20260913.json) ·
[Состояние package и boot](evidence/android-boot-diagnostics-20260913.json).

## Root cause

1. APK имеет разрешение `RECEIVE_BOOT_COMPLETED`, receiver включён, пакет не stopped,
   не suspended и уже запускался. Это проверено в реально установленном package.
2. В установленном Android 9 присутствует модификация `BroadcastQueue`: для обычных
   приложений отфильтровываются неадресные системные broadcast-запуски. Проверка
   сделана через штатный `oatdump` установленного `services.odex`; ни образ, ни
   системные свойства для обхода фильтра не менялись. Receiver доступен в
   `cmd package query-receivers`, но процесс не запускается при настоящем boot.
3. WorkManager хранит расписание в своей SQLite, но его native jobs не имеют
   `setPersisted(true)`. Их восстановление после reboot зависит от
   `RescheduleReceiver` с тем же boot broadcast. После неудачного reboot в
   JobScheduler не было задач этого package. Комментарий в `SphereApp`, обещавший
   независимость WorkManager от boot broadcast/stopped state, был неверным.
4. Shell watchdog живёт только до reboot. Попытки прежнего `RootAutoStart` записать
   `/system/etc/init/sphere_autostart.rc` и установить APK как system app здесь
   не дали результата: файла нет, у APK нет system flag. Наличие файлов в
   `/data/local` или `/data/adb/service.d` само по себе не означает наличие их boot-loader.

[Хеши и метод проверки firmware](evidence/android-boot-policy-20260913.json).
Сырые vendor binaries и полный disassembly не включены в репозиторий.

## Минимальный fix

`BootRecoveryJobService` регистрирует отдельный native JobScheduler job с
`setPersisted(true)`, без зависимости от сети, зарядки, WorkManager или внешней станции.
Android хранит его и восстанавливает самостоятельно. `SphereApp` регистрирует этот
путь до необязательных WorkManager workers. Не требуется делать APK системной,
перезаписывать firmware или менять глобальную boot-политику.

Это короткое one-shot задание: целевые minimum latency / deadline — 60 / 90 секунд.
Сначала оно сохраняет следующую попытку, затем просит запуск зарегистрированного
агента либо enrollment. Два чередующихся ID позволяют не отменять выполняющийся
job при сохранении следующего. Повторная инициализация сохраняет прежний deadline;
чужой service в зарезервированном ID не заменяется. Ошибка сохранения следующего
задания приводит к OS retry текущего. В job нет цикла ожидания, сетевых запросов,
выдачи root-команд или запуска Activity.

Affected files: Android manifest, `SphereApp`, комментарии `BootReceiver`, новый
`service/BootRecoveryJobService.kt` и версия Android **10202 / 1.2.2**.

## Regression tests и приёмка

`BootRecoveryJobServiceTest` использует production scheduler/service с настоящим
`JobInfo` и Robolectric JobScheduler: persistence, deadlines, отсутствие сетевых
constraints, idempotent schedule, смена job ID, отказ запуска службы, enrollment,
ошибка/отказ планировщика, сохранение чужого job и OS retry. **10 tests pass**;
полная dev JVM suite: **533 tests / 39 suites, 0 failures/errors/skips**.
[JUnit summary](evidence/android-boot-full-summary.json).

APK **`8d93e48`, 1.2.2-dev / 10202** установлена поверх прежней на оба Android.
В каждом reboot drill Windows NAT task отключена и восстановлена в `finally`.
Никаких app-launch команд или ручных UI действий в проверяемом интервале нет.

| Проверка | До fix | После fix |
| --- | --- | --- |
| Reboot второго Android | Нет процесса/команд весь интервал 240 s | Команда через **20.859 s** |
| Reboot первого Android | Отдельный before не проводился | Команда через **25.375 s** |
| SIGKILL второго APK | Отдельный before не проводился | Новый процесс и команда через **5.453 s**, boot ID прежний |

В обоих reboot Android `am_proc_start` прямо указывает причиной запуска
`BootRecoveryJobService`; production log подтверждает выполнение persisted job.
Job сохраняется после восстановления, Setup Activity не открывается. При SIGKILL
Android перезапустил `SphereAgentService`; это отдельный service recovery path.
Другой APK продолжает отвечать, его PID неизменен. Device IDs, signed cache v9 и
установленный SHA сохранены, новых регистраций нет. Затем **12/12 команд** и
настоящие 100-строчные журналы обоих устройств прошли через сервер.

[Native trials и rollout](evidence/apk-boot-native-rollout-20260913.json) ·
[Artifact manifest](evidence/apk-8d93e48-manifest.json) ·
[Все CI checks исходного fix успешны](evidence/ci-8d93e48-summary.json).

Обновление на этом этапе выполнено через ADB для контролируемой приёмки;
это не OTA. Локальный `LATEST-SphereAgent-pilot.apk` переведён на новый файл
только после native checks. Измеренные секунды относятся к двум конкретным
эмуляторам и включают Android boot и первую настоящую серверную команду.

## Residual risk

- JobScheduler execution зависит от Android: idle, quotas, user unlock и OEM
  поведение. Deadline 90 s не является SLA и не отменяет ограничения ОС.
- APK должна быть установлена и хотя бы раз запущена для регистрации задания.
  Свежий never-launched пакет или явный административный force-stop — отдельные
  состояния Android; обещания автономного выхода из любого такого состояния нет.
- Native acceptance на Android 9 не подтверждает все физические телефоны.
  В частности, Android 15 ограничивает запуск `dataSync` FGS из boot receiver и
  его суточное время; это отдельный открытый compatibility gate.
- Самозапуск не обеспечивает сеть и не заменяет работающий сервер/независимый
  ingress. На момент подготовки теста обе старые APK уже приняли discovery v9
  после смены адреса сервера; сохранённый local helper URL был устаревшим.
- OTA self-install, межпроцессная маршрутизация кадров, VPN и fleet capacity
  остаются отдельными открытыми задачами.

Официальные контракты:
[JobInfo.Builder](https://developer.android.com/reference/android/app/job/JobInfo.Builder) ·
[Android 15 foreground-service changes](https://developer.android.com/about/versions/15/behavior-changes-15).
