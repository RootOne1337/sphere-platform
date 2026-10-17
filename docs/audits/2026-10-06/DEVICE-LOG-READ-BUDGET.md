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
| HTTP `lines` | 1…10000 | Query validation; frontend запрашивает 1000 |
| Search | До 512 символов | Query validation; поиск только в проверенном tail |
| Одновременное чтение | 4 на worker, без ожидания admission | HTTP 503 + `Retry-After: 1` |

2 MiB не является пределом RSS или гарантией CPU-тайминга. Native allocations,
Python-объекты, JSON и OS buffers измеряются отдельно. Число workers умножает
admission budget; four-worker runtime допускает до 16 операций, не четыре глобально.

Пустой/отсутствующий каталог собственного устройства возвращает пустой измеренный
срез. Permission/filesystem error, каталог сверх budget или повреждение файла во
время чтения дают HTTP 503; они не превращаются в «логов нет». Дата имеет строгий
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
последних 1000 строк на той же 24 MiB fixture; живые сервисы не используются.

Локальные результаты до installation записаны отдельно от shipped image,
CI и настоящего HTTP/browser. Этот исходный раздел описывает границы проверки;
завершённая установка записана ниже с конкретными revisions и временем.
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
общим размером 454385 bytes находятся в `/tmp/sphere_device_logs`, в writable layer.
Recreate этого контейнера не сохраняет полученную историю. Это отдельный доказанный
дефект долговечности, а не доказанная причина уменьшения свободного Windows C:.

[Контракт хранения и безопасного переноса](../../operations/DEVICE-LOG-STORAGE.md)
добавляет named volume в full/production/local-pilot Compose и non-root ownership
в image. Установка с переносом/проверкой hashes записывается отдельным receipt;
само изменение Compose не считается успешной миграцией существующей истории.

## Установленный результат и пределы доказательств

