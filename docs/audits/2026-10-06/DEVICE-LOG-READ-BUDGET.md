# EP-033 A: ограниченное чтение сохранённых логов

**Дата:** 6 октября 2026, Asia/Yekaterinburg. **Приёмка EP-033:** OPEN.
**Область:** GET `/api/v1/logs/{device_id}`, UI системных логов; без изменения upload,
rotation, retention, глобальных quotas или работы Android.

[Приоритеты 41 оставшейся работы](ENTERPRISE-PRIORITIES.md) ·
[Исходное воспроизведение](evidence/log-read-budget/before.json) ·
[Текущее состояние](../../operations/CURRENT-STATE.md).

## Проблема и проверяемый результат

Раньше до трёх дневных файлов полностью читались/разбивались на строки в event loop;
`lines` и search ограничивали только конечную выборку. Три временных файла по 8 MiB
дали 48 271 208 bytes Python traced peak для запроса 1000 строк.

Новый reader идёт от конца самого нового файла блоками не больше 64 KiB. Перенос
между блоками ограничен одной строкой. Более длинная строка пропускается целиком;
обрезанный на границе byte budget фрагмент не выдаётся за исходную строку.
Результат возвращается в хронологическом порядке. UTF-8 с replacement invalid bytes,
разделители LF/CRLF; это не binary journal или экспорт произвольных line separators.

## Конечные бюджеты

| Ресурс | Предел на один запрос | Поведение по достижении |
|---|---:|---|
| Файловый scan | 2 MiB на все файлы вместе | Явный `scan_byte_limit`, без частичной строки |
| Сериализованный JSON-массив строк | 512 KiB | `response_byte_limit`; metadata — отдельный малый overhead |
| Исходная строка без LF | 16 KiB | Полностью пропущена, counter и `oversized_line` |
| Дневные файлы | 3 последних, либо точная UTC дата | `file_limit`, если более старые файлы не проверены |
| Размер directory catalog | 128 entries | HTTP 503 вместо произвольной выборки «новейших» |
| HTTP `lines` | 1…10000 | Query validation; frontend запрашивает1000 |
| Search | До512 символов | Query validation; поиск только в проверенном tail |
| Одновременное чтение | 4 на worker, без ожидания admission | HTTP503 + `Retry-After: 1` |

2 MiB не является пределом RSS или гарантией CPU-тайминга. Native allocations,
Python objects, JSON и OS buffers измеряются отдельно. Число workers умножает
admission budget; four-worker runtime допускает до16 операций, не четыре глобально.

Пустой/отсутствующий каталог собственного устройства возвращает пустой измеренный
срез. Permission/filesystem error, каталог сверх budget или повреждение файла во
время чтения дают HTTP503; они не превращаются в «логов нет». Дата имеет строгий
календарный YYYY-MM-DD без wildcard. Не читаются symlink log files/directories.
Каждый открытый descriptor закрывается при раннем завершении итерации.

## Event loop и отмена

Файловая работа исполняется в отдельном bounded ThreadPoolExecutor. До submission
берётся non-blocking semaphore token; новые запросы при перегрузке отвергаются.
Callback освобождает token только когда concurrent Future завершён или отменён
до начала работы. Cancelled HTTP coroutine не освобождает token работающего thread.
Contextvars request correlation передаются в worker; fixed-size pool/token state не
создаёт отдельный slot на device ID или растущую очередь.

Это соответствует ограничениям [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html):
работающий Future не останавливается `cancel()`, threads завершаются перед выходом
интерпретатора. Зависший OS/filesystem call нельзя безопасно прекратить отменой
HTTP. Byte bounds не объявляются hard wall-clock deadline или full shutdown SLA.
При таком отказе admission остаётся ограниченным; остальные API/WS не выполняют
этот filesystem call в event loop.

## Контракт UI

Существующие поля `device_id`, `lines`, `total` сохраняются; `total` — число
возвращённых строк, не полная длина архива. Новое typed поле `read` содержит
schema/scope, counts/budgets, reasons и omitted line counter.

UI показывает проверенные bytes/files, частичность и причины. Нет совпадений в tail
не означает отсутствия в старом журнале. Пустой ограниченный результат не получает
надпись «для устройства нет логов». Старый backend без metadata явно обозначается
как не подтвердивший полноту. Противоречивый/чужой/слишком большой ответ отвергается;
cached строки не показываются как успешное чтение после ошибки, delete выключен.

Не добавляются credentials, сырые пути или filename источника в response. Tenant
lookup и device:read выполняются прежде файлового чтения. Delete/upload и их права
остаются прежними. Эта реализация не является новым общим журналом EP-032.

## Проверки и границы приёмки

Регрессии проверяют порядок файлов/строк, точную дату и search, UTF-8/chunk
boundaries, пустые/CRLF строки, общие scan/response budgets и JSON escaping,
oversized lines, отсутствие whole-file read, unavailable source, directory bound,
admission, event-loop responsiveness и отмену HTTP до завершения worker.
UI проверяет частичный/legacy/malformed ответ, отсутствие ложной полноты и старые
source ownership/delete controls. Изолированный probe сравнивает content hash
последних1000 строк на той же24 MiB fixture; живые сервисы не используются.

Локальные результаты до installation записываются отдельно от shipped image,
CI и настоящего HTTP/browser. На этом этапе не объявляется установка завершённой.
EP-033 не закрывается: independent retention sweeper, org/global quotas,
rotation concurrency, upload body budget до buffering, disk forecast и drop metrics
ещё требуют отдельной реализации. Windows disk writer и длительная RAM leak
приёмка остаются UNKNOWN/OPEN; memory amplification fix их не диагностирует.

## Код и воспроизведение

[Reader](../../../backend/services/device_log_reader.py) ·
[HTTP route](../../../backend/api/v1/logs/router.py) ·
[Typed schema](../../../backend/schemas/device_logs.py) ·
[Backend regressions](../../../tests/devices/test_log_read_budget.py) ·
[UI](../../../frontend/app/%28dashboard%29/logs/page.tsx) ·
[UI regressions](../../../frontend/__tests__/logs/page.test.tsx) ·
[Probe](../../../scripts/audit/probe_log_read_budget.py).

```powershell
python -m pytest tests/devices/test_log_read_budget.py
python -m scripts.audit.probe_log_read_budget --expect-bounded --output .local-pilot/log-probe.json
```

Probe записывает source SHA, working-tree flag/hashes и очищает временные files
до сохранения receipt. Незакоммиченная проверка не выдаётся за exact-source build.

## Найденный при установке storage gap

Срез 5 октября 19:46 UTC / 6 октября 00:46 UTC+5: в установленном backend
`5405d465` отсутствует `SPHERE_LOGS_DIR` и перекрывающий mount. Семь новых файлов
общим размером454385 bytes находятся в `/tmp/sphere_device_logs`, в writable layer.
Recreate этого контейнера не сохраняет полученную историю. Это отдельный доказанный
дефект долговечности, а не доказанная причина уменьшения свободного Windows C:.

[Контракт хранения и безопасного переноса](../../operations/DEVICE-LOG-STORAGE.md)
добавляет named volume в full/production/local-pilot Compose и non-root ownership
в image. Установка с переносом/проверкой hashes записывается отдельным receipt;
само изменение Compose не считается успешной миграцией существующей истории.
