# Приоритеты продолжающегося аудита

Обновлено 6 сентября 2026. Этот документ задаёт порядок работ; наличие пункта
не означает, что его эксплуатация уже доказана. Для закрытия нужен воспроизводимый
сценарий, исправление, regression test и повторная проверка.

| Приоритет | Область | Текущее состояние | Следующее доказательство/критерий закрытия |
| --- | --- | --- | --- |
| 1 | Task lifecycle | SQL assignment/receipt recovery и Android journal проверены; pipeline/scheduler и rollout старых задач остаются | Сбой до/после claim, Redis reset с восстановлением presence, pipeline completion, конкурентные producers, commit/side-effect ordering |
| 1 | Авторизация и secrets | Исправлены role/API-key/device/task/n8n boundaries; RLS owner bypass подтверждён; plaintext account surfaces ещё открыты | Реальная непривилегированная PostgreSQL роль, межорганизационный доступ по всем API/jobs, отсутствие паролей в ответах/метаданных, безопасная миграция secrets |
| 1 | Orchestrator | Версии registration/farming закреплены; task metadata больше не получает копию пароля | Конкурентные ticks, account state после rollback, отсутствие повторной обработки terminal task, crash recovery pipeline |
| 1 | VPN | Дубли IP в общей subnet и повторная выдача после reinit подтверждены | Глобальное уникальное выделение, атомарность, повтор/revoke при отказе WG/AWG API, корректный PSK и маршруты |
| 1 | Deployment | Read-only startup исправлен; неочищенные Compose ports и RLS role rollout открыты | Итоговый merged Compose, закрытые DB/Redis ports, роли, immutable artifacts, запуск/health/recovery и restore backup |
| 2 | APK runtime и производительность | 316 JVM tests; реальный APK↔API и нагрузка 10–64 не завершены | FGS/boot/timeout по Android API, emulator/physical permissions, process death, codec backpressure/recovery, CPU/RAM/FPS/battery по заданному профилю |
| 2 | PC agent | Идентичность workstation и ORM registration исправлены | Реальный command/ACK контракт, reconnect и замена сессии, ошибки ADB/emulator process, идемпотентность |
| 2 | Dependencies/CI | Ruff fixes готовы; security job красный; есть mypy baseline diagnostics | Upstream advisory + reachability, совместимое обновление и тесты; отдельные real-service/load jobs с конечным timeout; GitHub checks на последнем head |
| 2 | Frontend/n8n/observability | Frontend build прошёл; остальные проверки неполны | Supported Node runtime, Jest/tsc/browser, API-key/HMAC/webhook contracts, реальные метрики/alerts и multiprocess |
| 3 | Уборка и удобство эксплуатации | После закрытия runtime/security blockers | Устаревшие Redis producer paths, документация конфигурации, согласованный gitignore для regression tests, runbooks и дашборды |

Ограничения проверки: запуск выделенного локального API отклонён автоматической
проверкой разрешений (`blocked by policy`), обход не выполнялся. Выделенный AVD
на порту 5580 недоступен; чужой emulator-5554 не изменялся. Результаты на JVM не
подменяют аппаратные измерения. PR остаётся draft, merge/deployment не выполнялись.
