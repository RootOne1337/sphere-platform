# Приоритеты продолжающегося аудита

Обновлено 8 сентября 2026. Этот документ задаёт порядок работ; наличие пункта
не означает, что его эксплуатация уже доказана. Для закрытия нужен воспроизводимый
сценарий, исправление, regression test и повторная проверка.

| Приоритет | Область | Текущее состояние | Следующее доказательство/критерий закрытия |
| --- | --- | --- | --- |
| 1 | Task lifecycle | SQL assignment/receipt recovery, Android journal, TaskService producer/cancel serialization, distinct control receipts, APK target matching/checkpoints в loop/retry/final outcome, batch/scheduler cancel/result serialization, batch counters, wave outcome/admission accounting, commit-before-launch, wave/cancel transaction fence и UTC watchdog исправлены | Durable cancellation/stop ACK, ordering controls той же задачи, Redis/commit failure при cancel, pipeline writer fencing/child stop, durable wave plan/replay/recovery, stale RUNNING reconciliation, pipeline/scheduler producers, post-commit webhook/events |
| 1 | Авторизация и secrets | Исправлены role/API-key/device/task/n8n boundaries, право reveal, шифрование всех account writers и key-aware migration/rotation CLI; logout cookie/header contract, single-use refresh и MFA consumption исправлены; RLS owner bypass подтверждён | Refresh-family revoke/unknown commit и multiple tabs (single-use SQL rotation исправлена в AUD-52; frontend session fixes в AUD-49–51), реальная непривилегированная PostgreSQL роль, межорганизационный доступ по всем API/jobs, rollout/backfill/restore с управляемыми ключами, журнал reveal, APK/cache/logs и косвенный доступ через tasks |
| 1 | Orchestrator | Версии закреплены; пароль исключён из новых metadata; account ownership, terminal receipt и rollback/retry исправлены | Конкурентные creation ticks, savepoint при частичной ошибке, crash recovery pipeline, транзакционные stats |
| 1 | VPN | Глобальная SQL uniqueness/intent до provider effects, generation fencing, unknown-outcome retention и health recovery исправлены; 64 конкурентных assignments проверены | [Реализация и остаточные риски](VPN-LEASE-DESIGN.md): authoritative provider inventory/reconciliation, rollout legacy/orphan peers, зарезервированные router IP, AWG/маршруты, encoded-key adapter и реальный command publisher |
| 1 | Deployment | Startup export и наследование dev commands/mounts/root/PG/Redis/application ports исправлены; оба Compose merge проверены | n8n/MinIO ingress, RLS roles, OTA/log persistence, запуск/health/recovery и restore backup |
| 2 | APK runtime и производительность | 344 JVM tests; лимит loop diagnostics не пропускает действия, coroutine cancellation выходит из body; typeText больше не пишет raw/encoded ввод в логи; root pipe unknown не повторяется автоматически через DAG/loop; сервер восстанавливает evicted presence по pong; реальный APK↔API и нагрузка 10–64 не завершены | Root execution ACK, Lua pcall/unknown reconciliation, FGS/boot/timeout, emulator/physical permissions, process death, codec backpressure/recovery, multi-worker session fencing, PubSub reconnect, CPU/RAM/FPS/battery |
| 2 | PC agent | Идентичность workstation и ORM registration исправлены | Реальный command/ACK контракт, reconnect и замена сессии, ошибки ADB/emulator process, идемпотентность |
| 2 | Dependencies/CI | Совместимое Python обновление: 1127 tests, pip check и joint pip-audit без известных уязвимостей; на 5d2f331 backend/frontend/Android CI успешны; Host→audit/log/metrics path исправлен | Frontend/Android/container advisories, hash lock/SBOM, dependency-aware mypy, actions runtime/version pins; отдельный подготовленный load job |
| 2 | Frontend/n8n/observability | 198 Jest tests и tsc проходят на Node 24; guard/cache/session/logout исправлены; frontend CI на 0eeeaca прошёл Linux tests/types/build/standalone entry point; browser checks неполны | Supported Node runtime, Jest/tsc/browser, API-key/HMAC/webhook contracts, реальные метрики/alerts и multiprocess |
| 3 | Уборка и удобство эксплуатации | HTTP schema/catalog воспроизводятся из кода; CI проверяет актуальность; Tasks/Batches и APK guide сверены | Устаревшие Redis producer paths, документация конфигурации, согласованный gitignore для regression tests, runbooks и дашборды |

Ограничения проверки: запуск выделенного локального API отклонён автоматической
проверкой разрешений (`blocked by policy`), обход не выполнялся. Выделенный AVD
на порту 5580 недоступен; чужой emulator-5554 не изменялся. Результаты на JVM не
подменяют аппаратные измерения. PR остаётся draft, merge/deployment не выполнялись.
