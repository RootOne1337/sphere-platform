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
14online остались10241; массовая волна остановлена, active grant очищен.
Это проверка нового guard10241, который не исполнялся при предыдущей установке
10240→10241. Успешная предыдущая волна не была доказательством этого guard.

Read-only диагностика: SDK28, root доступен, APK log содержит тот же код.
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
proof; исходный log сохранён отдельно. Реальные собственные подписанные APK41/42
также проходят format gate. Synthetic ZIPs в tests не выдаются за подписанные APK.

Кандидат10243 подготовлен в исходниках. Full build/signature check и native
acceptance нового guard ещё OPEN на момент source commit. Для устройства с
блокирующим guard10241 понадобится один scoped recovery install с проверенными
package/certificate/SHA; этот recovery не будет считаться успешным обычным OTA.
После него требуется отдельное обычное addressed обновление с terminal receipt
и свежим heartbeat. Автоматический replay неопределённой установки запрещён.

F33 остаётся PARTIAL, F36 OPEN; count33 source-fixed /8 OPEN не меняется.
FPS, click latency, browser/mobile/keyboard и длительный stream+scripts soak
этими тестами не приняты. Frozen audit не изменён.
