# Script Studio: контракт параметров опубликованных Android-действий

Дата: **6 октября 2026, Asia/Yekaterinburg**. Source baseline **de969f9**,
PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Этот source срез относится к **EP-016**, частично EP-014/018. Он не является
установленной версией, capability admission или завершением enterprise backlog.
Канонический счёт сохраняется: **9 accepted /41 open**.

**Датированное продолжение 7 октября:** UI b50d6ae установлен и получил
[отдельную browser/CI приёмку](../2026-10-07/STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json).
Windows repair завершён; ниже сохранён исторический host gate 6 октября.
Installed API eb7a7c26 ещё не подтверждает параметры. Следующий этап —
[admitted backend image и packaged guard](../2026-10-07/REVIEWED-BACKEND-DELIVERY.md),
source implementation без заявления об установленном server contract.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Операторская инструкция](../../operations/SCRIPT-STUDIO.md) ·
[Общий follow-up](STUDIO-INTERACTION-FOLLOWUP.md) ·
[Исторический probe](SCRIPT-STUDIO-FOUNDATION.md#уточнение-ep-016-параметры-и-фактические-android-handlers).

## Подтверждённая проблема

Исторический структурный parser принимает `tap` без `x/y`, строку вместо
`sleep.ms`, object вместо primitive `set_variable.value` и array вместо
`condition.params`. APK читает обязательные поля через `jsonPrimitive.int/long`
или `jsonObject`; отсутствие или неверный тип не являются исполняемым действием.
Проверка только имени action/связей не защищала прямого API-клиента.

Другой связанный пробел: шаблон формы содержал только часть runtime-параметров.
`fail_if_not_found`, `headers`, `save_to` и другие optional поля приходилось
добавлять через полный JSON без показа контрактных типов/границ/эффектов.

## Авторитетный контракт и сборочные контексты

Источник: [action_contract.v1.json](../../../backend/schemas/action_contract.v1.json),
версия **1.0**, scope `published-android-action-parameters`, ровно32 опубликованных
типа. Это **собственный формат правил Sphere**, не полный JSON Schema draft.
Неизвестные action fields сохраняются. Их наличие не добавляет APK handler.
Runtime-only `loop` по-прежнему не опубликован.

Backend читает packaged JSON из собственного `backend/schemas`; frontend
импортирует [генерируемую копию](../../../frontend/lib/dag/action-contract.v1.json).
Ни одному Docker build context не требуется ../runtime mount другого приложения.
[sync_action_contract.py](../../../scripts/sync_action_contract.py) копирует
только валидный JSON; `--check` читает обе копии и сравнивает точные bytes.
CI frontend и backend включают этот read-only check. Unit fixtures отдельно
сверяют registry с canonical backend/frontend action types.

Алгоритмы: [Python](../../../backend/schemas/action_parameters.py) ·
[TypeScript](../../../frontend/lib/dag/actionParameters.ts).
Нет device/network/DB calls, подстановки defaults, преобразования строк в числа,
переписывания action или отражения значений пользователя в сообщениях.

## Покрытие и бюджеты

| Группа | Проверяемые параметры |
| --- | --- |
| Координаты | Обязательные x/y, x1/y1/x2/y2; неотрицательный Int32 |
| Жесты | duration0–60000ms, directionup/down/left/right, percent0–1 |
| Время | delay/sleep0–86400000ms; selector/request timeout0–3600000ms |
| Текст и код | String до65536 Unicode codepoints; code/command непустые |
| Selector | Непустая строка до2048; xpath/id/text/desc/class |
| Candidates |1–64objects с обязательным selector, optional strategy/label |
| Приложения | Package до255 с dotted identifier format; явная цель очистки |
| Context | Key/save_to до128; primitive value, без object/array |
| Conditions | Нативные element_exists/text_contains/battery_above либо Lua fallback |
| Assertions | Отдельные семь checks и их params; condition.text vs assert.value |
| HTTP | Absolute HTTP(S) URL/host, method, string body/headers; до64headers |
| Служебные | Scalar types, boolean flags, поддержанный action type |

Это **новые publication policy limits**, а не замер аппаратных возможностей
каждого Android. Таймаут node/graph действует отдельно: sleep24h внутри node30s
не превращается в успешно выполненное24h ожидание. Границы экрана, XPath syntax
и matches, наличие package/root, DNS/TLS, IME, network outcome, Android keycode
поддержка, idempotency и root privileges этим JSON-контрактом не подтверждаются.

Direct API обязан передавать integer JSON tokens, например `1`, а не `1.0`:
Kotlin Int/Long чтение не принимает floating spelling. Browser JSON.parse теряет
numeric spelling и JSON.stringify отправляет integral JS Number как `1`.
Поэтому lexical round-trip исходного JSON не заявляется; параметрический
validator сам не нормализует исходный Python/TS объект.

Primitive `set_variable.value` сохраняет прежнюю Android-семантику: value имеет
приоритет над from_node/from_device_info и читается как строка. Нет нового typed
context runtime. Соответствующая подсказка видна в форме. `save_to` предлагается
как новый параметр только десяти handlers, которые действительно его читают.

## Guard черновика и публикации

[validate_publication_dag](../../../backend/services/script_service.py) сначала
выполняет прежний структурный/Lua parser, затем parameter check. Нормализованный
структурный DAG и прежний hash algorithm сохраняются; новые поля action не
подставляются. Один helper используется:

1. `POST /api/v1/scripts/validate`, только `script:read` и чистая проверка.
2. Создание нового сценария до первого обращения к mutation methods DB.
3. Update с новым DAG после ownership/current-version/archived guard, до metadata
   assignment, dedup и append-version. 422 не оставляет изменённое имя в ORM session.

Проверка текущей версии и tenant guards сохраняются. При неверном action сервер
отдаёт422 с `loc/type/msg`. Максимум100 уникальных ошибок, без `input`/`ctx`;
header names заменяются `<entry>`, values/body/text/code в ошибки не входят.
Слишком большой candidates/headers объект не обходится по всем вложенным полям.

Исторический `DAGScript` structural parser, чтение старых версий, pinned tasks,
metadata-only update, rollback и privileged preserved-source maintenance не
получают автоматического переписывания. **Это не DB-wide invariant для внешнего
SQL writer и не защита каждого legacy/maintenance publication path.** Их source
и hash остаются прежними; отдельный reconciliation/capability gate всё ещё нужен.

## API для tooling и совместимость UI/API

Read-only [GET /api/v1/scripts/action-contract](../../api-endpoints.md) требует
`script:read`, не использует mutation service или device admission. Ответ до64KiB,
Cache-Control:no-store, включает contract/version и два явных false:
`device_execution_verified`, `installed_apk_capabilities_verified`.
Это schema discovery для tooling, не инструкция автоматически запускать Android.

Validate receipt protocol остаётся schema_version1 и прежним subset scope
`structure-routes-lua-safety`; добавлены:

```json
{
  "action_contract_version": "1.0",
  "action_parameters_verified": true,
  "device_execution_verified": false
}
```

| Комбинация | Поведение |
| --- | --- |
| Новый UI + новый API1.0 | Проверка локально и на сервере; receipt показывает server parameter coverage |
| Новый UI + старый API | Local check действует; receipt явно говорит, что API параметры не подтвердил |
| Новый UI + неизвестная/частичная версия receipt | Receipt отвергается; успешная проверка не показывается |
| Старый UI + новый API | Additive receipt fields не мешают прежнему subset statement; новые action errors дают422 |
| Historical read/rollback | Нет rewrite/hash migration и не появляется автоматическая отметка action validation |

Новые API schemas и endpoint catalog регенерированы shipped dependency средой:
[OpenAPI](../../openapi.json),182 HTTP operations /144paths. Сам exporter не
запускает lifespan, не обращается к live API и не меняет database/device.

## UI/UX нового source кандидата

В [NodeInspector](../../../frontend/src/features/scripts/studio/NodeInspector.tsx)
есть [карточка контракта](../../../frontend/src/features/scripts/studio/ActionContractCard.tsx):
версия, эффект, обязательные поля, concrete notes, ошибки выбранного action и
раскрываемые типы/ограничения. Корректные параметры дают только **локальную**
отметку; capability или APK ACK не синтезируются.

**Дополнительные параметры** перечисляет optional runtime fields, отсутствующие
в текущей форме. Выбор списка ничего не пишет. Только **Добавить параметр**
материализует значение в непри­менённом JSON шага. Blank string/array/object
остаются видимыми для настройки; required fields и limits показывают проблему.
`fail_on_error`/`fail_if_not_found` первоначально true; это явное действие оператора.
Затем нужно **Применить параметры**. При чтении defaults не подставляются.

Полный JSON остаётся доступен. Invalid imported parameters можно исправить,
не удаляя source; local parameter gate действует на check/save, а не объявляет
весь historical source исполняемым. Прежняя structural parse/import защита остаётся.
Read-only operator не получает writable select/Add/Apply controls.

Layout использует min-width0, wrapping, bounded error panel, collapsible rule
details и существующие theme tokens. **Новая визуальная браузерная приёмка не
выполнена:** source ещё не собран и не установлен, скриншот старого UI не служит
доказательством этой карточки. Host C: остаётся Warning/Full Repair Needed.
[Gate и ещё один внешний повреждённый Python-файл](HOST-FILESYSTEM-INCIDENT.md).

## Проверки и дальнейшая приёмка

- Python: shared32valid +42negative/edge fixture cases, exact paths/codes,
  no source mutation/error privacy,100error cap,64candidate cap,unicode limits,
  huge integer/nonfinite inputs, historical parser compatibility.
- ASGI: malformed draft422, no mutation/DB/device dependencies; creation/update
  use same guard; rejected update не меняет имя; schema discovery enforces auth.
- UI: invalid source repair → save, old/new/unknown receipt, exact conditional
  keys, destructive effect, optional Add/read-only, template/handler alignment.
- Регрессии: все scripts frontend suites, прежние DAG structural contracts.

Final scoped rerun: **141 Python tests** с shipped FastAPI0.136.3,
Pydantic2.9.2, SQLAlchemy2.0.28, включая direct floating-token case.
Frontend **374 /16 suites**, TypeScript, scoped Ruff, mirror check passed.
Global backend mypy остановился на damaged SQLAlchemy2.0.32 source; pinned scoped
mypy сообщает Requests import-untyped. Full source CI ещё необходим; isolated
pure-validator mypy прошёл. Локальные heavy builds/install не запускались.

Следующая приёмка: CI с shipped requirements → postboot host acceptance →
immutable build/deploy → обе темы и узкий workbench с контрактом/optional поля →
доступность новой API/schema receipt и four-bad-case422 на canary deployment.
APK здесь не менялся и Android commands не отправлялись. Затем capabilities
конкретного APK, runtime condition/HTTP findings, continuous injector/channel,
rich XPath/native evidence и correlated replay. EP-016 целиком не закрыт.

## Полный hosted regression и корректировка фикстур

Head **a9d8b85**, backend [run37508482270](https://github.com/RootOne1337/sphere-platform/actions/runs/37508482270):
**5 failed /3006 passed /37 skipped**, coverage80.36%, 6 октября18:18 UTC.
Все пять failures — публикация `dag_fixture(count=5)` в production catalog
metadata tests: три промежуточных sleep не имели обязательного ms. Guard дал
422 action_parameter.required. Lint/mypy/security/RLS/bootstrap и frontend/Android
CI этого head прошли; полный backend CI не принят.

Фикстура теперь задаёт sleep.ms=1. Неизвестные Unicode/numeric/private payloads,
JSONB roundtrip, hash/dedup, CAS, archive и migration assertions сохранены.
Добавлены три pure fixture checks для2/5/500 шагов (**локально3/3**) и отдельная
реальная PostgreSQL регрессия: исторический source без ms остаётся читаемым;
новое update отклоняется без изменения name/current version; rollback сохраняет
исторический source и согласованную metadata pair. Эта регрессия требует hosted
test database; локальная production DB не использовалась.
Validator не ослабляется, tests/production budget historical fixtures не
переписываются как новые executable scripts. [Изменённые проверки](../../../tests/production/test_script_catalog_metadata.py).
Повторный full CI следующего head обязателен; prior green jobs не переносятся.

### Закрытие source CI на517d73b

6 октября18:43Z backend [run37511486723](https://github.com/RootOne1337/sphere-platform/actions/runs/37511486723)
завершился success: **3015 passed /37 skipped**, coverage80.35%, все шесть jobs
успешны, включая full mypy и реальный PostgreSQL historical regression.
Frontend **1686/133**, types/build; Android all-variant tests/signed smoke build
прошли на том же exact head. Preview guard success, deployment skipped.
[Pinned receipt](STUDIO-SOURCE-CI-20261006.json).
Таким образом первоначальные5fixture failures исправлены без ослабления guard.
Installed API/UI не обновлены; capability negotiation и Android runtime
semantics всего EP-016 этим CI не закрываются. Следующий root/packaging source
и последующие docs heads имеют собственные checks, не наследуют этот результат.
