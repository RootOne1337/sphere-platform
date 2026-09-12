# AUD-95: задержка GitHub discovery остаётся открытым эксплуатационным ограничением

**Severity: High для смены единственного доступного адреса · 12 сентября 2026 · OPEN.**

## Evidence и root cause

Подписанный предыдущий version остаётся валидным до expiry, хотя publisher уже
выпустил новый маршрут. Это не rollback и не ошибка проверки подписи. Задержка
публикации/кэширования и период опроса могут удерживать устройство на старых
кандидатах. GitHub Raw отдаёт Cache-Control max-age=300; no-cache request не
позволяет приложению управлять всей CDN-цепочкой.

Native миграция на `f61cd5a` с HTTP revalidation заняла **271.61 s** до echo.
В экспериментальном `9af3ee2` общий минутный query не улучшил наблюдение:
миграция снова заняла около 284 s. PID/identity сохранились, повторной регистрации
не было; обе миграции и обратный возврат прошли. Точный вклад origin propagation,
CDN edges, connection reuse и polling не установлен. Несколько наблюдений не
являются latency distribution.

## Принятое решение

Минутный query **удалён из итоговой реализации**: приёмка на реальном источнике не
подтвердила пользу, а изменение query добавляло требование совместимости для всех
public sources. Код signed discovery возвращён к проверенному контракту f61cd5a.
HTTP no-cache из AUD-94 сохранён: его независимый regression с настоящим HTTP
cache подтверждает revalidation для совместимых посредников.

Экспериментальный cache regression проходил для посредника, учитывающего query;
это не доказательство поведения GitHub. Его исходный failing case и implementation
сохранены в git history, но тест и workaround не входят в итоговый APK.

## Что требуется до закрытия

- Заранее известный второй работающий ingress к той же установке: saved-route
  failover не должен ждать публикации нового адреса после каждого отказа.
- Второй постоянный config host с измеренной свежестью документа и независимостью
  от первого provider. Gateway mirror полезен, пока доступен его собственный адрес.
- Автоматический publisher новых адресов и renewal до expiry; проверка при
  connector/host reboot, blocked provider и массовом reconnect.

Affected components: публичные config sources и rollout; клиент
[SignedDiscovery](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/SignedDiscovery.kt),
[ConfigWatchdog](../../../android/app/src/main/kotlin/com/sphereplatform/agent/service/ConfigWatchdog.kt).

Regression: [AUD-94](DISCOVERY-HTTP-CACHE.md) и подписанный cache/version contract
остаются в suite. Новый независимый ingress пока не готов, поэтому AUD-95 не
объявляется исправленным. Native evidence и все три замера публикуются отдельно
в [операционном guide](../../operations/LOCAL-PILOT.md).
