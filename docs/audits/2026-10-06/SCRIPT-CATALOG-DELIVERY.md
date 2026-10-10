# Каталог сценариев без загрузки исходников

Дата: **6 октября 2026**. API и UI **eb7a7c26** установлены на
**http://127.0.0.1:3015/scripts** в 07:35 UTC. Версии образов, миграция,
backfill и конечные проверки опубликованы в [реестре доказательств](SCRIPT-CATALOG-EVIDENCE.json).
Предыдущая пара **a670a3df / c2b91e32** сохранена для отката. Установка
подтверждается отдельным runtime receipt, а не выводится из CI.
[Контракт](SCRIPT-CATALOG-METADATA-CONTRACT.md) · [Исходный аудит](STUDIO-REDESIGN.md).

## Исправленный дефект

Каталог раньше загружал, десериализовал, хешировал и возвращал полный текущий DAG
каждой строки. Новый `GET /api/v1/scripts/catalog` отдаёт только согласованные
metadata текущей версии, число узлов и поля сценария. Изменение сокращает работу
при чтении списка и исключает исходники из его query cache. Оно не устанавливает
причину заполнения Windows C:, роста Docker VHD или общей утечки RAM.

## Реализация

- [Projection](../../../backend/services/script_service.py) явно выбирает scalar
  columns, page и count в одном statement/snapshot. Источник не выбирается,
  ORM current_version не загружается, hash на чтении не вычисляется.
- Owned join проверяет `version.id`, `script_id` и `org_id`. RBAC и RLS применяются
  к строкам и total. Несогласованный pointer или отсутствующая pair дают 503 с
  `script_catalog_metadata_unavailable` и `Cache-Control: no-store`.
- [DTO](../../../backend/schemas/script.py) имеет `catalog_schema=1`, запрещает
  лишние поля. Неопубликованная строка имеет три явных NULL; нулевой count возможен
  только при существующей подтверждённой версии. Count включает start/end.
- [Additive migration](../../../alembic/versions/20261006_script_catalog_metadata.py)
  добавляет nullable `dag_hash/node_count`, pair/format/nonnegative constraints.
  Она не переписывает JSONB, не заполняет старые источники и не меняет current pointer.
- Create/update/rollback вычисляют pair после PostgreSQL JSONB refresh, до commit
  pointer. Сохранённый hash совпадает с новым чтением, включая числовой round trip.
  Существующее правило дедупликации candidate-versus-stored DAG сохранено.
- Старые GET `/scripts`, detail/history/version и CRUD responses сохранены. Старое
  `include_dag=false` продолжает означать `dag:null` в прежнем DTO.
- [Frontend hook](../../../frontend/lib/hooks/useScriptCatalog.ts) имеет отдельные
  строгие типы/parser, actor/org/session query scope и AbortSignal. Нет автоматического
  fallback к старому ответу с DAG. Ошибка не подменяется пустым здоровым каталогом.
- Исходник загружается только после явного открытия выбранной версии через owned
  route. Cache key включает полный receipt версии и count. Ответ проверяется по
  script/version/hash/count/date; новое сохранение не подменяет открытый источник.
  Смена пользователя или организации отвергает поздний результат.

## Maintenance и совместимость записи

[Backfill](../../../scripts/backfill_script_metadata.py) требует org, по умолчанию
dry-run. `--apply` меняет только pair, явно сохраняет `updated_at`. Keyset cursor,
число версий, source byte limit и time budget ограничены. Временной бюджет проверяется
на границах операций; SQL имеет transaction-local statement timeout до 10 s и остатка
бюджета, но это не hard real-time deadline хеширования/сериализации процесса.

Размер JSONB проверяется под NOWAIT row lock **до переноса исходника в Python**:
shared для dry-run, exclusive для apply. Занятая строка не пересекается cursor;
последующий запуск возобновляет проверку. Oversize/malformed учитываются отдельно,
без печати кода. 57014 возвращает `query_budget`, включая первый ID-page SELECT.

`--reconcile` проверяет уже заполненные pair по существующему Python canonical hash.
Scalar readiness отдельно проверяет missing current pair и неверную принадлежность
pointer. `catalog_ready=true` само по себе **не** подтверждает пересчёт всех хешей.
Перед включением UI требуются clean reconcile и readiness для каждой целевой org.

[Maintenance publisher](../../../backend/services/script_version_admin.py) сохраняет
legacy формат/неизвестные поля, блокирует parent, проверяет exact expected pointer,
active/tenant и создаёт новую версию. Старый source не изменяется. Это привилегированное
DB maintenance, а не HTTP admission или runtime validation всех Android действий.

