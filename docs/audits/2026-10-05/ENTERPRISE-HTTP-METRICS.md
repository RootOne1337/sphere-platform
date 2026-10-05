# EP-008: реальные HTTP-метрики и разбор маршрутов

**Дата:** 5 октября 2026, Asia/Yekaterinburg.
**Этап:** IMPLEMENTED / LIVE_ACCEPTANCE_PENDING.

[Контракт и ограничения](../../../operations/HTTP-METRICS.md) ·
[Текущее состояние](../../../operations/CURRENT-STATE.md) ·
[Предыдущий пакет](ENTERPRISE-PRODUCT-FOLLOWUP.md)

Исходный реестр 50 замечаний сохраняется неизменным. Предыдущая приёмка закрыла
EP-001–007 (7 закрыто, 43 открыто). Этот пакет реализует EP-008: четыре HTTP
history panels, top-30 routes, route details и status-code breakdown.
EP-008 не считается закрытым до установки и проверки живого результата.

В локальном настоящем Prometheus до изменения UI уже подтверждены успешные
vector responses: общий rate, p95, routes и status codes. Это доказывает наличие
producer data, но не установку нового интерфейса. Backend middleware считает
request counter и histogram до response headers и использует route templates.
Новый frontend строит фиксированные queries поверх существующего producer.

**Проверки реализации:** 118 suites / 1235 frontend tests, 0 failures / pending;
TypeScript и ESLint изменённых файлов прошли с текущим `.eslintrc` в compatibility
mode. Первый запуск ESLint без этого режима остановился из-за отсутствия flat
config; это не было принято как successful lint. Два первых UI assertions
уточнены для повторяющихся видимых значений; затем 99 тематических tests прошли.
HTTP/Android в Jest mocked. Docker build, установка и browser receipt ещё впереди.

API/UI contract и конечные resource measurements будут сохранены раздельными
доказательствами. Нет заявления об исправленной исторической утечке, Android
stream SLA или закрытии CPU/RAM/tunnel gaps.
