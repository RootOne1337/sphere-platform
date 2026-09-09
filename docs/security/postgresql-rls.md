# PostgreSQL RLS: доказательства и условия внедрения

Обновлено 9 сентября 2026. Политики схемы исправлены в
`20260908_tenant_policies`; head теперь `20260909_user_auth_bootstrap`. **Полный переход приложения на runtime-роль ещё
заблокирован**. AUD-14 остаётся частично открытым. Это не инструкция немедленно
менять production credentials. Проверены только выделенный локальный PostgreSQL 15
и синтетические организации; production не изменялся.

## Подтверждённые дефекты

Проверка старого startup учитывала SUPERUSER/BYPASSRLS, но пропускала обычного
владельца таблиц. Тесты действительно читают обе организации от владельца,
отменяют FORCE RLS через ALTER и переходят в owner-role через SET ROLE.
Проверено и удаление всех синтетических строк через TRUNCATE с последующим rollback.
Production startup теперь отклоняет эти права, privileged membership, неактивный
RLS и отсутствие политик. Development сообщает предупреждение.

В схеме, обновлённой до `20260906_account_ciphertext`, 15 таблиц имели включённый
RLS без политик. Non-owner роль не могла прочитать даже свои devices/users/organizations
или добавить свой audit log. Три таблицы вообще не имели RLS:
`pipeline_settings`, `device_group_members`, `device_location_members`.
Роль с обычными CRUD grants читала чужие связи, создавала межорганизационные связи
и изменяла настройки оркестратора другой организации. Это SQL-воспроизведения
дефекта защиты БД; они не означают, что найден отдельный публичный HTTP exploit
на каждом из этих маршрутов.

До исправления: [19 failed, 2 passed](../audits/2026-09-05/evidence/rls-policies-before.txt).
После: [33 passed](../audits/2026-09-05/evidence/rls-policies-after.txt), включая
25 проверок фактической схемы, четыре сценария обновления политик и четыре
проверки CI inventory. Отдельно сохранены
[10 startup regressions и три lifespan tests](../audits/2026-09-05/evidence/rls-startup-after.txt).
Дополнительные сценарии после исходного proof проверяют UPDATE принадлежности,
startup на полной схеме и migration/operator behavior. Проверка неверного UUID
уточнена до отказа записи, а не требования возвращать пустой SELECT.

## Политики миграции

Все 28 mapped tables, включая обе M2M-таблицы, входят в frozen inventory миграции.
`organizations` изолируется по `id`, обычные таблицы — по `org_id`. Ассоциация
доступна только при принадлежности **обоих** концов текущей организации.
Внешний ключ сам по себе не защищает прямой SELECT/INSERT в M2M.

Для каждой таблицы установлена restrictive tenant boundary с USING и WITH CHECK.
Она не позволяет дополнительной permissive policy открыть чужие строки через OR.
Repository-owned старые policy names заменяются; неизвестные операторские политики
сохраняются, включая restrictive ограничения. Конфликт с новыми именами
`sphere_*` прерывает миграцию, а не заменяет неизвестную политику молча.

Audit runtime разрешает SELECT/INSERT только своей организации. Restrictive
UPDATE/DELETE запреты действуют даже при дополнительной permissive политике.
Записи с NULL org_id не доступны tenant runtime; платформенный аудит до выбора
организации требует отдельного контролируемого пути. Это ограничение ещё нужно
согласовать с auth/bootstrap, а не выдавать приложению BYPASSRLS.

Tenant setting приводится к UUID; индексируемый столбец org_id не приводится к
text. Отсутствующее/пустое значение закрывает доступ, неверный UUID вызывает ошибку.
Код привязывает Session к UUID из проверенного principal **до** доступа к данным:

```python
from backend.database.tenant import bind_tenant_context

await bind_tenant_context(db, str(validated_org_id))
# В следующих транзакциях этой Session контекст восстанавливается автоматически.
```

`get_tenant_db()` и `get_db_session(org_id=...)` используют тот же helper.
Состояние tenant хранится в Session, а PostgreSQL setting остаётся LOCAL для
каждой транзакции. Событие after_begin устанавливает контекст на предоставленном
Connection, включая новое соединение после recovery. Commit/rollback удаляют
setting из соединения; следующий запрос той же Session восстанавливает его.
Новая Session из того же пула остаётся без tenant, пока явно не привязана.

