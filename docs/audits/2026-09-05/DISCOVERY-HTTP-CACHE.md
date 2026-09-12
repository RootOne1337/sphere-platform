# AUD-94: HTTP-кэш задерживает получение нового management адреса

**Severity: High для unattended recovery · 12 сентября 2026.**

## Дефект и причина

`ZeroTouchProvisioner.fetchConfigJson` запрашивал изменяемый JSON без требования
перепроверять HTTP-кэш. Подпись и version floor защищают целостность и запрещают
rollback, но не отличают ещё действующий старый ответ от последнего опубликованного.
HTTP cache с `max-age=300` может пять минут отдавать старый маршрут без обращения
к publisher. Это задерживает восстановление после смены адреса.

## Доказательство до исправления

Новый `SignedDiscoveryTest.discovery revalidates HTTP cache before reusing signed routes`
использует настоящий MockWebServer и OkHttp Cache: сервер сначала выдаёт подписанный
v1, затем v2, оба с `Cache-Control: public, max-age=300`. После двух discovery checks
старый код всё ещё возвращает `https://old-route.invalid`, хотя ожидается
`https://replacement.invalid`. До fix: **1 test, 1 failure**. Это локальное
воспроизведение HTTP cache semantics, а не утверждение, что production client
обязательно имеет локальный disk HTTP cache.

В native pilot `b8e8fe2` подписанная миграция v1 → v2 при приостановленном старом
connector прошла за **145.53 s** до успешного shell command. GitHub Raw отдавал
`Cache-Control: max-age=300`; APK продолжал получать v1 после публикации v2.
CDN freshness и период опроса — возможные составляющие задержки; точный вклад
каждого не установлен. Успешная подпись сама по себе не гарантирует свежесть CDN.

## Минимальное исправление и regression

Каждый config GET теперь содержит `Cache-Control: no-cache`: совместимый HTTP
cache должен проверить актуальность ответа. Это не случайный query parameter на
каждом запросе и не новая частота опроса. При сетевом отказе signed mode продолжает
использовать собственный проверенный durable cache, не удаляя identity/routes.

Affected files:

- [ZeroTouchProvisioner.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/ZeroTouchProvisioner.kt)
- [SignedDiscoveryTest.kt](../../../android/app/src/test/kotlin/com/sphereplatform/agent/provisioning/SignedDiscoveryTest.kt)

Полный devDebug JVM прогон после fix: **522 tests / 37 suites**, без failures,
errors и skips; devDebug APK собран. Проверка на установленном APK фиксируется
отдельно в [pilot guide](../../operations/LOCAL-PILOT.md).

## Residual risk

Некоторые CDN могут не учитывать клиентское требование revalidation или ещё не
видеть новый объект у origin. Заголовок не даёт SLA публикации. Сохраняются poll
interval, сетевые таймауты, обнаружение потерянного WebSocket и reconnect backoff.
Нужны независимые config hosts, стабильные ingress и измерение времени обновления
на каждой площадке. Тест одного эмулятора не подтверждает массовое восстановление.
