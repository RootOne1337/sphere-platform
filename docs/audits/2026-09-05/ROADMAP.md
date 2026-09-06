# Приоритеты продолжающегося аудита

Обновлено 7 сентября 2026. Этот документ задаёт порядок работ; наличие пункта
не означает, что его эксплуатация уже доказана. Для закрытия нужен воспроизводимый
сценарий, исправление, regression test и повторная проверка.

| Приоритет | Область | Текущее состояние | Следующее доказательство/критерий закрытия |
| --- | --- | --- | --- |
| 1 | Task lifecycle | SQL assignment/receipt recovery, Android journal, TaskService producer/cancel serialization, distinct control receipts, APK target matching/checkpoints в loop/retry/final outcome, batch counters и UTC watchdog исправлены | Durable cancellation/stop ACK, ordering controls той же задачи, Redis/commit failure при cancel, batch/scheduler cancellation, stale RUNNING reconciliation, pipeline/scheduler producers, post-commit webhook/events |
| 1 | Авторизация и secrets | Исправлены role/API-key/device/task/n8n boundaries, право reveal, шифрование всех account writers и key-aware migration/rotation CLI; RLS owner bypass подтверждён | Реальная непривилегированная PostgreSQL роль, межорганизационный доступ по всем API/jobs, rollout/backfill/restore с управляемыми ключами, журнал reveal, APK/cache/logs и косвенный доступ через tasks |
| 1 | Orchestrator | Версии закреплены; пароль исключён из новых metadata; account ownership, terminal receipt и rollback/retry исправлены | Конкурентные creation ticks, savepoint при частичной ошибке, crash recovery pipeline, транзакционные stats |
| 1 | VPN | Глобальная SQL uniqueness/intent до provider effects, generation fencing, unknown-outcome retention и health recovery исправлены; 64 конкурентных assignments проверены | [Реализация и остаточные риски](VPN-LEASE-DESIGN.md): authoritative provider inventory/reconciliation, rollout legacy/orphan peers, зарезервированные router IP, AWG/маршруты, encoded-key adapter и реальный command publisher |
| 1 | Deployment | Startup export и наследование dev commands/mounts/root/PG/Redis/application ports исправлены; оба Compose merge проверены | n8n/MinIO ingress, RLS roles, OTA/log persistence, запуск/health/recovery и restore backup |
| 2 | APK runtime и производительность | 344 JVM tests; лимит loop diagnostics не пропускает действия, coroutine cancellation выходит из body; typeText больше не пишет raw/encoded ввод в логи; root pipe unknown не повторяется автоматически через DAG/loop; сервер восстанавливает evicted presence по pong; реальный APK↔API и нагрузка 10–64 не завершены | Root execution ACK, Lua pcall/unknown reconciliation, FGS/boot/timeout, emulator/physical permissions, process death, codec backpressure/recovery, multi-worker session fencing, PubSub reconnect, CPU/RAM/FPS/battery |
| 2 | PC agent | Идентичность workstation и ORM registration исправлены | Реальный command/ACK контракт, reconnect и замена сессии, ошибки ADB/emulator process, идемпотентность |
| 2 | Dependencies/CI | Совместимое Python обновление: 1047 tests, pip check и joint pip-audit без известных уязвимостей; на 748bb3e все backend jobs и Android CI успешны; Host→audit/log/metrics path исправлен | Frontend/Android/container advisories, hash lock/SBOM, dependency-aware mypy, actions runtime/version pins; отдельный подготовленный load job |
| 2 | Frontend/n8n/observability | Frontend build прошёл; остальные проверки неполны | Supported Node runtime, Jest/tsc/browser, API-key/HMAC/webhook contracts, реальные метрики/alerts и multiprocess |
| 3 | Уборка и удобство эксплуатации | После закрытия runtime/security blockers | Устаревшие Redis producer paths, документация конфигурации, согласованный gitignore для regression tests, runbooks и дашборды |

Ограничения проверки: запуск выделенного локального API отклонён автоматической
проверкой разрешений (`blocked by policy`), обход не выполнялся. Выделенный AVD
на порту 5580 недоступен; чужой emulator-5554 не изменялся. Результаты на JVM не
подменяют аппаратные измерения. PR остаётся draft, merge/deployment не выполнялись.
