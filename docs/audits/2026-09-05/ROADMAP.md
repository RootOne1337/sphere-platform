# Приоритеты продолжающегося аудита

Обновлено 11 сентября 2026. Этот документ задаёт порядок работ; наличие пункта
не означает, что его эксплуатация уже доказана. Для закрытия нужен воспроизводимый
сценарий, исправление, regression test и повторная проверка.

**Приоритет владельца от 9 сентября: реальная эксплуатация.** Порядок P0–P3 теперь
задаёт [эксплуатационная матрица](../../operations/READINESS.md): APK recovery/fallback,
сохранность заданий, запуск и наблюдаемость → достоверность UI → capacity → будущий AI.
Новые security barriers не являются самостоятельной целью development-этапа.
RLS остаётся условием корректной работы текущих путей и будущего rollout.

**Уточнение владельца от 11 сентября:** ближайший результат — первый рабочий
пилот: стек/веб/вход/APK/задача, затем VPN/recovery и основные операции UI.
[План приёмки с условными сроками](../../operations/PILOT-ACCEPTANCE.md). Завершение
всего исторического backlog не является условием первого пилота; новые blockers
этой цепочки получают приоритет. AI остаётся отдельным анализом.

## Технический backlog по компонентам

Таблица ниже сохраняет прежнюю классификацию аудита; текущий порядок работ — в
эксплуатационной матрице. Новый fleet target — сотни/тысячи APK, 10–64 на станции;
ёмкость не измерена. AUD-67 исправляет clean-close pacing и jitter (347 JVM tests).
AUD-68 исправляет ложный startup success; 17 новых regression cases проверяют
native CLI/readiness, полный daemon/reboot drill остаётся открытым.


