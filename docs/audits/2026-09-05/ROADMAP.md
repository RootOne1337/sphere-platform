# Приоритеты продолжающегося аудита

Обновлено 9 сентября 2026. Этот документ задаёт порядок работ; наличие пункта
не означает, что его эксплуатация уже доказана. Для закрытия нужен воспроизводимый
сценарий, исправление, regression test и повторная проверка.

| Приоритет | Область | Текущее состояние | Следующее доказательство/критерий закрытия |
| --- | --- | --- | --- |
| 1 — текущий | RLS | Owner/member/TRUNCATE bypass доказаны; guard и политики всех 28 tables исправлены; 39 PostgreSQL + 4 inventory cases; AUD-55 добавляет 16 cases сохранения tenant после commit/recovery и запрета rebind; audit writer переведён (AUD-56, 6 ASGI/PG cases); user JWT до lookup (AUD-57); API-key/device refresh bootstrap, Android ASGI auth/reconnect и key revoke race исправлены (AUD-58–60, 37 новых cases); post-auth task/progress/event Sessions исправлены (AUD-61, 15 новых cases); user login/refresh/logout/MFA bootstrap исправлен (AUD-62, 34 новых cases) | Перевод остальных unscoped callers на bound Sessions, фоновые jobs, provisioning отдельных ролей; разрешённые и запрещённые HTTP/worker сценарии под runtime credentials; rollout остаётся заблокированным |
| 1 | Task lifecycle | SQL assignment/receipt recovery, Android journal, TaskService producer/cancel serialization, distinct control receipts, APK target matching/checkpoints в loop/retry/final outcome, batch/scheduler cancel/result serialization, batch counters, wave outcome/admission accounting, commit-before-launch, wave/cancel transaction fence и UTC watchdog исправлены | Durable cancellation/stop ACK, ordering controls той же задачи, Redis/commit failure при cancel, pipeline writer fencing/child stop, durable wave plan/replay/recovery, stale RUNNING reconciliation, pipeline/scheduler producers, post-commit webhook/events |
| 1 | Авторизация и secrets | Исправлены role/API-key/device/task/n8n boundaries, право reveal, шифрование всех account writers и key-aware migration/rotation CLI; logout cookie/header contract, single-use refresh и MFA consumption исправлены; RLS owner bypass подтверждён | Refresh-family revoke/unknown commit и multiple tabs (single-use SQL rotation исправлена в AUD-52; frontend session fixes в AUD-49–51), реальная непривилегированная PostgreSQL роль, межорганизационный доступ по всем API/jobs, rollout/backfill/restore с управляемыми ключами, журнал reveal, APK/cache/logs и косвенный доступ через tasks |
| 1 | Orchestrator | Версии закреплены; пароль исключён из новых metadata; account ownership, terminal receipt и rollback/retry исправлены | Конкурентные creation ticks, savepoint при частичной ошибке, crash recovery pipeline, транзакционные stats |
| 1 | VPN | Глобальная SQL uniqueness/intent до provider effects, generation fencing, unknown-outcome retention и health recovery исправлены; 64 конкурентных assignments проверены | [Реализация и остаточные риски](VPN-LEASE-DESIGN.md): authoritative provider inventory/reconciliation, rollout legacy/orphan peers, зарезервированные router IP, AWG/маршруты, encoded-key adapter и реальный command publisher |
| 1 | Deployment | Startup export и наследование dev commands/mounts/root/PG/Redis/application ports исправлены; оба Compose merge проверены | n8n/MinIO ingress, RLS roles, OTA/log persistence, запуск/health/recovery и restore backup |
| 2 | APK runtime и производительность | 344 JVM tests; лимит loop diagnostics не пропускает действия, coroutine cancellation выходит из body; typeText больше не пишет raw/encoded ввод в логи; root pipe unknown не повторяется автоматически через DAG/loop; сервер восстанавливает evicted presence по pong; реальный APK↔API и нагрузка 10–64 не завершены | Root execution ACK, Lua pcall/unknown reconciliation, FGS/boot/timeout, emulator/physical permissions, process death, codec backpressure/recovery, multi-worker session fencing, PubSub reconnect, CPU/RAM/FPS/battery |
| 2 | PC agent | Идентичность workstation и ORM registration исправлены; API-key bootstrap и fresh registration tenant исправлены (AUD-63, 12 non-owner cases); потеря terminal replies до Redis channel исправлена (AUD-64, 10 protocol cases); client transport recovery/state cleanup исправлены (AUD-65, 9 lifecycle cases); unknown command false-success исправлен (AUD-66, 3 Redis cases) | Durable PC result/ACK, payload/correlation validation, topology replay, provisioning, real ASGI disconnect, reconnect и замена сессии, ошибки ADB/emulator process, идемпотентность |
| 2 | Dependencies/CI | Совместимое Python обновление: 1334 tests, pip check и joint pip-audit без известных уязвимостей; на eda33a7 backend/frontend/Android CI успешны с первой попытки; Host→audit/log/metrics path исправлен | Frontend/Android/container advisories, hash lock/SBOM, dependency-aware mypy, actions runtime/version pins; отдельный подготовленный load job; исследование повторяющейся timing variance DAG benchmark на CI (100 ms gate сохранён) |
| 2 | Frontend/n8n/observability | 198 Jest tests и tsc проходят на Node 24; guard/cache/session/logout исправлены; frontend CI на eda33a7 прошёл Linux tests/types/build/standalone entry point; browser checks неполны | Supported Node runtime, Jest/tsc/browser, API-key/HMAC/webhook contracts, реальные метрики/alerts и multiprocess |
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
