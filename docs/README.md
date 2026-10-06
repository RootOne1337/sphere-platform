<div align="center">

# 📚 Документация Sphere

**От первого подключения до воспроизводимого разбора отказа.**

[Главная](../README.md) · [Готовность](operations/READINESS.md) · [Открытые работы](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [Помощь](../SUPPORT.md)

</div>

> [!NOTE]
> **Срез навигации: 6 октября 2026.** Канонические source/runtime факты,
> версии Android, ограничения диагностики и будущий этап 20–30 устройств собраны
> в [актуальном состоянии](operations/CURRENT-STATE.md). Каталог не выполняет
> автоматическую проверку runtime; старые аудиты сохраняют собственные даты и
> версии и не должны читаться как текущий deploy. [Правила актуальности](DOCUMENTATION.md).

**5 октября — комплексный аудит продукта:**
[22 раздела в браузере, шесть подтверждённых дефектов, ограничение Grafana и 50 работ](audits/2026-10-05/ENTERPRISE-PRODUCT-AUDIT.md) ·
[Evidence/источники](audits/2026-10-05/ENTERPRISE-PRODUCT-AUDIT-EVIDENCE.json) ·
[Backlog с приёмкой](audits/2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json).
Исходники `c3937a1`, установленный на этапе аудита UI/API `c1a6e79a`; исходный аудит — только анализ.
Каталог API и элементов управления не заменяет живую проверку Android и 500–1000 устройств.

**6 октября — общий контракт параметров 32 действий Script Studio:**
Предшествующий свободной сборке source срез:
[Правила, API, форма узла, проверки и compatibility matrix](audits/2026-10-06/STUDIO-ACTION-PARAMETERS.md).
141 Python/ASGI/schema tests и374 frontend tests /16 suites, TypeScript и scoped
Ruff прошли; source ещё не установлен из-за host repair gate. APK capabilities,
runtime semantics и continuous gestures не объявляются подтверждёнными JSON-проверкой.

**6 октября — свободная сборка графа Studio:**
[Drag/drop, отдельные узлы, явная вставка, draft/publish split и приёмка](audits/2026-10-06/STUDIO-FREE-CANVAS.md).
395 tests /17 scripts suites и TypeScript прошли; runtime/visual ещё не приняты.
Удаление, выбор входа и Undo/Redo сохраняют возможность продолжить сборку.
[Полный hosted CI517d73b](audits/2026-10-06/STUDIO-SOURCE-CI-20261006.json):
3015 backend passed/37 skipped,1686 frontend/133 suites +types/build,
Android smoke success. Preview deploy skipped; следующий head проверяется отдельно.

**6 октября — admission упакованного веба и continuous input audit:**
[Next standalone: реальные HTTP страницы/JS/CSS перед установкой](audits/2026-10-06/FRONTEND-STANDALONE-ADMISSION.md) ·
[scrcpy5.0: pinned source, control-only adapter и безопасный held touch](audits/2026-10-06/CONTINUOUS-INPUT-INTEGRATION.md).
18 bounded HTTP tests passed после уточнения streamed Next redirect;
новый hosted artifact probe ещё требует исполнения.
Continuous capability не включена; client/server/APK изменения и canary обязательны.

**6 октября — связи Studio, упорядоченная selector queue и следующий input protocol:**
[Follow-up требований пользователя и план приёмки](audits/2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md) ·
[Явное редактирование связей](audits/2026-10-06/STUDIO-CONNECTION-EDITING.md).
234/11 scoped tests и types passed; source fixes ждут host repair/build/deploy.
Continuous gestures, rich pixel/XPath evidence и group input остаются отдельными
открытыми работами; Home recording проверен на installed PH010, PNG — PH011.

**6 октября, 21:58 UTC+5 — конкретный PNG пользователя проверен против Android RAW:**
[Pixel comparison и отсутствие DPI metadata](audits/2026-10-06/NATIVE-PNG-PIXEL-VERIFICATION.md) ·
[Pinned facts](audits/2026-10-06/NATIVE-PNG-PIXEL-EVIDENCE.json).
PH011: native PNG/RAW518 400pixels совпали; пользовательский файл полностью совпал
ниже строки состояния. Source1:1 preview и разделение native/video export:
49/3 scoped tests и types passed; deploy ожидает исправления C:.

**6 октября, 19:48 UTC+5 — PH011 на 1.2.47: screenshot ACK и bounded private PNG cache:**
[Контракт и открытая доставка task artifacts](audits/2026-10-06/ANDROID-SCREENSHOT-CACHE.md).
Одна saved v1 завершилась **14/14**, 10 снимков → последние 8 PNG / 1 880 304 B;
original 960×540 PNG hash-matched. По **869 passed / 3 skipped** в локальных
Dev/Enterprise, Linux JUnit — по **871 / 1** в четырёх вариантах, включая symlink
fixtures. Source CI success; task server upload остаётся открытым.
[Pinned evidence](audits/2026-10-06/ANDROID-SCREENSHOT-CACHE-EVIDENCE.json).

**6 октября, 18:48 UTC+5 — PH011 обновлена до 1.2.46; реальный canary 25/25:**
[Доставка, XPath проверки и screenshot gap](audits/2026-10-06/ANDROID-CLEAR-INSTALLED.md) ·
[Pinned evidence](audits/2026-10-06/ANDROID-CLEAR-INSTALLED-EVIDENCE.json).

**Историческая сборка 6 октября, 17:43 UTC+5 — APK text-clear fix, кандидат без установки:**
**1.2.46-dev / 10246**, source `6a9f570f`; по 855 passed / 1 assumption-skipped
Dev/Enterprise, signer/ZIP/DEX и четыре source CI прошли. Реальный SDK28 helper
очистил всю строку с курсором внутри; пустой повтор и следующий ввод прошли.
Это helper proof из временной копии, не полный canary обновлённого агента.
APK не установлен/не опубликован OTA, API/UI/туннели сохранены, 9 / 41 остаётся.
[Доставка, native PNG и ограничения](audits/2026-10-06/ANDROID-FOCUSED-TEXT-CLEAR.md) ·
[Pinned evidence](audits/2026-10-06/ANDROID-FOCUSED-TEXT-CLEAR-EVIDENCE.json) ·
[Новый generated-class incident](audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md#повреждённый-generated-class-в-android-сборке).

**6 октября, 16:50 UTC+5 — запись текста и Android-кнопок установлена:** UI
**`1c26ffc7`**, API **`eb7a7c26`** на [3015/scripts/builder](http://127.0.0.1:3015/scripts/builder).
Recorder сохраняет отправку и отдельное подтверждение APK, защищает pending/unknown
действия и переносит `key_event`/`type_text`. 1546 tests / 128 suites, types/build и
четыре source CI прошли; Preview deploy skipped. Один записанный remote PH025
сценарий с явными Settings prerequisites сохранён как v1 и выполнил **10/10** шагов.
Темы, 1280/390 px и реальные подтверждения проверены; 45 соседних контейнеров,
API/APK/туннели сохранены. Это не FPS/latency/fleet-soak или закрытие EP-018 целиком.
**9 / 41** сохраняется; отдельно найден P1 APK с неверной очисткой текста.
[Результат и ограничения](audits/2026-10-06/STUDIO-COMMAND-RECORDING.md) ·
[Evidence](audits/2026-10-06/STUDIO-COMMAND-RECORDING-EVIDENCE.json) ·
[Инструкция](operations/SCRIPT-STUDIO.md).

**Историческая установка 6 октября, 12:35 UTC+5 — metadata-only каталог:** API и UI
**`eb7a7c26`** на [3015/scripts](http://127.0.0.1:3015/scripts). Список получает
только метаданные, исходник — после явного открытия закреплённой версии.
Additive migration и reconcile подготовили 25 версий / 22 сценария; исходники,
указатели, даты и 445 заданий сохранились. Живой all-каталог — 14037 bytes вместо
34553 bytes; fixture 100×500 узлов — 85176 вместо 48889157 bytes.
171 source tests с shipped dependencies, отдельный final migration test и
1506 frontend tests / 126 suites прошли; exact image/build проверки записаны отдельно.
Первая попытка установки откатилась на сравнении эквивалентных Windows bind-path;
повторная сохранила 44 соседних контейнера, APK/OTA/туннели. Fleet 14/5 → 9/10 →
10/9 → 14/5 (контрольный GET 07:41:18 UTC) — конечные reconnect-срезы, не SLA;
новых Android команд не было. Четыре source CI `eb7a7c26` завершились success;
это не hosted deploy и не проверка следующего документационного head.
**9 / 41** сохраняется: p95/CPU/RSS/browser heap/load-soak и следующие Studio gates открыты.
[Доставка](audits/2026-10-06/SCRIPT-CATALOG-DELIVERY.md) ·
[Pinned evidence и native QA](audits/2026-10-06/SCRIPT-CATALOG-EVIDENCE.json) ·
[Инструкция каталога](operations/SCRIPT-CATALOG.md) ·
[Подтверждённый NTFS-инцидент, отдельно от storage writer](audits/2026-10-06/HOST-FILESYSTEM-INCIDENT.md).

**Историческая установка 6 октября, 07:00 UTC+5 — сценарии и лаборатория устройства:** UI `a670a3df`,
API `c2b91e32` на [3015/scripts](http://127.0.0.1:3015/scripts). Сохраняемый каталог,
группы действий, формы и читаемый граф с локальным ELK, один живой Android,
запись отправленных жестов, свежий XPath и задания сохранённой версии.
Исправлены потеря неприменённых полей, закрытие pending запуска и устаревшие
итоговые счётчики; карточка результата обновлена для обеих тем и узких экранов.
**1451 tests / 125 suites**, types/build прошли. Два canary одной remote PH025 v1
получили по 3 успешных отчёта; это не все runtime actions или frame-exact replay.
Все четыре source CI `a670a3df` завершились success; backend — 2844 passed /
30 skipped / 1 warning. [CI receipt](audits/2026-10-06/evidence/studio-redesign/source-ci.json)
отдельно от проверок документационного head. Preview deploy skipped по условию
включения; success workflow не означает hosted deploy.
Сохранены 45 соседних контейнеров; срезы 14 online / 5 offline из 19 не являются SLA.
Общий счёт **9 / 41** сохраняется; metadata-only каталог, preflight и trace/replay
остаются отдельными приоритетами.
[Результат и native-скриншоты](audits/2026-10-06/STUDIO-REDESIGN.md) ·
[Evidence](audits/2026-10-06/STUDIO-REDESIGN-EVIDENCE.json) ·
[Инструкция](operations/SCRIPT-STUDIO.md) · [Приоритеты](audits/2026-10-06/ENTERPRISE-PRIORITIES.md) ·
[Следующий контракт каталога](audits/2026-10-06/SCRIPT-CATALOG-METADATA-CONTRACT.md).

**Историческая установка 6 октября — Script Studio, этап A:** API `c2b91e32`, UI `952b5e2f` на
[3015/scripts/builder](http://127.0.0.1:3015/scripts/builder). Граф ↔ JSON, 32 действия,
bounded drafts/history, import/export, серверная проверка и адресный запуск версии.
Remote PH025 canary завершил 3/3 шага; 631 exact-image backend и 1353 frontend tests
прошли. Recorder/replay и capability schema ещё открыты; общий счёт **9 / 41**.
[Результат с доказательствами](audits/2026-10-06/SCRIPT-STUDIO-FOUNDATION.md) ·
[Инструкция](operations/SCRIPT-STUDIO.md) · [Приоритеты](audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 01:37 UTC+5 — ограничен приём загружаемых APK-журналов:**
Установленный API `76596c39`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Body больше 512 KiB отвергается до полного buffering; total ASGI intake deadline 60 s.
Четыре uploads на worker включают приём и filesystem writer; весь FS lifecycle
в отдельном executor. 8 MiB fixture: declared oversize 0 receive, unknown length
9 вместо 128 chunks; Python traced peak около 8 MiB → 0,506 MiB для unknown case.
Это не общий RSS limit или установленная причина расхода Windows C:.
В packaged image прошли 537 device/status/WS/VPN cases, включая 35 новых upload,
и 35 resource cases: **572 passed**; mypy/scoped Ruff/OpenAPI check прошли.
Сохранены 14 original-byte prefixes / 3614902 bytes и 45 соседних контейнеров.
В 01:42 UTC+5 после переключения подтверждены новые uploads в пяти файлах;
живые declared/chunked oversize POST вернули 413, PH025 GET — 1000 строк.
В браузере проверены непустой журнал, поиск, refresh и границы данных.
Online 14 / offline 5 из 19 — конечный срез, не SLA; UI/APK/OTA/туннели сохранены.
Source CI пока не принят целиком; последующий docs head проверяется отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: общие квоты, независимая очистка,
rotation/delete concurrency, backup/restore и leak/load gates остаются.
[Контракт и результат](audits/2026-10-06/DEVICE-LOG-UPLOAD-BUDGET.md) · [Pinned evidence](audits/2026-10-06/DEVICE-LOG-UPLOAD-EVIDENCE.json) · [Приоритеты](audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Историческая установка 6 октября, 00:55 UTC+5 — ограниченное чтение и постоянное хранение логов:**
API `9889c9ac`, UI `5405d465` на [3015/logs](http://127.0.0.1:3015/logs).
Предел чтения — 2 MiB, JSON-массива строк — 512 KiB; четыре операции на worker
без растущей очереди. Файловый I/O вынесен из event loop. На одинаковом архиве
24 MiB совпали последние 1000 строк; Python traced peak снизился с 46,04 до 0,447 MiB.
Это не замер RSS и не установленная причина расхода Windows-диска.
14 файлов / 902996 bytes перенесены в постоянный том; исходные байты проверены
после rollback и пересоздания контейнера. Сохранены 45 соседних контейнеров.
Проверки образов: 502 + 35 тестов reader, затем 26 тестов final storage image;
23 Compose-проверки, 1307 frontend-тестов / 121 suite, build/types и scoped lint прошли.
В живом браузере проверены ширины 1440/390 px, обе темы, поиск и обновление;
настоящий GET для PH025 вернул 483 строки. Срезы online 14→9 и 14→11 сохранены;
устранение reconnects и непрерывная стабильность ещё не подтверждены.
Полный CI не прошёл: GitHub не выделил runner для backend Tests и Security.
Android CI storage-source прошёл; CI последующего docs-коммита учитывается отдельно.
**9 принято / 41 открыто**, EP-033 OPEN: квоты, независимая очистка, upload budget,
backup/restore и проверки утечек/нагрузки ещё впереди.
[Результат и ограничения](audits/2026-10-06/DEVICE-LOG-READ-BUDGET.md) · [Доказательства](audits/2026-10-06/DEVICE-LOG-READ-EVIDENCE.json) · [Приоритеты](audits/2026-10-06/ENTERPRISE-PRIORITIES.md).

**Исторический срез 6 октября, 00:00 UTC+5 — tenant-сводка EP-010 Stage B:**
API `7fef9c53`, веб `9ad0a69e` на [3015/monitoring](http://127.0.0.1:3015/monitoring).
Шесть отдельных источников: активный парк, связь, VPN-отчёт Android, назначения,
сохранённые handshakes и неподключённые проверки публичного транспорта.
Живое окно 19:00 UTC: 19 устройств, 14 online + 5 unknown; 14 VPN inactive + 5 unknown.
Первая установка выявила text/binary Redis mismatch; отдельный фикс и регрессия
подтвердили исправление. 476 + 35 exact-image tests, 1298 frontend tests, Node24
build/types, scoped Ruff и OpenAPI прошли. Сохранены 45 соседей; APK/OTA не менялись.
CI исходников API `7fef9c53`: backend 2754 passed / 30 skipped; frontend, Android
и остальные gates прошли. CI последующего docs-коммита проверяется отдельно.
**9 принято / 41 открыто**, EP-010 OPEN: независимый producer, транспортные probes
и нагрузочный прогон ещё не приняты. [Доказательства и ограничения](audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE.md) ·
[Pinned receipts](audits/2026-10-05/ENTERPRISE-FLEET-COVERAGE-EVIDENCE.json).

**Историческая установка foundation — 5 октября, 21:11 UTC+5:** API `d656b579`,
UI `cb5b3f91` сохранён. VPN-отчёт Android имеет независимое серверное время и
владельца сеанса; атомарная запись защищена от запоздавшего старого подключения.
После 120 с отчёт не считается свежим. Живое окно16:20 UTC:14 свежих false и5
unknown при14 online/5 offline из19. Это не проверка VPN-трафика или SLA.
Exact image444+35 tests; source CI backend2722 passed/30 skipped, frontend и
Android прошли. Сохранены 45 соседей. **9 принято/41 открыто**, EP-010 ещё OPEN.
[Результат, ограничения и следующие критерии](audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION.md) · [Pinned evidence](audits/2026-10-05/ENTERPRISE-ANDROID-VPN-OBSERVATION-EVIDENCE.json).

**Историческая установка Stage A — 5 октября, 20:31 UTC+5:** backend `66714f26`,
UI `cb5b3f91` сохранён. Список peers и pool counts теперь одинаково исключают
устаревший/future handshake, неназначенные и непривязанные peers; добавлено время
SQL-среза. Exact image: 99 VPN + 27 resource tests, mypy 231/Ruff прошли; сохранены
45 соседних контейнеров. Живой текущий VPN-каталог пуст: нули не доказывают работу
VPN на Android. Последующее окно 6×3 с: 14 online из 19, без утверждения SLA.
**9 принято / 41 открыто**: весь EP-010 ещё открыт.
[События, polling и оставшиеся источники](audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-NEXT.md) · [Image/runtime evidence](audits/2026-10-05/ENTERPRISE-LIVE-COVERAGE-EVIDENCE.json).

**5 октября, 19:55 UTC+5 — EP-009 принят на живом 3015:** API/UI **`cb5b3f91`**,
gateway config **`993d9eac`** сохранён. Реальная история CPU в использованных ядрах
и памяти в GiB cgroup контейнера: окна 1/6/24 h, сбор/обновление 15 с, среднее CPU за 1 минуту.
Лимит памяти 2 GiB подтверждён; CPU quota не подменяется нулём. Host/RSS сюда не
смешиваются. 1275 frontend tests/120 suites, production Node24 build/types и 27
tests в exact API image, mypy 231/Ruff, promtool и живые queries прошли. Браузер
1600/390 px, обе темы и автоматическое обновление проверены. При замене каждого
API/UI сохранены 45 соседей; Prometheus reload без replacement всех 46.
Сохранена временная потеря 14→12→13 online; последующее конечное окно 6×3с:
14 online /5 offline из19. Это не непрерывный SLA или устранение утечки.
**9 закрыто / 41 открыто из 50**; следующий EP-010, host leak attribution, Studio
и stream+script load/soak открыты.
[Приёмка и screenshots](audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-HISTORY.md) ·
[Pinned evidence](audits/2026-10-05/ENTERPRISE-CONTAINER-RESOURCE-EVIDENCE.json) · [Живой monitoring](http://127.0.0.1:3015/monitoring).

**Исторический срез: 5 октября, 19:03 UTC+5 — текущий пакет HTTP-метрик установлен и проверен:**
UI `7c985feb`, API `51ccaa36`, gateway `993d9eac`; [живой monitoring3015](http://127.0.0.1:3015/monitoring).
EP-008: RPS/p95/4xx/5xx и разбор маршрутов с реальными данными, bounded queries,
проверкой freshness и отдельными partial/error/empty состояниями. DNS race review
gateway исправлен; mobile refresh40×40 px. 1235 frontend tests,99 тематических,
14 gateway tests/types/lint/build; конечные HTTP/Grafana/browser проверки прошли.
**8 закрыто /42 открыто из50**; CPU/RAM history, tunnels/fleet и Studio ещё открыты.
Короткий502 при замене UI сохранён; zero downtime не заявляется.
[Приёмка и screenshots](audits/2026-10-05/ENTERPRISE-HTTP-METRICS.md) ·
[Source/runtime evidence](audits/2026-10-05/ENTERPRISE-HTTP-METRICS-EVIDENCE.json) ·
[HTTP contract](operations/HTTP-METRICS.md) · [Gateway procedure](operations/REVIEW-GATEWAY.md).

**Исторический срез: 5 октября, 08:19 UTC+5 — второй пакет установлен и проверен:**
API `51ccaa36`, UI `6b7de0cc`, topology `52403b4`; [живой monitoring3015](http://127.0.0.1:3015/monitoring).
EP-006: ошибки HTTP callback корректно классифицированы, реальные HTTP retries/HMAC проверены.
EP-007: встроенный dashboard Grafana с реальными данными и immediate logout revoke.
1196 frontend tests/types/build, 70 целевых API image checks, mypy229/Ruff/schema прошли.
Guard rollbacks и краткое падение online count сохранены; конечный срез14 online/5 offline.
**7 закрыто /43 открыто из50**. APK/туннели/DB/public18080 сохранены; storage soak RUNNING.
[Журнал и ограничения](audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP.md) ·
[Source/runtime/HTTP/визуальные доказательства](audits/2026-10-05/ENTERPRISE-PRODUCT-FOLLOWUP-EVIDENCE.json).

**Ресурсы12:58 UTC+5:** [recorder COMPLETE /241 срезов /C:−2,154GiB /VHD без роста /exact VSS0](audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md).
Крупный drop1,77GiB за2min ещё не атрибутирован; physical RAM/Windows commit
измерены отдельно. [Конечный manifest](audits/2026-10-05/HOST-STORAGE-NIGHT-FINAL-EVIDENCE.json);
не объявляется исправленная утечка.

**Исторический срез: 5 октября, 07:33 UTC+5 — первый пакет:** UI `6ff6bc2`
на [3015](http://127.0.0.1:3015/devices), API `c1a6e79a` сохранён. Пять подтверждённых
дефектов и отдельный cache-дефект исправлены; 1185 tests/types/build и browser/API
приёмка записаны в [журнале реализации](audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION.md)
и [evidence](audits/2026-10-05/ENTERPRISE-PRODUCT-IMPLEMENTATION-EVIDENCE.json).
Исходный план из 50 работ целиком не закрыт; 45 сохраняют открытые критерии.

**Предыдущая совместная установка веба и API: 4 октября 2026, после перезагрузки ПК, в 17:14 UTC.
API/UI c1a6e79.** [Аудит диска, ОЗУ, сборки и RPC](audits/2026-10-04/HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md) ·
[Эксплуатационная процедура](operations/HOST-RESOURCES.md).

**5 октября — текущая работа с ресурсами:**
[Конечный8h disk/VSS/RAM recorder /16MiB / source02b5084 /68 tests / COMPLETE](audits/2026-10-05/HOST-STORAGE-NIGHT-WATCH.md) ·
[ETW writer / exact VSS / 51 owned image / 10,938 GiB guest reclaim](audits/2026-10-05/DISK-WRITER-ATTRIBUTION.md) ·
[APK10245 local+remote startup canary / 1680 passed, 2 skipped / long soak OPEN](audits/2026-10-05/APK-LOG-RETENTION.md).
Source recorder `1402612` / projection `9a9256f`, 8 Windows tests; API/UI c1a6e79,
Позднее PH010/PH025 адресно обновлены10245,12 online остаются10244; startup quota доказана.
AdGuard update объясняет отдельный короткий скачок,
но полная историческая атрибуция, VHD compaction и RAM soak ещё открыты.
[Предыдущие объёмные срезы](audits/2026-10-05/HOST-DISK-GROWTH.md) сохранены как история.

**22:52 UTC follow-up:** [VSS+1,969GiB /net free−2,033GiB, shadow inventory и retention review](audits/2026-10-05/VSS-RETENTION-REVIEW.md).
Read-only image planner14 tests /actual0 additional candidates. После одобрения
22:58 UTC VSS quota8GiB применена, обе system copies удалены Windows;
free C:+17,205GiB. Runtime/46 containers сохранены, VHD не сжат.

**Дополнительная инвентаризация, 17:50 UTC:** [размер Sphere / обход C: / package cleanup](audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP.md).
Workspace 8 GiB, tracked files 22 MiB; shared Docker VHD 219 GiB отдельно.
На C: free 41,43 GiB после дополнительной очистки; 46 контейнеров сохранены,
14 online10244. [Sanitized receipts](audits/2026-10-04/HOST-DISK-INVENTORY-AND-CLEANUP-EVIDENCE.json).

В образах прошли 113 наборов / 1122 frontend-теста и 186 API-проверок; отдельно
18 проверок допуска сборки. Все четыре source CI прошли. Исправлены повторные
слои зависимостей; выполнена адресная очистка. Сжатие VHD и длительная утечка ОЗУ
ещё не приняты. Remote 504 сохранён рядом с отдельным успешным PNG 200;
первое окно связи FAILED: 11→14, последующее сохранило 14 online / даты подключений.
APK 10244, Tuna и OTA сохранены. Исходный реестр: 34 исправлено / 7 незакрытых;
визуальная приёмка, FPS/задержка, длительная нагрузка и Fleet32 admission открыты.

**Исторический follow-up: 4 октября 2026, 10:06 UTC+5. API/UI9716348**, APK 10244 unchanged.
[Native PNG, управление и manual Android profile](audits/2026-10-04/DEVICE-CONTROL-AND-NATIVE-CAPTURE.md).
1117 frontend / 140 API cases в образах, schema178/140. PH025/PH010 original PNG accepted;
Android/server/file hashes matched. 14online в конечном UI readback; первый remote504
и seven code1005 disconnects сохранены. Human native download/keyboard, UA2/nonroot,
full visual/latency/load/soak OPEN; original ledger34/7 не изменён.

Историческая runtime-проверка этапа XPath — **4 октября 2026, 05:55 UTC+5**:
[F35 XPath: контракт и live Android](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md) ·
[Evidence](audits/2026-10-04/UI-HIERARCHY-INSPECTOR-EVIDENCE.json).
API **9274e50** / UI **84750e3** на 3015; 110 suites / 1043 frontend и 108 API cases
в образах. Вход в инспектор загружает дерево; выбор, атрибуты, подсветка и активное
автообновление покрыты 8 pointer workflow tests. PH010 45 / PH025 49 реальных узлов.
После UI rollout 14 online APK 10244 и прежние даты соединений во всех 7 срезах;
API/Tuna/OTA и 15 соседей сохранены. Предыдущее API окно FAILED 14→13/PH015
не скрыто. **34 source-fixed / 7 незакрытых, включая 3 PARTIAL**; browser/soak OPEN.

Предыдущая runtime-проверка — **4 октября 2026, 02:04 UTC+5**:
[F39: формы групп и локаций](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS.md) ·
[Evidence](audits/2026-10-04/ORGANIZATION-ACTION-PERMISSIONS-EVIDENCE.json).
API **37bb436** / UI **922f479** на 3015; 1013 frontend / 89 API проверок в образах.
14 online APK 10244, даты соединений сохранены. Остальные формы и визуальная приёмка OPEN.
Предыдущие [registry permissions](audits/2026-10-04/DEVICE-ACTION-PERMISSIONS.md) и
[N10 rollout](audits/2026-10-04/VIEWER-AUTHORIZATION.md) сохранены как датированная история.
[JPEG Matrix план](audits/2026-10-04/MATRIX-PREVIEW-PLAN.md) ещё не реализован.

Предыдущая проверка видео — **3 октября, 15:53 UTC**:
[H.264 recovery и измеренная доставка](audits/2026-10-03/STREAM-REFERENCE-RECOVERY.md).
Для прежнего API 37415e3 / UI 77fca37 на PH025/PH010 получено по 599 кадров за
20 с — 29,95 кадра/с до получателя. Отрисовка браузера и задержка ввода ещё не приняты.
Прошли 230 WebSocket-тестов и 41 PostgreSQL/Redis case, все 271 — в собранном образе.

[Native OTA 44](audits/2026-10-03/OTA-SIGNER-COMPATIBILITY.md) ·
[ABR proof](audits/2026-10-03/STREAM-BITRATE-RECOVERY.md) ·
[OTA contract](operations/OTA-PUBLICATION-AND-APK-CHECKS.md).
Normal/dev 10209; stable/manifest/bulk/visual/soak/F36 OPEN. Исходный аудит: 33/8.


## 🧭 Выберите задачу

| Мне нужно | Начать здесь | Дальше |
| --- | --- | --- |
| Проверить полный веб-аудит и текущие исправления | [Аудит всех маршрутов, меню и возможностей API — 1 октября](audits/2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md) | [Журнал исправлений F01–F41](audits/2026-10-01/WEB-AUDIT-REMEDIATION.md) · [Fixes: актуальные tests / installed UI](audits/2026-10-01/WEB-AUDIT-FIXES-VALIDATION.json) · [Frozen audit evidence](audits/2026-10-01/WEB-FULL-CAPABILITY-AUDIT-EVIDENCE.json) · [Проверки документа](audits/2026-10-01/AUDIT-VALIDATION.json) |
| Выбрать UI-элемент рядом с видео устройства | [XPath-инспектор](audits/2026-10-04/UI-HIERARCHY-INSPECTOR.md) | Actual root APK/tree, limits, errors и [evidence](audits/2026-10-04/UI-HIERARCHY-INSPECTOR-EVIDENCE.json); nonroot/visual gate OPEN |
| Создать площадку, задать координаты или изменить иерархию | [Контракт локаций](operations/LOCATION-HIERARCHY.md) | [F26 proof](audits/2026-10-03/LOCATION-HIERARCHY.md) · [Receipts](audits/2026-10-03/LOCATION-HIERARCHY-EVIDENCE.json) |
| Просмотреть/изменить pipeline и допуск запусков | [Определения pipeline](operations/PIPELINE-DEFINITIONS.md) | [F28 proof](audits/2026-10-03/PIPELINE-DEFINITION-WORKFLOW.md) · [Receipts](audits/2026-10-03/PIPELINE-DEFINITION-WORKFLOW-EVIDENCE.json) |
| Просмотреть DAG версии, откатить сценарий или открыть архив | [Версии сценариев](operations/SCRIPT-VERSIONS.md) | [F27 proof](audits/2026-10-02/SCRIPT-VERSION-WORKFLOW.md) · [Receipts](audits/2026-10-02/SCRIPT-VERSION-WORKFLOW-EVIDENCE.json) |
| Опубликовать OTA и проверить package/signature перед install | [Publication/APK contract](operations/OTA-PUBLICATION-AND-APK-CHECKS.md) | [1.2.41 proof](audits/2026-10-03/OTA-RELEASE-IDENTITY.md) · [JSON receipts](audits/2026-10-03/OTA-RELEASE-IDENTITY-EVIDENCE.json) |
| Обновить одно Android-устройство и проверить receipt/heartbeat | [Адресное OTA](operations/OTA-ADDRESSED-UPDATES.md) | [F33 remote proof](audits/2026-10-02/OTA-ADDRESSED-DELIVERY.md) · [Evidence JSON](audits/2026-10-02/OTA-ADDRESSED-DELIVERY-EVIDENCE.json) |
| Найти audit событие за первой страницей и выгрузить CSV | [F37: source/installed evidence](audits/2026-10-02/AUDIT-INVESTIGATION.md) | [Контракт и лимит5000](operations/AUDIT-INVESTIGATION.md) · [JSON receipts](audits/2026-10-02/AUDIT-INVESTIGATION-EVIDENCE.json) |
| Проверить форму пользователя, смену роли и отключение | [F38: source/installed evidence](audits/2026-10-02/USER-ACCESS.md) | [Операторский контракт](operations/USER-ACCESS.md) · [JSON receipts](audits/2026-10-02/USER-ACCESS-EVIDENCE.json) |
| Проверить иерархию групп и сохранность audit отказов | [N04/N05: исправление и live readback](audits/2026-10-02/GROUP-HIERARCHY-AND-AUDIT.md) | [Evidence](audits/2026-10-02/GROUP-HIERARCHY-AND-AUDIT-EVIDENCE.json) · [Контракт иерархии](operations/GROUP-HIERARCHY.md) |
| Проверить discovery request/response и принадлежность результата | [F19/F20 + N02 — 2 октября](audits/2026-10-02/DISCOVERY-REQUEST-OWNERSHIP.md) | [Before/after/installed evidence](audits/2026-10-02/DISCOVERY-REQUEST-OWNERSHIP-EVIDENCE.json) · legacy errors N03 OPEN |
| Проверить восстановление веба и реальный rerun Android | [Docker review / remote PH025 — 2 октября](audits/2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md) | [Runtime + Android receipts](audits/2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN-EVIDENCE.json) · browser visual OPEN |
| Проверить снимки задания и повтор исходной версии | [Task artifacts / rerun — 2 октября](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN.md) | [Installed API/UI evidence](audits/2026-10-02/TASK-ARTIFACTS-AND-RERUN-EVIDENCE.json) · Android upload N01 открыт |
| Проверить страницы оркестрации и выбор цели расписания | [Каталоги без ограничения первой страницей — 2 октября](audits/2026-10-02/ORCHESTRATION-CATALOG-PAGING.md) | [F13 / текущая установка](audits/2026-10-01/WEB-AUDIT-REMEDIATION.md) |
| Сверить новый cross-layer audit, установленный APK10240 и API/UI | [Callbacks / runtime / OTA canary — 1 октября](audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY.md) | [Web ownership](audits/2026-10-01/STREAM-DIAGNOSTIC-OWNERSHIP.md) · [Pipeline terminal heartbeat](audits/2026-10-01/PIPELINE-TERMINAL-HEARTBEAT.md) · [Codec lifecycle](audits/2026-10-01/ENCODER-CALLBACK-OWNERSHIP.md) · [JSON evidence](audits/2026-10-01/CALLBACK-LIFECYCLE-CANARY-EVIDENCE.json) |
| Узнать актуальные версии, что APK может диагностировать/исполнять и что реально подтверждено | [Текущее состояние](operations/CURRENT-STATE.md) | [Readiness](operations/READINESS.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19) |
| Сверить версию и OTA перед pilot install | [Текущее состояние](operations/CURRENT-STATE.md) | [Local pilot ledger](operations/LOCAL-PILOT.md) · [Приёмка первого устройства](operations/PILOT-ACCEPTANCE.md) |
| Поднять новую установку | [Startup / bootstrap](operations/STARTUP.md#first-install) | [Configuration](configuration.md) · [Deployment](deployment.md) |
| Подключить удалённые Android | [Remote pilot](operations/REMOTE-PILOT.md) | [Signed discovery](architecture/ANDROID-SIGNED-DISCOVERY.md) |
| Понять оставшиеся проблемы | [Текущее состояние и границы доказательств](operations/CURRENT-STATE.md) | [Fleet32](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [A/B ingress](audits/2026-09-24/REMOTE-INGRESS-AB.md) · [Readiness](operations/READINESS.md) · [Roadmap](../ROADMAP.md) |
| Проверить полноту веб-панели, источники метрик и расхождение preview с checkout | [Web operations / observability audit — 29 сентября](audits/2026-09-29/WEB-OPERATIONS-OBSERVABILITY-AUDIT.md) | Подтверждённые пробелы, риски масштаба 500–1000 устройств и очерёдность следующей работы |
| Подключить серверную историю и Grafana прямо в веб | [Prometheus / Grafana](operations/OBSERVABILITY.md) | Docker-стек, права доступа, лицензии, retention и границы multi-worker метрик |
| Сверить, какая сборка frontend и backend реально открыта | [Build provenance в интерфейсе](operations/BUILD-PROVENANCE.md) | SHA веб-сборки в шапке, SHA API из runtime endpoint и честные состояния unknown/unavailable |
| Проверить профиль, MFA и API-ключи | [Настройки аккаунта — 30 сентября](audits/2026-09-30/WEB-SETTINGS-ACCOUNT-SECURITY.md) | Контракты API, реальные даты/статусы, подтверждения и отказные сценарии |
| Проверить читаемость реестра и источники сигнала | [Fleet Matrix — 30 сентября](audits/2026-09-30/WEB-FLEET-READABILITY.md) | Отдельная версия APK, heartbeat/контакт, реальные даты и доступные колонки |
| Открыть диагностику конкретного устройства, его задачи, события и логи | [Карточка и инспектор — 30 сентября](audits/2026-09-30/WEB-DEVICE-INSPECTOR.md) | Источники API, отказные сценарии, PNG из фактического кадра, границы Android команд |
| Проверить пагинацию и значения статусов в Fleet Matrix | [Контракт реестра устройств](operations/DEVICE-CATALOG.md) | Scope/status counts, Redis live presence, поведение при недоступности Redis и пределы текущего масштаба |
| Проверить frontend dependency advisories и статус исправлений в PR #19 | [Frontend dependency security report](audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md) | [Текущее состояние](operations/CURRENT-STATE.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19) |
| Проверить подпись, release APK, CI, OTA и доказательства Android-кандидата | [Android release-readiness audit](audits/2026-09-28/ANDROID-RELEASE-READINESS.md) | [Android agent guide](android-agent.md) · [Текущее состояние](operations/CURRENT-STATE.md) |
| Разделить graphics input, захват и AVC encode на Android | [Codec input canary](operations/CODEC-INPUT-CANARY.md) | [Synthetic control](audits/2026-10-01/PH010-CODEC-INPUT-EVIDENCE.json) · [Real capture, OTA и независимый decode](audits/2026-10-01/PH010-PH025-PLANAR-CAPTURE-EVIDENCE.json) · [Video cadence](operations/VIDEO-CADENCE-CANARY.md) |
| Разобрать чёрный экран стрима по стадиям | [Android stream observability](audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) | APK capture/encode/queue · browser decode/render · ограничения доказательств |
| Проверить APK limits, grid/detail видео и визуальную XPath-инспекцию | [Android inspection / video modes — 30 сентября](audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md) | Source findings, готовые engines и лицензии, Android-only архитектура, следующий canary/mass-test plan |
| Разобрать offline после clone/re-enrollment | [AUD-172 — enrollment HTTP 401](audits/2026-09-25/CLONED-ENROLLMENT-401.md) | Reject в `/devices/register`, shared bootstrap file и границы подтверждённой причины |
| Разобрать ложный Online сразу после подключения | [AUD-173 — presence до первого heartbeat](audits/2026-09-25/DEVICE-PRESENCE-FIRST-HEARTBEAT.md) | `connecting` → первый pong → `online`, тесты и rollout gate |
| Разобрать live-стрим без новых кадров | [AUD-175 — stale frame при живом WebSocket](audits/2026-09-25/FLEET-STREAM-STALE-FRAME.md) | Отдельный таймер декодированного кадра, keyframe recovery и границы доказательств |
| Проверить, что локальные APK и логи не входят в Docker build context | [AUD-174 — private artifacts и Docker context](audits/2026-09-25/DOCKER-CONTEXT-PRIVATE-ARTIFACTS.md) | Реальный BuildKit `COPY` probe и CI gate для корневого context |
| Проверить адресный APK OTA и результат установки | [AUD-171 — terminal receipts](audits/2026-09-25/OTA-TERMINAL-RECEIPTS.md) | Receipt commit/ACK, повтор после потери ACK, tenant scope и текущий canary gate |
| Разобрать сбой по времени и устройству | [Support: что собрать](../SUPPORT.md) | [Runbooks](runbooks/README.md) · [Fleet operations, stream и observability](architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) |
| Изменить код | [Contributing](../CONTRIBUTING.md) | [Development](development.md) · [Тесты](../tests/production/README.md) |

## 🚀 Запуск и эксплуатация

| Руководство | Что внутри |
| --- | --- |
| [Навигация Android в видеопотоке](operations/ANDROID-NAVIGATION.md) | Back/Home/Recents/Menu, root/RBAC, подтверждённый результат, unknown без автоповтора и remote Back proof |
| [Управление статичным экраном](operations/STATIC-STREAM-INPUT.md) | Single-device tap/swipe по кадру текущего socket, first-frame/reconnect/error gates и отдельная свежесть PNG |
| [Startup](operations/STARTUP.md) | Первый запуск, повторный старт, env precedence и значение readiness |
| [Local pilot](operations/LOCAL-PILOT.md) | Установленные версии, веб, APK, учётная запись и отдельный Compose project |
| [Remote pilot](operations/REMOTE-PILOT.md) | Устройства в другой сети, ingress и ограничения резервирования |
| [Удалённое видео и OTA](audits/2026-09-24/REMOTE-VIDEO-OTA-DECISION.md) | AUD-163: публичный tunnel против Android first-frame, что реально опубликовано и почему общий OTA rollout пока остановлен |
| [Отказоустойчивая OTA-архитектура](architecture/ANDROID-OTA-RELIABILITY.md) | Слои bootstrap/control/artifact/install, подтверждённый canary, быстрые проверки, резервные origins, receipts и Fleet32 gates |
| [A/B ingress и три remote VM](audits/2026-09-24/REMOTE-INGRESS-AB.md) | AUD-164: локальный/альтернативный viewer, SPS/PPS без IDR на удалённом агенте, reconnect rate и гейт для проверки Cloudflare |
| [Android stream observability](audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) | AUD-168: stage counters, protected diagnostics API, viewer decode metrics, crash upload and what remains unproven remotely |
| [Cloned enrollment HTTP 401](audits/2026-09-25/CLONED-ENROLLMENT-401.md) | AUD-172: rejected enrollment credential, identical clone bootstrap and unresolved route/key source |
| [Presence до первого heartbeat](audits/2026-09-25/DEVICE-PRESENCE-FIRST-HEARTBEAT.md) | AUD-173: не считать authenticated socket живым устройством до первого pong; отдельный fleet `connecting` count |
| [OTA terminal receipts](audits/2026-09-25/OTA-TERMINAL-RECEIPTS.md) | AUD-171: persist-before-ACK, bounded replay history, lost-ACK recovery and pilot rollout gate |
| [Deployment](deployment.md) · [Полный guide](../FULL-DEPLOYMENT-GUIDE.md) | Bootstrap, конфигурации и обслуживание; оценки масштаба требуют своей приёмки |
| [Discovery publisher](operations/DISCOVERY-PUBLISHER.md) | Публикация подписанных маршрутов и восстановление publisher |
| [Redis memory](operations/REDIS-MEMORY.md) | Dataset/container budget, persistence, pressure test и остаточные риски |
| [Redis concurrent AOF follow-up](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md) | AUD-143: CI OOM, source budget and pilot rollout boundary |
| [OTA transport retry](audits/2026-09-20/OTA-TRANSPORT-RETRY.md) | AUD-144 / F32-33: bounded retry after interrupted APK body, candidate and remote-acceptance gates |
| [Clone binding v2](audits/2026-09-20/CLONE-BINDING-V2.md) | AUD-145 / F32-34: emulator serial binding, backend-first migration and 32-clone acceptance gate |
| [Golden image and portable clone provisioning](architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md) | Master can be launched and configured; portable identity contract, clone-rebind gates, LDPlayer adapter evidence and cross-emulator acceptance matrix |
| [LDPlayer network recovery](operations/LDPLAYER-NETWORK-RECOVERY.md) | Диагностика сети станции и границы Windows watchdog |
| [Overnight soak](operations/ANDROID-OVERNIGHT-SOAK.md) | Безопасные DAG, receipts, видео, завершение и evidence |
| [Runbooks](runbooks/README.md) | Backend outage, PostgreSQL, fleet offline и VPN incidents |

## 🧩 Компоненты и интерфейсы

| Компонент | Документы |
| --- | --- |
| Общая архитектура | [Обзор](architecture.md) · [Fleet operations / observability](architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) · [Архитектурные решения](adr/README.md) |
| Backend | [Генерируемый API-каталог](api-endpoints.md) · [OpenAPI JSON](openapi.json) · [Обзор API](api-reference.md) |
| Web UI | [Экранные сценарии](web-ui-guide.md) · [Сессии и cache lifecycle](security/frontend-sessions.md) |
| Android | [Agent guide](android-agent.md) · [Протокол соединения](architecture/ANDROID-CONNECTION-PROTOCOL.md) |
| Discovery / recovery | [Подписанный manifest](architecture/ANDROID-SIGNED-DISCOVERY.md) · [Сохранённые маршруты](architecture/ANDROID-SAVED-ROUTES.md) · [Фоновая регистрация](architecture/ANDROID-BACKGROUND-ENROLLMENT.md) |
| APK updates | [Отказоустойчивая OTA](architecture/ANDROID-OTA-RELIABILITY.md) · [Transport retry](audits/2026-09-20/OTA-TRANSPORT-RETRY.md) |
| PC-agent | [Workstation identity, локальные инструменты и подключение](pc-agent.md) |
| PostgreSQL | [RLS / runtime roles](security/postgresql-rls.md) · [Worker RLS](audits/2026-09-20/PIPELINE-RLS.md) |
| Задачи | [Task control protocol](security/task-control-protocol.md) · [Durable cancellation](audits/2026-09-20/DURABLE-CANCELLATION.md) |
| Оркестрация | [Pipeline recovery](audits/2026-09-20/PIPELINE-RECOVERY.md) · [Batch recovery](audits/2026-09-20/BATCH-RECOVERY.md) · [Nested waiting](audits/2026-09-20/PIPELINE-NESTED-WAIT.md) |
| Identity / credentials | [User bootstrap](security/user-auth-bootstrap.md) · [Device bootstrap](security/device-credential-bootstrap.md) · [Device refresh](security/device-refresh-recovery.md) · [Account credentials](security/account-credentials.md) |
| VPN | [Control outcomes](operations/VPN-CONTROL-OUTCOMES.md) · [F32 evidence](audits/2026-10-03/VPN-CONTROL-OUTCOMES.md) · [Реестр ограничений F32-11/12/21](audits/2026-09-20/FLEET32-PREFLIGHT.md) · [VPN intents](audits/2026-09-05/VPN-LEASE-DESIGN.md) · [Runbook](runbooks/02-vpn-incident.md) |

## 🔬 Что подтверждено проверкой

| Последняя контрольная точка | Доказательства и границы |
| --- | --- |
| Согласованный rollout backend/APK 1.2.8 | [Canary 21 сентября](audits/2026-09-20/CANARY-20260921.md): OTA, backup/restore, 15 tasks, два pipeline |
| Frontend `9924eb1` | [AUD-138](audits/2026-09-20/DECODER-RECOVERY.md): decoder bounds/recovery и два живых потока после restart |
| Первый IDR и восстановление | [AUD-140 / F32-29](audits/2026-09-20/STREAM-FIRST-FRAME.md) · [AUD-142 / F32-31](audits/2026-09-20/ANDROID-KEYFRAME-STARTUP.md): browser retry, отложенный Android keyframe до старта encoder, backend forwarding regression; удалённая приёмка ещё OPEN |
| Standalone-сборка frontend | [AUD-141 / F32-30](audits/2026-09-20/FRONTEND-STANDALONE.md): Linux CI build/root-entrypoint passed; отдельный frontend Docker image не проверен; Windows trace warning remains |
| Redis budget | [Текущий бюджет и evidence](operations/REDIS-MEMORY.md): после нового OOM на 2 GiB source ceiling 3 GiB прошёл same-image Desktop и GitHub Linux pressure/restart; installed pilot 1536 MiB и fleet capacity проверяются отдельно. [AUD-143](audits/2026-09-20/REDIS-PERSISTENCE-HEADROOM.md) сохранён как история |
| OTA transfer | [AUD-144 / F32-33](audits/2026-09-20/OTA-TRANSPORT-RETRY.md): local before/after regression and bounded retry; 1.2.10/10210 is historical and was not a published OTA catalog entry |
| Clone binding and reconnect | [AUD-145 / F32-34](audits/2026-09-20/CLONE-BINDING-V2.md) · [AUD-162](audits/2026-09-24/REMOTE-RECONNECT-INCIDENT.md) · [Android-only clone plan](architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md): local 1.2.15 debug candidate contains terminal refresh and duplicate-start recovery; OTA rollout, remote identity and 3-clone acceptance remain open |
| Первый кадр на Android | [AUD-161](audits/2026-09-23/ANDROID-INITIAL-FRAME-RACE.md): воспроизведено отбрасывание раннего ImageReader callback; source fix и 621 тест на flavor прошли, удалённый canary ещё не принят |
| Сетевые отказы | [Native matrix](audits/2026-09-05/NETWORK-RECOVERY-NATIVE.md) · [Reconnect debt](audits/2026-09-05/ANDROID-RECONNECT-DEBT.md) |
| Автозапуск и разрешения | [Boot recovery](audits/2026-09-05/ANDROID-BOOT-RECOVERY.md) · [Root capabilities](audits/2026-09-05/ANDROID-UNATTENDED-CAPABILITIES.md) |
| Несколько viewers | [AUD-126](audits/2026-09-05/STREAM-MULTI-VIEWER.md) · [Критерий новых кадров](audits/2026-09-05/SOAK-VIEWER-MOTION.md) |
| Последний длинный прогон | [FAILED через 3 ч 33 мин](audits/2026-09-05/STREAM-START-DELIVERY.md); восемь часов не приняты |

Полная история: **[Audit report](audits/2026-09-05/AUDIT-REPORT.md)**.
Тестовая база: [PostgreSQL/Redis regressions](../tests/production/README.md) ·
[Container probes](../tests/containers/README.md) · [CI workflows](../.github/workflows/).

## 🛠️ Участие в проекте

[Contributing](../CONTRIBUTING.md) · [Support и диагностические формы](../SUPPORT.md) ·
[Security policy](../SECURITY.md) · [Changelog](../CHANGELOG.md) ·
[Как поддерживать документацию](DOCUMENTATION.md) · [Устройство GitHub-репозитория](../.github/REPOSITORY-GUIDE.md).

## 🗂️ Проекты и исторические материалы

Эти документы полезны для контекста. Они не подтверждают установленную возможность
или достигнутую производительность:

- [AI readiness](architecture/AI-READINESS.md) — будущие observation/action consumers; реализация отложена.
- [Synthetic load architecture](load-test/01-ARCHITECTURE.md) · [сценарии](load-test/02-SCENARIOS.md) · [KPI](load-test/03-METRICS-AND-CRITERIA.md) · [исторический execution report](load-test/04-EXECUTION-REPORT.md).
- [Bootstrap discovery design](architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) · [Discovery recovery design](architecture/ANDROID-DISCOVERY-RECOVERY.md).
- [Предметный анализ автоматизации](ANALYSIS-FARMING-SUMMARY.md) · [подробный анализ](ANALYSIS-FARMING-PLATFORM.md).

Не нашли ответ или нашли противоречие? [Открыть замечание к документации](https://github.com/RootOne1337/sphere-platform/issues/new?template=documentation.yml).
