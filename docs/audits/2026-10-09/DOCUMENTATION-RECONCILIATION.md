# Повторная сверка документации и effective статусов

Дата: **9 октября 2026 (UTC+5)**. Source base: **f79de047**. Область: документация,
машинный реестр и consistency guards. Backend/UI/APK не заменялись, новых Android
actions, tasks, cleanup, collectors или fleet acceptance в этом проходе нет.

[Действующие работы](../../operations/WORK-STATUS.md) ·
[Машинный реестр](../../operations/STATUS-REGISTRY.json) ·
[Инвентарь](../../operations/DOCUMENT-INVENTORY.json) ·
[Предыдущий crosscheck](CHAT-CODE-RECONCILIATION.md).

## Итог и что не было переаттестовано

Все **388 tracked/new Markdown** классифицированы по назначению. Локальные
inline navigation paths проверены в8 входных документах и 63 руководствах; anchors,
reference-style links, сторонние URLs и исполнение runbook commands не входят
в этот bounded scanner. Это не построчная аттестация всех инструкций.
223 прежних отчёта, 74 проектных документа, 6 ADR, 7 файлов правил и 6
supporting docs не переписаны как текущие возможности; этот новый receipt добавляет
ещё один dated document. Итоговый inventory хранит224 датированных отчёта.

Глубокая source/runtime сверка 50 EP уже записана предыдущим crosscheck. Здесь
проверены расхождения входных указателей, контракты current versus history,
15 требований из чата и exact installed schema. На новую документацию не
переносятся прежние source fingerprints или live results как новая приёмка.

Продукт: **9 принято / 41 открыто**. В остатке30 расширений возможностей, 6 задач дизайна и структуры,
5 будущих направлений. Все шесть подтверждённых defects первоначального аудита имеют
recorded scope EP-001–006; это не исключает новых runtime defects в PARTIAL EP.
Оценка оставшегося охвата:16 M / 18 L / 7 XL, не сроки и не severity.
Legacy: **34 source-fixed / 7 незакрытых**, отдельная пересекающаяся область;
F32/F33/F39 PARTIAL, F34/F36/F40/F41 OPEN. Два предыдущих изменения — коммиты,
отдельного двухпунктного problem ledger нет. Числа разных аудитов не складываются.

## Подтверждённые документационные расхождения и исправления

| ID | Было | Исправление / граница |
| --- | --- | --- |
| DOC-01 | README, docs catalog и freshness guide начинались с установок 6–7 октября installed versions | Current header и единый WORK-STATUS; старые checkpoints сохранены как явно исторические |
| DOC-02 | Второй status section README называл 1 октября текущим |Актуальный статус 9 октября отдельно; срез 1 октября помещён в history |
| DOC-03 | Frozen baseline OPEN и effective9/41 читались как разные текущие списки | STATUS-REGISTRY сохраняет baseline criteria/dependencies, scope closures и evidence; old7 имеют отдельный crosswalk |
| DOC-04 | Инструкция Studio говорила неопределённо «Distributed lease OPEN» | Redis continuous viewer lease существует; общая viewer/task/API/scheduler arbitration остаётся OPEN |
| DOC-05 | Leaf continuous contracts после integration всё ещё читались как «routes не подключены» | Current startup/runtime/live pointer добавлен над явно historical component checkpoint |
| DOC-06 | Host guide содержал настоящее время работающих observers после их deadline | Current coverage gap и новый finite read отдельно от исторических8h окон |
| DOC-07 | APK guide, UI guide, RLS head, v4.6/v4.7 labels и farming analysis могли выглядеть текущими | Pinned PH01110249 scope, current pointers и явные historical/design labels; fleet и RLS sign-off не выдуманы |
| DOC-08 | Manual API guide подразумевал доступную public root schema | Local gateway18080root GET/openapi.json вернул404; documented snapshot/direct FastAPI/gateway routing разделены |
| DOC-09 | Chat microrequirements терялись внутри общего EP scope |15 CHAT IDs: finite accepted scope/remaining/evidence и parent EP; trajectory и rich bundle не закрыты кнопками/normal gestures |
| DOC-10 | Нет automatic guard от stale summary, omitted docs и false closure | Проверка реестра и 15 регрессионных тестов, подключены в Backend CI lint job |

Root/docs README сохраняют историю в collapsed sections; основные anchors и
операторские ссылки не удалены. DOCUMENTATION больше не дублирует длинный deployment
changelog; старая версия доступна по pinned git URL. Исторические audits/JSON
receipts предыдущих проходов не изменены. Единственный новый audit — этот проход.

## Повторная проверка runtime и API формы

Read-only Docker inspect подтвердил в **2026-10-08T23:10:38Z**:

