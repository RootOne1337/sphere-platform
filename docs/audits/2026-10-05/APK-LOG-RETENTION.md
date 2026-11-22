# R09 — ограничение постоянных логов и очереди APK

**Дата:** 5 октября 2026, Asia/Yekaterinburg; измерения — UTC 4 октября.
**Source:** `ae90715`; версия кандидата `e75d365`, `1.2.45-dev / 10245`.
**Собранный artifact:** `bdfebea`, `1.2.45-dev / 10245`, 23:14:07 UTC.
**Установленный canary:** локальный PH010 и удалённый PH025 получили 10245 через
адресное root recovery; 12 других online остаются на 10244, normal/android-dev — 10209.
Это адресная приёмка кандидата, не stable promotion и не обычный OTA rollout.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Исходное наблюдение](HOST-DISK-GROWTH.md) ·
[Диск хоста и writer attribution](DISK-WRITER-ATTRIBUTION.md) ·
[Проверки и hashes](APK-LOG-RETENTION-EVIDENCE.json).

## Подтверждённая проблема

У PH010 и PH025 на установленном10244 было шесть обычных файлов логов при
configured maximum пять. Каталоги занимали около10–11 MiB. Это отдельная
ошибка ограничений; она не объясняет накопление сотен гигабайт на Windows.
Особенно нельзя переносить размер логов удалённого Android на C: локального ПК.

В прежнем коде prune происходил до создания нового файла, а проверка размера —
до записи без учёта входящего сообщения. Имена имели точность до секунды.
При запуске старые oversized файлы не приводились к установленному пределу.
Очередь ограничивалась количеством4096 строк, но не размером их payload.

До исправления: **18 targeted cases, 12 passed / 6 failures**. Регрессии
воспроизвели quota/rotation/startup/UTF-8/entry-size нарушения. После исправления:
**20 targeted cases,20 passed**; старые проверки тоже сохранены.

## Получившийся контракт

| Область | Ограничение и поведение |
|---|---|
| Обычные файлы | Не более5 файлов по2 MiB при доступной записи в filesystem |
| Ротация | Проверка encoded bytes до append; активный файл защищён от prune |
| Имя | Milliseconds + sequence и атомарное создание, без collision при быстрых rotations |
| Startup | Prune старых файлов, затем bounded UTF-8 tail retained oversized файлов |
| Одна запись | Не более16 KiB; явный marker truncation, включая большой throwable |
| Очередь | Не более256 encoded entries, до4 MiB payload плюс служебные объекты |
| Переполнение | Evict oldest, сохранить newest и увеличить process-scoped dropped counter |
| Загрузка диагностики | `dropped_entries_total` в bounded upload; большой logcat не вытесняет этот итог |
| Другие файлы | Sidecar/directories и посторонние файлы не входят в ordinary-log prune |

Ошибка storage остаётся best-effort и не должна блокировать запуск агента.
Невозможно обещать исправление quota при отказе filesystem/delete/write.
Предел4 MiB — очередь encoded payload, а не RSS всего Android-приложения.
Counter обнуляется при новом процессе; он не является durable history.

Исходники:
[FileLoggingTree](../../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt),
[LogUploadWorker](../../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/LogUploadWorker.kt).

## Проверки

```text
:app:testDevDebugUnitTest
:app:testEnterpriseDebugUnitTest
```

136 suites /1682 JUnit cases: **1680 passed,2 skipped,0 failures,0 errors**.
В каждом variant841 cases; один skip в `ConfigRecoveryTest`. Эти два skip
не объявляются проверенными. Full run241,77s; отдельные20 logger cases31,69s.
GitHub для `e75d365`: Frontend, Backend, Android и Preview completed/success.

Проверены file quota, pre-append UTF-8 размер, быстрые rotations, startup repair,
исключение чужих файлов, huge entry/throwable, bounded queue с последними
сообщениями и upload health counter при большом logcat. Эти тесты не заменяют
длительное наблюдение установленного Android и не измеряют Windows disk writers.

## Исторический preflight и установленный canary

