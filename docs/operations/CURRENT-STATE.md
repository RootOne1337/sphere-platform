# Sphere: актуальное состояние и критерии приёмки

**Проверено:** 28 сентября 2026, Asia/Yekaterinburg<br />
**Область:** исходники и документация ветки PR #19, записанные runtime-наблюдения, Android APK и готовность следующего прогона.<br />
**Канонический документ текущего состояния:** этот файл. Исторические отчёты ниже сохраняют исходные даты и факты.

[Главная](../../README.md) · [Каталог документации](../README.md) · [Readiness](READINESS.md) · [Fleet32 gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

> [!IMPORTANT]
> Это сверка исходников, CI и уже записанных наблюдений. В этом проходе не выполнялись live-запросы к устройствам, серверу или OTA-каталогу и не запускались задания. Поэтому ниже отдельно указано, что проверено в исходниках, что видел оператор и что требует новой runtime-проверки. Не считайте этот документ отчётом о выкладке.

## Состояние на дату проверки

| Область | Подтверждённое состояние | Что это не доказывает |
| --- | --- | --- |
| PR | PR #19 открыт как draft. GitHub CI на `5c9e56c` завершился успешно 28 сентября 2026, 00:46:11 UTC: backend, Android, frontend, lint/security, RLS, production-image bootstrap и Alembic checks прошли; Preview deploy был пропущен. | Нет merge, production deploy или подтверждения работающей публичной версии сайта. Это исходные проверки PR, не доказательство запуска этих image в production. |
| APK source | Кандидат исходников PR задаёт **1.2.35 / 10235**. Последний записанный оператором/сервером canary — отдельный **1.2.34-dev / 10234**. Релизный путь и пределы доказательств описаны в [Android release-readiness audit](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md). | Source version 1.2.35 не удостоверяет собранный production APK, его подпись, OTA-публикацию или установку на устройства. Для rollout нужны пакет/flavor, `versionCode`, signer, SHA-256, OTA entry и installed report. |
| APK release pipeline | Локально кандидат прошёл все 4 тестовых варианта (2 764 запуска, 0 failures/errors, 4 существующих skips), lint (0 ошибок, 74 warnings), fail-closed проверку без ключа и подписание обоих release flavors одноразовым smoke-сертификатом с успешной проверкой `apksigner` и package/version metadata. GitHub Android CI на `e2d0577` прошёл за 11:52, parser follow-up `2ad9fb3` — за 12:32. После runner deprecation/cache annotations action majors обновлены на Node 24-compatible versions; финальный CI по этим workflow-изменениям ожидается. | Одноразовые APK и ключ удалены после smoke; это не production signing. Production signer, tag/Release, OTA entry, deployed backend, реальная удалённая установка и canary здесь не проверялись. Не устанавливать smoke APK как обновление. |
| APK release / OTA | В записанном canary-контексте кандидат `1.2.34-dev / 10234` был **локальным артефактом**, `published_to_ota=false`; оператор вручную установил его на несколько удалённых эмуляторов. Сервер увидел три свежих agent reports с кодом 10234. | Массовая OTA не публиковалась и не подтверждена. Последнее чтение OTA-каталога для этой даты не выполнялось; версию канала нельзя назвать без нового read-only запроса. Установка трёх пакетов с конкретным SHA независимо не доказана. |
| Удалённое видео | 28 сентября в 03:18 оператор подтвердил видимую живую картинку в браузерной Device Stream странице во время canary. Это прямое наблюдение минимум одного просмотренного потока. | Не зафиксированы точный device/session ID этого viewer, активный маршрут Tuna/fallback, browser decode/render counters, FPS, latency, длительный soak или успех для всего удалённого парка. |
| Парк | Последний записанный read-only snapshot в canary-аудите: **29 записей каталога, 19 active, 14 с heartbeat/WS не старше 45 секунд и 5 active без свежего статуса**. Оператор обозначил 14 устойчиво работающих устройств как базу сравнения. | Число 14 — базовая выборка на момент прежнего наблюдения, а не заново измеренный uptime на момент этой документации. Ожидаемые 23 и масштаб 20–30 устройств не прошли приёмку. |
| Backend / frontend runtime | CI на `b30a849` прошёл проверки сборки/тестов backend, frontend и Android. Source содержит обновлённую truthful monitoring-страницу. | Источник не равен deployed image. Не перечитывались активные container digests, runtime readiness, публичный URL и фактический frontend/backend commit. |
| Frontend dependencies | В PR source обновлены Next.js и `eslint-config-next` с `15.5.13` до `15.5.26`, PostCSS до `8.5.28`; lockfile содержит исправленный Handlebars `4.7.9` и совместимые транзитивные обновления. Локальные Jest (41 suites / 306 tests), type-check и `npm audit` по `frontend/` прошли; аудит сообщает 0 уязвимостей. GitHub frontend CI на `5c9e56c` также прошёл `npm ci`, tests/types/build и standalone entrypoint check. | Это ещё не означает, что версия попала в production image или развёрнутый сайт. Аудит относится к frontend lockfile, а не ко всему репозиторию или production runtime. Подробности и условные advisory — в [отчёте по frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). |
| Default-branch dependency alerts | При push `2cf7e50` GitHub сообщил о 145 Dependabot alerts на `main`: 5 critical, 64 high, 63 moderate, 13 low. | Это GitHub snapshot default branch, не инвентаризация текущего PR lockfile и не доказательство достижимости каждой уязвимости в production. Frontend lockfile текущей ветки проверен отдельно; остальные манифесты требуют собственного triage. |

Подробные основания: [Android release-readiness](../audits/2026-09-28/ANDROID-RELEASE-READINESS.md), [Tuna remote-stream canary, включая обновление 28 сентября](../audits/2026-09-27/TUNA-REMOTE-STREAM-CANARY.md), [truthful monitoring AUD-152](../audits/2026-09-28/INFRASTRUCTURE-MONITORING-TRUTHFUL-TELEMETRY.md), [старые удалённые connection/OTA gates](../audits/2026-09-27/REMOTE-CONNECTION-AND-OTA-GATES.md). Версии из отчётов 25–27 сентября относятся только к указанным в них снимкам.

## Что APK реально умеет сообщить

| Сигнал | Реализованное поведение в исходниках | Граница наблюдаемости |
| --- | --- | --- |
| Идентичность и версия | Агент отправляет device identity и `agent_version`/`agent_version_code`; регистрация и clone rebind — отдельные шаги. | Version code не равен SHA-256 установленного APK и сам по себе не доказывает уникальность клона. |
| Связь/presence | Management WebSocket, ping/pong, reconnect, сохранённые маршруты и recovery state. Backend/UI различают факт принятого соединения и heartbeat/pong. | `online`/сокет не означает, что video frames дошли до браузера или команда успешно завершилась. Для точной диагностики нужны device + session + timestamps и receipts. |
| Видео | APK измеряет локальные capture/render/encode и очередь отправки; backend и viewer имеют отдельные диагностические счётчики. Кадры создаются при callback захвата экрана; неизменившийся экран не обязан повторно слать тот же кадр. | APK queue-accepted не подтверждает backend ingress. Android counters не являются browser FPS. Старый кадр в UI не доказывает текущую связь. Для приёмки нужен контролируемый движущийся экран и корреляция до browser decode/presentation. |
| Файловые логи | Timber logs пишутся асинхронно в app-private storage: кольцевая ротация до пяти файлов по 2 MiB; очередь ограничена 4096 записями; чтение хвоста до 256 KiB. Переполнение очереди отбрасывает новые записи. Ошибки записи выводятся в `System.err`. | Это ограниченный локальный буфер, не постоянный полный event journal. При нехватке места или переполнении часть логов может потеряться. |
| WebSocket lifecycle | Отдельный sidecar ограничен 64 KiB и при ротации оставляет около 32 KiB; uploader берёт до 32 KiB приоритетных lifecycle-записей. | Это диагностические события о lifecycle, не packet capture и не полная трасса каждого сообщения. |
| Android logcat | `LogcatCollector` просит до 5000 строк и удерживает не более 2 MiB; режим `full` запускает unfiltered `logcat` через `ProcessBuilder`, без `su`. | `READ_LOGS` — signature/privileged permission. APK не обещает видеть чужие app logs, системные crash buffers, kernel/native tombstones, LMK и полный ANR-след. Root в эмуляторе не меняет UID этого конкретного collector. |
| Crash | `CrashHandler` сохраняет необработанные Java/Kotlin исключения в app-private файл и обрезает старую часть, когда файл превышает 256 KiB. Log worker может передать до 128 KiB снимка при следующей успешной загрузке и удалить его только если он не изменился во время передачи. | Нельзя гарантировать файл при native `SIGABRT`/`SIGSEGV`, убийстве ядром/LMK, power loss или сбое диска. Их нужно сверять с baseline системного crash buffer или отдельным разрешённым collector. |
| Доставка диагностики | `LogUploadWorker` ставит периодическую работу раз в 15 минут с условием наличия сети и exponential backoff; разовая диагностика имеет случайный сдвиг до 2 минут. В upload включаются до 32 KiB обычных файловых логов, до 300 Sphere logcat строк, lifecycle tail и crash snapshot; общий request ограничен 480 KiB. | WorkManager расписание — best-effort и может задержаться из-за Doze, условий сети, OEM политики или процесса. Это не потоковая телеметрия и не гарантия немедленной доставки. Успех upload подтверждает HTTP ответ, но не полноту всех системных логов. |

### Серверное хранение логов и capacity risk

Backend принимает `POST /api/v1/logs/upload` до 512 KiB, проверяет device API key и пишет дневные файлы по device. Код задаёт дневной file rollover при превышении 50 MiB; файлы старше 30 дней удаляются **только во время следующей загрузки этого же устройства**. Путь по умолчанию — `/tmp/sphere_device_logs`; production должен задать `SPHERE_LOGS_DIR` и обеспечить нужный persistent volume. GET по устройству доступен с `device:read` и по умолчанию читает до трёх последних дневных файлов.

Это не общий disk quota: отдельного per-device/global budget и независимой ежедневной retention-задачи код не задаёт. Грубая оценка при полном использовании дневного cap — порядка 1.5 GiB на устройство за 30 дней (без filesystem overhead; отдельный дневной файл может немного превысить порог на один upload). Это расчётный worst case, не измеренное потребление. Перед ростом fleet требуется persistent-volume capacity, свободное место alerts, глобальная/per-device quota, гарантированный sweeper и политика безопасной деградации при заполнении. См. [`backend/api/v1/logs/router.py`](../../backend/api/v1/logs/router.py) и [stream/logging audit](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md).

Исходники: [`FileLoggingTree.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/FileLoggingTree.kt), [`LogcatCollector.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/LogcatCollector.kt), [`CrashHandler.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/logging/CrashHandler.kt), [`LogUploadWorker.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/workers/LogUploadWorker.kt), [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt), [`CommandDispatcher.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt), [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt), [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt).

### Вывод об отладке

APK уже даёт полезную удалённую диагностику Sphere, включая версии, состояние управления, ограниченные application logs, некоторые crash records и локальные этапы видеоконвейера. Этого хватает, чтобы локализовать часть отказов при хорошем временном/device/session correlation. Это **не «видим всё на устройстве»**: нет гарантированной полной системной телеметрии, записи каждого кадра, native tombstone, packet capture или точного browser FPS без viewer-side данных. Важный следующий разрыв — связать единым trace/correlation ID APK → backend worker/ingress → Redis/broker → viewer receive/decode/render и хранить результат с определённым retention/quota.

## Выполнение скриптов и автономность

### Что уже умеет код

Серверное orchestration API хранит pipeline и конкретные PipelineRun; шаг
`execute_script` может создать device task. APK принимает `EXECUTE_DAG` по
management WebSocket и исполняет сценарий внутри Android. В текущем runner есть:

- Ввод и время: `tap`, `swipe`, `type_text`, `sleep`, `key_event`, `long_press`,
  `double_tap`, `scroll`, `scroll_to`.
- Экран и UI: `screenshot`, `find_element`, `find_first_element`,
  `tap_first_visible`, `wait_for_element_gone`, `tap_element`, `get_element_text`,
  `input_clear`, `launch_app`, `stop_app`, `get_device_info`.
- Поток и значения: `condition`, `assert`, `set_variable`, `get_variable`,
  `increment_variable`, `loop`, `start`, `end`.
- Сеть/система: `http_request`, `open_url`, `clear_app_data`, `shell`, `lua`.

`condition` ограничен проверками `element_exists`, `text_contains`,
`battery_above`; `assert` — проверками элемента, текста, переменной и HTTP status.
Эти predicate-наборы описаны в [`DagRunner.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt); это не произвольный набор библиотек или вызовов ОС. Backend orchestration также содержит `execute_script`, `condition`, `action`, `delay`, `wait_for_event`, `parallel`, `loop`, `sub_pipeline` и `n8n_workflow` handlers.

На APK-стороне есть защитные пределы: до 500 DAG nodes, вложенность выполнения
до 10, максимум 500 routing hops, timeout DAG по умолчанию 300 секунд и node
timeout по умолчанию 30 секунд; вывод node log и loop logs также ограничен.
Lua sandbox удаляет `os`, `io`, `require`, `dofile`, `load`, `debug`, `package`,
`luajava` и raw/metatable escape-функции. Встроенные Lua bindings дают ограниченный
доступ к tap/swipe/type/key, sleep/log/screenshot, UI-element helpers и запуску/
остановке приложения. Это исполняемая автоматизация с результатами/прогрессом,
а не произвольный внешний Python/ADB runtime.

**Открытый Lua-риск из source review:** `executeWithTimeout` использует coroutine `withTimeout`, тогда как LuaJ `chunk.call()` синхронный. В просмотренном коде нет Lua instruction budget или preemption hook. Поэтому 30-секундный coroutine timeout сам по себе не доказывает остановку CPU-bound/infinite Lua loop; такой payload может занять interpreter thread дольше ожидаемого. Пока нет жёсткого лимита инструкций и регрессии на cancellation, на удалённых устройствах запускать только доверенный, review-нутый Lua. См. [`LuaTimeoutWrapper.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaTimeoutWrapper.kt) и [`LuaEngine.kt`](../../android/app/src/main/kotlin/com/sphereplatform/agent/lua/LuaEngine.kt).

### Важные ограничения

- «Автономно» означает: сохранённый pipeline/task может быть запущен расписанием/событием на сервере, доставлен подключённому Android-агенту и выполнен без открытого UI оператора; затем нужно сверить terminal task/pipeline receipt. Это не означает выполнение APK произвольного задания, пока устройство offline, приложение force-stopped или ОС не разрешает нужную операцию.
- После потери связи получение команды и доставка результата имеют отдельные состояния. Не считать `queued`, `sent`, локальный ACK или зелёный progress окончательным успехом. Для каждого canary сверять серверный terminal receipt; `unknown`/timeout требует reconciliation, а не слепого повтора.
- DAG `shell`/`SHELL` вызывает `su -c` и имеет root-эффект; оболочка фильтрует ряд shell metacharacters и ограничивает один вызов пятью секундами, но это всё равно привилегированная удалённая команда. Не направлять непроверенные пользовательские тексты в shell. До массового запуска требуются tenant/RBAC, audit actor, allowlist сценариев, review payload и rollback/stop procedure.
- Один Android device исполняет один DAG одновременно; в backend параллельный `execute_script` для одного device не поддерживается. Pipeline `parallel` нельзя трактовать как безопасный способ параллельно послать конкурирующие скрипты одному устройству.
- Lua sandbox и лимит размера DAG не являются доказательством безопасности/детерминизма всего сценария: действия зависят от root, permission, версии игры, состояния экрана, сети и OEM/Android. Скрипт может менять устройство; тестировать сначала на изолированном canary.
- Интеллектуальный агент, LLM/motor policy, самогенерация безопасного сценария и автоматический выбор игрового аккаунта не входят в подтверждённые возможности данного APK/PR.

Итак: можно выдать заранее определённое, ограниченное задание и позволить серверу оркестрировать его, а APK выполнить device actions после получения. Нельзя на текущем подтверждении обещать «любые скрипты» или полностью автономную работу при любых состояниях сети и Android.

## Android platform guarantees и разрешения

Текущая конфигурация Android: `minSdk 26`, `targetSdk 35`, `compileSdk 35`. Долгоживущий management agent объявлен как foreground service типа `specialUse`; screen capture отделён в `mediaProjection`; фоновые recovery/log jobs используют WorkManager/dataSync. Разрешения и декларации в manifest — не доказательство, что OEM, пользовательские настройки или конкретная Android версия разрешат бесшумный старт во всех случаях.

Android 14+ требует пользовательское согласие для каждого нового MediaProjection capture session и запрещает повторно использовать один projection token. Android 15 для target 35 вводит 6-часовой в 24 часа лимит для `dataSync` foreground services и ограничивает их запуск из `BOOT_COMPLETED`; это отдельно важно для фоновых рабочих задач. В проекте основной management service имеет другой тип, `specialUse`, но WorkManager/boot paths и screen capture должны валидироваться на реальных API/OEM профилях. У WorkManager точное время запуска не гарантируется.

Источники платформы (первичные, сверены 28 сентября 2026):

- [Android 14: MediaProjection consent per session](https://developer.android.com/about/versions/14/behavior-changes-14)
- [Android 15: target 35 behavior changes and FGS limits](https://developer.android.com/about/versions/15/behavior-changes-15)
- [Android 15: foreground-service type restrictions](https://developer.android.com/about/versions/15/changes/foreground-service-types)
- [WorkManager persistent work and retry semantics](https://developer.android.com/develop/background-work/background-tasks/persistent)
- [WorkManager timing depends on constraints/system optimization](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work)
- [Android `READ_LOGS` permission level](https://developer.android.com/reference/android/Manifest.permission#READ_LOGS)

## Следующий приёмочный этап: 20–30 устройств, видео + сценарии

Это **планируемый gate**, тест в рамках этого документа не запускался. Сохранить выбранные оператором 14 стабильных устройств как read-only comparison baseline; сначала завести отдельный canary cohort и зафиксировать устройства/версии до любых команд.

| Шаг | Доказательство на выходе | Условие перехода |
| --- | --- | --- |
| 0. Заморозить build | Build provenance: source SHA, flavor/package ID, `versionCode`, signer, SHA-256, bootstrap/discovery config fingerprint без секретов. | Артефакт и server OTA entry проверены отдельно; если OTA не опубликована — явно использовать ручной canary и не называть это OTA. |
| 1. Сверить идентичность | Для каждого тестового Android — уникальный server device ID, org, последняя версия, boot/session epoch; клоны не должны делить действующие credentials/ID. | Число уникальных свежих устройств соответствует размеру тестовой ступени; duplicate IDs и stale records разобраны, а не переименованы вручную. |
| 2. Одно устройство | Свежий heartbeat; определить фактический маршрут; запустить контролируемое движение экрана; сопоставить Android capture/encode/queue, backend ingress/bridge, viewer receive/decode/present; записать command/session IDs и время. | Видимый кадр принадлежит той же сессии и есть stage-by-stage counter deltas. Статичный idle интервал проверяется отдельно и не требует повторной отправки идентичного кадра. |
| 3. Безопасный DAG на canary | Один заранее reviewed idempotent сценарий, например `get_device_info` + screenshot + проверка результата; связать pipeline run → task/command ID → APK progress/terminal receipt → серверный receipt. | Все receipts терминальны и согласованы. Потеря ACK проверяется reconciliation; нет слепого повтора root/игрового действия. |
| 4. Ступени 14 → 20 → 30 | На каждой ступени сохраняются уникальные устройства, heartbeat-age distribution, reconnect counts, stream session counts, кадры по стадиям, браузерные FPS/age/latency, task receipts, CPU/RAM/network/Redis/DB и crash/ANR delta. | Переход разрешён только если ступень полностью собрана, контрольные данные актуальны, ресурсы не ухудшаются сверх заранее утверждённых SLO, нет новых crash/ANR и нет необъяснённых offline/unknown receipts. |
| 5. Отказ и восстановление на canary | Поочерёдные тесты потери WAN/device-side и backend-side, затем восстановление; один короткий управляемый reconnect. | Тот же device identity возвращается, сессии/receipts корректно reconciled, кадр снова доходит до viewer, duplicate command effects не появляется. Не вводить несколько fault одновременно на первом прогоне. |

Измеряемые SLO/stop thresholds следует согласовать и зафиксировать **до** запуска: задержку first frame, frame age/FPS на движущемся экране, heartbeat freshness, reconnect budget, command terminal receipt latency, crash delta и host capacity. Старый проектный документ нагрузочных метрик содержит синтетические и не привязанные к текущему профилю цифры; не переносить их как production SLO без пересчёта и утверждения. Использовать [Fleet32 readiness/evidence gates](../audits/2026-09-20/FLEET32-PREFLIGHT.md), [метод stream observability](../audits/2026-09-25/ANDROID-STREAM-OBSERVABILITY.md) и [операционный runbook](READINESS.md).

Ступень немедленно остановить при новом Sphere crash/ANR, смене PID без запланированного рестарта, повторяющихся identity collision, потерянном/противоречивом receipt, отсутствии stage correlation, деградации baseline либо неконтролируемом root effect. Сырые логи, токены и signing material держать вне Git; в отчет включать очищенные выдержки и ссылки на приватный evidence.

## Проверки PR #19

На `5c9e56c` GitHub Actions завершил успешно backend real-service regression tests, production-image/bootstrap, lint (`ruff` + `mypy`), security (`bandit` + `pip-audit`), RLS coverage, Alembic single-head, Android build/unit tests и frontend tests/types/build. Последний check завершился в 00:46:11 UTC 28 сентября 2026; Preview deploy job **skipped**. Frontend job подтвердил Linux `npm ci`, tests/types/build и standalone entrypoint. Это подтверждает source CI на указанном SHA, но не production deployment. Локальная Windows-сборка и предупреждение Next standalone tracing, npm audit и остальные границы описаны в [отчёте по безопасности frontend dependencies](../audits/2026-09-28/FRONTEND-DEPENDENCY-SECURITY.md). Статусы новых коммитов смотрите по актуальной вкладке Checks в [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

Для навигации и истории см. [CHANGELOG](../../CHANGELOG.md), [readiness](READINESS.md), [локальный pilot](LOCAL-PILOT.md), [Android guide](../android-agent.md) и [правила поддержания документации](../DOCUMENTATION.md).
