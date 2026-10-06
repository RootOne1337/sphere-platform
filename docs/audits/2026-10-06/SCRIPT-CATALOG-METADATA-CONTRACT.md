# Каталог сценариев: контракт чтения без DAG

Дата: **6 октября 2026**. Это проект следующего изменения, выведенный из
исходников API **c2b91e32** и интерфейса **a670a3df**. Описание исходной точки
ниже относится к этим историческим ревизиям, а не к новому коду. Контракт теперь
реализован в исходниках и проверен на отдельной PostgreSQL; установка API/UI
на момент этого source commit ещё не подтверждена. [Результат этапа](SCRIPT-CATALOG-DELIVERY.md)
разделяет source tests, fixture budget и последующие runtime receipts. Общие
p95/RSS/browser heap/load gates остаются условиями проверки.
Документ развивает [открытый P1 аудита Studio](STUDIO-REDESIGN.md).
Причина прежнего роста памяти или диска здесь не устанавливается.

## Проверка реализации 6 октября

148 проверок каталога/legacy API, 22 проверки maintenance и отдельный бюджетный
тест прошли на disposable loopback PostgreSQL/Redis. Фикстура: 100 сценариев,
500 узлов, 491520 B канонического исходника на версию. Фактический raw JSON
legacy response — 48889157 B, catalog — 85176 B (снижение 99,8258%). Catalog
остался 85176 B и при меньшем источнике. Projection делает один SELECT без DAG
и вычисления хеша. Весь frontend: 1506 tests / 126 suites, TypeScript прошёл.
Это конечные fixture checks, не замер развёрнутого p95, heap или WAN.
Старые SQL patch-файлы теперь отказываются от in-place UPDATE; replacements
публикуют новую версию с явными org/script/expected-version. Seed требует org/apply.

## Подтверждённая исходная точка

