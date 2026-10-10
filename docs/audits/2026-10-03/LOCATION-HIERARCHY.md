# F26 — география и иерархия локаций

Дата: 3 октября 2026, Asia/Yekaterinburg.
Baseline приложения: `5964fd4`; API: `db6be05`; UI: `8e0aeb5`.

[Операторский контракт](../../operations/LOCATION-HIERARCHY.md) · [Receipts](LOCATION-HIERARCHY-EVIDENCE.json) · [Реестр F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Текущее состояние](../../operations/CURRENT-STATE.md)

## Результат

F26 исправлен на уровне source, tests, immutable production image и конечного
live API canary. Новый review работает на
[3015/locations](http://127.0.0.1:3015/locations). Это не публичный frontend rollout
и не закрытие визуальной либо общей production приёмки.

Форма поддерживает родителя, корень, широту, долготу, явное очищение nullable
полей и редактирование только реально изменённых значений. Карточки показывают
путь иерархии, координаты, ID, дату изменения и прямые назначения устройств.
Удаление имеет собственный диалог с последствиями для детей и memberships.
Контролы соответствуют ролям API; смена сессии закрывает прежний черновик.

API добавляет owned GET detail с прямыми счётчиками и датами. Tenant-scoped
transaction fence, проверка ancestry и optional timestamp conditions защищают
иерархию и просмотренную ревизию. Новый UI всегда передаёт эти условия при
PUT/DELETE. Миграция схемы БД не понадобилась.

## Доказанные исходные проблемы

Замороженный [F26](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f26) фиксировал
отсутствие географии и иерархии в форме. Дополнительное исследование полного
сервисного пути обнаружило реальные ошибки backend:

- parent мог стать собственным потомком: PUT возвращал `200` и сохранял цикл;
- `null` не очищал родителя, широту и долготу;
- обновлённая карточка теряла реальные счётчики, возвращая default `0`;
- writers не имели общей защиты от двух встречных reparent;
- unknown fields и `name:null` молча принимались;
- owned GET detail отсутствовал: `405`; `updated_at` не было в ответе;
- UI не разделял роли и не проверял актуальность редактируемой версии.

Первые PostgreSQL проверки завершились **15 failures / 11 passed / 0 errors**,
всего 26 cases. После исправления исходного набора добавлены ещё четыре
независимые проверки: conditional delete, legacy corrupt ancestry, concurrent
duplicate create и stale identity-map ancestry. Их baseline отдельно не запускался.

UI baseline: **11 failures / 7 passed**, 18 cases. Старый page renderer проверялся
с уже добавленными pure-helper controls; эти семь controls не объявляются
проверками реализации старого helper, которого в baseline не было.

## Верификация исходников

| Проверка | Результат | Область доказательства |
|---|---|---|
| Location PostgreSQL | 30 passed | Null, zero/boundaries, owner/RLS, cycle, locks, rollback, stale revision, counters, deletion |
| Location + group PostgreSQL | 40 passed | Соседняя иерархия и реальные независимые транзакции |
| Новый production image + PostgreSQL | 30 passed | Приложение из immutable image; backend исходники не подмонтированы |
| Новый UI workflow | 26 новых cases passed | Create/edit/delete, roles/session, dirty/stale, receipt, uncertain outcome |
| Весь frontend | 102 suites / 893 tests | 0 failures и 0 skips; 311 regressions выше baseline 582 |
| Types / build / lint | Passed | Compile не означает визуальную приёмку |
| Ruff 0.15.2 | backend/tests passed | Зависимости shipped image |
| Mypy | 224 modules passed | Весь backend |
| OpenAPI | 175 operations / 137 paths; check passed | Генерация Pydantic 2.9.2; отдельный check в новом image |

Frontend lint содержит **44 прежних warnings**, ни одного в новом location
workflow. Body UI commit сохранил старое число 45; этот отчёт и JSON используют
фактический текущий лог. Предупреждения не объявлены устранёнными во всём проекте.
Host audit Python использует старый Pydantic 2.6.3; повтор в production image
подтверждает контракт на shipped Pydantic 2.9.2.

## Установленный runtime

- API `db6be05`: image `sha256:906b381388f6461483c0bbd1d19d7546910958e30c3b8996b263300a35fe2b39`;
  установлен и подтверждён readiness/build **2 октября 22:03:44 UTC**.
- UI `8e0aeb5`: image `sha256:f2314fc54b64a0279b98701e4fad3cbc7664915db30588288dd893a3e1a3a050`;
  UI/gateway healthy **22:06:40 UTC**. В локальном часовом поясе уже 3 октября.
- Самостоятельная integration проверка **22:06:46 UTC**: normal login,
  same-origin API, статический asset и compiled build stamp, unauthenticated
  observability `401`, Prometheus backend UP, Grafana session/health и events
  WebSocket snapshot/pong passed.
- UI/gateway сохраняют read-only root, dropped ALL capabilities,
  `unless-stopped`; review listener открыт только на `127.0.0.1:3015`.
- 13 остальных постоянных running containers сохранили ID, image ID,
  StartedAt и running state. Public UI, APK, OTA и Tuna не обновлялись.

Первый neighbor checker ошибочно включил наш transient `docker run --rm`
контейнер production-image теста и остановился после его штатного завершения.
Исправленная проверка отдельно фиксирует этот own probe и сравнивает 13
постоянных сервисов. Ни missing container, ни первоначальный failure не скрыты
под утверждением, что «всё осталось неизменным».

## Собственная живая проба API

Время: **2 октября 22:06:04–22:06:05 UTC**. Только две собственные локации
`F26-canary-73b88634de5d-*`, без memberships, schedules, scripts и команд Android.

1. Root создан с координатами `0,0`, child — с `−90,180` и настоящим родителем.
2. Попытка сделать root потомком child вернула `400`; имя и поля root не изменились.
3. Широта `91` вернула `422`.
4. Parent/latitude/longitude очищены явным `null`; GET подтвердил значения.
5. PUT с предыдущей датой вернул `409`, без перезаписи состояния.
6. Child возвращён под root с координатами `0,0`.
7. Root изменён; DELETE с прежней датой получил `409`.
8. Conditional DELETE root с новой датой вернул `204`; GET child подтвердил
   сохранённую локацию, root parent и нулевой membership.
9. Child удалён; оба созданных ресурса отсутствуют. Metadata всех прежних
   локаций точно совпадает с исходным снимком.

Квитанция не подменяется UI click test: операции выполнены через реальный
review gateway/API, а клики/формы отдельно проверены JSDOM component tests.

## Конечное наблюдение парка

Шесть срезов **22:07:11–22:09:41 UTC**, каждые 30 секунд, показывают
**19 записей / 14 online / 5 offline**. Online cohort и `connected_since`
совпадают во всех шести срезах. Максимальный возраст online heartbeat:
**31.280295 s**. Никакие device commands не отправлялись.

Это конечное восстановление и readback, не непрерывный uptime SLA, видеоприёмка,
draw FPS, CPU budget, input latency или combined load на 20–30 Android.

## GitHub и дальнейшие gates

API `db6be05` и UI `8e0aeb5` опубликованы отдельными атомарными commits.
Последний полностью проверенный предыдущий head `5964fd4` завершил
[frontend 37067762709](https://github.com/RootOne1337/sphere-platform/actions/runs/37067762709),
[backend 37067762644](https://github.com/RootOne1337/sphere-platform/actions/runs/37067762644) и
[Android 37067762662](https://github.com/RootOne1337/sphere-platform/actions/runs/37067762662):
success, backend **2300 passed / 16 skipped**.

Новый application head `8e0aeb5` имеет свои
[frontend 37070432656](https://github.com/RootOne1337/sphere-platform/actions/runs/37070432656),
[backend 37070432689](https://github.com/RootOne1337/sphere-platform/actions/runs/37070432689) и
[Android 37070432779](https://github.com/RootOne1337/sphere-platform/actions/runs/37070432779).
Их фактический статус на момент фиксации находится в JSON; успех `5964fd4`
не считается успехом нового SHA. Следующий documentation head также получает
отдельный CI. PR19 остаётся draft, merge не выполнен.

Реестр содержит **33 source-fixed / 8 OPEN**: F32, F33 PARTIAL, F34, F35, F36,
F39, F40, F41. N01/N03 и durable audit outbox остаются отдельными работами.
Свежая visual/keyboard/mobile acceptance остаётся `OPEN_URL_POLICY_BLOCKED`.
Не добавлены карта, geocoder, массовые location actions, масштабный load test,
новая APK или изменения tunnel. Следующий этап — подтверждённые outcomes
существующих VPN/OTA действий и отдельные video/XPath gates.