| Приоритет | Область | Текущее состояние | Следующее доказательство/критерий закрытия |
| --- | --- | --- | --- |
| 1 — rollout | RLS | Owner/member/TRUNCATE bypass доказаны; guard и политики всех 28 tables исправлены; 39 PostgreSQL + 4 inventory cases; AUD-55 добавляет 16 cases сохранения tenant после commit/recovery и запрета rebind; audit writer переведён (AUD-56, 6 ASGI/PG cases); user JWT до lookup (AUD-57); API-key/device refresh bootstrap, Android ASGI auth/reconnect и key revoke race исправлены (AUD-58–60, 37 новых cases); post-auth task/progress/event Sessions исправлены (AUD-61, 15 новых cases); user login/refresh/logout/MFA bootstrap исправлен (AUD-62, 34 новых cases) | Перевод остальных unscoped callers на bound Sessions, фоновые jobs, provisioning отдельных ролей; разрешённые и запрещённые HTTP/worker сценарии под runtime credentials; rollout остаётся заблокированным |
| 1 | Task lifecycle | SQL assignment/receipt recovery, Android journal, TaskService producer/cancel serialization, distinct control receipts, APK target matching/checkpoints в loop/retry/final outcome, batch/scheduler cancel/result serialization, batch counters, wave outcome/admission accounting, commit-before-launch, wave/cancel transaction fence и UTC watchdog исправлены | Durable cancellation/stop ACK, ordering controls той же задачи, Redis/commit failure при cancel, pipeline writer fencing/child stop, durable wave plan/replay/recovery, stale RUNNING reconciliation, pipeline/scheduler producers, post-commit webhook/events |
| 1 | Авторизация и secrets | Исправлены role/API-key/device/task/n8n boundaries, право reveal, шифрование всех account writers и key-aware migration/rotation CLI; logout cookie/header contract, single-use refresh и MFA consumption исправлены; RLS owner bypass подтверждён | Refresh-family revoke/unknown commit и multiple tabs (single-use SQL rotation исправлена в AUD-52; frontend session fixes в AUD-49–51), реальная непривилегированная PostgreSQL роль, межорганизационный доступ по всем API/jobs, rollout/backfill/restore с управляемыми ключами, журнал reveal, APK/cache/logs и косвенный доступ через tasks |
| 1 | Orchestrator | Версии закреплены; пароль исключён из новых metadata; account ownership, terminal receipt и rollback/retry исправлены | Конкурентные creation ticks, savepoint при частичной ошибке, crash recovery pipeline, транзакционные stats |
| 1 | VPN | Глобальная SQL uniqueness/intent до provider effects, generation fencing, unknown-outcome retention и health recovery исправлены; 64 конкурентных assignments проверены | [Реализация и остаточные риски](VPN-LEASE-DESIGN.md): authoritative provider inventory/reconciliation, rollout legacy/orphan peers, зарезервированные router IP, AWG/маршруты, encoded-key adapter и реальный command publisher |
| 1 | Deployment | Startup export и наследование dev commands/mounts/root/PG/Redis/application ports исправлены; оба Compose merge проверены | n8n/MinIO ingress, RLS roles, OTA/log persistence, запуск/health/recovery и restore backup |
| 2 | APK runtime и производительность | Последний локальный Android итог: 485 JVM tests (AUD-77); лимит loop diagnostics не пропускает действия, coroutine cancellation выходит из body; typeText больше не пишет raw/encoded ввод в логи; root pipe unknown не повторяется автоматически через DAG/loop; сервер восстанавливает evicted presence по pong; реальный APK↔API и нагрузка 10–64 не завершены | Root execution ACK, Lua pcall/unknown reconciliation, FGS/boot/timeout, emulator/physical permissions, process death, codec backpressure/recovery, multi-worker session fencing, PubSub reconnect, CPU/RAM/FPS/battery |
| 2 | PC agent | Идентичность workstation и ORM registration исправлены; API-key bootstrap и fresh registration tenant исправлены (AUD-63, 12 non-owner cases); потеря terminal replies до Redis channel исправлена (AUD-64, 10 protocol cases); client transport recovery/state cleanup исправлены (AUD-65, 9 lifecycle cases); unknown command false-success исправлен (AUD-66, 3 Redis cases) | Durable PC result/ACK, payload/correlation validation, topology replay, provisioning, real ASGI disconnect, reconnect и замена сессии, ошибки ADB/emulator process, идемпотентность |
| 2 | Dependencies/CI | Последний полный локальный прогон AUD-78: 1413 tests / 69,38%; совместимое Python обновление, pip check и joint pip-audit без известных уязвимостей; на 769aec3 backend/frontend/Android CI успешны с первой попытки; Host→audit/log/metrics path исправлен | Frontend/Android/container advisories, hash lock/SBOM, dependency-aware mypy, actions runtime/version pins; отдельный подготовленный load job; исследование повторяющейся timing variance DAG benchmark на CI (100 ms gate сохранён) |
| 2 | Frontend/n8n/observability | 198 Jest tests и tsc проходят на Node 24; guard/cache/session/logout исправлены; frontend CI на 769aec3 прошёл Linux tests/types/build/standalone entry point; browser checks неполны | Supported Node runtime, Jest/tsc/browser, API-key/HMAC/webhook contracts, реальные метрики/alerts и multiprocess |
| 3 | Уборка и удобство эксплуатации | HTTP schema/catalog воспроизводятся из кода; CI проверяет актуальность; Tasks/Batches и APK guide сверены | Устаревшие Redis producer paths, документация конфигурации, согласованный gitignore для regression tests, runbooks и дашборды |

Ограничения проверки: запуск выделенного локального API отклонён автоматической
проверкой разрешений (`blocked by policy`), обход не выполнялся. Выделенный AVD
на порту 5580 недоступен; чужой emulator-5554 не изменялся. Результаты на JVM не
подменяют аппаратные измерения. PR остаётся draft, merge/deployment не выполнялись.


Code head `f272360` (AUD-61) полностью прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705525),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705438) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34348705527).
Сохранены [backend](evidence/ci-f272360-backend.json),
[frontend](evidence/ci-f272360-frontend.json) и [Android](evidence/ci-f272360-android.json)
snapshots. [Linux summary](evidence/ci-f272360-tests.txt): **1266 passed / 68,65%**;
Windows: **1266 passed / 68,71%**, четыре warnings; неизменный 65% gate пройден.
Все 15 новых cases входят в CI. Preview guard успешен, deploy пропущен. Временных
runtime LOGIN-ролей и соединений после локальных прогонов осталось ноль. Проверены
222 локальные Markdown-ссылки в 11 руководствах перед добавлением CI-снимков.
Независимых PR reviews нет; PR остаётся draft. Следующий documentation-only commit
сохраняет результаты и запускает собственные checks; production code не меняется.


