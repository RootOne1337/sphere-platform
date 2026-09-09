# 01 — Backend недоступен или не готов

**Обновлено 10 сентября 2026.** Массовая потеря управления — эксплуатационный P0.
[Общие правила и Compose selection](README.md) · [Fleet recovery](04-fleet-offline.md)

## Диагностика

1. Получите `config --services` и `ps --all` выбранного Compose project. Сравните
   running/restarting/exited и времена последнего запуска с началом инцидента.
2. Ограничьте backend/nginx logs интервалом инцидента; сохраните request ID,
   device/task ID, exception/reason и code revision.
3. Через **фактический настроенный ingress** проверьте
   `GET /api/v1/health/healthz` (процесс отвечает) и
   `GET /api/v1/health/readyz` (проверка PostgreSQL/Redis). Пути `/health` и
   `/health/live` из старой версии runbook не являются этим контрактом.
4. При failed readiness перейдите к [database guide](03-database-failure.md),
   проверьте Redis connectivity с конфигурацией этой установки. Не подставляйте
   неаутентифицированный `redis://redis:6379/0` в систему с паролем.
5. Сравните proxy и backend результат. HTTP response не доказывает успешный WS auth
   и доставку команды. Сбой только у WS требует отдельного handshake/close анализа.

Для development recipe из корня:

```powershell
docker compose -f docker-compose.yml -f docker-compose.full.yml ps --all
docker compose -f docker-compose.yml -f docker-compose.full.yml logs --since 15m --tail 200 --timestamps backend nginx postgres redis
```

Для конкретного container ID, полученного через Compose, смотрите ExitCode,
OOMKilled, RestartCount и health state через `docker inspect`. Exit 137 сам по себе
не доказывает OOM; нужен OOMKilled/host evidence. В отчёт достаточно этих полей,
полный inspect содержит environment и не нужен.

## Выбор восстановления

- Ошибка конфигурации/миграции: исправить конкретную причину по логам, затем
  повторить readiness. Restart без исправления создаёт цикл той же ошибки.
- Ресурсы/диск: подтвердить bottleneck и влияние на PostgreSQL/Redis; не повышать
  workers/лимиты вслепую. Число pool connections умножается на workers.
- Proxy/network: восстановить путь к тому же management service; не стирать APK
  credentials и не публиковать новый endpoint, если старый просто временно не готов.
- Однократный crash: контролируемый restart выбранного сервиса допустим после
  сохранения evidence и проверки, что он не повторит внешние task effects.

Новая версия не требует автоматического restart/pull/redeploy по любому инциденту.
Rollback кода также должен учитывать применённую схему и незавершённые intents.

## Критерий завершения

Readiness стабилен, устройство восстановило auth, одно тестовое задание получило
подтверждённый result, duplicates/unknown outcomes сверены, парк возвращается без
ручного enrollment. Сохраните время отказа/возврата и regression reproduction.
Не объявляйте инцидент закрытым только по зелёному container status.