Два seed CLI требуют явные org и `--apply`; первая случайная организация больше
не выбирается. Два reactive генератора вызывают explicit publisher с org/script/
expected-version и dry-run по умолчанию. Три прежних SQL patch-файла отказываются
от in-place UPDATE; replacements `publish_script_source --patch` сохраняют named
targets, порядок и неизвестные поля и создают новую версию при `--apply`.
Старые runtime writers создают NULL pair; поэтому writer rollout и reconciliation
предшествуют новому UI. Внешний неизвестный SQL writer автоматически не запрещён.

## Подтверждённые проверки

| Проверка | Результат | Граница |
| --- | --- | --- |
| PostgreSQL contract + legacy + unit + maintenance + budget | 171 passed, 0 failures/errors/skips, 55,620 s | Повтор всего выбранного набора с shipped dependencies; disposable loopback audit PG/Redis |
| Финальная migration regression | 1 passed, 0 failures/errors/skips | Повтор после добавления transaction-local lock/statement timeout; входит в тот же выбранный набор |
| Large source budget | Входит в 171 passed | 100 сценариев × 500 узлов × 480 KiB current source |
| Полный frontend | 1506 passed / 126 suites | Hook/page/fixtures hashes сохранены в receipt |
| TypeScript | Passed | После двух scope/cache hardening fixes |
| Полный backend mypy | Passed | Версия из shipped requirements 2.3.1 |
| Ruff backend/tests/maintenance | Passed | Версия из shipped requirements 0.15.2 |
| OpenAPI export/check | Passed | Declared HTTP schema, без lifespan/HTTP/device execution |
| Установленный API image | 596 agent/status/device/VPN; 37 catalog; 35 resource; 5 bootstrap — все passed, 0 skips | Offline exact-image contracts; 37 catalog пересекаются с source набором |
| CLI, mypy, Ruff, OpenAPI в том же API image | Passed; mypy 237 files | Packaged maintenance startup без source mount; архивные scripts для Ruff смонтированы read-only ради классификации imports |
| Source CI eb7a7c26 | Backend / Frontend / Android / Preview workflow success | Preview guard success, deploy skipped; автоматического preview deployment не было |

[Source receipts](evidence/script-catalog/source-tests.json),
[frontend](evidence/script-catalog/frontend-tests.json),
[exact image](evidence/script-catalog/exact-image-checks.json),
[CI jobs](evidence/script-catalog/source-ci.json). Наборы пересекаются;
суммарное число уникальных тестов между прогонами не заявляется. Source hashes
проверены против revision Git blobs; различия checkout — только Windows CRLF.

Ранее локальный Ruff 0.3.0 остановился на существующей exact-int проверке credentials.
После выравнивания инструментов с pinned requirements весь scope прошёл. Этот отказ
не скрыт; product credentials code не менялся ради старой lint версии.

Budget fixture имеет name64/description256. Канонический current source: **491520 B**
на версию; фактический legacy raw body **48889157 B**, metadata body **85176 B**.
Сокращение **99,8258%**, ниже ворот 256 KiB. При minimal source33307 B catalog имеет
те же85176 B. Per-page25/50/100/200 проверены на одну scalar SQL projection без DAG/hash.
Single-request local ASGI timings из окончательного shipped-dependency JUnit:
catalog **47,310 / 48,859 ms** (small/heavy), legacy **298,027 / 689,896 ms**.
[Budget receipt](evidence/script-catalog/fixture-budget.json) сохраняет параметры
и ограничения. Это не deployed p95, SQL buffers, CPU/RSS, browser heap или WAN.

Исходные тесты:
[contract](../../../tests/test_script_catalog_contract.py),
[stored JSONB/RLS/snapshot/migration](../../../tests/production/test_script_catalog_metadata.py),
[maintenance](../../../tests/production/test_script_catalog_maintenance.py),
[budget](../../../tests/production/test_script_catalog_budget.py),
[frontend contract](../../../frontend/__tests__/hooks/useScriptCatalog.test.ts).

## Установка и оставшиеся ворота

Оба production images собраны из одного `git archive` **eb7a7c26**:
API `sha256:559b6bf58e39ed080244d2708a2189856b086dc3c89bf281f62cf42d5f2b28f3`,
UI `sha256:63159a43a6dde21edc4950b0dd33aa99e01e04ad06e6643d7bf572fba087b1b6`.
[Build receipt](evidence/script-catalog/builds.json) сохраняет архив и SHA образов.

