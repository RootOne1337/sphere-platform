# AUD-93 · High · Регистрация смешивала адрес и ключ разных discovery-ответов

**12 сентября 2026 · initial enrollment / Android foreground и background.**

[Отчёт](AUDIT-REPORT.md) · [Связанный signed discovery](../../architecture/ANDROID-SIGNED-DISCOVERY.md)

## Влияние и доказательство

После выбора `ProvisionConfig` без ключа workers запрашивали `fetchServerConfig()`
ещё раз и отправляли полученный ключ по **прежнему** адресу. Setup дополнительно
мог подставить BuildConfig key без проверки его связи с выбранным адресом. Если
конфигурация сменилась между ответами, регистрация использовала несогласованную пару.

Сохранённый test `workers never mix a selected route with a key from a later
discovery response` даёт первому discovery один адрес без ключа, а второму — другой
адрес с другим ключом. На исходных worker-файлах из `51323fe` test падает: worker
проводит регистрацию вместо ожидаемого retry. **1 test / 1 failure**. Transport
double фиксирует реальные запросы `DeviceRegistrationClient`; сторонние серверы
не используются. Один before-case подтверждает auto worker; after-case также
проверяет periodic worker и отсутствие второго discovery HTTP.

## Исправление и regression

Setup, AutoEnrollmentWorker и KeepAliveWorker используют только credential,
связанный с уже выбранным `ProvisionConfig`. Повторного HTTP поиска ключа и
неограниченного BuildConfig fallback в UI больше нет. Если ключ отсутствует,
enrollment не отправляется, identity не создаётся; boot worker сохраняет retry,
periodic worker продолжает будущие тики.

`ZeroTouchProvisioner` уже возвращает ключ и маршрут вместе: из локального
provisioning, одного legacy HTTP-ответа, явно связанной baked пары или нового
проверенного signed manifest. Новый адрес из подписанного документа может
получить локальный ключ только после проверки установки и подписи.

Файлы: [SetupActivity](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ui/SetupActivity.kt),
[AutoEnrollmentWorker](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/AutoEnrollmentWorker.kt),
[KeepAliveWorker](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/KeepAliveWorker.kt).
Regression: [BackgroundEnrollmentTest](../../../android/app/src/test/kotlin/com/sphereplatform/agent/workers/BackgroundEnrollmentTest.kt).
Legacy `KeepAliveWorkerTest` fixture приведён к настоящему контракту provisioner:
ключ уже входит в его результат, дополнительный fetch запрещён assertion.

## Residual risk

Явное ручное provisioning/MDM по-прежнему принадлежит оператору. Этот fix не
обеспечивает атомарность удалённого SQL commit с локальным Android storage и не
решает потерю initial-registration response. Работа после регистрации проверяется
отдельно от initial enrollment. Дефект воспроизведён через worker/client harness,
а не отправкой credential на чужую инфраструктуру.
