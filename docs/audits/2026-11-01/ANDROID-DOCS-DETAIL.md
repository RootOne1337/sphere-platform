# Android: сверка архитектурной и эксплуатационной документации

**Срез исходников:** рабочая ветка на `6b08f09f`; статическая проверка 1 ноября 2026.
Это реестр рассмотренных контрактов, не повторная аттестация всех абзацев или доказательство
работающей установки. APK, Android, сервисы, реальный OTA, cloud workflow и устройства
не запускались и не изменялись. Записанные ранее результаты и версии имеют свои даты.

## Найденные и исправленные расхождения

| Документ | Что проверено и исправлено | Исходный источник |
|---|---|---|
| [ANDROID-DISCOVERY-RECOVERY](../../architecture/ANDROID-DISCOVERY-RECOVERY.md) | При изменении предпочитаемого адреса watchdog может переподключить уже работающий WS; изменение только резерва не требует такого переподключения. Dev config URL не указывает на GitHub Raw по умолчанию. Уточнены signed mode и fallback. | [ConfigWatchdog](../../../android/app/src/main/kotlin/com/sphereplatform/agent/service/ConfigWatchdog.kt), [Gradle](../../../android/app/build.gradle.kts), [ZeroTouchProvisioner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/ZeroTouchProvisioner.kt) |
| [ANDROID-SAVED-ROUTES](../../architecture/ANDROID-SAVED-ROUTES.md) | В новом цикле порядок: preferred primary, последний подтверждённый и fallback без дубликатов. Новый активный адрес требует `auth_ok`. Исправлено описание reconnect и различие legacy/signed удаления резерва. | [AuthTokenStore](../../../android/app/src/main/kotlin/com/sphereplatform/agent/store/AuthTokenStore.kt), [WS client](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt), ConfigWatchdog |
| [ANDROID-SIGNED-DISCOVERY](../../architecture/ANDROID-SIGNED-DISCOVERY.md) | Уточнены допустимая build-time передача enrollment key в обоих flavor и контролируемый reconnect при смене предпочтительного маршрута. | Gradle, ConfigWatchdog, AuthTokenStore |
| [ANDROID-BOOTSTRAP-DISCOVERY](../../architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) | Уточнены до трёх конфигурационных источников, отсутствие unsigned/baked fallback в signed mode и условие reconnect. | ZeroTouchProvisioner, ConfigWatchdog |
| [ANDROID-CONNECTION-PROTOCOL](../../architecture/ANDROID-CONNECTION-PROTOCOL.md) | Убрано абсолютное обещание, что discovery никогда не прерывает рабочую сессию. Предыдущий адрес остаётся кандидатом, новый подтверждается ACK. | ConfigWatchdog, AuthTokenStore, WS client |
| [ANDROID-OTA-RELIABILITY](../../architecture/ANDROID-OTA-RELIABILITY.md) | Старые записи каталога и результаты отделены как срез 25 сентября. Дополнены source checks фактического APK и проверка HTTPS origin по host/port сохранённых management routes. Будущая подписанная release policy остаётся проектной. | [OtaUpdateService](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt), [OtaApkVerifier](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaApkVerifier.kt) |
| [FLEET-OPERATIONS-AND-OBSERVABILITY](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) | Добавлена явная граница: наблюдения, статус и предложения относятся к архитектурному срезу 23 сентября и не являются инвентаризацией текущего deployment. | Заголовок и собственный scope документа; новое окружение не опрашивалось |
| [ANDROID-CLOUD-PILOT](../../operations/ANDROID-CLOUD-PILOT.md) | Наличие workflow в репозитории отделено от фактической включённости hosted Actions и результата отдельного запуска. | [ci-android.yml](../../../.github/workflows/ci-android.yml) |
| [ANDROID-OVERNIGHT-SOAK](../../operations/ANDROID-OVERNIGHT-SOAK.md) | Старый backend и отсутствие повторной ночи отмечены датированным наблюдением, не текущим состоянием runtime/расписания. | Исторический отчёт и [android_soak.py](../../../scripts/pilot/android_soak.py) |

## Просмотрены без правки

| Документ | Сверенный участок | Оставшаяся граница |
|---|---|---|
| [ANDROID-BACKGROUND-ENROLLMENT](../../architecture/ANDROID-BACKGROUND-ENROLLMENT.md) | Очередь WorkManager KEEP, retry/ошибки регистрации, сохранённая identity и отсутствие параллельной регистрации в пределах процесса: [AutoEnrollmentWorker](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/AutoEnrollmentWorker.kt). | Не проверены все варианты WorkManager, конфликтов, реальное FGS/boot поведение и 4xx на устройстве. |
| [ANDROID-EMULATOR-GOLDEN-IMAGE](../../architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md) | Требование rebind до использования credentials и ограничение одинакового serial сопоставлены с [InstanceRegistrationGuard](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/InstanceRegistrationGuard.kt) и [DeviceRegistrationClient](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/DeviceRegistrationClient.kt). | Копирование VM, индивидуальные identity, root permissions и remote Fleet32 не проверялись. |

## Проверки и остаток

Сопоставлены исходники Gradle, Android provisioning, token store, WebSocket client,
watchdog, APK verifier и затронутые workflow/runbook. Проверка не включает точный
анализ всех веток, полный выпуск и подпись, взаимодействие GitHub API, диагностику
каждого runbook или реальное переключение маршрутов. Примеры существующих регрессий:
[SavedRouteFailoverTest](../../../android/app/src/test/kotlin/com/sphereplatform/agent/ws/SavedRouteFailoverTest.kt),
[SignedDiscoveryTest](../../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/SignedDiscoveryTest.kt),
[BackgroundEnrollmentTest](../../../android/app/src/test/kotlin/com/sphereplatform/agent/workers/BackgroundEnrollmentTest.kt),
[OtaApkVerifierTest](../../../android/app/src/test/kotlin/com/sphereplatform/agent/ota/OtaApkVerifierTest.kt).
После статической сверки локально с JDK Android Studio и Android SDK выполнено
`gradlew.bat testDevDebugUnitTest --tests '*SavedRouteFailoverTest' --tests '*SignedDiscoveryTest'`:
31 и 19 JVM-тестов прошли, ошибок и пропусков нет. Gradle сообщил, что configuration
cache отброшен из-за `:awg-sdk:verifyUpstream`; сборка завершилась успешно. Это
выборочная проверка, а не полный Android CI, установка APK или проверка устройства.
Для вывода о фактической установке нужны отдельные версии артефактов, runtime
readback и разрешённые устройственные проверки. Исторические evidence-файлы
не переписаны.