Code head `d642273` (AUD-62) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906033),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906010) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34379906047).
Снимки: [backend](evidence/ci-d642273-backend.json),
[frontend](evidence/ci-d642273-frontend.json), [Android](evidence/ci-d642273-android.json).
[Linux summary](evidence/ci-d642273-tests.txt): **1300 passed / 68,77%**;
Windows: **1300 passed / 68,80%**, включая **428 PostgreSQL/Redis cases**, четыре
warnings. Неизменный 65% gate пройден. Новая миграция и все 34 user-bootstrap cases
проверены в CI. Preview guard успешен, deploy пропущен. После локальных тестов
временных runtime LOGIN-ролей и соединений ноль. PR остаётся draft без независимого
review; production grants/cutover не выполнялись. Следующий документационный commit
сохраняет эти результаты и запускает собственные checks, не меняя production code.


Code head `eda33a7` (AUD-63–64) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128767),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128758) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34383128765).
Сохранены [backend](evidence/ci-eda33a7-backend.json),
[frontend](evidence/ci-eda33a7-frontend.json) и [Android](evidence/ci-eda33a7-android.json)
snapshots. [Linux summary и все 22 новых PC cases](evidence/ci-eda33a7-tests.txt):
**1322 passed / 69,27%**, 264,00 s; Windows: **1322 / 69,30%**, включая **450
PostgreSQL/Redis cases**, четыре warnings. Порог 65% сохранён; lint/mypy, dependency
security, RLS и миграции прошли. Preview guard успешен, deploy пропущен. Временных
локальных runtime LOGIN-ролей и соединений ноль. Документационный commit сохраняет
эти результаты и запускает собственные checks; production code после `eda33a7`
не меняется. PR остаётся draft без независимого review; OS/ADB/LDPlayer/APK/network
и нагрузка 10–64 не объявлены проверенными. Merge/deployment не выполнялись.


