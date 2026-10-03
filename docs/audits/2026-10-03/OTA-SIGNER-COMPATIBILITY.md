# N08 — реальный отказ обновления и совместимость Android API подписи

Дата: 3 октября 2026, Asia/Yekaterinburg; timestamps ниже UTC.
[Current State](../../operations/CURRENT-STATE.md) ·
[Реестр](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Evidence JSON](OTA-SIGNER-COMPATIBILITY-EVIDENCE.json) ·
[Контракт OTA](../../operations/OTA-PUBLICATION-AND-APK-CHECKS.md).

## Native canary: отказ подтверждён

APK 1.2.42-dev/10242 из b39676e собран: 822 cases на каждый flavor,
821 passed / 0 failures / 1 skip. Backend/frontend/Android CI этого source прошли.
SHA-256: `f99d166f6b6e33ff29e4723d7d3751faa88d8651e5688404f037e7480e843f78`.
Публикация в managed android-canary/dev подтверждена HTTP201 и exact GET readback
13:45:12 UTC. Normal android/dev остаётся10209.

На одной удалённой PH028 exact installed hash10241 проверен до dispatch.
Cert SHA256 у41/42 одинаков:
`3ab40797d26e4f52f9e440afc6fe69f197caef71a5a27c63c86735bb1801871f`.
В13:46:07.612815 UTC command `84ef644a-0282-4e21-9d12-105a56b34cbc`
получил terminal failed / `ota_signer_unavailable`. Установок10242: **ноль**.
14 online остались10241; массовая волна остановлена, active grant очищен.
Это проверка нового guard 10241, который не исполнялся при предыдущей установке
10240→10241. Успешная предыдущая волна не была доказательством этого guard.

Read-only диагностика: SDK 28, root доступен, APK log содержит тот же код.
Расположение сбоя установлено: signer boundary до installer. Какой именно
PackageInfo — candidate или installed — вернул недоступные данные, старые
логи не различают. Null SigningInfo конкретного OEM пока является проверяемой
гипотезой; новый bounded log различает обе стороны без путей и секретов.

## Исправленная политика в кандидате1.2.43

На API28+ запрашиваются оба флага GET_SIGNING_CERTIFICATES/GET_SIGNATURES.
Если SigningInfo существует, используется только apkContentsSigners, включая
отказ при пустом ответе. Совпадающая legacy history не может заменить иной
современный current signer. Набор текущих сертификатов сравнивается точно.

Если SigningInfo отсутствует, непустой legacy набор допускается лишь после
проверки соответствующего файла на **v2-only** структуру. Candidate и installed
проверяются независимо. Gate разрешает один v2 block и optional verity padding;
v3/v3.1/unknown, duplicate, ZIP64/multidisk, неверные границы и недоступный файл
отклоняются. Signing block ограничен2MiB, ZIP tail65557bytes. API26–27 сохраняет
прежнюю GET_SIGNATURES политику. Это не универсальная поддержка ротации ключей.

