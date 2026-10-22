# Облачная упаковка настроенного pilot APK

Это дополнительный ручной путь, когда локально нельзя запускать тяжёлую Android
сборку. Он не продвигает обычный OTA-канал и не объявляет VPN принятым.

Полный `.github/workflows/ci-android.yml` по умолчанию работает как прежде.
Режим `workflow_dispatch` с `package_only=true` и `validation_run=<run id>` вызывает
отдельный reusable workflow упаковки. Проверенный полный прогон должен уже иметь
успешный job `Android tests and signed release smoke build`; успех одной упаковки
для следующего запуска не подходит.

## Допуск исходников и native

Упаковщик проверяет GitHub run/repository/workflow, точные Android/native-builder
Git objects и неизменность полного build recipe. Исключение в сравнении recipe —
только явный gate выбора `package_only`; сами шаги, проверки, варианты и native
сборка должны совпадать. Изменение Android, builder или recipe требует нового
полного CI. Dirty tracked components и посторонние файлы в Android source не принимаются.

Артефакт `android-app-vpn-candidate-<tested source>` скачивается с проверкой
GitHub SHA-256 и размера. После redirect GitHub Authorization не передаётся
storage endpoint. Проверяются допустимый HTTPS host, zip bounds/path/duplicates,
hardening manifest и SHA всех трёх `libwg-go.so`. Native libraries извлекаются
только в фиксированные ABI-пути. Тяжёлая native-сборка повторно не нужна.

## Настройки и артефакт

Для явно авторизованного ручного запуска оператор готовит одноразовый repository
secret `SPHERE_PILOT_PACKAGE_ONCE`. JSON содержит ровно `environment` и
`recipientPublicKeyDer`. Допустимые environment keys:

- `SPHERE_SERVER_URL` и `SPHERE_FALLBACK_SERVER_URL` — пустые;
- `SPHERE_CONFIG_URL`, `SPHERE_CONFIG_MIRROR_URLS` — HTTPS discovery endpoints;
- `SPHERE_DISCOVERY_INSTALLATION_ID`, `SPHERE_DISCOVERY_PUBLIC_KEY`, `SPHERE_DISCOVERY_KEY_ID`;
- `SPHERE_ENROLLMENT_KEY` — enrollment credential этого pilot installation.

Приватный ключ получателя и APK signer остаются локально. Recipient — отдельный
RSA-3072/4096 public DER, а не ключ WireGuard или ключ подписи discovery.
VPN PrivateKey/PSK, пользовательские пароли и действующие device tokens этому
процессу не нужны. Secret передаётся CLI через stdin, без значения в командной строке.
Существующий чужой secret с тем же именем не перезаписывается.

Вход ограничен 16 KiB, список переменных закрытый, дубликаты/переносы/неожиданные
URL отвергаются до записи. Значения маскируются, затем пишутся в `GITHUB_ENV`
как данные с отдельными delimiters. Gradle cache upload отключён, build/configuration
cache не используются. Ненастроенные CI smoke APK не заменяют настроенный pilot.

После configured compile/test/lint проверяются реальные generated BuildConfig,
application ID, source revision, canary flags и native contents итогового APK.
Затем APK шифруется AES-256-GCM, ключ оборачивается RSA-OAEP-SHA256. Метаданные
source/run/native/APK SHA связаны с ciphertext через AAD. В GitHub artifact идут
**только ciphertext и квитанция**. Открытый настроенный APK, BuildConfig, signing
private key и environment JSON в artifact paths не входят.

Оператор удаляет принадлежащий этому запуску одноразовый secret после подготовки
настроек job либо после завершения/ошибки, сохраняя локальную квитанцию удаления.
Не удалять одноимённую настройку без доказательства, что её создал этот запуск.

## Локальное завершение

1. Проверить GitHub conclusion, head source и digest именно package artifact.
2. Расшифровать в новый локальный файл с ожидаемыми source/run. Само шифрование
   подтверждает целостность bundle, но не заменяет проверку его GitHub provenance.
3. Проверить APK badge, package/version, native hashes и CI signer.
4. Переподписать существующим локальным pilot signer; проверить его сертификат
   и неизменность ZIP payload entries, записать оба SHA.
5. Публиковать/доставлять только через действующий адресный OTA и отдельно
   проверять установленный пакет. Физический tunnel/traffic/fault test следует после OTA.

Скрипт `scripts/pilot/android_cloud_package.py` ничего не устанавливает.
Обычные каналы, отсутствие серверного operation journal/leases, сетевые и
ресурсные ограничения не обходятся этим путём.

Локальные проверки: конфигурационная инъекция/duplicate fields, weak/private
recipient, неизменность env при отказе, CI source/job admission, redirect без auth,
digest/native mismatch, zip traversal, AES receipt/ciphertext tamper и запрет
перезаписи output. Это проверки механизма доставки; полный hosted pipeline и
реальный APK фиксируются отдельными квитанциями после выполнения.
