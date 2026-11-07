# Группы: редактирование, состав устройств и старые ссылки

**Дата:** 2 октября 2026, Asia/Yekaterinburg; установка проверена **05:48 UTC+5**.<br />
**Application / review UI:** `eb4598b4b62c406a1e53a4b9af82fb5dfc486c56`.<br />
**API:** `5fcf18a87f9a2ab198b1d145eae485218871bc01`; backend, Android APK и туннели этим изменением не заменены.

[F24](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f24) · [F25](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f25) · [Журнал](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Evidence](GROUP-WORKFLOWS-EVIDENCE.json) · [Текущее состояние](../../operations/CURRENT-STATE.md) · [PR19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Что было подтверждено до изменения

На `/fleet` была отдельная старая группировка с кнопкой Settings2 без обработчика.
На `/groups` были создание, удаление и счётчики, хотя сервер уже предоставлял PUT группы.
Входа в редактирование и состав группы не было. `/devices` не читал `group_id` из URL:
ссылка с этим параметром открывала общий парк вместо запрошенного состава.

Одинаковые **32 targeted scenarios** запущены на архивированных page/hooks исходниках
`a7829df` и на новой версии. Before: **23 assertion failures / 9 controls passed /
0 runtime errors**. After: **32 passed**. В этих тестах используется настоящий
React Query/cache и Radix Dialog, HTTP transport заменён fixtures. Старые device
regressions включены в controls; они не считаются новыми кейсами.

## Реализованный операторский путь

1. Открыть [группы на review3015](http://127.0.0.1:3015/groups). Каталог показывает
   полные названия и описания с переносом, серверные total/online и родительскую
   группу при наличии. Данные перечитываются каждые 30 секунд; есть ручное обновление.
2. «Изменить» открывает форму выбранного ID. Название ограничено 255 символами,
   описание — 1000. Цвет — `#RRGGBB`. Отправляются только изменённые поля;
   очистка описания отправляет `""`. Неизменённый nullable цвет не заменяется default.
3. Пустая/слишком длинная/неизменённая форма не записывается. Dirty draft сохраняется
   при background GET, конфликте и отказе в доступе. Исчезновение группы или ошибка
   каталога блокируют запись, сохраняя форму для восстановления.
4. На время команды закрытие и повторная отправка блокируются. Mutation retry=false
   задан явно, включая create/delete/move. Потеря ответа не вызывает повторную команду
   автоматически. Ответ PUT должен подтвердить тот же ID и все отправленные поля;
   ответ DELETE должен быть HTTP204. Несогласованный результат не объявляется успехом.
5. «Устройства» ведёт в существующий реестр `/devices?group_id=<UUID>`. С первого
   запроса применяется серверный фильтр группы, pagination остаётся ограниченной.
   Смена URL-группы пересоздаёт область реестра: страницы, selection и открытые действия
   не переносятся на другую группу. Остальные registry operations сохранены.
6. Удаление открывает именованный Dialog с конкретным ID, последними counts и
   объяснением удаления членства. Сами Android-устройства не удаляются. После update
   и delete перечитываются groups и devices, чтобы названия и назначения не оставались
   в кэше прежними. Права окончательно проверяет backend; role-aware UX остаётся F39.
7. Старый bookmark `/fleet` использует штатный Next redirect в `/groups`.
   Duplicate UI и мёртвая settings affordance удалены. В установленном streamed
   HTTP200 присутствует `NEXT_REDIRECT;replace;/groups;307;`. Первая проверка, ожидавшая
   HTTP307/Location header, не прошла; это ожидание исправлено в проверочном скрипте.
   Фактическая навигация браузера остаётся отдельным OPEN gate.

## Источники и покрытие

| Область | Источник | Что проверено |
|---|---|---|
| Групповой workflow | [groups/page](../../../frontend/app/%28dashboard%29/groups/page.tsx) | каталог, error/loading/empty, входы в операции |
| Metadata editor | [GroupEditor](../../../frontend/src/features/groups/GroupEditor.tsx) | immutable owner, dirty draft, validation, pending guard |
| Подтверждение удаления | [GroupDeleteDialog](../../../frontend/src/features/groups/GroupDeleteDialog.tsx) | последствия, owner, failure, no silent success |
| API и кэш | [useGroups](../../../frontend/lib/hooks/useGroups.ts) | response validation, explicit no retry, cache invalidation |
| Состав | [devices/page](../../../frontend/app/%28dashboard%29/devices/page.tsx) | первый group-filtered request, reset scope, existing controls |
| Legacy | [fleet/page](../../../frontend/app/%28dashboard%29/fleet/page.tsx) | redirect к единому поддерживаемому workflow |
| Backend контракт | [schemas](../../../backend/schemas/groups.py), [router](../../../backend/api/v1/groups/router.py), [service](../../../backend/services/group_service.py) | name bounds, ownership, uniqueness, move semantics |
| Группа | [21 regressions](../../../frontend/__tests__/groups/group-workflows.test.tsx) | metadata/clear/color, 409/403, invalid read/outcome, dirty/refetch, single flight, delete, create |
| Старый URL | [redirect regression](../../../frontend/__tests__/groups/legacy-fleet-route.test.tsx) | штатный redirect target |
| Device scope | [registry tests](../../../frontend/__tests__/devices/device-list-page.test.tsx) | 2 новых cases и 8 прежних controls |
| Hook compatibility | [CRUD tests](../../../frontend/__tests__/hooks/useGroups.test.ts) | полные response fixtures, correct owner/DELETE204 |

Два старых hook fixtures исправлены: update дочерней группы возвращал ID родителя,
а DELETE fixture не содержал HTTP status. В полном прогоне они честно выявили
несовместимость со строгой проверкой ответа. Проверки рабочего кода не отключались.

Итог: **94 suites / 753 frontend tests / 0 failures / 0 skips**, `tsc --noEmit` exit0,
**24 новых regressions** в этом блоке, **171** относительно remediation baseline582.
Isolated Git archive собран с исходным production Next15.5.26 standalone config на
Node24.21.0 в Docker. Build passed; compiled SHA и новый membership link проверены
в установленном artifact. Предыдущие lint warnings не скрыты и не объявлены устранёнными.

## Реальный API canary

В **05:44:49 UTC+5** через тот же review gateway созданы две собственные пустые группы.
Команды на Android и изменение реальных назначений не выполнялись.

| Сценарий | Результат | Граница вывода |
|---|---|---|
| Создание | POST201, собственные server IDs | не массовая миграция групп |
| Metadata PUT | HTTP200, отдельный GET подтвердил rename/color/empty description | без backend CAS/revision |
| Duplicate name | HTTP409 | конфликт имени, не вся матрица ограничений |
| Members filter | GET200, scoped total0/items[] | собственная пустая группа; non-empty move не проверен live |
| Удаление | оба DELETE204, сначала child, затем parent | удалялись только canary группы |
| Preservation | исходный set group IDs и все device group_ids совпадают | finite before/after snapshot, не глобальный SLA |

Секреты, access/refresh tokens и чужие журналы в public evidence отсутствуют.
Сохранены только allowlisted canary receipts и deployment metadata.

## Дополнительный N04: очистка родительской группы

**Статус OPEN, P2.** Текущий `GroupService.update_group` проверяет
`if data.parent_group_id is not None`, поэтому explicit JSON null игнорируется.
Это воспроизведено на собственном child canary: PUT200 с null сохранил прежний
parent ID. Такой ответ не подтверждает снятие родителя. Новый hook отвергает
несовпадение отправленных fields; новая форма показывает parent только для чтения.

Следующий backend fix должен различать omitted field и explicit null; null снимает
связь, UUID проверяется на принадлежность организации и отсутствие циклов. Нужны
отдельные tests для null/omitted/self/descendant/foreign-org и concurrency policy.
Циклы в живой базе не создавались. Возможность unsafe hierarchy editing не открыта
в этом UI. F25 metadata/members workflow исправлен; N04 не спрятан в его статусе.

## Установленная версия и оставшиеся gates

- [3015/groups](http://127.0.0.1:3015/groups): review Docker UIeb4598b / API5fcf18a.
  Login, same-origin API, compiled stamp, static asset, Prometheus target,
  Grafana session/health и events WS snapshot/pong passed. Каталог19, reported online14/
  offline5 — моментальный API snapshot, не новое доказательство стабильности парка.
- **44 прежних containers**, из них **14 running**, сохранили ID/image/StartedAt/running.
  Заменены только два контейнера собственного review project. Предыдущий d4364e5
  image/context остаётся для rollback. Restart evidence предыдущей сборки сохранён
  в [runtime follow-up](REVIEW-RUNTIME-AND-REMOTE-RERUN.md); текущая установка — новый
  startup/probe, не Windows/Docker-daemon restart trial.
- Published verification heada7829df завершился success по backend/frontend/Android.
  Новые GitHub checks после source/docs push должны оцениваться по собственному SHA.
- **28/41 source findings исправлено; 13 исходных OPEN**, дополнительные N01/N03/N04
  OPEN. Browser visual acceptance остаётся `OPEN_URL_POLICY_BLOCKED`; запрет не обходился.
  HTTP/RSC/compiled artifact checks не изображаются как реальные screenshots.
- Отдельно нужны non-empty group membership/move acceptance, permission matrix,
  keyboard/focus/mobile visual acceptance, optimistic concurrency policy. Stream FPS,
  input latency, XPath, Android upload и global OTA не объявляются исправленными этим блоком.
