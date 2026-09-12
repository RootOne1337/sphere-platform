# Подключение распределённых APK: проверка 12 сентября 2026

[Отчёт аудита](AUDIT-REPORT.md) · [Готовность](../../operations/READINESS.md)

## AUD-89 · High · Первая регистрация не использовала резервный адрес

**Эксплуатационное влияние.** Новое устройство не регистрировалось при отказе
основного HTTP endpoint, даже когда оператор заранее указал рабочий резерв.
Резервирование уже зарегистрированного WebSocket не исправляло эту ситуацию.

**Причина.** `DeviceRegistrationClient.registerLocked` делал единственный запрос к
`serverUrl`. `fallbackServerUrl` сохранялся только после успешного ответа основного
адреса. До этого шага клиент при отказе сети не доходил.

**Воспроизведение до fix.** В `RegistrationRecoveryTest` добавлены сценарии:
IOException основного → успешный резерв; HTTP 503 основного → успешный резерв;
оба адреса недоступны → две попытки без изменения прежних credentials. Все три
падали: **19 cases, 3 failures**. Контроли неверного ключа, throttling и повторения
того же нормализованного адреса подтверждают границы переключения.

**Минимальный fix.** Клиент нормализует и исключает дубликаты двух заданных
маршрутов; при IOException, HTTP 408 или 5xx пробует второй. HTTP 401/403 не
превращаются в повторную регистрацию, HTTP 429 возвращается планировщику для
backoff. Отмена прерывает текущий Call и не запускает резерв. Обе попытки сохраняют
одну registration version; credentials записываются один раз после успешного
ответа. Ошибка записи в хранилище не запускает новый удалённый запрос.

**Проверка после fix.** Targeted registration/recovery/persistence/background
suite: **63 passed**, Gradle BUILD SUCCESSFUL. В worker regression теперь
проверяется последовательность `primary → backup → primary` при следующем retry.
Существующая проверка десятисекундного deadline отдельного запроса оставлена с
одним маршрутом.

**Затронутые файлы и regression tests:**

- [DeviceRegistrationClient.kt](../../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/DeviceRegistrationClient.kt)
- [RegistrationRecoveryTest.kt](../../../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/RegistrationRecoveryTest.kt)
- [BackgroundEnrollmentTest.kt](../../../../android/app/src/test/kotlin/com/sphereplatform/agent/workers/BackgroundEnrollmentTest.kt)

**Residual risk.** HTTP каждой попытки ограничен 10 s; два последовательно
недоступных маршрута могут занимать до 20 s плюс fingerprint/preferences I/O.
Это два пути к одной установке, а не резервная БД или сервер. Потеря ответа после
серверного commit первоначальной регистрации остаётся отдельным сценарием:
повтор может перевыпустить tokens для того же fingerprint. Проверка использует
управляемые HTTP doubles, а не два реальных независимых WAN провайдера.

## AUD-90 · High · Публичный discovery терял локально заданный enrollment key

**Влияние и причина.** `discoverConfig()` выбирал доступный HTTP discovery раньше
BuildConfig. Если документ содержал маршруты без enrollment key, возвращался
пустой ключ. Фоновые enrollment workers снова запрашивали тот же документ и
оставались без ключа, хотя он уже был включён в APK. Публиковать этот ключ в
анонимном internet endpoint для работоспособности приложения не требуется.

**Доказательство до fix.** Discovery возвращает baked server URL и
`features.auto_register=true`, не передаёт ключ. Новый сценарий ожидал локально
заданный credential и получал пустую строку: **1 failure / 1 negative control**.
Первоначальная ошибка mock Context/filesDir была исправлена в harness до этой
подтверждённой baseline и не считается продуктовым дефектом.

**Fix.** Для совпадающего нормализованного baked primary/fallback используется
локальный ключ. Для другого discovered URL ключ не подставляется. При этом
резерв берётся только из baked пары, а не из произвольного публичного поля.
`SPHERE_FALLBACK_SERVER_URL` добавляет второй адрес при сборке; незаданный адрес
остаётся пустым. Документ со своим enrollment key сохраняет прежний контракт.

**Регрессии:** [ConfigRecoveryTest.kt](../../../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/ConfigRecoveryTest.kt)
проверяет public discovery и отсутствие отправки credentials в discovery запрос,
а также negative control другого origin. Все **23 ConfigRecovery cases** прошли.
После AUD-89/90 полный devDebug JVM-прогон: **493 tests / 35 suites, 0 failures,
0 errors, 0 skipped**, Gradle BUILD SUCCESSFUL за 2 min 16 s.

**Файлы:** [ZeroTouchProvisioner.kt](../../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/ZeroTouchProvisioner.kt),
[app/build.gradle.kts](../../../../android/app/build.gradle.kts), указанный test.

**Residual risk.** Новая установка с полностью изменившейся парой адресов требует
доверенного обновления provision config; произвольный новый URL из анонимного
документа не получает baked credential. MDM и локальный файл по-прежнему имеют
приоритет перед HTTP и BuildConfig. UI lifecycle и фоновый worker ещё требуют
отдельной проверки на установленном APK. JVM-тесты не доказывают Android runtime.