Format gate не проверяет криптографию APK: сертификаты предоставляет
PackageManager, окончательную подпись и установку проверяет Android installer.
GET_SIGNATURES на28+ может представлять предка при ротации; поэтому fallback
без ограничения формата был бы недостаточным. См. официальные
[PackageManager](https://developer.android.com/reference/android/content/pm/PackageManager),
[APK v2](https://source.android.com/docs/security/features/apksigning/v2) и
[APK v3](https://source.android.com/docs/security/features/apksigning/v3).
Консервативное отклонение неизвестных blocks — наша OTA политика; обычный v2
reader может игнорировать неизвестные IDs.

## Тестовое доказательство и пределы

На b39676e с новым набором: **10 cases /6 passed /4 failures**.
После production fix: **10 passed /0 failures /0 errors /0 skips**.
Проверены missing-modern positive paths, чужой signer, пустой набор,
authoritative modern mismatch/empty и запрет rotation/unknown/malformed files.
Первый compile attempt имел MockK overload ambiguity и не считается regression
proof; исходный log сохранён отдельно. Реальные собственные подписанные APK 41/42
также проходят format gate. Synthetic ZIPs в tests не выдаются за подписанные APK.

Кандидат10243 подготовлен в исходниках. Full build/signature check и native
acceptance нового guard ещё OPEN на момент source commit. Для устройства с
блокирующим guard 10241 понадобится один scoped recovery install с проверенными
package/certificate/SHA; этот recovery не будет считаться успешным обычным OTA.
После него требуется отдельное обычное addressed обновление с terminal receipt
и свежим heartbeat. Автоматический replay неопределённой установки запрещён.

F33 остаётся PARTIAL, F36 OPEN; count33 source-fixed /8 OPEN не меняется.
FPS, click latency, browser/mobile/keyboard и длительный stream+scripts soak
этими тестами не приняты. Frozen audit не изменён.

## Scoped recovery10243: выполнен,14:23 UTC

Source aa37ab7: full build832 cases/flavor,831 passed/1 skip,0 failures/errors.
APK 43 SHA256 `83075d7bfe0b94de640ee4b4819ee2a8eac185baa551fd6df7c662ffed6aef0e`.
Cert/package совпадают с установленным41. Managed canary publication/readback
14:22:46 UTC, normal channel не изменён.

На PH028 использован существующий Android root SHELL, без hostADB/PC agent.
Временный120s device-role credential получен на backend и отозван сразу после
скачивания. Ключ подписи остался на backend; operator JWT на устройство не
передавался. Artifact exact SHA проверен до единственной `pm install -r`.
Installer HTTP reply потерян при замене приложения: это не terminal OTA receipt.
Результат принят отдельно по exact installed-file SHA и новому heartbeat
14:23:23.697115 UTC. Device ID и данные сохранены, собственный временный файл удалён.

Шесть конечных срезов после recovery:14 online,PH02810243/13 others10241,
heartbeat<60s, connection epochs между срезами неизменны; все16 контейнеров
сохранены. Это короткое наблюдение, не длительный soak. Нормальная OTA приёмка
нового guard всё ещё OPEN; **recovery не подменяет этот gate**.

Для его проверки подготовлен follow-up candidate **1.2.44/10244**. Functional
код относительно43 не меняется; новая монотонная версия нужна для настоящего
43→44 install, поскольку тот же versionCode guard намеренно отклоняет.
Candidate остаётся android-canary/dev, normal/stable не продвигается.
Следующая операция — один addressed43→44; остальные13 устройств ждут результата.

## Обычное addressed OTA и завершённая волна10244

Source **ad34c12**, APK 1.2.44-dev / 10244: **832 cases на каждый flavor,
831 passed/1 skip**,0 failures/errors. Full GitHub source checks passed:
[Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/37129606933),
[Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/37129606890),
[Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/37129606894),
[Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/37129603363).
Docs receipt head имеет собственный CI. Предыдущий push-aa37 Android отказал
при разрешении AGP8.7.3 до compilation; успешные ad34 runs записаны отдельно.

43→44 на удалённой PH028 прошёл через штатный OtaUpdateService, без root SHELL
recovery команды: command `e8f806f7-3331-4649-b279-2491c203363f`, exact completed
receipt14:33:34.803615 UTC, fresh heartbeat14:33:35.538610 UTC; grant auto-clear.
После этого installed-file hash проверен read-only через APK:
`9659468fa74f43a430cd04d2482ec38a6b342bc2aeb46e33db2c61fcfb87b1a9`. Package/certificate и подписанный artifact совпадают.
Это успешное **адресное** OTA. Periodic normal/android-dev ещё10209; его promotion
не подменяется этим результатом.

Остальные13 устройств имели блокирующий guard 10241 и получили один scoped root
recovery install10244 каждое, после SHA/package/cert preflight. Для каждого
приняты exact installed SHA/new heartbeat, временный device credential отозван,
собственный APK-файл удалён. Вместе с первоначальной установкой APK 43 на PH028 это 14 recovery installs
и **один отдельный обычный43→44 OTA receipt**;13 root outcomes не называются
normal OTA receipts. Данные/ID сохранены, hostADB/PC Agent не использовались.

Волна шла тремя фазами4+5+4 успешных целей. Две предварительные остановки были
до мутации APK. PH014: исходный stderr не сохранён; read-only exact41 hash,
online и отсутствие active grant подтверждены перед новым preflight. Точная
исходная причина не выдумывается. PH019: сохранён HTTP429 при operator login,
до обращения к устройству. Helper теперь использует одну operator session
через локальный private stdin; лимит5/60s сохранён, выполненные цели исключены.
Unknown installer никогда автоматически не replay.

**Все 14 доступных устройств теперь1.2.44-dev / 10244**,5 offline вне этой приёмки.
12 конечных samples 2026-10-03T14:59:13.108173+00:00–2026-10-03T15:01:03.364635+00:00: тот же cohort, heartbeat<60s,
connection epochs между samples без изменений. Все 16 прежних контейнеров
сохранили ID/image/StartedAt; UI77fca37/API facba9a/public frontend/Tuna сохраняются.
Release catalog25 entries, canary44 managed, normal/dev10209. Финальный readback:
2026-10-03T15:01:04.005342+00:00. Это короткое наблюдение, не непрерывный uptime SLA.

Read-only APK log tail после normal OTA не содержал missing-modern fallback
diagnostics. Поэтому успешный native upgrade подтверждает исправленную политику
с обоими flags; конкретный fallback branch и виновная сторона старого PackageInfo
не объявляются доказанными native. Negative certificate/rotation cases проверены
в Robolectric, а не разрушительной подменой installed приложения.

N07 ABR fix присутствует на всех14 новых APK, но measured bitrate/FPS/input latency
не приняты. F33 PARTIAL/F36 OPEN и33 source-fixed / 8 OPEN сохранены. Next priority:
profile request→accepted codec config→measured capture/encode/forward/render FPS,
selected-device input latency; matrix preview budget отдельный. Current
StreamingManagerImpl создаёт EncoderConfig без viewer profile, FrameThrottle
имеет фиксированный target 30; этот аудит не превращается в claim реализации.
Browser visual OPEN_URL_POLICY_BLOCKED; API/JSDOM не считаются screenshots.
