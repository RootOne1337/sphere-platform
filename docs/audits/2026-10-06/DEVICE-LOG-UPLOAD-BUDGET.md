# EP-033 B: ограничение приёма загрузок журнала

Дата: 6 октября 2026, Asia/Yekaterinburg. Статус: **PARTIAL, установлен**;
EP-033 целиком **OPEN**. Исходный контракт `12915dd7`; установленный backend
`76596c39`, UI `5405d465`. Исторический backend до изменения — `9889c9ac`.

[Приоритеты](ENTERPRISE-PRIORITIES.md) · [Reader и evidence](DEVICE-LOG-READ-BUDGET.md) ·
[Хранение](../../operations/DEVICE-LOG-STORAGE.md) · [Текущее состояние](../../operations/CURRENT-STATE.md).

## Подтверждённый дефект

Исторический `POST /api/v1/logs/upload` в `12915dd7` вызывает `await request.body()` и только после полного
buffering сравнивает размер с 512 KiB. Поэтому этот лимит не ограничивает приём
большого body в память. `_get_log_file`, проверка размера для ротации и
`_clean_old_logs` выполняют файловые операции синхронно в HTTP event loop.
Append отдельно вынесен в общий thread pool; собственный admission budget всей
цепочки приём/хранение отсутствует.

[Изолированный probe](../../../scripts/audit/probe_log_upload_budget.py) сгенерировал
8 MiB как 128 переиспользуемых ASGI chunks по 64 KiB. Проверены два варианта:
с объявленным Content-Length и без него. Auth/tenant lookup заменены fixture;
настоящие APK, HTTP socket, PostgreSQL и Redis не используются.

[Baseline receipt](evidence/log-upload-budget/before.json): оба запроса возвращают
413, но перед отказом потребляют все **8388608 bytes / 128 receive calls** и
сохраняют `Request._body`. Python traced peak: 8421847 / 8403361 bytes.
Ни одного файла не создано; временный каталог удалён. Это не проверка авторизации,
всего RSS или поведения reverse proxy, и не установленная причина расхода C:.

## Контракт, установленный 6 октября в 01:37 UTC+5

Сохранить auth, device ownership, query/header compatibility, 204 успешного upload,
512 KiB body budget и формат дневных файлов. Не принимать часть журнала как
успешную полную загрузку.

| Граница | Предел | Результат отказа |
|---|---:|---|
| Объявленный Content-Length | 512 KiB | 413 до первого ASGI receive |
| Body без длины или с ложной длиной | 512 KiB | 413 на первом превышающем chunk, без append |
| Незавершённый body | 60 s на всю ASGI intake | 408, без append |
| Intake + filesystem операции | 4 одновременно на HTTP worker | 503 + Retry-After, без растущей очереди |
| Некорректная/не совпавшая длина | Строгая ASCII-десятичная длина | 400, без append |
| Разрыв клиента | Нет записи частичного body | Ошибка запроса, без 204 |

Проверять auth/ownership перед intake. Полностью читать только body, уложившийся
в byte/time budgets. Прекратить дальнейшие `receive` после превышения; не вызывать
`Request.body()` и не заполнять его body cache. 480 KiB ограничение Android
`LogUploadWorker` совместимо с этим серверным пределом.

Перенести mkdir, stat/rotation, append и старую очистку в отдельный фиксированный
executor. Admission token охватывает и ожидание body, и работу с файлом. Если HTTP
отменён после начала filesystem операции, token освобождается только при её
фактическом завершении; отмена coroutine не расширяет число работающих threads.
I/O error нельзя выдавать за успешную загрузку или отсутствие журнала.

## Ограничения этого этапа

- ASGI chunk уже выделен HTTP-сервером до передачи приложению. Предел принятого
  bytearray не является лимитом размера этого chunk, всех транспортных буферов,
  JSON/log middleware, Python objects или общего RSS.
- Reverse proxy может буферизовать body до backend. HTTP timeout измеряет время
  intake внутри ASGI, а не весь путь Android→туннель→proxy. Отдельные proxy budgets
  требуют проверки конфигурации; реальные slow-WAN тайминги не доказаны fixture.
- Четыре workers допускают до 16 uploads одновременно; предел установлен на worker,
  не глобально на весь парк. Между процессами нет общего upload semaphore.
