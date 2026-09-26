# Диагностика и восстановление

**Сверено с кодом 10 сентября 2026.** [Главная документации](../README.md) ·
[Эксплуатационный план](../operations/READINESS.md) · [Доказательства](../audits/2026-09-05/AUDIT-REPORT.md)

| Сценарий | Руководство |
| --- | --- |
| Backend недоступен или не готов | [01 — Backend outage](01-backend-outage.md) |
| VPN не работает / закончились адреса | [02 — VPN](02-vpn-incident.md) |
| PostgreSQL отказал / соединения или миграции | [03 — Database](03-database-failure.md) |
| Массово пропали устройства | [04 — Fleet offline](04-fleet-offline.md) |

[Startup contract](../operations/STARTUP.md) описывает, что означает успешный запуск
launcher и какие операции ещё нужно проверить.

## До изменения состояния

Зафиксируйте интервал в UTC (и исходный timezone), device/workstation/task/command
IDs, версии кода/APK, deployment project и набор Compose files. Отделите «процесс
запущен», «API готов», «устройство аутентифицировано» и «задача выполнена».

Ниже `docker compose -f docker-compose.yml -f docker-compose.full.yml` означает
**существующий development recipe из корня репозитория**. Для другой установки
используйте ровно её `-f` и `--project-name`: выбранный другой project покажет не
те контейнеры. Не предполагайте имена `sphere_backend`, `sphere_postgres` или
`celery_worker`; получайте inventory через Compose.

```powershell
docker compose -f docker-compose.yml -f docker-compose.full.yml config --services
docker compose -f docker-compose.yml -f docker-compose.full.yml ps --all
docker compose -f docker-compose.yml -f docker-compose.full.yml logs --since 15m --tail 200 --timestamps backend nginx
```

Это read-only диагностика. Вложения не должны включать `.env`, connection strings,
access/refresh tokens, вводимые пароли или decrypted VPN/account config.

## Что действительно измерено

В репозитории есть monitoring configuration и runbooks. Это не подтверждение
работающих Prometheus/Grafana/alerts: [effective merge выявил проблемы](../operations/READINESS.md).
Утверждения прежней версии о возврате всех устройств за пять минут, hourly backups,
RTO 30 min и назначенных дежурных не были доказаны и не являются обязательствами.
Численные SLO/RTO/RPO принимаются после drill и назначения владельца эксплуатации.

HTTP request ID помогает сузить backend logs; сквозной timeline APK/task/request
ещё строится. Для воспроизведения нужно сохранить исходный сценарий и terminal /
unknown outcome. После восстановления проверяется одно контролируемое задание,
затем возврат парка ступенями и отсутствие повторных эффектов.
