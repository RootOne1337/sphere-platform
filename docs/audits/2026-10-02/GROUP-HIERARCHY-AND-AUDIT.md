# N04/N05: иерархия групп и аудит отклонённых команд

**Дата:** 2 октября 2026, Asia/Yekaterinburg.<br />
**Последняя установленная проверка:** 06:41:13 UTC+5; audit readback —06:42:02.<br />
**Review UI:** `a9240a7c81c47951e0029eb07cfccb6249f75bf3`.<br />
**Backend:** `933164e2929be0223b9a918902795ade7f0a6dfa`.<br />
**Адрес:** [3015/groups](http://127.0.0.1:3015/groups).

[Evidence JSON](GROUP-HIERARCHY-AND-AUDIT-EVIDENCE.json) · [Контракт иерархии](../../operations/GROUP-HIERARCHY.md) · [Rollback identity](AUDIT-ROLLBACK-IDENTITY.md) · [Первый group canary](GROUP-WORKFLOWS.md) · [Текущее состояние](../../operations/CURRENT-STATE.md) · [Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [PR19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Результат

N04 исправлен в source и подтверждён finite live API: явный null снимает родителя,
omission сохраняет связь, descendant parent отклоняется без частичной metadata записи.
Create/update/delete сериализованы по организации до commit; конкурентная запись
получает409 сразу. Циклы и повреждённая цепочка не принимаются. UI позволяет выбрать
или снять родителя, сохраняет draft при refetch/error и требует подтверждённого ответа.

Во время проверки настоящих логов обнаружен N05: после отклонённых400/409/422 запросов
истекшие ORM attrs теряли tenant, и audit INSERT не происходил. Authentication теперь
сохраняет immutable UUID snapshot до rollback. Live `/api/v1/audit/logs` вернул3 строки
для400/404/409 с правильным actor/resource/status. За последующее ограниченное окно
backend logs не встретилось error/critical events; это не результат длительного soak.

## Атомарные изменения

| Commit | Содержание |
|---|---|
| `dce2c99` | nullable clearing, свежая ancestry projection, PostgreSQL write fence, HTTP/DB tests, исправление API reference |
| `a9240a7` | guarded parent editor, explicit unlink, создание дочерней группы, server response confirmation,8 UI regressions |
| `933164e` | immutable audit identity, rollback/error response audit recovery,4 actual RLS/ASGI regressions |

Frozen audit source1354d66 и commit80fb365 не переписываются. По исходному реестру
остаётся28 source fixes/13 исходных OPEN; N04/N05 — дополнительные исправленные
findings, не увеличение исходного41. N01 и N03 остаются открытыми.

## Проверки до и после

| Проверка | Before | After |
|---|---|---|
| Group HTTP/null/ancestry |4 failures/3 controls на 1767bec |34 full group tests passed |
| Initial PostgreSQL races |6 failures/2 controls на 1767bec |10 hierarchy tests passed |
| Parent UI |8 failures/0 runtime errors на archived 1767bec |8 regressions passed; full95 suites/761 tests |
| Audit rollback identity |4 failures на a9240a7 |4 new +10 existing audit cases passed |
| Combined production DB |— |24 PostgreSQL cases passed locally и внутри933164e image |
| Compile/checks |— |tsc, Ruff, mypy, UI/backend Docker builds, actual image OpenAPI `--check` passed |

Группа34 и production24 —58 разных backend cases, включая overlap10 hierarchy cases
внутри24, а не дополнительно к ним. Production проверки используют disposable
PostgreSQL/Redis на loopback, не pilot database. Actual hierarchy image также отдельно
прошёл34 HTTP и10 DB cases. Итого179 frontend regressions сверх исходного baseline582.

Before сохраняет отрицательные results; проходящие tests не заменяют live acceptance.
Component tests используют mock HTTP transport. Старый локальный dependency runtime
дал отличающийся generated OpenAPI; exporter внутри установленного production image
совпал с committed171 HTTP operations/134 paths. Документ не переписан старой версией.
Одна React Query test assertion ожидала синхронный refetch; исправлено ожидание re-render,
проверка исчезнувшего parent не ослаблена.

## Установка и конечные live проверки

UI и API собраны из отдельных immutable Git archives. После N04 API былa9240a7;
N05 заменил только backend на933164e. Frontend source между этими commits не изменён,
его установленный compiled stamp остаётсяa9240a7. Правильность двух версий проверена
через health/build и static artifact, не предполагается из последнего Git HEAD.

1. N04 canary создал3 собственные пустые группы. POST201, PUT200, отдельный GET
   подтвердил clear, omission и reassignment. Descendant PUT400 сохранил старое имя.
   DELETE204 родителя сохранил child/leaf; остаток canary удалён204. Исходные group IDs
   и memberships всех19 устройств совпали до/после.
2. N05 canary создал2 пустые группы и отправил только контролируемые отклонённые PUT:
   duplicate409, self-parent400, unknown ID404. Все3 failure audit entries подтверждены
   отдельным authorized read, правильный actor совпал с authenticated operator.
   Временные группы удалены204. Первый read probe ошибочно использовал `/audit`;
   исправлен на существующий `/audit/logs` с aliases `from/to`. Повторных writes не было.
3. Login/API,401 observability без auth, Prometheus backend target UP,
   Grafana90sec HttpOnly/SameSiteStrict session+health, events WS snapshot/pong passed.
   Установленный finite catalog снова19/online14/offline5 после backend restart.
4. Из46 pre-existing containers менялись только owned backend/UI/gateway. Другие43,
   включая13 running, сохранили ID/image/StartedAt/running. APK/OTA/tunnels/public
   frontend сохранены. Предыдущие images/private configs оставлены для rollback.

## Открытые ограничения

- Fresh Sphere visual acceptance остаётся `OPEN_URL_POLICY_BLOCKED`; блокировка
  браузера не обходилась. Pixel layout, native select appearance и client navigation
  не объявлены принятыми на основании API/compiled/component checks.
- Нет нового теста20–30 Android со стримами/скриптами и длительного network soak.
  Нет global OTA promotion или массовой установки APK.
- Полная live permission matrix и API-key HTTP acceptance не выполнены; RLS/403 и
  tenant isolation проверены production tests. Roles UX остаётсяF39.
- Advisory fence не заменяет revision/ETag и не защищает обходящие сервис прямые SQL.
- Audit background writer остаётся best effort при process/DB crash после HTTP commit;
  durable outbox остаётся отдельной работой. Полноценная архитектурная гарантия доставки
  всех событий этим исправлением не заявляется.
- Published 1767bec полностью прошёл backend/frontend/Android CI. Новый опубликованный
  head должен пройти собственные checks; pending не считается success.
