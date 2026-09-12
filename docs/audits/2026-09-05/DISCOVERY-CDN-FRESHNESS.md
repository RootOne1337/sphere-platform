# AUD-95: CDN продолжает выдавать старый discovery после revalidation request

**Severity: High для восстановления после смены адреса · 12 сентября 2026.**

## Root cause и воспроизведение

Подписанный v3 оставался допустимым для APK, пока GitHub уже публиковал v4.
`Cache-Control: no-cache` в AUD-94 помогает совместимому HTTP cache, но не даёт
приложению управления всей CDN-цепочкой. Native тест `f61cd5a` получил новую
конфигурацию и выполнил echo только через **271.61 s** после отключения исходного
connector. Процесс и device ID сохранились, повторной регистрации не было.
Вклад каждой ступени CDN/polling в это время не установлен.

Регрессия `signed source leaves stale CDN cache bucket on next minute` моделирует
посредника, игнорирующего request `no-cache`, с настоящими OkHttp Cache и
MockWebServer. Publisher выдаёт подписанные v1/v2 с `max-age=300`. После продвижения
времени на минуту старый код всё ещё возвращает v1. **До fix: 1 test, 1 failure.**

## Fix

Только signed mode добавляет к публичному source URL query parameter
`sphere_bootstrap_epoch=floor(unix_seconds/60)`. Остальные query parameters
сохраняются. Это общий cache key для устройств внутри минуты: нет случайного
per-device nonce, дополнительных HTTP requests или ускорения periodic polling.
`no-cache` сохраняется. Legacy source URLs не меняются.

Подписанные sources должны отдавать тот же документ при этом query parameter.
Pre-signed/одноразовые URLs, которым нельзя менять query, для этого contract не
подходят. Подпись документа проверяется независимо от transport query, а durable
version floor продолжает запрещать downgrade.

Affected files:

- [SignedDiscovery.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/SignedDiscovery.kt)
- [ZeroTouchProvisioner.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/ZeroTouchProvisioner.kt)
- [SignedDiscoveryTest.kt](../../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/SignedDiscoveryTest.kt)

Регрессия проверяет одну origin fetch внутри минуты, новый origin fetch в следующей
минуте, принятие нового подписанного маршрута и сохранение исходного query.
Native повтор фиксируется в [pilot guide](../../operations/LOCAL-PILOT.md).

## Residual risk

Это не минутное SLA reconnect: CDN может не учитывать query, origin может ещё не
обновиться; остаются частота опроса, обнаружение обрыва, backoff и состояние сети.
Wall clock используется также для срока подписи; неверные часы требуют диагностики.
Нужен второй постоянный config host и ingress, а также автоматическая публикация
и renewal. Увеличение числа CDN cache keys ограничено одним в минуту на source;
реальная нагрузка парка ещё не измерена.
