# Подписанная конфигурация Android и резервные источники

**12 сентября 2026 · opt-in реализация в audit branch; постоянный WAN резерв ещё не принят.**

[Архитектурное решение](ANDROID-BOOTSTRAP-DISCOVERY.md) · [Сохранённые маршруты](ANDROID-SAVED-ROUTES.md) ·
[Пилот](../operations/LOCAL-PILOT.md) · [Аудит](../audits/2026-09-05/AUDIT-REPORT.md)

## Что меняется

При подготовке APK можно задать до трёх HTTPS источников, installation ID и
открытый verification key. В этом режиме `ZeroTouchProvisioner` принимает только
подписанный routes-only документ этой установки. Baked management URL для него не
нужен; после сетевого отказа он не переключается на unsigned BuildConfig/HTTP.
Явные MDM/локальные provisioning-файлы сохраняют прежний приоритет оператора.

Обычные сборки без новых параметров сохраняют legacy JSON contract. Для них
`SPHERE_CONFIG_MIRROR_URLS` добавляет резервные источники без подписи; это
совместимость, а не эквивалент signed mode. Не указывайте там недоверенные hosts.

| Build environment | Значение |
| --- | --- |
| `SPHERE_CONFIG_URL` | Начальный HTTPS URL подписанного JSON |
| `SPHERE_CONFIG_MIRROR_URLS` | Дополнительные HTTPS URLs через запятую; всего максимум 3 уникальных |
| `SPHERE_DISCOVERY_INSTALLATION_ID` | Канонический UUID именно этой установки |
| `SPHERE_DISCOVERY_PUBLIC_KEY` | RSA public key, DER SubjectPublicKeyInfo, стандартный Base64 |
| `SPHERE_DISCOVERY_KEY_ID` | ID ключа, default `sphere-bootstrap-v1` |
| `SPHERE_ENROLLMENT_KEY` | Отдельный локально подготовленный ключ; никогда не публикуется в JSON |

Частичный signed build, неверный UUID/key или не-HTTPS source отклоняются Gradle.
Enterprise flavor может получить enrollment key только при явно включённом signed
mode; обычный enterprise provisioning не меняется. Для pilot dev build можно
задать пустой `SPHERE_SERVER_URL`: подписанный документ предоставит management URL.

## Wire contract v1

Envelope содержит ровно `key_id`, `payload`, `signature`. Payload — стандартный
Base64 точных UTF-8 байтов JSON, signature — Base64 подписи этих байтов. Ключ
выбирается только из заранее доверенного набора, не загружается из документа.
Алгоритм фиксирован: **RSA PKCS#1 v1.5 / SHA-256**, Android `SHA256withRSA`.
Параметр `alg` из сети не принимается. RSA key: 2048–4096 bits; pilot использует 3072.

