# AUD-91 · High · Конкуренция первой регистрации APK

[Общий отчёт](AUDIT-REPORT.md) · [Маршруты и discovery](CONNECTION-RECOVERY.md)

## Доказательство из Android runtime

После обновления pilot APK на доступном `emulator-5554` обнаружение нового HTTPS
endpoint прошло успешно. Но `SphereApp` и `BootReceiver` для обновлённого пакета
ставили работу с политикой REPLACE: начатая registration отменялась. Одновременно
SetupActivity самостоятельно регистрировала тот же fingerprint. В logcat:
отмена worker в `13:10:58.816`, затем две записи `DeviceRegistration: RE-ENROLLED`
в `13:10:59.135` и `13:10:59.361` с одним UUID. Время взято с Android 12 сентября,
а не с часов сервера. Исходная APK — `74d2ea9`, уже с исправленными WAN defaults.

## Root cause и fix

Workers использовали общую enrollment mutex и проверяли уже выданную identity;
экран этого не делал. Нижняя registration mutex сериализовала два HTTP запроса,
но не устраняла второй после первого успешного ответа. Повторный enqueue с
REPLACE дополнительно обрывал текущий запрос.

Автоматическая регистрация экрана теперь входит в ту же блокировку и повторно
проверяет token + device ID после ожидания. Полная identity используется повторно;
один token без UUID недостаточен. Повторная постановка AutoEnrollmentWorker
использует KEEP. Экран наблюдает завершение фонового worker, а при временной
сетевой ошибке сообщает об автоматическом retry. Отмена auto-flow пробрасывается
наружу, не превращаясь в сообщение о неверных credentials.

## Regression tests и affected files

[BackgroundEnrollmentTest.kt](../../../android/app/src/test/kotlin/com/sphereplatform/agent/workers/BackgroundEnrollmentTest.kt)
проверяет оба порядка гонки с настоящим registration client/store и worker,
единственный HTTP запрос, повторное использование identity и неполное старое
состояние. [EnrollmentSchedulingTest.kt](../../../android/app/src/test/kotlin/com/sphereplatform/agent/workers/EnrollmentSchedulingTest.kt)
использует настоящий WorkManager test database: две постановки оставляют один
неотменённый Work ID. Targeted **29 tests passed**, включая пять новых cases.

Изменены [AuthTokenStore.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/store/AuthTokenStore.kt),
[SetupActivity.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ui/SetupActivity.kt),
[AutoEnrollmentWorker.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/AutoEnrollmentWorker.kt),
указанные tests и test-only WorkManager dependency той же версии 2.9.0.

## Residual risk

Гонка исходной версии подтверждена на устройстве, устранение дублирования проверено
на JVM. Обновление уже зарегистрированной APK не равно повторению чистой установки.
Потеря HTTP ответа после серверного commit и намеренное ручное переподключение к
другой установке требуют отдельной проверки. Этот fix не обещает exactly-once
enrollment при смерти процесса; existing-data update не очищает device identity.
