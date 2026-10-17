# Долговечное владение VPN-адресами

Статус на 6 сентября 2026: SQL reservation и generation fencing реализованы;
provider reconciliation и реальный VPN runtime остаются открытыми. Документ
заменяет первоначальный план этой ревизии аудита. Связанные findings: AUD-11,
AUD-27, AUD-28/AUD-29 в AUDIT-REPORT.md.

## Реализованные инварианты

- PostgreSQL `vpn_peers` владеет адресом до любого POST /peers. Глобальный partial
  unique index `uq_vpn_held_ip` запрещает одинаковый INET для всех non-FREE peers,
  независимо от организации. Host-only constraint запрещает префиксы подсетей.
- Короткая PostgreSQL advisory lock сериализует выбор адреса; уникальный индекс
  остаётся последней защитой. Ни advisory, ни row lock не удерживаются при HTTP IO.
- Private key, PSK, IP, AWG parameters, split_tunnel и operation UUID записываются
  до intent commit. Retry успешного назначения возвращает ту же конфигурацию.
- Redis не участвует в выдаче или освобождении адреса. Legacy ZSET helpers ещё
  присутствуют для прежних тестов/диагностики, но не вызываются lifecycle/API.
  Reinitialization, eviction и потеря Redis не меняют SQL ownership.
- IP освобождается только после принятого provider DELETE и commit состояния FREE.
  Неудачный SQL commit сохраняет предыдущее долговечное состояние.
- Поздний ответ провайдера завершает только совпадающий operation_id, peer_id,
  org_id и ожидаемое состояние. Ошибка/cancellation не удаляет committed intent.

## Состояния и ответы

| Состояние | IP удерживается | Поведение |
| --- | --- | --- |
| PROVISIONING | Да | Intent перед POST; незавершённый/неизвестный результат остаётся в этом состоянии |
| ASSIGNED | Да | Конфигурация доступна для retry; можно начать revoke |
| REVOKING | Да | Intent перед DELETE; неизвестный результат остаётся в этом состоянии |
| ERROR | Да | Legacy error; требует отдельной сверки |
| FREE | Нет | Подтверждённое освобождение; история peer сохраняется, device_id очищается |

PROVISIONING/REVOKING не имеют автоматического timeout-release. Повтор assign или
revoke незавершённого peer возвращает 409 с требованием reconciliation, без нового
provider call. HTTP ошибки lifecycle возвращают 503 без текста provider response.
`is_active` отражает handshake; оно не разрешает переиспользовать адрес.

Это сознательное ограничение восстановления: в репозитории нет авторитетного
контракта inventory/idempotency WG Router. Нельзя безопасно повторять неизвестный
POST или удалять его и немедленно возвращать IP — поздний POST может завершиться
после DELETE. Автоматический reconciler пока не реализован.

## Транзакционные границы

`VPNPoolService.assign_vpn` и `revoke_vpn` владеют commits на выделенной SQL-сессии.
Обе production DI-фабрики создают её отдельно от HTTP/auth caller. Передавать
service сессию с чужими pending writes нельзя. Health monitor использует только
чистую сборку конфигурации и собственную наблюдательную транзакцию.

Authorization + reservation + intent → commit → provider call → условный SQL
transition по operation_id → commit → ответ. Rollback до intent commit запрещает
provider effect; rollback после внешнего эффекта сохраняет intent. Bulk rotation
выполняет отдельно фиксируемые revoke/assign; частичная ошибка не откатывает уже
подтверждённые операции других устройств.

Адреса выбираются из настроенной IPv4 subnet не шире /16. Семантика старого
split_tunnel (True означает весь IPv4 traffic) пока сохранена; для новых peers
выбор долговечен. Для legacy rows split_tunnel неизвестен и используется прежний
fallback True. Это не исправляет AWG server/client mismatch или hardcoded routes.

## Миграция и rollout

Применяется `20260906_vpn_intents` после `20260906_task_accounting`. Миграция
преобразует tunnel_ip в INET, расширяет status, добавляет operation_id и
split_tunnel, host-only constraint и глобальную уникальность non-FREE адресов.
Дубли/невалидные адреса/префиксы отклоняют миграцию атомарно. Она не выбирает
победителя, не перенумеровывает устройство и не удаляет конфликтующие peers.
Downgrade запрещён, пока существуют PROVISIONING/REVOKING intents.

До rollout остановите старые allocation writers через контролируемое обслуживание
и сверьте PostgreSQL, legacy Redis и реальный router inventory. Одновременная
работа старой версии недопустима: она всё ещё выполняет POST до SQL reservation.
SQL uniqueness не обнаружит orphan provider peers, отсутствующие в базе. Их
адреса должны быть сверены/зарезервированы до включения новых назначений.

Локально старые накопленные фикстуры содержали 227 искусственных peers и дубли.
Миграция ожидаемо отказала и сохранила старый head/строки. После удаления только
этих disposable Audit A/B peers в `sphere_audit` миграция прошла. Новые тесты
удаляют свои VPN peers по двум созданным UUID организаций; production не менялся.

## Подтверждённые проверки

`tests/production/test_vpn_durable_leases.py` проверяет настоящие PostgreSQL commits,
row/index constraints и in-memory httpx transport:

- cross-tenant allocation и 64 параллельных назначения;
- видимый другой SQL-сессии intent перед POST и DELETE;
- отказ intent/final commit, потерянный ответ и cancellation после начала POST;
- запрет повторного POST/DELETE неизвестной операции;
- потерю/poisoned reinitialization/недоступность Redis;
- release после подтверждённого удаления и SQL commit, pool exhaustion;
- generation mismatch и сохранение выбранной конфигурации при retry.

`test_vpn_migration.py` выполняет реальную миграцию в throwaway schema PostgreSQL:
дубли, invalid IP, network prefix, downgrade с provisioning/revoking и успешный
обратный переход после явного FREE. Вся schema откатывается после проверки.
64 назначения — concurrency regression сервера, не benchmark 64 Android-эмуляторов.

## Остаточные риски

Provider inventory/reconciler отсутствует; pending intents требуют управляемой
сверки. HTTP adapter и реальный AWG handshake не подтверждены. Redis health lock
не имеет renewal, VPN EventPublisher остаётся stub. Full RLS/runtime role rollout
открыт: глобальная занятость должна быть доступна allocator без выдачи tenant
secrets. Partial unique index предотвращает двойную выдачу даже при неполной
видимости, но не гарантирует успешное выделение из-под будущей RLS-роли.

Не измерены CPU/RAM/FPS/battery или реальная ёмкость эмуляторов. Не проверены
reserved router addresses, серверные маршруты и управляемое восстановление после
полного отказа провайдера. Изменение WG_ROUTER_URL не создаёт новый независимый
address namespace. Несколько роутеров требуют явного routing-domain design.