В AUD-55 подтверждены потеря доступа после commit/rollback/SQL error/invalidation
и возможность оставить в одной ORM identity map объекты разных организаций при
повторной привязке. До fix — [14 failed, 2 passed](../audits/2026-09-05/evidence/tenant-transactions-before.txt);
после — [17 passed](../audits/2026-09-05/evidence/tenant-transactions-after.txt).
Шестнадцать новых тестов используют реальные non-owner LOGIN credentials,
полную мигрированную схему и pool_size=1; pg_backend_pid подтверждает повторное
использование одного соединения. Disconnect моделируется закрытием соединения
через Session.invalidate(), а не отказом всей сети/PostgreSQL failover.

Tenant нельзя менять в той же Session даже после commit/close/reset: создайте новую
Session. Это защищает от смешивания сохранённых ORM identities, но не проверяет
объекты, загруженные **до первой привязки** unscoped сессией. Первую привязку внутри
savepoint helper отклоняет: rollback savepoint мог бы убрать LOCAL setting,
оставив внешнюю транзакцию активной. Привязывайте до begin_nested(); повторная
привязка того же tenant и rollback вложенной транзакции проверены.

Обычный `get_db()` остаётся unscoped. Auth/bootstrap и глобальные jobs ещё требуют
перевода на эти границы. Middleware лишь инициализирует request state и не задаёт
контекст PostgreSQL. Проверка helper напрямую не подтверждает все ASGI/worker пути.