Code head `8692a58` (AUD-65–66) прошёл с первой попытки
[backend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387311587),
[frontend CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387311505) и
[Android CI](https://github.com/RootOne1337/sphere-platform/actions/runs/34387314911).
Сохранены [backend](evidence/ci-8692a58-backend.json),
[frontend](evidence/ci-8692a58-frontend.json) и [Android](evidence/ci-8692a58-android.json)
snapshots. [Linux summary, 12 новых cases и исправленный backoff test](evidence/ci-8692a58-tests.txt):
**1334 passed / 69,27%**, 266,92 s; Windows: **1334 / 69,31%**, включая **453
PostgreSQL/Redis cases**, четыре прежних warnings. Порог 65% сохранён; lint/mypy,
security, RLS и миграции прошли. Preview guard успешен, deploy пропущен. Временных
локальных runtime LOGIN-ролей и соединений ноль. Документационный commit сохраняет
результаты и запускает собственные checks; исполняемый код после `8692a58` не
меняется. PR остаётся draft без независимого review, merge или deployment. Реальные
PC/APK sockets, OS/subprocess и нагрузка 10–64 устройств не объявлены проверенными.


Ревизия `769aec3` (включая AUD-67/68): backend/frontend/Android CI прошли с первой
попытки; Linux **1351 passed / 69,27%**, Windows **1351 / 69,32%**. Все 17 новых
startup cases прошли на обеих ОС. APK suite — **347 JVM tests**, сборка CI успешна.
[Сохранённая проверка](AUDIT-REPORT.md) отделена от предстоящих OS/network/load drills.


### Следующий этап после AUD-69/70

Device refresh lost-response recovery исправлен: 24 SQL/ASGI и семь APK cases,
общий Windows прогон **1375 tests / 69,35%**, **477 PG/Redis**, **354 Android JVM**.
Code commits: `83585d3`, `484cca6`; текущий schema head `20260910_device_refresh_retry`.
[Recovery/rollout](../../security/device-refresh-recovery.md) ограничен одним
нерасходованным преемником, без продления expiry. CI `9177769` прошёл attempt 1: backend/frontend/Android; Linux **1375 / 69,30%**.
[Exact snapshots](AUDIT-REPORT.md) сохранены; следующие OS/network испытания отдельны.

На этапе AUD-71 hard HTTP timeout/cancellation refresh воспроизведён и исправлен:
исходные четыре failures/один control, восемь новых regressions; **362 Android JVM
tests / 29 suites** проходят. Deadline отменяет конкретный Call, late body не
записывает credentials, pending ID сохраняет recovery. Это не SLA блокирующего
disk/keystore commit и не OS/socket proof. [Evidence и границы](AUDIT-REPORT.md#aud-71--high-зависший-apk-refresh-задерживал-stopreconnect-и-сохранял-ответ-после-отмены).

Следующие P0: сохранённый secondary management
route и локальный discovery без GitHub; real Android process/host/network recovery;
сохранность текущего задания/ACK после отказа. Исторические user-session lost commit
и initial enrollment loss не закрываются device-refresh протоколом. Monitoring
wiring, truthful VPN UI, incident timeline и measured capacity остаются открытыми.

CI ревизии `fec0c5f` с AUD-71 прошёл с первой попытки: backend/frontend, Android
push и PR. Linux **1375 tests / 69,30%**, все 24 SQL refresh-recovery cases; Android
Dev/Enterprise × Debug/Release test tasks успешны. [Snapshots и точные границы](AUDIT-REPORT.md#проверка-ревизии-fec0c5f-с-aud-71)
сохранены. Preview guard прошёл, deployment skipped; PR остаётся draft.


### Предпосылка резервного канала: AUD-72

Проверка выбора рабочего маршрута выявила ложный `isConnected` до server auth
и callbacks завершённого WS во время backoff. Исправлено подтверждение device ID
перед application traffic и fencing terminal session: 16 новых JVM и восемь
SQL/ASGI cases, полный local backend/PC **1383 / 69,39%**, **485 PG/Redis**, Android
**378 / 30 suites**. [Handshake / rollout](../../architecture/ANDROID-CONNECTION-PROTOCOL.md).
Новый APK требует обновления всех backend workers; schema не менялась.

Резервный route пока не реализован: сохранённые primary/secondary endpoints одной
установки, local discovery, versioning/rollback конфигурации и реальные OS/network
drills остаются следующим P0. ACK не является probe всех downstream dependencies.

CI code revision `70c6a21` с AUD-72 прошёл с первой попытки: backend/frontend,
Android push и PR. Linux **1383 tests / 69,34%**, включая все восемь новых SQL/ASGI
auth-ack cases; четыре Android Dev/Enterprise × Debug/Release test tasks успешны.
[Снимки, excerpts и границы проверки](AUDIT-REPORT.md#проверка-ревизии-70c6a21-с-aud-72)
сохранены. Временных SQL runtime-ролей и других DB connections не осталось.
Документационный commit не меняет code revision; preview deployment skipped,
PR остаётся draft. Rollout требует **все backend workers → APK**.


### Устранение отказов существующего discovery: AUD-73

Воспроизведены JWT-as-API-key 401, 64 параллельных forced checks, блокирующий HTTP,
late response после stop/смены URL и чтение oversized body. Исправлены публичный
cancellable request, один active check и local revision fence. **399 Android tests /
31 suites**, 21 новый case, два SQL/ASGI contract controls; [доказательства](AUDIT-REPORT.md).
Это ещё не secondary route. Следующий P0 — сохранить рабочий адрес при проверке
кандидата, primary/secondary одной установки и local discovery без GitHub; затем
проверить реальные OS/network/fleet drills. [Границы](../../architecture/ANDROID-DISCOVERY-RECOVERY.md).

Полный Windows backend/PC прогон AUD-73: **1385 / 69,42%**, **487 PG/Redis** и
25 deployment cases; Ruff/API export pass. Schema не менялась, временных runtime
ролей/других DB connections ноль. CI code revision `e68ec0a` прошёл с первой
попытки: backend/frontend, Android push/PR; Linux **1385 / 69,36%**, оба новых
discovery contract cases и четыре Android test tasks успешны.
[Точные snapshots и ограничения](AUDIT-REPORT.md#проверка-ревизии-e68ec0a-с-aud-73).
Документационный commit сохраняет проверенную code revision; deployment skipped,
PR остаётся draft.

### Сохранённый резерв и выбор подтверждённого маршрута: AUD-74

Предыдущая запись «secondary route ещё не реализован» описывает ревизии до AUD-74.
Теперь сохранены primary/fallback + выбранный адрес; WS и refresh перебирают их
без обращения к GitHub. Discovery не обрывает здоровую связь; выбранный адрес
меняется по подтверждению device ID. Пара сохраняется одним commit, локальные
MDM/файлы читаются при старте без bootstrap key для уже enrolled APK. Генератор
переносит fallback, его enrollment key распознаётся APK; LAN registration сохраняет
адрес запроса. [Контракт и rollout](../../architecture/ANDROID-SAVED-ROUTES.md).

Следующие P0: фактический OS/network/backend restart drill с метриками возврата,
durable config revision/rollback и проверка установки до credentials; диагностика
инцидента по device/task/time. Не заявлены кластер БД, независимый transport,
гарантированный reconnect SLA или совместимость со всеми Android. Отдельно остаются
loss при enrollment и unknown outcome физических действий. P1 monitoring/UI data
и профилирование ресурсов сохраняют приоритет после восстановления управления.

CI `5f7900e`: backend/frontend/Android push прошли, Android PR обнаружил race
в discovery assertion после preference commit. Управляемая пауза воспроизвела
раннюю проверку счётчика; harness теперь ожидает completion. Evidence первой
неуспешной попытки сохранена, исправление теста проверяется отдельным commit.
Legacy `UPDATE_CONFIG` остаётся single-URL путём; пару задают MDM/JSON/discovery.

Ревизия AUD-74 `2bbd9a5`: все backend/frontend/Android CI прошли с первой
попытки; Linux **1390 / 69,38%**, новые пять Python cases PASSED,
все четыре Android test variants. [Evidence](evidence/ci-2bbd9a5-tests.txt).
Legacy `UPDATE_CONFIG` остаётся single-URL путём и очищает резерв; расширение
его контракта должно проверять сохранение работающего маршрута и identity.

## AUD-75 — фоновая регистрация и identity: локально исправлено

Supplied bootstrap key больше не становится рабочим token без registration;
generated JSON flag/null разобраны правильно. Workers сериализованы и повторяют
activation уже выданной identity. WS перечитывает ID и отвергает поздний ACK старого
устройства. **24 новых JVM cases; 450 / 33 suites проходят**. Baseline failures и
границы проверки — в [AUD-75 report](AUDIT-REPORT.md) и [контракте](../../architecture/ANDROID-BACKGROUND-ENROLLMENT.md).

Следующие P0: initial registration response loss/atomic disk state, ручной setup
против background enrollment, legacy UPDATE_CONFIG с резервным адресом, реальные
boot/network/fleet drills и расследуемый incident timeline. Monitoring Compose,
фиктивные VPN measurements и resource profiles сохраняют приоритеты матрицы.
Новая ревизия требует собственного CI; merge/deployment не выполнялись.

### CI AUD-75 зафиксирован

Runtime **`be75f57`**: backend/frontend/Android PR+push прошли с первой попытки;
preview только guard, deploy skipped. Backend **1390 / 69.38%**, Android все
четыре test variants. Локально **450 / 33 suites**. [Точные SHA/run links и evidence](AUDIT-REPORT.md).
Это проверка очередного исправления, не завершение всего аудита или аппаратного rollout.

## AUD-76 — registration HTTP: локально исправлено

Blocking HTTP, отсутствие call cancellation, поздняя запись после stop и чтение
body до лимита воспроизведены и исправлены. **15 новых cases; 465 / 34 suites**.
Отдельно сохранена корректировка ложного interceptor-count assertion, без изменения
runtime policy. [AUD-76 report](AUDIT-REPORT.md) содержит baseline и residual risks.

Следующий P0 — initial registration response loss и atomic identity persistence,
конкуренция ручного setup и worker, clone identity/config metadata; затем legacy
UPDATE_CONFIG и реальные OS/fleet drills. HTTP cancellation не закрывает эти задачи.
CI новой ревизии обязателен; весь запрос владельца ещё не завершён.

### CI AUD-76 зафиксирован

Runtime **`2f17a85`**: backend/frontend/Android PR+push прошли с первой попытки;
preview только guard, deploy skipped. Backend **1390 / 69.37%**, Android все
четыре test variants. Локально **465 / 34 suites**. [Точные SHA/run links и evidence](AUDIT-REPORT.md).
Это проверка очередного исправления, не завершение всего аудита или аппаратного rollout.

## AUD-77 — registration persistence и порядок issuance: локально исправлено

Единый checked commit и общий mutex с refresh закрывают воспроизведённые потери
UUID/tokens/routes и обратный порядок ответов. Versions защищают от clear/route/ID
changes. **20 новых cases; 485 / 35 suites**. Baseline: **8 failures / 1 control**.
Это закрывает локальные части atomic identity/manual HTTP concurrency из AUD-75/76.

Следующий P0: server commit response loss, failed re-enrollment с уже отозванным
старым refresh и recovery intent; затем clone identity, legacy static setup/config
и initial fallback traversal. Аппаратные OS/network/fleet drills, наблюдаемость,
достоверный UI и ресурсные бюджеты остаются в плане. [Доказательства](AUDIT-REPORT.md).
CI новой runtime ревизии обязателен; audit целиком не завершён.

### CI AUD-77 зафиксирован

Runtime **`93a4872`**: backend/frontend/Android PR+push прошли с первой попытки;
preview только guard, deploy skipped. Backend **1390 / 69.40%**, Android все
четыре test variants. Локально **485 / 35 suites**. [Точные SHA/run links и evidence](AUDIT-REPORT.md).
Это проверка очередного исправления, не завершение всего аудита или аппаратного rollout.

## AUD-78 — bootstrap пилота: локально исправлено

23 новых SQL/HTTP/process cases; **1413 общий прогон / 505 real-service / 33 deployment**.
Отдельный admin Python process проходит login→registration→device read; launcher
functions передают credentials и не скрывают ошибки. [Доказательства](AUDIT-REPORT.md).

Следующий шаг рубежа A: согласовать env-file/Compose и migration order для fresh
startup; пройти выбранный browser/APK/task путь на разрешённом стенде. Затем VPN,
initial enrollment recovery и clone identity. Наблюдаемость, truthful UI и capacity
остаются в [критериях пилота](../../operations/PILOT-ACCEPTANCE.md); AI не внедряется.

AUD-79 закрывает Bash Compose argument routing: global IFS больше не превращает
file options в один аргумент. Четыре before failures, 37 passing deployment cases;
следующие startup priorities — единый env-file, migration ordering, runtime roles,
истинная readiness. [Доказательства](evidence/compose-arguments-before-summary.json).

AUD-78/79 exact runtime CI завершён: `0da40f1` — 1413 Linux cases;
`ac7a11f` — **1417 / 69.37%**, 228.42 s. Backend/frontend/Android/preview
на каждой ревизии прошли с первой попытки; preview deployment пропущен. Последний
локальный общий итог 1413 / 69,38%, затем 37 deployment cases. [CI итог](evidence/ci-ac7a11f-tests.txt).
Это подтверждает компонентные проверки bootstrap/argv; полный pilot acceptance открыт.

AUD-80 закрывает env selection full-deploy wrapper / штатного start-dev на Windows:
`.env.local` → `.env`, explicit absolute path. Семь новых cases, 44 deployment pass.
Открыты Bash dotenv/source и Windows legacy paths, lifecycle секретов и migration→API
ordering; этот fix не является sign-off полного запуска. [Evidence](evidence/windows-env-before-summary.json).

AUD-80 runtime `ea8e606` прошёл все четыре PR workflows с первой попытки:
**1424 / 69.38%**, 238.84 s. [CI](evidence/ci-ea8e606-tests.txt). Локально 44
deployment cases проходят. Следующий приоритет — fresh bootstrap ordering,
наличие bootstrap CLI в immutable image и корректная identity первого устройства.
Статические наблюдения этих путей требуют отдельных воспроизведений до fix.

AUD-81 закрывает отсутствие admin/enrollment CLI в immutable image: настоящий
container воспроизводит 2 failures, после минимального COPY 4 cases проходят.
CI теперь имеет обязательный image-bootstrap job. Дальше — migration/API ordering
и dev enrollment lifecycle. [Image evidence](evidence/image-bootstrap-summary.json).

AUD-82 закрывает порядок full-deploy и его readiness contract: dependencies →
one-off migration/admin/key → applications; production probes проверяют API/login.
21 baseline failure / 7 controls, все 65 deployment cases проходят. Нет SQL/API
daemon запуска: next — роли/grants, secret lifecycle, dev-key hook и настоящее
fresh image bootstrap. [Evidence](evidence/startup-sequence-after-summary.json).