- OS filesystem call нельзя безопасно остановить отменой HTTP. Нет hard I/O deadline
  или новой гарантии shutdown. После потери ответа клиент может повторить запись;
  idempotency ключа upload здесь нет, 204 не означает fsync/backup guarantee.
- Существующая ротация проверяет текущий дневной файл до append, не весь каталог.
  Ротация конкурентных writers и delete/upload race пока отдельно открыты.
- Нет общей квоты org/disk или независимой очистки при неактивном устройстве.
  Старые файлы в этом этапе не удаляются отдельно от существующего upload lifecycle.

## Обязательные проверки перед установкой

Проверить early reject без чтения; overflow без/с ложным Content-Length; точную
границу 512 KiB; бинарные/UTF-8 bytes без преобразования; cancellation/disconnect
и total timeout без частичного файла; saturation до чтения body; освобождение
слота после read error и actual writer finish; event-loop responsiveness при
зависшем writer; I/O failure; tenant/auth rejection перед receive.

Сравнить before/after на тех же chunks и отдельно прогнать route+reader регрессии.
Проверить packaged production image без mounted application source и синхронность
OpenAPI. Затем заменить только подтверждённый backend image, сохранив том журналов,
исходные byte prefixes, соседние контейнеры и rollback. Срезы online/ready/log read
и настоящее поступление загрузок сохранять отдельно от тестовых доказательств.

До этих проверок исправление не объявляется установленным; baseline 9 принято /
41 открыто сохраняется. EP-033 целиком этим этапом не закрывается.

## История локальной проверки до packaged image

[Intake service](../../../backend/services/device_log_upload.py) ·
[Route](../../../backend/api/v1/logs/router.py) ·
[Регрессии](../../../tests/devices/test_log_upload_budget.py).

Новые 34 cases и прежние 26 reader / 3 diagnostics-budget cases прошли: **63 passed**.
Ruff изменённых файлов и mypy двух изменённых backend-модулей прошли.
Изменение опубликованного контракта 400/408/413/503 отражено в generated OpenAPI.
Локальная среда имеет 571 унаследованный warning; её версии зависимостей не выдаются
за точные зависимости production image. Packaged image и живой HTTP ещё впереди.

Первые прогоны выявили две особенности тестирования deadline: уже доступные ASGI
chunks могут не отдать управление планировщику cancellation, поэтому после каждого
chunk проверяется monotonic deadline; тест медленного receive фиксирует попытку
до ожидания, чтобы загрузка Windows не превращала корректный ранний timeout в
ложное падение проверки. Не увеличивался реальный production deadline: он 60 s.

Working-tree probe той же 8 MiB fixture: объявленная oversized length отвергается
без receive; без длины — после девятого chunk (589824 bytes переданы ASGI), вместо
128 chunks / 8388608 bytes. Body cache отсутствует. Этот provisional результат
не выдаётся за exact-source build; повтор после commit будет сохранён отдельно.

### Исправление генерации схемы

Первый exporter в локальной среде с Pydantic 2.6 внёс посторонние изменения в `$ref`
и Literal schemas. Это было обнаружено до установки: схема перегенерирована с
зависимостями установленного production image `9889c9ac` и Git-архивом нового backend.
`backend/requirements.txt` между sources совпадает. Экспортер работал без сети и с
readonly application mount; это отдельная генерация, не проверка нового packaged image.
Сравнение полного JSON с `12915dd` подтвердило: меняются только четыре upload responses
400/408/413/503. Новый образ обязан отдельно пройти `export_api_docs --check`.

Дополнительный ASGI transport case проверяет HTTP dispatcher, JSON ошибки и пустой
204 response: после допустимой записи rejected chunked body останавливается на
девятом chunk и не меняет существующий файл. Теперь **35 upload cases passed**,
включая этот HTTP-контракт. Auth/ownership здесь по-прежнему fixture, не PostgreSQL RLS.

## Проверка production image и установка

Source `76596c394f5332bd0131a9fde7e3476ba7c00d52`; image ID
`sha256:485728529eb13daab946233306ac19e1f6f544ae491460a23ac4ba22a13dee8b`.
Application source взят из Git archive этого commit; при проверках backend source
не подменялся bind mount. Tests/config mounts readonly; контейнер без сети,
memory 1 GiB / CPU 2 / tmpfs 128 MiB. Это границы тестового запуска, не новый
production resource limit или проверка всего парка.