- UIec3f2267: тот же container `0880bfe0`, image `2cb783f7`, старт 21:43:08Z;
- APIbe803773: тот же container `1b45b96a`, image `49a0ac9d`, старт 20:17:14Z;
- оба running; это не новая stream/input/Android canary;
- PH011 `1.2.49-dev/10249` взят из предыдущего pinned installed receipt, новый
  inventory всего парка не снимался;
- visible matching collector processes 0; scope — доступные process command lines,
  не privileged kernel доказательство отсутствия любого стороннего collector;
- одно чтение C: free 50 563 411 968 bytes. Ни скорость расхода, ни writer этим не установлены.

Schema экспортирован **из установленного API image `be803773`** вызовом app.openapi()
без startup hooks и HTTP actions. Canonical JSON совпал с committed docs/openapi.json:
**182 HTTP operations / 144 paths**, SHA-256
`488e804a84f62de7c81313b14d5e2dfca522c630d2583b0712c9399950950968`.
Успешный schema export не означает работающие handlers/auth/outcomes и не
описывает WebSocket control. Корневой HTTPschema request через local gateway
сохранил 404; routing не менялся и отдельная браузерная Swagger-приёмка не выполнена.

## Требования чата и остаток

Принятый finite scope: возврат scroll 2132.5→2132.5, свободный node add/drop/
disconnect/reconnect/Undo, четыре системные кнопки рекордера, обычные live MOVE
на PH011, native PNG в согласованном scope. Это не full parent EP closure.

PARTIAL: mobile composition и landscape readability, WS invalidation плюс
15 s polling, общая inspector/inventory/action runtime matrix. Source-fixed, не
installed:1577e01e clock correction tap→XPath→tap→late key ACK.

OPEN: continuous trajectory recording, automatic pre-action XPath/crop/pixel
bundle, correlated replay,128 thumbnail wall/shared budgets/Connect all/
synchronizer, общий input owner, idle receipt failure и новое host writer coverage.
Deferred: универсальные ресурсы, AI/VPN providers, исследование direct browser↔Android.
Полные критерии/ссылки находятся в WORK-STATUS/JSON; здесь только readable summary.

## Проверки и автоматическое удержание актуальности

- Registry:50 unique IDs, 9 evidence-backed accepted, 41 OPEN; criteria/dependencies/
  priority/kind сохранены из frozen baseline, legacy 7 отдельно,15 chat references.
- Evidence fingerprints используют LF-normalized repository bytes: CRLF checkout
  Windows не создаёт ложного mismatch в LinuxCI. Это не перенос fingerprint
  старого source snapshot на изменившийся current guide.
- Inventory/local paths:388 documents, 8 entrypoints + 63 guides, missing paths 0.
- 15 unittest regressions: false closure, counts/duplicates/criteria, modified
  receipt, fleet overclaim, source-versus-install, legacy overlap, unknown chat
  mapping, omitted document, Markdown links/code examples, CRLF portability,
  human table drift, чужой closure receipt и ложный trajectory accepted.
- Scoped Ruff и diff whitespace checks прошли; full frontend/backend tests не
  перезапускались из-за documentation-only/runtime-unchanged scope.
- Exact source **f79de047** workflows завершились успешно: [Frontend37856889527](https://github.com/RootOne1337/sphere-platform/actions/runs/37856889527),
  [Backend37856889502](https://github.com/RootOne1337/sphere-platform/actions/runs/37856889502),
  [Android37856889561](https://github.com/RootOne1337/sphere-platform/actions/runs/37856889561),
  [Preview37856889489](https://github.com/RootOne1337/sphere-platform/actions/runs/37856889489).
  Следующий commit с checker имеет собственный CI и не наследует эти conclusion.

```powershell
python -m scripts.check_documentation_status
python -m unittest discover -s tests -p test_documentation_status.py
```

При добавлении/удалении Markdown: `python -m scripts.check_documentation_status --write-inventory`.
Команда меняет только inventory и запускает проверку, не services/collectors.
Полный EP-049 остаётся OPEN: автоматическая consistency не заменяет semantic
freshness каждого guide, actual install admission и дальнейшую визуальную приёмку.

## Следующий этап direct media

Не требуется закрывать все будущие 41 функции до архитектурного исследования.
Нужны versioned contract, measurement baseline, auth/control ownership и resource
accounting; для production pilot дополнительно исправленный idle input, global
arbitration, session/geometry fences, budgets и direct/relay/network/reconnect/
revocation/version compatibility acceptance. Технология не выбрана и transport
не внедряется этим проходом. Online 14/18—наблюдение пользователя, не uptime SLA.