Android документирует `SHA256withRSA` с API 1+, тогда как встроенный Ed25519 — с
API 33. Поэтому новая тяжёлая библиотека для minSdk 26 не добавлена.
[Android Signature API](https://developer.android.com/reference/java/security/Signature).
Python использует штатные операции библиотеки cryptography, совместимые с Android.
[Cryptography RSA](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/rsa/).

Пример **декодированного payload**, не готовая подпись:

```json
{
  "schema_version": 1,
  "installation_id": "04b8c5d2-c28e-4d12-a687-b3e211a9b6c7",
  "config_version": 7,
  "issued_at": 1799999940,
  "expires_at": 1800003600,
  "server_url": "https://primary.example.invalid",
  "fallback_server_url": "https://backup.example.invalid"
}
```

Имена полей строго ограничены. Токены, enrollment key и произвольные feature flags
не допускаются. Version — целое 1…2^53−1, schema version — 1; boolean/string/float
не преобразуются в integer. Management URLs — HTTPS origins без credentials,
query, fragment или path. Для removal резервного кандидата field отсутствует либо
равен null; это полный signed route set. Последний выбранный рабочий адрес остаётся
доступным до проверки другого соединения по `auth_ok`.

## Получение и durable state

Signed источники запрашиваются параллельно, максимум три Call по **5 s** каждый,
без device/enrollment credentials. Каждая body ограничена 64 KiB до JSON parse,
decoded payload — 32 KiB. Доступный новый mirror не затеняется старым первым
ответом. Среди пригодных подписанных ответов выбирается наибольшая version.
Одинаковая version с разными payload не получает случайного победителя.

Полный принятый envelope сохраняется через `AtomicFile` в app-private
`files/signed-discovery.json`. Он одновременно содержит durable version floor и
кандидатов; после process restart cache заново проверяется тем же ключом. Кэш
сохраняется перед возвратом нового результата вызывающему коду. Сбой записи не
выдаёт новую конфигурацию и не очищает прежние credentials/routes.

Документ принимается для обновления, если `issued_at <= now + 300 s` и
`now < expires_at`. Более старая версия и та же версия с другим payload отклоняются.
Rollback выпускается с **большим** version number. Если источники не отвечают,
используется ещё актуальный verified cache. Если cache просрочен, новая миграция
адресов не выполняется, но уже зарегистрированный APK продолжает использовать
сохранённые management routes и свой refresh/WS протокол.

Concurrent callers объединяются в один текущий mirror cycle. Parent cancellation
отменяет HTTP Calls; поздний callback не пишет cache или маршруты. `ConfigWatchdog`
сохраняет свои generation/revision guards и не разрывает healthy WS из-за новой
конфигурации. Registered APK запускает связь по сохранённым routes независимо от
скорости fetch; JSON не запрашивается для каждой команды или видеокадра.

## Подготовка и публикация

[Offline CLI](../../scripts/discovery_manifest.py) принимает отдельный PEM RSA key
и payload, проверяет схему, подписывает точные байты и атомарно заменяет output
**только после локальной проверки подписи**. Не перезаписывает input/key.

```powershell
python scripts/discovery_manifest.py sign --payload PRIVATE/payload.json `
  --private-key PRIVATE/signing-key.pem --key-id installation-v1 `
  --output PUBLIC/discovery.json
python scripts/discovery_manifest.py verify --manifest PUBLIC/discovery.json `
  --public-key PRIVATE/public-key.pem --key-id installation-v1 `
  --installation-id YOUR-INSTALLATION-UUID
```

CLI не публикует документы, не проверяет доступность маршрутов и не объявляет
timestamp свежим. Проверку подписи/схемы нельзя выдавать за HTTPS/WSS acceptance.
Private key должен быть защищён и сохранён владельцем; он не входит в APK, образ
gateway, публичный JSON или репозиторий. При публикации новой версии сначала
проверьте новый ingress, затем обновите mirrors. Старый адрес выводится только
после rollout, а не сразу после commit документа.

## Текущий pilot и оставшиеся ограничения

Для `sphere-pilot-20260911` создан отдельный подписанный документ в
[config PR #1](https://github.com/RootOne1337/sphere-agent-config/pull/1), ветка
`codex/pilot-bootstrap-20260911`. Основной source — GitHub Raw вне туннеля; копия —
`/bootstrap/agent.signed.json` текущего pilot gateway. Старые environment configs
не изменены. Ветка является bootstrap URL: её нельзя удалять после merge, пока
APK зависит от неё. Начальный документ имеет срок 30 дней от выпуска.

[Host publisher](../operations/DISCOVERY-PUBLISHER.md) теперь автоматически
наблюдает Quick Tunnel, публикует signed version и продлевает документ за 7 дней
до expiry. Native restart → publication → APK recovery принят на новом Windows pilot.
Это не переносимый system service: текущая установка работает при logon пользователя.

**Открыто:** второй постоянный внешний config host, независимый второй ingress,
host reboot и долгосрочная приёмка renewal, обновление
списка bootstrap hosts и verification keys без APK update, versioned diagnostics
в UI, jitter/rate limit forced config polling, fleet/physical-device acceptance.
Сейчас bootstrap sources и verification key задаются при сборке; не обещается
удалённая ротация этих root-of-trust параметров.

Повреждённый cache не сбрасывается молча: иначе можно потерять version floor.
Registered routes сохраняются, а дальнейшая config migration требует диагностики
локального storage. AtomicFile снижает риск частичной записи, но не доказывает
durability при неисправном накопителе/OEM или атомарность с encrypted preferences.
Ошибочные часы могут помешать новой установке принимать свежий документ; уже
сохранённые routes не удаляются. Изоляция и доверие ручному MDM/file provisioning
не заменяются этим механизмом.

## Native pilot

APK `0f1410e` установлен с пустыми baked management URLs.
Его Android код совпадает с `f61cd5a`. На этой реализации проверены приём подписанного cache, смена адреса через GitHub при отказе исходного
tunnel/config mirror и обратный переход. PID/identity сохранены, новых регистраций нет.
[Сценарий, времена и evidence](../audits/2026-09-05/SIGNED-DISCOVERY-NATIVE.md).
Discovery GET требует HTTP revalidation. Минутный query удалён: он не ускорил
GitHub в native acceptance. [AUD-95 OPEN](../audits/2026-09-05/DISCOVERY-CDN-FRESHNESS.md).

## Сохранённые проверки

- Три before-failures для primary transport failure, malformed primary и mirror-only
  configuration; legacy controls сохранены.
- [SignedDiscoveryTest](../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/SignedDiscoveryTest.kt):
  подпись, другой key/installation, strict schema/URL, stale mirror, version conflict,
  time window, reconstructed AtomicFile cache, failed write/corrupt cache,
  concurrency/cancellation, 5 s stuck-source deadline, no unsigned downgrade и
  первый credential, связанный с совершенно новым адресом.
- Общий public-only vector проверяется Python signer tests и Android JCA;
  приватный тестовый ключ после создания vector не сохраняется.
- [Python signer](../../tests/test_discovery_manifest.py): **21 passed**, включая
  настоящий CLI и сохранение старого public file при ошибке.

Robolectric API 26 и JCA подтверждают contract, но не являются доказательством
Android OS/provider на всех телефонах. Native pilot acceptance фиксируется в
операционном отчёте отдельно от JVM count.