Миграция довела Alembic head до `20261006_script_catalog_metadata`. Для одной
действующей организации проверены **22 сценария / 25 версий**: сначала dry-run
выявил 25 незаполненных pair, apply заполнил 25, полный reconcile дал ноль
расхождений. Во второй попытке все три прохода изменили ноль строк. Current
pointers, исходники, идентификаторы, даты и **445 заданий** сохранились. Source
digest до/после одинаков:
`f017e765338fda0f0c2e8efab2e4b5565bf930377e11736891f65fe705820179`.
[Backfill evidence](evidence/script-catalog/migration-backfill.json) отдельно
показывает scalar readiness и полный reconcile; один `catalog_ready` не доказывает
пересчёт source hashes.

Первая попытка автоматически откатила UI/API: сравнитель принял Linux Docker
Desktop и Windows spelling одного bind-пути за изменение тома. Сверены только
две записи `/app/agent-config` и `/var/lib/sphere/updates`; нормализация drive-path
aliases и регистра сохранила остальные mount/configuration fields. Второй запуск
подтвердил прежние rollback images перед установкой и завершился успешно.
Additive columns при откате сохранились; downgrade не выполнялся.

[Runtime receipt](evidence/script-catalog/runtime-installation.json) подтверждает
замену только API/UI и сохранение 44 соседних контейнеров. APK, туннели и Android
команды не менялись. Реальный `state=all` каталог: **22 строки / 14037 raw B**, ранее
legacy ответ для тех же строк **34553 raw B**; `catalog_schema=1`, `no-store`, DAG
в списке отсутствует. [Native browser receipt](evidence/script-catalog/native-ui.json)
отдельно подтверждает перечисленные ниже проверки интерфейса.

Presence во время переключения: **14 online / 5 offline** до него, **9 / 10** после
API и **10 / 9** сразу после UI. В конечном read-only наблюдении **07:41:18 UTC**
вернулось **14 / 5**, всего 19 устройств, presence доступен.
[Конечная проверка](evidence/script-catalog/final-readonly.json) — один snapshot;
он не доказывает длительную стабильность стрима, выполненный Android сценарий
или отсутствие потерь при перезапуске.

Порядок: immutable source → production images/checks → additive migration с коротким
lock timeout → новые writers/API → per-org dry-run/apply/reconcile/readiness → новый UI
→ native browser lazy-source/pagination/theme/preferences → finite API/fleet receipts.
Rollback: сначала прежний UI, затем прежний API; additive columns остаются. Downgrade
не выполняется во время работы новых writers. Private plan содержит rollback images
и конфигурационную сверку соседних контейнеров; секреты не входят в публичный receipt.

Открыты: deployed p95/CPU/RSS/query buffers, browser cache/heap lifecycle на большой
фикстуре, длительная concurrent load/soak и неизвестные внешние writers. Реальный
small-catalog GET не заменяет эти проверки. Source tests не принимают весь EP-014…020;
исходный backlog остаётся **9 принято / 41 с открытыми критериями** до отдельной приёмки.
Recorder/UIA2/frame-correlated replay/capability preflight — следующие отдельные этапы.

## Визуальная приёмка установленной сборки

Настоящий Codex browser, UI/API **eb7a7c26**, реальные данные tenant: 19 активных,
3 архивных, 22 всех сценария; серверный поиск `Studio` дал 2 строки. Проверены
список и карточки, read-only DAG выбранной v1, совпадение hash и version ID в
истории, диалог запуска с той же версией и переход в редактор с 3 узлами и 32
действиями. Без выбранных целей кнопка запуска недоступна; задание не отправлялось.
Архивные строки не предлагают запуск или редактирование. Страница с одним набором
данных не позволяет проверить переход между несколькими страницами; pagination
подтверждается отдельными source regression tests, а не выдуманным живым прогоном.

После F5 сохранились вид списка, компактная плотность, размер страницы 25 и светлая
тема. Временные viewport overrides 724×884 и 390×844 сброшены; исходные карточки и
тёмная тема восстановлены. Document scrollWidth совпал с viewport на 1280, 724 и
390 px, в редакторе также 1280 px. Run и settings dialogs на 390 px имеют доступный
внутренний scroll и не расширяют страницу. В captured console warnings/errors — 0.
Ни browser network timing, ни heap/cache profile этой проверкой не измерялись.

Девять оригинальных JPEG имеют SHA256, размеры, source revision в
[manifest](SCRIPT-CATALOG-EVIDENCE.json). Примеры:
[исходник и светлая тема](assets/script-catalog/catalog-source-light-1280.jpg),
[редактор](assets/script-catalog/editor-light-1280.jpg),
[мобильные настройки](assets/script-catalog/settings-light-390.jpg),
[мобильный запуск](assets/script-catalog/run-light-390.jpg).

Воспроизводимая read-only проверка frozen receipts, Git blob hashes и JPEG:
`python -m scripts.audit.validate_script_catalog_delivery`.
Она не обращается к сети, Docker или Android и не заменяет исходные тесты.