Основание реализации: [SessionEvents.after_begin](https://docs.sqlalchemy.org/en/20/orm/events.html#sqlalchemy.orm.SessionEvents.after_begin)
и [asyncio events через sync_session](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html#using-events-with-the-asyncio-extension).

## Фоновая запись HTTP audit log

AUD-56 исправляет конкретного unscoped writer: `audit_middleware` теперь привязывает
свою новую Session к captured principal.org_id перед INSERT. До исправления реальный
ASGI запрос успешно менял устройство, но non-owner audit writer получал RLS violation
и не сохранял audit row. [До: пять падений и контроль](../audits/2026-09-05/evidence/audit-tenant-before.txt),
[после: 26 связанных проверок](../audits/2026-09-05/evidence/audit-tenant-after.txt).

Шесть новых тестов проверяют 200/403/404, concurrent A/B, отсутствие context в новой
Session и SQL error после flush с последующей записью другой организации. Runtime
LOGIN credentials применены именно к audit writer; request/auth fixture в этих
сценариях остаётся привилегированной. Это не завершает перевод всей HTTP цепочки.

При SQL error после успешной бизнес-операции audit entry всё ещё теряется: текущий
BackgroundTask сообщает error, но не имеет durable retry/outbox. Этот остаточный
риск зафиксирован тестом, а не скрыт успешным HTTP ответом. Отсутствующий tenant не
подменяется глобальным доступом; pre-auth/platform auditing остаётся открытым.

## User access JWT и tenant context

AUD-57 привязывает проверенный `org_id` до SELECT пользователя. Принимается только
user token purpose `access` с UUID subject/organization; подпись, срок и blacklist
проверяются прежде обращения к tenant rows. User lookup содержит оба условия
`id` и `org_id` и обновляет ORM snapshot: перенос пользователя в B делает старый
токен A непригодным, а текущие role/is_active читаются из БД.

[22 HTTP regression cases](../../tests/production/test_jwt_tenant_runtime.py)
проверяют `/auth/me` и PUT `/devices/{id}` под фактическими runtime credentials,
включая audit callback, concurrent A/B requests и pool_size=1. Сохранены
[падающий before proof](../audits/2026-09-05/evidence/jwt-tenant-before.txt) и
[последующий успешный прогон](../audits/2026-09-05/evidence/jwt-tenant-after.txt).
Owner-controls дополнительно проверяют обязательность token/user org match.

User JWT проверен в AUD-57. AUD-58 добавляет ограниченный opaque API-key/device-refresh
bootstrap, AUD-59 проверяет ASGI Android WS и agent HTTP, AUD-60 сериализует проверку
enrollment key с отзывом. [Механизм и обязательные grants](device-credential-bootstrap.md).
AUD-61 связывает отдельные post-auth Android Sessions перед task receipt/result,
progress ownership и EventReactor SQL. [15 runtime regressions](../../tests/production/test_agent_messages_runtime.py)
проверяют ASGI receive loop, commit-before-ACK, duplicate accounting и SQL abort/retry.
AUD-62 закрывает проверенные HTTP login, user refresh/logout и MFA bootstrap:
[user resolver grants, threat boundary и MFA v2 cutover](user-auth-bootstrap.md).
Остальные auth callers и глобальные jobs ещё требуют проверки.
Нельзя решать их default deny выдачей BYPASSRLS, публичным SELECT credential tables
или доверяя неподписанному tenant header. Production rollout остаётся заблокированным.
SQLite unit adapter `set_config` поддерживает SQL-вызов, но не реализует RLS;
доказательства tenant isolation получены только на PostgreSQL.

## Migration и rollback

Из корня репозитория, под отдельной migration-role и с проверенным search_path:

```bash
python -m alembic -c alembic/alembic.ini upgrade head
python scripts/check_rls.py
```

Статическая проверка сопоставляет model declarations и migration inventory,
включая Table() без org_id. Она не подменяет PostgreSQL tests. Новая таблица
требует новой reviewed migration и обновления ссылки на inventory; применённую
миграцию не следует редактировать задним числом.

Старые `infrastructure/postgres/rls_policies.sql` и `audit_log_policies.sql`
теперь явно завершаются ошибкой с указанием Alembic, чтобы старый deployment script
не сообщил об успешной настройке неполных политик. Автоматический downgrade `20260908_tenant_policies`
запрещён: возврат к открытым ассоциациям/настройкам требует отдельного
решения, а исправление политики — новой forward migration. Транзакционный отказ
upgrade не должен отмечаться как применённая revision. Проверьте это на копии
схемы с реальными операторскими политиками до любого production rollout.

## Что остаётся блокером

1. Разделить migration ownership и runtime credentials. Runtime не должен быть
   owner/member, SUPERUSER/BYPASSRLS, участником privileged role или иметь TRUNCATE.
   Не выдавать ему DDL/role administration. Compose пока использует общий
   PostgreSQL bootstrap user; production guard должен отклонить такой запуск.
2. Проверить остальные auth callers и provisioning. User JWT, device credentials,
   Android WS и user login/refresh/logout/MFA исправлены в AUD-57–62.
   Runtime требует explicit EXECUTE на четыре функции; их owner/DDL/grants защищаются
   отдельно, приложение не должно наследовать права владельца. В явно привязанных Session восстановление
   после смены транзакции исправлено в AUD-55; unscoped callers ещё нужно перевести.
3. Перевести глобальную enumeration и фоновые scheduler/orchestrator/VPN/audit
   jobs на проверенные границы организации (HTTP audit writer исправлен отдельно
   в AUD-56). Проверить разрешённые операции через
   фактические ASGI/worker пути, конкурентность, rollback и повторное использование
   соединений под runtime credentials. Текущие SQL policy tests этого не заменяют.
4. Проверить cross-tenant FK ссылки обычных таблиц, изменение организации
   родительской записи и конкурентные изменения связей. Равенство row.org_id
   не гарантирует принадлежность каждого FK; эта миграция явно защищает оба
   конца только двух M2M-таблиц.
5. Проверить планы/latency на целевой нагрузке. Сохранена форма сравнения с UUID
   индексом, но benchmark PostgreSQL и 10–64 APK не проводился.

GUC-контекст защищает от забытых tenant filters в доверенном приложении; SQL caller,
который может произвольно выполнять SET, способен выбрать другой контекст.
Это не граница против компрометации backend credentials или произвольного SQL.
Владелец/администратор БД может изменить RLS; audit immutability также не распространяется
на владельца, backup/restore и привилегированные maintenance операции.

Основания PostgreSQL: [Row Security Policies](https://www.postgresql.org/docs/15/ddl-rowsecurity.html)
описывает owner bypass, default deny, TRUNCATE, FK checks и сочетание политик;
[System Information Functions](https://www.postgresql.org/docs/15/functions-info.html)
описывает проверки ролей и фактически активного RLS.
