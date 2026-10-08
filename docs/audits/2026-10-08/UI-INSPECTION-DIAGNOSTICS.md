# XPath: диагностика одного чтения Android

8 октября 2026, Asia/Yekaterinburg. Связанный открытый incident:
[установленная приёмка управления и XPath](CONTROL-HANDOFF-INSTALLED-ACCEPTANCE.md).
Один auto read ранее завершился `Shell command exited with code 1`.
Причина и этап того исторического отказа не установлены. Повторные успешные
чтения сами по себе не устраняют intermittent failure.

## Проблема и изменение

`POST /api/v1/devices/{id}/ui-hierarchy` возвращал общий502 для отказа native
команды или неполного receipt. Оператор не мог отличить отказ `wm size`,
`uiautomator dump` и `cat`, а ошибка cleanup не была связана с исходным отказом.
Новая диагностика сохраняет строковый `detail` и исходный HTTP status;
добавляет ограниченные заголовки и одно структурированное событие на snapshot.
Веб показывает понятное описание, этап, ID и кнопку копирования диагностики.

Текущий этап **source prepared**, обновление3015 требует successful exact-source
CI, admission того же image и установленной проверки. Runtime до обновления:
UI `e88c4db`, API `2225f73`, PH011 APK10249.

## Протокол диагностических заголовков

Заголовки выдаются после приобретения собственного Redis lock и завершения
попытки очистки. Ошибки авторизации/чужого устройства или приобретения lock
не являются чтением дерева и не получают native diagnostic ID.

| Заголовок | Значение |
| --- | --- |
| `X-Sphere-Ui-Snapshot` | UUID32 hex, совпадает с snapshot ID и log event |
| `X-Sphere-Ui-Stage` | первый failed stage; `complete` при успешном чтении |
| `X-Sphere-Ui-Reason` | ограниченный reason enum; `ok` при успешном чтении |
| `X-Sphere-Ui-Native-Exit-Code` | только точный ненулевой Android exit1..255 |
| `X-Sphere-Ui-Cleanup` | `confirmed` / `unconfirmed` |
| `X-Sphere-Ui-Lock-Release` | подтверждение удаления именно UUID-owned lock |
| `X-Sphere-Ui-Elapsed-Ms` | elapsed чтения и cleanup, не video/input latency |
| `X-Sphere-Ui-Rpc-Count` | число попыток fixed native RPC, включая cleanup |
| `Cache-Control` | `no-store`, в том числе ошибки уже начавшегося чтения |

Этапы: `geometry_before`, `dump`, `read_xml`, `geometry_after`,
`validate_geometry`, `validate_tree`, `cleanup`. Первый отказ фиксируется
до cleanup; cleanup не заменяет failed stage/reason/native exit code.
Отказ cleanup не уничтожает успешно прочитанное дерево.

Причины: `native_exit_nonzero`, `native_input_busy`,
`native_input_outcome_unknown`, `native_command_failed`,
`invalid_device_receipt`, `transport_unavailable`, `command_deadline_exceeded`,
`snapshot_deadline_exceeded`, `display_geometry_changed`,
`inspection_internal_error` и существующие ограниченные parser reasons
`display_geometry_*` / `ui_dump_*`. Cancelled HTTP request журналируется
как `request_cancelled`/499, когда выполнение доходит до final trace.
Это не обещает доставку ответа отменившему запрос клиенту или successful cleanup.

## Границы и конфиденциальность

- Не добавляются retry, новые Android команды, рост timeout или input replay.
- 40s total read, 8s один native RPC, отдельная bounded cleanup attempt;
  browser timeout50s и Redis UUID lock60s сохраняются.
- Native error классифицируется по точным известным строкам. Неизвестный
  текст остаётся `native_command_failed`; raw stderr/command/XML не публикуются.
- Лог `ui_inspection_finished`: device/snapshot IDs, HTTP status, known reason,
  native exit code, elapsed, до7 scalar stage durations, RPC count,
  cleanup/lock confirmation. Не хранит tree или текст элементов.
- Веб принимает только известные stage/reason, UUID32 и bounded integer.
  Неизвестные заголовки переходят к существующему строковому API error.
- На ошибке автоопрос остановлен, ещё валидное дерево сохранено. Новое чтение
  только через явное обновление/возобновление по существующим правилам.
- Видео и дерево по-прежнему независимы; snapshot diagnostic ID не делает
  дерево атомарным с кадром. Живые жесты и gate XPath→Control не меняются.
- 200 с `cleanup=unconfirmed` — прочитанное дерево, отдельная проблема cleanup;
  `lock-release=unconfirmed` не даёт права удалить чужой lock.

## Проверки и доказательства

Новые тесты сначала запускались против прежнего кода:
backend11failed/5passed из-за отсутствующих diagnostic headers;
frontend1failed/20passed, показывал только `generic root failure`.

После изменения:18 HTTP/SQL/Redis regression cases passed; Android transport
явно подменён fixtures, это не Android canary. Проверены permissions/scoping,
чужой lock, offline503, native exit1, busy/unknown input, неполный XML/receipt,
смена геометрии, deadline и internal failure, успешное дерево с failed cleanup.
Смешанный read failure + cleanup failure сохраняет оригинальный этап.
Проверены отсутствие private error/XML в headers/body и structured trace.

151 frontend tests /4suites passed: inspector, continuous pointer, pointer
control и error mapping. Проверены сохранение дерева, остановка polling,
fallback unknown headers, prototype keys, неправильные/большие exit codes.
Non-incremental TypeScript passed; targeted Ruff passed.
18 installer boundary tests passed: admit только reviewed router/scalar trace,
dependency/schema/bootstrap/runtime/environment protections сохранены.

Local mypy не завершён: установленный файл SQLAlchemy `orm/sync.py`
5779B содержит invalid UTF-8 byte0xff на offset4096, SHA-256
`81f6db1651ee18dbd4412bf32510405f2f211ece97bc21374fc3b82f06c5e3f6`.
Это отдельный дефект окружения, не ошибка типов данного patch; необходим
полный CI на clean dependencies. Причина повреждения не установлена.

## Следующий контроль и остающиеся проблемы

После CI установить отдельно API/UI из admitted artifacts, без миграций/OTA.
Проверить native successful read/cleanup/log correlation, browser дерево,
highlight, read→Control и отсутствие лишнего input. Error UI должен пройти
визуальную проверку на явно обозначенном synthetic receipt без native fault.
Исторический root exit1 остаётся OPEN до нового реального отказа с stage/reason.
Не выводить root cause из одного exit code и не увеличивать таймаут вслепую.

SF26-05OPEN; product ledger9accepted/41open. Rich recording XPath/crop/pixel,
correlated playback, remote/fleet fault qualification и storage incident
сохраняются в аудите; диагностический patch не закрывает эти пункты.