- 537 device/status/WebSocket/VPN cases (включая 35 upload cases) и 35 resource cases: **572 passed**,
  0 failed/errors/skipped. JUnit и receipts сохранены отдельно.
- Mypy всего backend, scoped Ruff backend/new tests/probes прошли.
- Generated OpenAPI exporter `--check` прошёл в том же образе.
- Схема отличается от baseline только четырьмя upload response descriptions.
  Dependency compatibility проверена shipped versions, не старым локальным Pydantic.

Повтор идентичного 8 MiB probe после commit: declared oversized body — **0 receive**,
Python traced peak 6149 bytes; без Content-Length — **9 receive / 589824 bytes**,
peak 530137 bytes. Body cache отсутствует; 413, 0 stored files, temporary cleanup.
До исправления оба варианта читали 128 chunks / 8388608 bytes с peak около 8 MiB.
Это изолированная allocation-проверка: не process RSS, нагрузочный SLA или причина
роста Windows C: / Docker VHD.

На live gateway [3015](http://127.0.0.1:3015/logs) заменён только backend.
Постоянный том, остальные mounts и log rotation сохранены. **14 исходных файлов /
3614902 bytes** проверены по original-byte prefix SHA256 после замены; writer UID1001.
Сохранены identity/image/start/mount/log-config **45 соседних контейнеров**.
UI/APK/OTA/туннели не изменялись. Перед/после установки: 14 online / 5 offline из 19.
Ready успешен. Это два конечных среза, не zero downtime или continuous uptime proof.

## Живые HTTP и поступление данных

Срез **6 октября, 01:42:53 UTC+5**: real PH025 GET вернул 1000 строк; scan 196608 bytes,
response-line JSON 136492 bytes; metadata явно сообщает line-limit truncation.
Два настоящих HTTP POST через gateway — declared и chunked, по 524289 bytes —
вернули **413**. Это административный JWT в X-API-Key с реальным tenant lookup;
не отдельная проверка APK credential или socket receive-count. Rejected fixture
отсутствует в проверенном tail; успешные synthetic uploads не отправлялись.
Новая own API-сессия закрыта 204; повтор чтения с её токеном получил 401.

Без отправки Android-команд обнаружены новые серверные upload separators после
установки в **5 из 14 файлов**. Получено 324393 дополнительных bytes; полный размер
каталога этого среза 3939295 bytes. Все 14 prefixes / 3614902 bytes ещё совпадают.
Последнее серверное время upload — 20:42:43 UTC; raw APK logs/device-path manifest
не публикуются. Данные подтверждают поступление загрузок после переключения,
не уникальность каждого batch, отсутствие повторов или здоровье остальных устройств.
Client Android timestamp и серверный upload UTC не отождествляются.

В реальном встроенном браузере проверены авторизация, непустой PH025 журнал,
manual refresh, no-match search и сообщение о ограниченном scope. Component badges
показывают **WEB 5405d465 / API 76596c39 / MISMATCH**: разные revisions здесь
ожидаемы и сохранены, новый UI не устанавливался. Screenshot содержит только
safe no-match результат, не содержимое APK-журнала.

[Pinned evidence](DEVICE-LOG-UPLOAD-EVIDENCE.json) ·
[Проверка целостности артефактов](../../../scripts/audit/validate_log_upload_budget.py).
Сохранены 14 очищенных от секретов receipts, JUnit двух наборов, 12 hashes source
файлов и один настоящий browser capture. Offline checker прошёл; также сохранены
предыдущие reader/storage proofs. Проверены 774 локальные ссылки / 19 anchors в
11 обновлённых документах и 41 уникальный открытый пункт приоритетов.
CI snapshot в 01:48 UTC+5: Preview success; Android in progress; Backend/Frontend
queued. Это не полный зелёный CI. Последующий evidence/docs commit имеет собственный CI, не наследует зелёный
статус source. **9 принято / 41 открыто; EP-033 OPEN**: следующий ресурсный этап —
общие квоты, независимая retention очистка, согласованная ротация/удаление и
backup/restore с доказательствами. Без доказанного writer host storage incident открыт.
