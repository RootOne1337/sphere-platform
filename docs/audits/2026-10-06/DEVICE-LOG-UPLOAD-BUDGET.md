# EP-033 B: ограничение приёма загрузок журнала

Дата: 6 октября 2026, Asia/Yekaterinburg. Статус: **OPEN**; исходный контракт
`12915dd7`, установленный backend до изменения `9889c9ac`.

[Приоритеты](ENTERPRISE-PRIORITIES.md) · [Reader и evidence](DEVICE-LOG-READ-BUDGET.md) ·
[Хранение](../../operations/DEVICE-LOG-STORAGE.md) · [Текущее состояние](../../operations/CURRENT-STATE.md).

## Подтверждённый дефект

`POST /api/v1/logs/upload` вызывает `await request.body()` и только после полного
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

## Реализованный контракт; установка ещё не выполнена

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

## Локальная проверка до packaged image

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
