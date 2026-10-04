# Иерархия групп: контракт записи и восстановления

**Дата:** 2 октября 2026, Asia/Yekaterinburg.<br />
**Область:** N04 из [первого live group canary](../audits/2026-10-02/GROUP-WORKFLOWS.md).

[Текущее состояние](CURRENT-STATE.md) · [API](../api-reference.md#groups--groups) · [Журнал исправлений](../audits/2026-10-01/WEB-AUDIT-REMEDIATION.md)

## Инварианты API

- `PUT /api/v1/groups/{UUID}` изменяет только переданные поля. Отсутствующий
  `parent_group_id` сохраняет связь, `null` явно снимает её. Тот же принцип применяется
  к nullable `description` и `color`; `name:null` не является операцией переименования.
- Родитель и изменяемая группа принадлежат текущей организации. Неизвестный или
  чужой ID даёт404. Собственная группа, потомок, цикл или повреждённая цепочка —400.
- Проверка предшествует присвоению metadata. Ошибка иерархии не должна частично
  переименовать группу. Проверка ancestors использует свежую SQL projection всех
  групп организации: один запрос, обход с visited set, без рекурсии/N+1.
- Снятие связи разрешено и при ранее повреждённой цепочке. Устройства не перемещаются;
  это операция с организационной иерархией, а не с M2M membership.
- DELETE удаляет выбранную группу; дочерние становятся корневыми, устройства остаются,
  остальные memberships сохраняются. Разрешение DELETE — `device:delete`.

## Конкурентные изменения

Create/update/delete используют один transaction advisory lock для организации.
Ключ — первые64 бита SHA256 от `sphere:group-writes:v1:<org UUID>`, signed bigint.
`pg_try_advisory_xact_lock` возвращает отказ сразу: API409, без ожидания другой
транзакции и без сетевых/device-команд под lock. Fence удерживается до commit/rollback
в router. Вероятная hash collision вызывает лишний409, но не разрешает цикл.

Два процесса не смогут одновременно подтвердить `A.parent=B` и `B.parent=A`:
второй получает409; после первого commit повторный явный запрос читает свежую цепочку
и получает400. Другой tenant не разделяет этот ключ. ORM identity map не используется
как источник ancestor graph; выбранная группа перечитывается с `populate_existing`.

Поведение сверено с официальной документацией PostgreSQL:
[transaction locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)
и [try transaction lock function](https://www.postgresql.org/docs/current/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS).
Внешние источники подтверждают свойства PostgreSQL; работу Sphere доказывают тесты.

SQLite применяется только как адаптер unit tests и не подтверждает конкурентную
защиту. Прямой SQL, обходящий GroupService, не участвует в этом протоколе. Без
revision/ETag два последовательных допустимых изменения одного поля имеют обычную
семантику последней записи; optimistic concurrency не заявляется.

## Проверки

До исправления HTTP regressions:4 failed/3 controls; PostgreSQL:6 failed/2 controls.
В их числе — проигнорированный parent=null, допустимый цикл и timeout конкурентного
duplicate create. После:34 group HTTP/schema cases и10 production PostgreSQL cases
passed. Production проверки используют только disposable loopback audit database.

Проверяются clear/omission, descendant/corrupt ancestry, foreign/missing IDs,
отсутствие частичной metadata записи, commit/rollback, contention create/update/delete,
другой tenant, реальный non-owner RLS login, stale loaded ancestors и сохранение
child/device memberships после удаления родителя. Исходники:
[HTTP tests](../../tests/groups/test_hierarchy.py),
[PostgreSQL tests](../../tests/production/test_group_hierarchy.py),
[service](../../backend/services/group_service.py).

## Операторский путь

В `/groups` форма создания/изменения позволяет выбрать родителя или «Без родительской
группы». Собственная группа, потомки и повреждённые цепочки отсутствуют в допустимых
вариантах. Если выбранный родитель исчез при refresh, форма сохраняет выбор и запрещает
запись до явного исправления. Невалидная исходная связь может быть явно снята.

Изменение отправляет только changed fields; снятие родителя — `parent_group_id:null`.
Dirty draft не сбрасывается при background updates. Pending lock, ошибочный ответ,
409 и потеря подтверждения сохраняют существующий single-flight/retry=false workflow.
Ответ create должен подтвердить выбранного родителя; PUT — тот же ID и все переданные
поля. Членство устройств этим выбором не меняется.

8 новых [component regressions](../../frontend/__tests__/groups/group-hierarchy.test.tsx)
на архивированных исходниках1767bec дали8 assertion failures/0 runtime errors;
на изменении passed. Полный frontend:95 suites/761 tests, types passed. Transport
в component tests заменён fixtures, React Query и dialog работают реально.

Installed source, дата установки, finite live canary и browser acceptance записываются
отдельно в текущем состоянии и evidence. Unit/production database tests сами по себе
не являются доказательством установленного API или визуальной приёмки.
