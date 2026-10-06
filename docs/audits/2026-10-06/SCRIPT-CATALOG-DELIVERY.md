# Каталог сценариев без загрузки исходников

Дата: **6 октября 2026**. Source implementation и проверки ниже завершены;
на момент первого коммита этого документа живой UI/API ещё **a670a3df / c2b91e32**.
Установка и её доказательства добавляются отдельным receipt, а не выводятся из CI.
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
| PostgreSQL contract + legacy workflows + unit | 148 passed, 0 failures/skips | Disposable loopback audit PG/Redis |
| Maintenance | 22 passed, 0 failures/skips | Реальные row locks/RLS/backfill; временные org удалены |
| Large source budget | 1 passed | 100 сценариев × 500 узлов × 480 KiB current source |
| Полный frontend | 1506 passed / 126 suites | Hook/page/fixtures hashes сохранены в receipt |
| TypeScript | Passed | После двух scope/cache hardening fixes |
| Полный backend mypy | Passed | Версия из shipped requirements 2.3.1 |
| Ruff backend/tests/maintenance | Passed | Версия из shipped requirements 0.15.2 |
| OpenAPI export/check | Passed | Declared HTTP schema, без lifespan/HTTP/device execution |

Ранее локальный Ruff 0.3.0 остановился на существующей exact-int проверке credentials.
После выравнивания инструментов с pinned requirements весь scope прошёл. Этот отказ
не скрыт; product credentials code не менялся ради старой lint версии.

Budget fixture имеет name64/description256. Канонический current source: **491520 B**
на версию; фактический legacy raw body **48889157 B**, metadata body **85176 B**.
Сокращение **99,8258%**, ниже ворот 256 KiB. При minimal source33307 B catalog имеет
те же85176 B. Per-page25/50/100/200 проверены на одну scalar SQL projection без DAG/hash.
Single-request local ASGI timings: catalog51,383/62,707 ms (small/heavy), legacy
376,325/854,611 ms. Это не deployed p95, SQL buffers, CPU/RSS, browser heap или WAN.

Исходные тесты:
[contract](../../../tests/test_script_catalog_contract.py),
[stored JSONB/RLS/snapshot/migration](../../../tests/production/test_script_catalog_metadata.py),
[maintenance](../../../tests/production/test_script_catalog_maintenance.py),
[budget](../../../tests/production/test_script_catalog_budget.py),
[frontend contract](../../../frontend/__tests__/hooks/useScriptCatalog.test.ts).

## Установка и оставшиеся ворота

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
