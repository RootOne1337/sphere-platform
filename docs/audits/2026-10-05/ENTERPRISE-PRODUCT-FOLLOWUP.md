# Второй пакет исправлений продуктового аудита

Дата: 5 октября 2026, Asia/Yekaterinburg. PR #19, исходная точка `7293057`.

[Замороженный аудит](ENTERPRISE-PRODUCT-AUDIT.md), [50 исходных работ](ENTERPRISE-PRODUCT-BACKLOG.json)
и [приёмка первого пакета](ENTERPRISE-PRODUCT-IMPLEMENTATION.md) сохраняются отдельно.
Этот журнал фиксирует последующие изменения; историческое OPEN в baseline не переписывается.

## EP-006: task/batch webhook acknowledgements

Статус: **SOURCE_FIXED / REGRESSION_VERIFIED; runtime установка ещё не выполнена**.

Подтверждённый дефект: `status_code < 500` записывал HTTP 403 и 429 как
`webhook.delivered`. Это достижимая ветка task completion и batch completion;
регистрация n8n использует отдельный сервис, который не заменён этим изменением.

Новый контракт:

| Ответ | Итог / повторы |
| --- | --- |
| 200…299 | `delivered`, остановка |
| 429 | `rate_limited`, до трёх повторов |
| 500+ | `server_error`, до трёх повторов |
| Сетевая ошибка httpx | `transport_error`, до трёх повторов |
| Остальные HTTP ответы, включая redirect/403 | `rejected`, без повторов |

Backoff 5/30/120 секунд; Retry-After для 429 принимает целые секунды или HTTP date,
ограничивается 0…120 секунд, неверное/слишком длинное значение использует backoff.
Это локальный бюджет callback, не гарантия выполнения произвольного срока получателя.
Максимум четыре HTTP попытки с timeout 10 секунд. Redirect не выполняется.
Сериализованные bytes, HMAC и `X-Sphere-Delivery` неизменны при повторах.
Один httpx client закрывается после доставки; cancellation передаётся вызывающему коду.

Structured logs содержат `delivery_id`, `event_type`, attempt/status/outcome,
retryability/следующую задержку и один окончательный failure receipt. URL, тело,
секрет подписи и текст transport exception не записываются этой веткой.
Это коррелируемые логи, **не новая таблица durable delivery receipts** и не новая
панель истории вебхуков. Task/batch результат не отменяется отказом callback.

Проверки: 38 webhook tests, в том числе 5 проверок прежнего n8n signed receiver
contract (200/204/403/429/503); до добавления этих пяти прошли 65 tests для
webhook + batch service + n8n API. Ruff и mypy целевого backend-файла проходят.
Предупреждения Pydantic Field/deprecated regex относятся к существующим схемам.

[`probe_webhook_delivery.py`](../../../scripts/audit/probe_webhook_delivery.py)
проверяет настоящий httpx POST на временный loopback HTTP receiver: 204, 403,
429→204, 503→204, исчерпание четырёх 503. Задержки только записываются и пропускаются,
поэтому этот probe не измеряет 155 секунд wall-clock retry. Нет внешних получателей,
DB/task/Android команд; receiver закрывается. Runtime receipt добавляется после установки.

## EP-007: Grafana auth proxy и привязка Sphere session

Статус: **SOURCE_FIXED / REGRESSION_VERIFIED; live приёмка ещё не выполнена**.

В 02:53 UTC браузер на UI `6ff6bc2` снова показал Welcome. Grafana log того же
запроса содержит `auth-proxy.invalid-ip`, HTTP 302, peer `172.27.0.3`.
Whitelist фактически был `172.27.0.1` — gateway для прежнего host preview.
Следовательно, этот срез доказывает rejection текущего Docker frontend;
он не доказывает исчезновение UID или проблему Prometheus datasource.

Согласованный compose overlay задаёт review-ui постоянный IPv4 в private tools
сети с явно указанным IPAM subnet. Grafana принимает только **этот** адрес.
Новая сеть вместо удаления занятой сети сохраняет возможность rollback.
Для новой установки обязательны имя/непересекающаяся подсеть, проверка владельца
адреса и совместное применение frontend/Grafana конфигурации.
Динамическая выдача адресов ограничена отдельным pool, исключающим proxy IP;
это предотвращает конфликт при запуске Grafana/Prometheus раньше frontend.
Нет широкого CIDR whitelist, anonymous login или Editor permission.
Контракт проверен по [официальной документации Grafana](https://grafana.com/docs/grafana/latest/setup-grafana/configure-access/configure-authentication/auth-proxy/)
5 октября 2026; подробная инструкция — [OBSERVABILITY](../../operations/OBSERVABILITY.md).

Cookie теперь AEAD ticket AES-256-GCM: random nonce, отдельный derived key,
проверка целостности/формата/90-секундного срока, HttpOnly/SameSite/path/Secure.
Зашифрованный исходный Sphere token никогда не передаётся Grafana. Перед каждым
upstream запросом проверяются auth/me, blacklist и актуальная роль super_admin;
тот же user ID обязателен. Fail-closed при недоступной авторизации. Это устраняет
прежнее окно доступа до конца TTL после logout/понижения роли. Уже переданные
данные/ответ нельзя отозвать задним числом. Cookie старого формата отвергается;
повторное открытие iframe выдаёт новый ticket.

Upstream 401/403/login redirect больше не скрывается переходом в Welcome:
прокси выдаёт явную ошибку 503 конфигурации Grafana, без upstream cookies.
60 frontend tests (server bridge + panel lifecycle) проходят, TypeScript проходит.
Проверены tampering, random nonce, key rotation, oversized cookie/token, revoked
token, current role/identity change, auth outage, safe/unsafe redirects, read-only
mutation/feature endpoint allowlist. Живые dashboard/Viewer/query/logout receipts
и screenshot будут записаны отдельно после установки.
