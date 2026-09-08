# PostgreSQL RLS: доказательства и условия внедрения

Обновлено 8 сентября 2026. Политики схемы исправлены в
`20260908_tenant_policies`; **полный переход приложения на runtime-роль ещё
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
text. Отсутствующее/пустое значение закрывает доступ, неверный UUID вызывает ошибку
до записи. Код должен передавать UUID из проверенного principal параметром:

```python
await db.execute(
    text("SELECT set_config('app.current_org_id', :org_id, true)"),
    {"org_id": str(validated_org_id)},
)
```

Это значение действует только до конца транзакции. После commit/rollback его нужно
установить заново в следующей транзакции той же Session. Обычный `get_db()` и
текущее использование `get_db_session(org_id=...)` ещё не обеспечивают контекст
на всём жизненном цикле HTTP/auth/jobs. Наличие middleware не доказывает обратного.

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
не сообщил об успешной настройке неполных политик. Автоматический downgrade этой
revision запрещён: возврат к открытым ассоциациям/настройкам требует отдельного
решения, а исправление политики — новой forward migration. Транзакционный отказ
upgrade не должен отмечаться как применённая revision. Проверьте это на копии
схемы с реальными операторскими политиками до любого production rollout.

## Что остаётся блокером

1. Разделить migration ownership и runtime credentials. Runtime не должен быть
   owner/member, SUPERUSER/BYPASSRLS, участником privileged role или иметь TRUNCATE.
   Не выдавать ему DDL/role administration. Compose пока использует общий
   PostgreSQL bootstrap user; production guard должен отклонить такой запуск.
2. Обеспечить проверенный tenant context **до** user/device/API-key lookup,
   login/MFA/refresh/enrollment bootstrap и после каждой смены транзакции.
3. Перевести глобальную enumeration и фоновые scheduler/orchestrator/VPN/audit
   jobs на проверенные границы организации. Проверить разрешённые операции через
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
