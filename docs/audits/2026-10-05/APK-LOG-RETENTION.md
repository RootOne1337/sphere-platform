# R09 — ограничение постоянных логов и очереди APK

**Дата:** 5 октября 2026, Asia/Yekaterinburg; измерения — UTC 4 октября.
**Source:** `ae90715`; версия кандидата `e75d365`, `1.2.45-dev / 10245`.
**Установленная версия:** `1.2.44-dev / 10244` на последнем live-срезе
20:55:39 UTC. Новый APK этим этапом не собран, не опубликован и не установлен.

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

## Runtime и следующие критерии

Live read-only preflight через3015: API ready, PostgreSQL/Redis ok,14 online;
PH010/PH025 online10244. Package path/hash соответствуют прежнему10244 artifact.
Host ADB/обязательный PC Agent для этого не использовались.

**R09 SOURCE_FIXED / INSTALLED_CANARY_OPEN.** Из-за срочного наблюдения C: новый
APK build и rollout отложены: Gradle/build-cache запись исказила бы disk window.
Версия10245 в исходниках не означает, что OTA-каталог или эмуляторы обновились.

Для закрытия установленного R09: собрать и проверить signer/hash10245, доставить
точечно, подтвердить новый heartbeat version и установленный package hash;
нагрузить logger на одном локальном и одном удалённом экземпляре, проверить
пять файлов/2 MiB, bounded upload и recovery. Затем отдельно staged fleet rollout.
Не публиковать кандидат как стабильный массовый релиз до этих проверок.

R07 server global quota/sweeper, RAM soak, VHD compaction и Fleet32 остаются
отдельными открытыми работами. Число34 source-fixed /7 unclosed в исходном веб-аудите
этим исправлением не изменяется.