Live read-only preflight через3015: API ready, PostgreSQL/Redis ok,14 online;
PH010/PH025 online10244. Package path/hash соответствуют прежнему10244 artifact.
Host ADB/обязательный PC Agent для этого не использовались.

После завершения ETW окна и ресурсного preflight выполнена отдельная сборка:
`:app:assembleDevDebug`, `:app:assembleEnterpriseDebug` и оба unit variants.
Сборка: 4m14s, 1680 passed / 2 skipped; v2 signatures и signer совпадают с 10244.
Файл: 8 473 519 bytes, package `com.sphereplatform.agent.pilot.debug`, SHA-256:

`f2a5c1532340e6014500d08480ae02f61d7b8f58224150fe0c4d0424642f39eb`.

23:17:44 UTC immutable hash artifact опубликован в `android-canary/dev`;
normal/android catalog unchanged. Source logger tree совпадает с `e75d365`.
После package/cert/hash preflight выдана ровно одна scoped recovery grant на цель,
последовательно PH010 затем PH025, без data wipe, host ADB или automatic retry.
PH010 accepted 23:18:05 UTC; PH025 — 23:18:48 UTC. У обоих completed receipt,
installed_version_code 10245, новый heartbeat и exact native installed APK hash.
Grants автоматически очищены; краткий offline во время смены процесса сохранён
в raw receipt и не выдаётся за uninterrupted connection.

| Native filesystem after restart | PH010 local | PH025 remote |
|---|---:|---:|
| Ordinary count before → after | 6 → 5 | 6 → 5 |
| Largest file before, bytes | 2 097 284 | 2 101 247 |
| Largest retained after, bytes | 2 097 152 | 2 097 152 |
| Ordinary total after, bytes | 8 761 622 | 9 560 342 |
| Separate bounded WS sidecar, bytes | 26 320 | 61 449 |

Read-only native metadata/hash verification 23:19:45–23:19:48 UTC: 6 commands,
root support работает на обеих целях. Logger сам выполнил startup prune/repair;
мы не удаляли или искусственно раздували Android files.

Оба APK прислали после установки новый health footer `dropped_entries_total=0`:
PH010 — 23:19:45 UTC / 59 355 bytes; PH025 — 23:32:04 UTC / 65 453 bytes. Server-time
separator подтверждает свежесть, тела upload меньше 480 KiB. Первые remote-срезы
23:19/23:23 ещё содержали только прежний upload 23:17 и не были засчитаны как pass.
Periodic worker 15min не обещает непрерывный real-time upload; native log read
отдельно уже успешно выполнен на обеих целях.

Finite observation: 11 срезов / 30s interval,
2026-10-04T23:21:44.259314+00:00 → 2026-10-04T23:26:50.805722+00:00.
Все 14 online IDs/connection epochs сохранялись после canary restart: 2×10245
и 12×10244, heartbeat <60s, API ready. Все 46 container identities/image/start epochs
сохранены. Disk/RAM guard прошёл во всех 11 срезах. Это короткий pass, не long soak.

GitHub source `bdfebea`: Android, Backend, Frontend и Preview completed/success.
Первый backend lint на `e3b0518` упал на I001 import order; `bdfebea` исправляет
его. Воспроизведён именно Ruff 0.15.2 из CI, весь CI scope проверен локально;
прежний проход Ruff 0.3.0 не используется как эквивалент этой проверки.

**R09 SOURCE_FIXED / STARTUP_CANARY_VERIFIED / LONG_RETENTION_SOAK_OPEN.**
Startup quota и installed artifact доказаны на local+remote. Live saturation,
многократная ротация, process-loss counter semantics и долгий RAM/retention soak
ещё не приняты; source regressions не заменяют эти измерения. Normal OTA и stable
fleet promotion остаются отдельными gates, mass install не отправлен.

R07 server global quota/sweeper, RAM soak, VHD compaction и Fleet32 остаются
отдельными открытыми работами. Число34 source-fixed /7 unclosed в исходном веб-аудите
этим исправлением не изменяется.