- `GET /scripts` не принимает `include_dag`, возвращает полный текущий DAG
  каждой строки. `_to_version_response` вычисляет хеш из `v.dag` даже при
  `include_dag=false`: [router.py:36](../../../backend/api/v1/scripts/router.py#L36),
  [list:63](../../../backend/api/v1/scripts/router.py#L63).
- Сервис загружает `current_version` целиком через `selectinload`; `dag` —
  обычный JSONB-столбец. Сохранённых хеша и количества шагов нет:
  [service:211](../../../backend/services/script_service.py#L211),
  [model:15](../../../backend/models/script.py#L15).
- Каталог считает шаги из `current_version.dag`, когда нет верхнего `node_count`;
  серверная `ScriptResponse` этого поля не содержит. Запуск и счётчик
  опубликованных строк требуют объект `current_version`:
  [schema:63](../../../backend/schemas/script.py#L63),
  [presentation:3](../../../frontend/src/features/scripts/scriptPresentation.ts#L3),
  [catalog:84](../../../frontend/app/(dashboard)/scripts/page.tsx#L84).

Удаление поля из ответа или фильтрация DAG после получения браузером не
устраняют загрузку JSONB, его десериализацию и вычисление хеша на чтении.

Один [реальный GET каталога](evidence/studio-redesign/catalog-payload-sample.json)
от 02:13:52 UTC на UI **a670a3d** / API **c2b91e32** (`active`, page 1,
per_page 25) вернул 19 строк из 19, все с полным текущим DAG. Декодированное
тело и загруженное тело при `Content-Encoding: identity` — **31 368 B**,
в DAG суммарно 106 узлов. Повторная JSON-сериализация DAG дала **17 715 B**;
это оценка вклада, а не точная разбивка wire bytes по полям. Round trip
**8,591 мс** включает локальный UI proxy/HTTP. Этот GET подтверждает доставку
источников в небольшом каталоге; он не измеряет heap, SQL-время, WAN, нагрузку
большой страницы или утечку памяти. Сценарии, версии и задания не менялись.

## Решение и форма ответа

Добавить **`GET /scripts/catalog`**, зарегистрированный перед `/{script_id}`.
Существующий `GET /scripts`, CRUD-ответы, detail/history и их значения
`include_dag` сохранить. Это явная совместимость со старыми клиентами, а не
незаметная замена их ответа. На старом API новый клиент получит отказ маршрута;
неизвестный query-параметр старого `/scripts` не должен изображать поддержку.

Параметры нового маршрута повторяют текущие: `query`, `page >= 1`,
`per_page` от 1 до 200, по умолчанию 50; `state=active|archived|all`, по
умолчанию `active`. UI сохраняет выбор 25/50/100. Envelope:

```text
{ catalog_schema: 1, items: ScriptCatalogItem[],
  total: integer, page: integer, per_page: integer, pages: integer }

ScriptCatalogItem = {
  id: UUID, org_id: UUID, name: string, description: string|null,
  is_archived: boolean, created_at: timestamp, updated_at: timestamp,
  current_version_id: UUID|null,
  node_count: integer|null,
  current_version: {
    id: UUID, script_id: UUID, version: integer >= 1,
    dag_hash: lowercase SHA-256 hex, created_at: timestamp
  } | null
}
```

`dag`, `versions`, код, параметры действий, notes и автор версии не входят в
эту схему. `node_count` берётся из той же версии, что `current_version.id`,
а этот ID равен `current_version_id`. Считать все узлы сохранённого массива,
включая начало/конец; это размер источника, а не число выполненных шагов.
Ноль и неизвестное значение различаются. Только отсутствие текущей версии
означает одновременно `current_version_id=null`, `current_version=null`,
`node_count=null`. Опубликованная строка имеет подтверждённые хеш и count.

Схема не вводит `has_dag`: отсутствие тела в каталоге не означает отсутствие
источника. Кнопка исходника работает для известного ID версии, включая архив;
для неопубликованной строки показывает явное отсутствие версии. Чтение одного
источника выполняется существующим `GET /scripts/{id}/versions/{version_id}`.
Каталог передаёт выбранный ID, проверяет принадлежность ответа и хеш, поэтому
публикация новой версии между кликом и ответом не подменяет выбранный источник:
[owned version read](../../../backend/services/script_service.py#L280).
Открытие редактора по ID сценария по-прежнему читает актуальную серверную версию.

Для нового маршрута — отдельные Pydantic DTO и frontend-типы. Не выдавать
metadata-object за полный `ScriptVersion`: существующий `dag` обязателен,
хотя допускает `null`, а parser detail/history отклоняет пропуск поля:
[types:25](../../../frontend/lib/hooks/useScripts.ts#L25),
[parser:10](../../../frontend/src/features/scripts/versionWorkflow.ts#L10).
Старое `include_dag=false` продолжает возвращать `dag:null`.

## Хранение, запись и backfill

Добавить в **`script_versions`** nullable `dag_hash` и `node_count`;
проверять пару «оба NULL либо оба заполнены», формат хеша и count >= 0.
Метаданные принадлежат неизменяемой версии, не дублируются в `scripts`.
Сразу делать столбцы NOT NULL нельзя: старые образы и внешние writers ещё
создают версии без этих полей, а откат приложения должен оставаться возможным.

При create/update пара должна соответствовать **сохранённому DAG, видимому
после чтения из PostgreSQL**, и записываться в одной транзакции с версией и новым
`current_version_id`. Hash точно повторяет `_compute_dag_hash`:
`json.dumps(..., sort_keys=True, ensure_ascii=False).encode()` с текущими
разделителями, затем SHA-256; `digest(jsonb::text)` не является заменой.
При одинаковом DAG сохранять прежнюю версию; переименование не меняет пару.
Rollback создаёт новый ID/номер с парой выбранного источника:
[hash/normalization](../../../backend/services/script_service.py#L31),
[create](../../../backend/services/script_service.py#L114),
[dedup/update](../../../backend/services/script_service.py#L161),
[rollback](../../../backend/services/script_service.py#L292).

Отдельный gate эквивалентности: `_validate_dag` хеширует in-memory dict
([service:108](../../../backend/services/script_service.py#L108)), а ответ
хеширует `v.dag` ([router:42](../../../backend/api/v1/scripts/router.py#L42)).
JSONB round trip чисел может менять Python/JSON-представление; это **непроверенная
гипотеза, не доказанный дефект**. Проверить реальные PostgreSQL fixtures с
`1e20`, `-0.0`, дробями разной точности и вложенными числами. Если значения или
хеш расходятся, после вставки версии выполнить flush и refresh DAG в той же
транзакции, вычислить пару из read-visible dict, затем установить пару и указатель
до commit. Не менять существующий алгоритм хеша или семантику дедупликации в
этом этапе; не использовать новую пару как замену dedup-проверке до доказанной
эквивалентности. Rollback-пара также должна совпадать с прочитанным новым DAG.

Backfill — отдельная возобновляемая операция после развёртывания writers с
новыми полями. Обрабатывать версии keyset-порциями по ID, короткими транзакциями,
по одному DAG в памяти; фиксировать курсор, число обработанных/ошибочных строк
и расход ресурсов без вывода тела. Вычислять из уже сохранённого dict, без
повторной нормализации новой схемой: она может изменить исторический источник
и его прежний хеш. Обновлять только производные поля; ID, DAG, версия,
`created_at`, текущий указатель и задания не меняются. Повтор прохода идемпотентен.
Память одного такого чтения зависит от размера одной версии; лимит Studio
512 KiB не является ограничением всех записей БД или backend API.

Старое `nodes` не-массивом, повреждённый источник или несогласованный указатель
выводятся в отдельный реестр исправления. Не заменять их правдоподобным нулём.
Число элементов массива можно вычислить для исторического DAG вне нынешних
2–500 узлов; это не подтверждает его пригодность для запуска.
Структурная схема и произвольный `action:dict` не проверяют все runtime-параметры:
[DAGNode:44](../../../backend/schemas/dag.py#L44),
[limits:105](../../../backend/schemas/dag.py#L105).

**Блокирующий пробел writers:** append-only сейчас является соглашением.
[build_reactive_dag_v2.py:418](../../../scripts/build_reactive_dag_v2.py#L418)
меняет DAG существующей версии, а
[build_reactive_dag.py:358](../../../scripts/build_reactive_dag.py#L358)
меняет версии по ID сценария. Seed-пути также создают версии в обход сервиса:
[seed_farming_dags.py:1401](../../../scripts/seed_farming_dags.py#L1401),
[seed_black_russia.py:549](../../../scripts/seed_black_russia.py#L549) и
[create:577](../../../scripts/seed_black_russia.py#L577).
Прямые SQL-патчи также обходят ORM:
[fix_sleep_wait.sql:1](../../../scripts/fix_sleep_wait.sql#L1),
[fix_dag_v2.sql:2](../../../scripts/fix_dag_v2.sql#L2),
[fix_dag_add_validate.sql:1](../../../scripts/fix_dag_add_validate.sql#L1);
последний меняет и число узлов. Включить их в перевод или retirement writers.
До включения каталога перевести используемые writers на общее создание новой
версии с парой и precondition либо вывести их из эксплуатации. Одного ORM-hook
недостаточно для прямого SQL. Запрет UPDATE поля DAG в БД возможен только после
совместимого перевода этих путей; молча ломать существующие deploy-скрипты нельзя.

## Чтение, изоляция и конкурентные изменения

Новый SQL выбирает **явные скалярные столбцы** сценария и метаданных версии,
соединяя `current_version_id = version.id`, `version.script_id = script.id`
и обе организации. Не применять `_to_script_response`, ORM relationship
serialization или fallback к вычислению хеша. Не выбирать `dag`, не вызывать
JSONB-функции над ним и не выполнять отдельный запрос версии для каждой строки.
Deferred ORM-загрузка дешевле полного чтения только пока сериализатор не
касается DAG; явная проекция снимает эту зависимость. SQL count из JSONB всё
ещё читает источник и не соответствует выбранному контракту.

Если у выбранной опубликованной строки нет корректной пары или owned-версии,
возвращать `503` с стабильным кодом `script_catalog_metadata_unavailable`,
без тела DAG и автоматического fallback на старый список. GET не запускает
backfill и не пишет в БД. Доступ к старому списку при откате выбирается флагом
релиза, а не скрытым повтором после любой ошибки. `Cache-Control: no-store`;
browser query-cache остаётся отдельным ограниченным механизмом интерфейса.

Сохранить `script:read`, tenant context и явный `org_id`-фильтр для items и total.
Join не заменяет RLS: обе таблицы включены в tenant policies.
Не добавлять `script:execute`/`script:write` для чтения каталога:
[permission](../../../backend/core/dependencies.py#L176),
[tenant binding](../../../backend/database/tenant.py#L19),
[RLS inventory](../../../alembic/versions/20260908_tenant_policies.py#L20).

Поиск остаётся серверным `ILIKE` по name/description, с текущей семантикой
`%`/`_`; state, total, пустая страница, `pages=0` при total=0 и сортировка
`updated_at DESC, id ASC` повторяют [list service:219](../../../backend/services/script_service.py#L219).
Получать count и page одной SQL-командой с общей фильтрованной выборкой
(count CTE + page projection); пустая страница всё равно возвращает total.
Все поля строки и total относятся к снимку этой команды. Запись не блокируется
чтением; при конкурентном commit ответ представляет целиком старое либо новое
видимое состояние, а не пару «новый ID / старый hash/count».
Последующие страницы offset-пагинации могут сместиться после публикации —
устойчивый snapshot между запросами не обещается.

Архивирование сохраняет версии и ранее созданные задания. Старая строка
каталога не является разрешением на запуск или запись: клиенты передают
`expected_current_version_id`, сервер сохраняет имеющиеся active/precondition
проверки и lock/admission; при изменении — 409 и явное обновление:
[locks:44](../../../backend/services/script_service.py#L44),
[run:78](../../../backend/services/script_service.py#L78),
[archive:253](../../../backend/services/script_service.py#L253).

## Переход интерфейса и значимые регрессии

Добавить `useScriptCatalog` с key prefix `['scripts','catalog',scope,params]`,
где scope включает org/user/session; передавать AbortSignal, отклонять чужой
или устаревший ответ, проверять `catalog_schema` и инварианты пары.
Это сохраняет [инвалидацию по `['scripts']`](../../../frontend/lib/hooks/useScripts.ts#L93).
Не объединять cache нового списка с source/detail или старым полным списком.
Legacy `useScripts` и его array-fallback остаются доступными старым потребителям.
Мигрировать `/scripts`, затем read-only selectors задач, orchestration и
pipeline-settings отдельными проверяемыми потребителями; каждый должен получать
count из метаданных, без запроса источника для вычисления числа.

| Фикстура / действие | Обязательный результат |
| --- | --- |
| Две организации, viewer, оператор без `script:read`, одинаковые имена и даты | Viewer читает свою org; без права 403; items/total не раскрывают чужую; tie сортируется по ID. Проверить также non-owner DB role с RLS. |
| Active + archived + unpublished; name-only/description-only mixed-case search; `%`/`_`; страницы 1/2/после конца, 1/25/50/100/200, invalid state/limits | Равенство legacy выборки, порядка, total/pages и статусов ошибок; архив читается, unpublished count=null. |
| v1 с 2 узлами, v2 с 5, v3 rollback v1; rename; identical-DAG update | Новая пара привязана к нужному ID; rollback hash/count равны v1 с новым ID; rename/dedup не меняют пару. Сравнить с существующим full version endpoint. |
| Unicode, вложенные unknown action-поля, различный порядок ключей, `0`/`false`/`null`, loop DAG | Backfill-хеш совпадает с текущим Python helper без повторной нормализации; count равен длине массива, не числу уникальных типов/отчётов. |
| Реальный PostgreSQL: `1e20`, `-0.0`, дроби разной точности и вложенные числа; create/update/rollback/backfill, затем новая read session | Metadata hash/count совпадают с helper на прочитанном сохранённом DAG и full-version ответом. Проверить candidate → JSONB → read-visible JSON, не подменяя проверку mock/SQLite; сохранить прежнее поведение dedup. |
| Metadata NULL, non-array nodes, неправильно owned current pointer; остановка/повтор backfill; старый writer после миграции | Нет ложного ready/нуля, GET не читает DAG; 503 для затронутой страницы, исправление/повтор измеримы, legacy продолжает работать. |
| Публикация/архивирование с барьерами до и после SQL snapshot; stale pinned task/batch/archive | Только согласованная старая или новая строка; state соответствует snapshot; stale действия отклоняются, существующее задание сохраняет версию. |
| 100 строк; capture SQL + запрещённый доступ к `ScriptVersion.dag`/hash helper в новом read path | Ни одной загрузки тела или пересчёта хеша, постоянное число SQL-команд, нет N+1; JSON не содержит поля DAG или синтетических приватных markers. |
| Canonical frontend fixture без DAG: version object/hash, node_count 0/5/null; invalid negative/fraction/unsafe count | Правильные подписи, summary и ID/hash; неизвестное явно; invalid response отклонён. Начальный render не читает source/history. |
| Run single/batch из metadata; explicit source/history open; publish во время source read; query/session change, late response | Run использует ID без source fetch и проверяет receipt. Inspector читает выбранную owned-версию и redacts источник; history сохраняет `dag:null` + отдельные source reads. Чужой/поздний ответ не заменяет состояние. |
| Picker consumers и cache вариантов | Counts не становятся `undefined`/вычислением по DAG; старый список и detail сохраняют контракты, ошибки/отмена не вызывают скрытого fallback. |

Основы для расширения: [реальные PostgreSQL version/concurrency/RLS тесты](../../../tests/production/test_script_version_workflow.py#L29),
[catalog tests](../../../frontend/__tests__/scripts/page.test.tsx#L17),
[strict version workflow](../../../frontend/__tests__/scripts/version-workflow.test.tsx#L61).
Full-DAG фикстура каталога сама по себе не доказывает работу без DAG.

## Измерения и ворота релиза

Создать два воспроизводимых 100-row набора с одинаковыми длинами метаданных:
name 64, description 256 символов, по 500 достижимых узлов. В первом минимальные
action payloads, во втором заполнение синтетическими строками примерно до
480 KiB исходника на версию; записать фактические UTF-8 размеры. Отдельно
проверить 25/50/100 и совместимый API-лимит 200. Не исполнять нагрузочные DAG.

На одном API/БД и одинаковых параметрах выполнить legacy и новый GET:
10 прогревов, затем 30 запросов каждого варианта, три серии. Зафиксировать
raw UTF-8 и фактические wire bytes при одинаковом Accept-Encoding, p50/p95,
server CPU/peak RSS, SQL count/plan/rows/buffers. Изолированный холодный прогон
пометить отдельно. Измерить query-cache size и browser heap после пяти циклов
страница → поиск → страница → закрытие source, затем после очистки cache/GC
в контролируемом тестовом браузере. Плато и освобождение измерять отдельно;
они не доказывают отсутствие всех утечек приложения.

Ворота: ноль DAG reads/hash recomputations на новом списке; 100-row heavy
fixture не больше 256 KiB raw metadata и минимум 95% меньше legacy raw ответа;
размер нового ответа не растёт при увеличении только action payloads;
p95 не хуже legacy более чем на 10% в одинаковых сериях. Числа — предложенные
бюджеты этого fixture. Приложить измерения к развёрнутой новой API-ревизии,
а не переносить результаты mock/staging на API c2b91e32.

Порядок: additive nullable migration → все writers с производной парой,
флаг нового чтения выключен → backfill/reconciliation → API regression и
нагрузочные ворота → ограниченное включение по org → миграция каждого UI
потребителя с cache/session тестами → расширение. До включения у всех текущих
версий соответствующей org должна быть проверенная пара и owned pointer;
старые прямые DAG writers должны быть закрыты или переведены.

Откат: выключить metadata-флаг и вернуть проверенный legacy read/client,
сохранить добавленные столбцы и данные. Ошибки metadata, рост p95/ресурсов,
расхождение pair/source, tenant или pinned-version регрессия останавливают
расширение. Старый writer после отката может создать NULL metadata: перед
повторным включением снова backfill/reconcile. Не удалять версии, не откатывать
tenant policies и не делать destructive downgrade ради выключения каталога.
Закрытие P1 требует этих receipts; этот проект контракта его не закрывает.
