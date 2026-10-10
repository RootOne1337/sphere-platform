# AUD-100: большой UTF-8 журнал скрывал последние события APK

**13 сентября 2026 · Medium / operational diagnostics · воспроизведено на APK и production JVM-классе.**

[Источник журнала API, AUD-98](DEVICE-DIAGNOSTICS-SOURCE.md) · [Готовность](../../operations/READINESS.md)

## Root cause

`FileLoggingTree.readRecentLogs(maxBytes)` вычислял смещение через `File.length()`
в байтах, но передавал его в `Reader.skip()`, который считает символы. У большого
файла с кириллицей/emoji смещение уходило за EOF: API возвращал HTTP 200 и пустой
журнал. При объединении файлов бюджет уменьшался на `String.length`, поэтому
реальный UTF-8 ответ также мог превышать запрошенное количество байтов.

Прежние тесты повторяли алгоритмы и сравнивали константы сами с собой; настоящий
`FileLoggingTree` не создавался. Новый набор вызывает production class, настоящий
диск и поток записи. Mock используется только для Android `Context.filesDir`.

## Evidence / reproduction

На втором LDPlayer с установленной APK `0f1410e` временно создан отдельный
синтетический журнал **540035 bytes**: кириллица, emoji и конечный marker.
Только fixture получила mtime на две минуты позже, чтобы сообщения самого запроса
не меняли выбор проверяемого хвоста. Обычный authenticated
`POST /api/v1/devices/{device_id}/logcat`, body `{"mode":"sphere","lines":100}`,
отправил APK `REQUEST_LOGS(max_bytes=65536)`.

Ответ: **HTTP 200 / 0 bytes / marker отсутствует**, 0.531 s. PID APK сохранился.
В `finally` удалены только fixture в APK и `/data/local/tmp`; проверено сохранение
исходных log files. Пароли, ключи и настоящие журналы не публикуются.
[Native before](evidence/native-utf8-log-tail-before.json).

Новые tests: **6 failed / 4 passed до fix → 10 passed после**.
[Before JUnit](evidence/apk-log-tail-before.xml) · [After JUnit](evidence/apk-log-tail-after.xml).
Ранняя версия теста неверно вызывала перегрузку `Timber.log`; это исправлено до
сохранённого baseline. Ошибки harness не считаются дефектами APK.

## Fix и regression

[FileLoggingTree.kt](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt)
читает только хвост через `RandomAccessFile.seek` и bounded byte buffer. Общий
бюджет уменьшается на прочитанные bytes. UTF-8 decoder пропускает неполные/
повреждённые последовательности: отсечённое начало code point или незавершённую
запись после аварии. Полные последние символы сохраняются без раздувания ответа
replacement characters. Read использует тот же monitor, что и writer/rotation.

Запрос ограничен **256 KiB**, default по-прежнему 64 KiB, LogUploadWorker — 32 KiB.
Нулевой/отрицательный budget возвращает пустую строку. Чанки соединяются один раз
от старых к новым; чтение маленького хвоста не загружает целый файл.

[Regression](../../../android/app/src/test/kotlin/com/sphereplatform/agent/logging/FileLoggingTreeTest.kt):
ASCII, большой UTF-8, budget ротаций, все позиции границы кириллицы/CJK/emoji,
оборванная запись, порядок файлов, пределы budget, реальный writer, конкурентные
reads/writes и остановка тестового потока без утечки.

Полный dev JVM suite: **515 tests / 37 suites / 0 failures, errors, skipped**
([summary](evidence/apk-log-tail-full-summary.json)). Число уменьшилось с 522:
17 прежних replica/constant cases заменены 10 проверками настоящего класса.

## Статус и residual risk

**Native after принят:** APK из `9618a57` собрана с той же package/signature,
installation identity и enrollment credential. Signed dev/enterprise сборки
проходят по **29 tests**: 19 signed discovery + 10 настоящего logger.
BuildConfig и упакованный DEX проверены, management URLs по-прежнему пусты.
Bootstrap mirror этой новой сборки обновлён на текущий gateway, проверенный по
подписи документа v8; он остаётся временным и не является независимым ingress.
[Manifest](evidence/apk-9618a57-manifest.json).

Оба эмулятора обновлены через `adb install -r`, без сброса app data и ручного
открытия APK. Реальная команда вернулась на втором через **7.828 s**, на первом
через **8.406 s** от начала установки; существующие IDs и подписанный cache v8
сохранились, новых registration events в процессах нет. Пока один обновлялся,
второй выполнял команды и сохранял свой PID.

Повтор большого UTF-8 fixture на новом APK: **HTTP 200 / 4388 bytes / 100 строк**,
последний marker присутствует, replacement characters отсутствуют, **0.609 s**.
Fixture after на один byte короче before из-за слова AFTER вместо BEFORE в marker;
сам Unicode prefix одинаков. Fixture удалена, исходные журналы сохранены.
[Native after](evidence/native-utf8-log-tail-after.json).

Затем **12/12 команд** на двух APK и обычные журналы по 100 настоящих строк
(10067 / 10490 UTF-8 bytes), без synthetic fixture. Хеш установленного APK проверен
на обоих устройствах. Только после приёмки обновлён `LATEST-SphereAgent-pilot.apk`.
[Rollout evidence](evidence/apk-log-tail-native-rollout-20260913.json).

Writer остаётся асинхронным: чтение не обещает flush очереди. Queue overflow/disk
errors могут терять сообщения; retention ограничен. Повреждённые UTF-8 bytes
намеренно пропускаются. Snapshot ненадолго блокирует writer, максимум на 256 KiB
чтения; массовая нагрузка и физические устройства ещё не измерены. Центральный
архив, сквозная timeline и восстановление удалённых логов остаются открытыми.
Исправление требует обновления APK, backend API совместим.
