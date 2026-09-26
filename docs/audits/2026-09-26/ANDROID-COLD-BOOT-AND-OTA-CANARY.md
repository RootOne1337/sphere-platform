# Android boot и адресная OTA: контрольная приёмка 26 сентября 2026

**Область:** изолированный `sphere-pilot-20260911`, два локальных Android 9 LDPlayer
и один удалённый canary `auto-ph-025`. Legacy Compose-проекты не менялись.
Это операционная приёмка конкретных экземпляров, а не гарантия для любого Android.

## Что означало наблюдение оператора

Оператор вручную открывал APK после включения эмулятора. Поэтому прежний факт
`online` не доказывал автономный запуск. Кроме того, отсутствие на экране Activity
Sphere не равно отсутствию фонового агента: при штатном boot агент должен поднять
foreground service и подключиться, не перекрывая игру экраном настройки.

## Полное OFF/ON без ручного запуска APK

Для каждого локального canary LDPlayer остановлен командой `quit`, затем запущен
`launch`. Между ними и серверным heartbeat **не выполнялись** `runapp`, `am start`,
ADB install или ручное открытие Activity. Проверены новый Android boot ID,
`sys.boot_completed`, новый PID APK, причина старта процесса в Android,
`BootRecoveryJobService`, foreground service, версия PackageManager, серверный
heartbeat и crash buffer. Второй эмулятор оставался работающим контролем.
Сырые локальные следы находятся в ignored `.local-pilot/rollout-10228/`.

| Canary | Установленная версия | Наблюдение после нового boot ID | Вердикт |
| --- | --- | --- | --- |
| `emulator-5554` / `auto-ph-011` | `1.2.28-dev / 10228` | Android boot completed `18:03:50Z`; новый процесс от persisted job; API `online` со свежим heartbeat `18:03:56Z`, foreground service; новый crash Sphere отсутствует | **PASS** для этого экземпляра |
| `emulator-5556` / `auto-ph-010` | `1.2.27-dev / 10227` | Android boot completed `18:05:10Z`; новый процесс от persisted job; API `online` со свежим heartbeat `18:05:13Z`, foreground service; новый crash Sphere отсутствует | **PASS** для этого экземпляра |
| `emulator-5556` после адресной OTA | `1.2.28-dev / 10228` | Android boot completed `18:27:59Z`; persisted job запустил APK, PID `3244`, foreground service; сервер зафиксировал auth и первый heartbeat `18:28:14Z`; Redis позже подтвердил `online`/10228 | **Runtime boot подтверждён; тестовый harness помечен failed из-за HTTP 429 на повторных admin login** |

Последняя строка сознательно не помечена `harness PASS`: скрипт опрашивал
авторизованный API новым login каждые три секунды и достиг лимита 429. Независимые
Android и backend/Redis доказательства показывают автономный запуск примерно через
15 секунд после завершения загрузки Android; ошибка harness не является crash APK.
Для будущего soak harness должен переиспользовать токен или читать Redis через
контролируемый read-only probe.

Ограничение: установленная APK должна хотя бы раз запуститься для регистрации
persisted job. Never-launched, административно force-stopped пакет, OEM-политики
и Android 14+ требуют отдельных тестов. См. [первоначальный root cause и fix](../2026-09-05/ANDROID-BOOT-RECOVERY.md).

## OTA: локальный успех и удалённый отказ

Артефакт `1.2.28-dev / 10228`, SHA-256
`15abeee280bf743e67e544ed94b36575590557c3353d73e911d1279ab2946ce9`,
имеет тот же pilot debug signer, что прежние локальные установки. Лишь локальный
`emulator-5554` получил его через ADB для canary. На `emulator-5556` **адресная OTA
без ADB install** обновила 10227 → 10228: PID сменился, PackageManager и hash
установленного `base.apk` совпали с артефактом, затем пришёл новый authenticated
heartbeat. В pilot-каталоге опубликован только канал `android-canary/dev`;
обычный `android/dev` при проверке всё ещё указывал на 10209. Это не массовый
релиз и не публикация в GitHub Releases.

Удалённый `auto-ph-025` оставался на `1.2.22-dev / 10222`. Первая адресная OTA
вернула клиентский `failed` **до скачивания**. Сохранённый в APK активный адрес
управления был резервным LocalTunnel, а URL артефакта указывал на подписанный
основной Cloudflare. `OtaUpdateService.validateDownloadUrl()` разрешал только
host активного адреса; клиентский журнал зафиксировал исключение `SSRF protection:
download host != server host`. Корень доказан по установленному старому APK и
исходнику; это не доказательство, что Cloudflare не передаёт APK.

Адресная команда `UPDATE_CONFIG` для одного PH025 получила `completed/updated`
и сохранила основной и резервный адреса. После неё вторая OTA-публикация вернула
лишь `subscribers > 0`; **за 240 секунд не пришли ни новая версия, ни квитанция
второй команды**. Запрос журнала этого же `online` устройства через API также
вернул 504. Backend фиксировал повторяющиеся обрывы WebSocket `1005` примерно
через 40–60 секунд и повтор старой `failed` OTA-квитанции. Это доказывает
ненадёжный control path на этом remote canary, но не локализует его единственную
причину до конкретного tunnel provider. `Redis PUBLISH` с подписчиком не означает
доставку Android; после этих двух контролируемых попыток команда не повторялась.

## Source fix и регрессионный сценарий

**P1 · OTA при переключении доверенного маршрута, fix `20481c0`.** В
`android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt`
валидация теперь сравнивает HTTPS `scheme + host + port` URL загрузки со всеми
сохранёнными management routes, включая основной и резервный. Bearer token не
отправляется постороннему origin, другому порту, HTTP URL или URL с userinfo.
В `OtaUpdateServiceRecoveryTest` настоящий `performUpdate` с тестовым HTTP client
воспроизводит fallback→primary и проверяет, что запрещённые URL отвергаются до
сетевого вызова. **До fix два теста падали**: доверенный primary отклонялся, чужой
порт проходил. После fix прошли обе полные JVM suites: **680 тестов на flavor,
0 failures/errors, 1 skipped**; `lintDevDebug`, `assembleDevDebug` и
`assembleEnterpriseDebug` также прошли. Версия исходника поднята до
`1.2.29 / 10229`, чтобы OTA могла отличить его от 10228. Зелёные JVM/build checks
не означают, что этот APK уже установлен на удалённом Android.

## Rollout gate и остаточный риск

- **NO-GO для remote/mass OTA:** PH025 не подтвердил доставку, остальные удалённые
  устройства не обновлялись. Новый 10229 source fix не может исправить уже
  установленную 10222, пока управление/доставка до неё не восстановлены.
- Нужны настоящая квитанция команды от Android, post-install PackageManager/hash,
  свежий heartbeat и наблюдение reconnect. `online` и счётчик Redis-подписчиков
  сами по себе недостаточны.
- Сохранённый нераспознанный OTA-result многократно пересылается при reconnect;
  этот отдельный дефект ack/журнала и 504 на `REQUEST_LOGS` требуют адресного
  regression и runtime проверки до широкого rollout.
- Два Android 9 LDPlayer не закрывают Android 14+/физические телефоны, отсутствие
  root, потерю обоих WAN-маршрутов и нагрузку 32 устройств.

[Текущее состояние APK](ANDROID-PRESENCE-AND-APK-RELEASE.md) ·
[Надёжность OTA](../../architecture/ANDROID-OTA-RELIABILITY.md) ·
[Диагностика удалённого control path](REMOTE-CONTROL-PATH-DIAGNOSIS.md)
