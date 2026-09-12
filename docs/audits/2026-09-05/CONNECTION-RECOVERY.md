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