**6 октября 00:55 UTC+5 / 5 октября 19:55 UTC:** API `9889c9ac`, UI `5405d465`
на [3015/logs](http://127.0.0.1:3015/logs). Reader/UI source `5405d465`; отдельный
storage source `9889c9ac` меняет Dockerfile/Compose, сохраняя байт-в-байт backend
application tree и frontend. Разные component SHA в badge ожидаемы; они не
объявляются одинаковыми или доказательством совместимости всех API.

[Pinned manifest](DEVICE-LOG-READ-EVIDENCE.json) содержит 25 очищенных от секретов receipts,
четыре native browser captures и Git source hashes. [Офлайн checker](../../../scripts/audit/validate_log_read_budget.py)
проверяет их целостность; он не обращается к production и не подтверждает текущее
online, длительную стабильность или полную приёмку EP-033.

Сравнение на той же 24 MiB fixture: возвращены 1000 строк, их SHA256 совпадает.
Python traced peak: **48271208 → 468754 bytes** (46,04 → 0,447 MiB),
прочитано 25165824 → 131072 bytes. Peak примерно в 103 раза меньше на этой fixture.
Это не RSS, не гарантия памяти произвольного запроса и не диагностика Windows writer.
Whole-file reads отсутствуют; temporary files удалены до записи receipt.

Проверки shipped reader image: **502 device/status/WS/VPN + 35 resource cases**,
mypy 235 source files, scoped Ruff и generated OpenAPI passed. Ни сеть, ни mounted
application source не использовались. Final storage image повторно прошёл 26 reader
cases; его application tree равен исходному tested reader. Настоящий non-root
UID 1001 создал файл в новом томе; второй disposable container прочитал те же байты.
Временный test volume был пустым, отдельно созданным и удалён после проверки label.
**23 real Compose merge/settings cases**, changed test/checker lint passed.
UI: **1307 tests / 121 suites**, production Node 24 build/types и changed-file lint
passed. Унаследованные library/config/build warnings не выдаются за отсутствие warnings.

Исходная API-установка 19:41 UTC и UI 19:42 UTC сохранены отдельно. До и после API
видно 14 online/5 offline; до и после UI 9/10. Потеря появилась до UI replacement.
Ограниченный backend log window содержит 1005 disconnects, несколько в одну секунду,
и 4009 replacement closes; heartbeat timeout в этом срезе не найден. Причина 1005
не определена: это не доказательство отказа Python, Tuna или APK.

### Миграция существующих файлов

Graceful stop только backend остановил writer workers; приватные stopped tar/staging
сохранены. Перенесены **14 файлов / 902996 bytes** в project-scoped `device_logs`.
Сверены SHA256 всех файлов до запуска, а затем исходных byte prefixes после rollback
и следующего recreate: новые uploads могли дописать конец файла. UID 1001 получил
права записи; owned temporary write canary удалён. Сохранены 45 соседних контейнеров,
их identity/image/start/mount/log config; прежние API mounts/rotation сохранены.
APK, OTA artifacts и туннели не обновлялись. Zero downtime не заявляется.

Две неудачные попытки не скрыты. Root helper с dropped DAC privileges не смог
повторно пройти в UID 1001 directory mode 0700: старый контейнер запущен до recreate,
staging/частично скопированные файлы сохранены. Retry работал как UID 1001 и проверил
ранее скопированные файлы. Затем raw Windows/WSL representations одного bind source
дали ложное несовпадение соседнего mount: guard вернул прежний image с постоянным
томом. После canonicalization совпали и pre-migration UI snapshot, и final 45 соседей.
Последующая установка final image сохранила все 14 исходных byte prefixes. Первый
probe logout во время restart не подтвердился; поздние probe sessions отдельно
завершены 204, revoked GET 401. Human browser session не завершалась.

Final replacement 19:55:29–38 UTC: 14 online/5 offline до и после. Позднее чтение
19:56:15 UTC показало 11 online, 3 explicit offline, 5 unknown из 19. Registry и coverage
имеют разные unknown semantics. Эти конечные срезы не являются многодневным SLA,
устранением reconnects или подтверждением 23 ожидаемых Android instances.

### Живое чтение и браузер

PH025 вернул **483 строки**, 65187 scanned bytes из 2 MiB, один файл; HTTP 200.
Не совпавший search вернул 0 строк с тем же измеренным источником. Недопустимые
calendar date/wildcard и search 513 chars дали 422. До накопления новых uploads старый
срез 5405 честно вернул 0 файлов; он не переименован в успешный nonempty read.

Живой браузер видел 483 строки, затем проверен search без совпадений и manual refresh.
Для screenshots выбрана эта настоящая search-state, чтобы не публиковать raw APK logs.
1440 px: обе темы; 390 px: controls и region внутри ширины, region 352/scroll 352.
Temporary viewport reset; исходная dark theme восстановлена; normal viewport 1280×720
без horizontal overflow. Query console logs вернул 0 warning/error entries в своём
ограниченном результате. Delete/Android commands не использовались.

[Desktop light](assets/log-read-budget/desktop-light.jpg) ·
[Desktop dark](assets/log-read-budget/desktop-dark.jpg) ·
[Mobile controls](assets/log-read-budget/mobile-light.jpg) ·
[Mobile source](assets/log-read-budget/mobile-sources.jpg).

При первом быстром capture сразу после viewport change получился переходный размер;
mobile/desktop captures повторены после DOM state и перерисовки. Manifest хранит
фактические JPEG dimensions, не только запрошенный viewport. Скриншоты не заменяют
полный accessibility/load аудит или проверку всех страниц.

### CI и следующая диагностика

Срез CI в manifest не подтверждает полный успех. Для `5405d465` frontend прошёл,
backend отменён, Android workflow завершился failure при cancelled job без steps.
Для `9889c9ac` frontend, lint/types, RLS и production bootstrap прошли; Tests и
Security отменены без выделенного runner. GitHub annotations прямо сообщают,
что hosted runner не получил задания после нескольких попыток. Причина записана
в [отдельном receipt](evidence/log-read-budget/source-ci-runner-annotations.json).
Это не провал выполненных тестов, но и не прохождение полного backend CI.
Android storage-source `9889c9ac` завершил tests и signed release smoke build:
[run 37365950910](https://github.com/RootOne1337/sphere-platform/actions/runs/37365950910).
Все шаги, включая проверку подписей smoke APK, прошли; это disposable CI signer,
не новый production APK или OTA rollout. Поздние docs-коммиты имеют собственный CI;
чужой зелёный результат или незавершённая проверка не наследуются.

APK-журнал содержит repeated `Cannot parse command` с отсутствующими required fields
и lifecycle SSLException/HTTP 502/1012; historical priority segment также содержит
DNS/HTTP404 failures. Содержимое действительно получено от агента, но timestamp
Android не содержит timezone; upload time и client event time нельзя автоматически
считать одним UTC clock. Current source уже имеет регрессию `noop` transport ACK;
само предупреждение не доказывает отсутствие этого handling в установленном APK.
Следующая диагностика должна сопоставить frame class, installed artifact/source,
route slot и server receipt. Причина live flicker и отказа произвольных commands
этими строками не доказана. Raw logs и private migration device-path manifest не
публикуются в Git.

**9 принято / 41 открыто; EP-033 OPEN.** Global quotas/sweeper, upload-before-buffering,
rotation concurrency, backup/restore и leak/load gates остаются обязательными.
