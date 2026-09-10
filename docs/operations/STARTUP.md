# Запуск development-стека и значение readiness

**Сверено 10 сентября 2026 · AUD-68.** [Эксплуатационный план](READINESS.md) ·
[Runbooks](../runbooks/README.md) · [Deployment](../deployment.md).

## Подготовка

Нужны PowerShell 7, Docker с Compose v2, поддерживающим `up --wait --wait-timeout`,
и заполненный `.env` в корне checkout. Для production overlay уже требуется
Compose 2.24.4+ из-за `!reset`. Параметры перечислены в
[configuration guide](../configuration.md); этот launcher использует base + full,
а не production overlay. Не запускайте его поверх другого deployment project.

Если `.env` отсутствует, скрипт копирует `.env.example` и заканчивает работу с
ошибкой. Заполните параметры и повторите запуск. Шаблон не является готовой
конфигурацией. Миграции, runtime DB role/grants и initial identity необходимо
подготовить по соответствующим rollout guides; launcher не меняет их автоматически.

```powershell
./scripts/start-dev.ps1
# Если действительно изменились зависимости/образы:
./scripts/start-dev.ps1 -Rebuild -ReadyTimeoutSec 300
```

`COMPOSE_PROJECT_NAME` и Compose project resolution сохраняются. Скрипт передаёт
абсолютные пути двух YAML, поэтому startup не зависит от имён контейнеров или
текущего каталога shell. Старый дополнительный tunnel path этого свойства ещё
не гарантирует.

## Когда скрипт сообщает успех

1. Docker CLI доступен, `docker info` завершился с кодом 0.
2. `compose config --quiet` завершился с кодом 0, без вывода secrets configuration.
3. Если запрошена пересборка, `compose build` завершился с кодом 0.
4. `compose up -d --wait --wait-timeout N` дождался running/healthy. По умолчанию
   N=180 s; этот срок относится к ожиданию сервисов, а не к build/pull/всей команде.

| Сервис | Что проверяет health probe |
| --- | --- |
| PostgreSQL | Существующий `pg_isready` |
| Redis | Существующий authenticated PING |
| Backend | Локальный HTTP `/api/v1/health/readyz`, статус 200 и JSON `status=ready`; готовность PG/Redis через приложение |
| Frontend | Локальный HTTP `/login`, только 200; redirect/error/timeout не проходят |
| Остальные | Compose running, если для конкретного сервиса нет отдельного healthcheck |

Контракт `--wait` описан в [официальной документации Docker](https://docs.docker.com/reference/cli/docker/compose/up/).
Параметры API/frontend probes находятся в `docker-compose.full.yml`: interval 10 s,
timeout 5 s, start period 30 s, retries 12. HTTP timeout — 3 s. Первая компиляция
Next dev может потребовать большего startup window на медленной машине.

## Ошибка и повторный запуск

Native Docker failure даёт ненулевой exit скрипта, останавливает следующие шаги и
не печатает итоговый успех. При неготовности часть контейнеров может остаться
запущенной. Они и volumes сохраняются: перед повтором используйте `ps --all` и
ограниченный `logs --since ... --tail ...` с тем же project и файлами Compose.
[Backend runbook](../runbooks/01-backend-outage.md) описывает сбор причин.

Успех readiness не доказывает Alembic head, корректность runtime grants, login,
APK auth, WS recovery, выполнения задания и доставки результата. Эти сценарии
проверяются отдельно. В full recipe frontend работает в dev mode; backend reload
включается только при `ENVIRONMENT=development`.

`-Tunnel`, `-Down` и `-Status` — старые отдельные ветки launcher, этот fix их
корректность не подтверждает. Tunnel не используется как принятый резервный LAN
канал. Unattended production autostart, reboot/restore и сетевые failure drills
остаются в operational matrix.

## Проверка изменения

17 regression cases исполняют настоящий PowerShell launcher и фактические
health expressions из Compose merge. Docker/HTTP boundaries подменены, exit codes
поступают из отдельных native processes. Это позволяет доказать ошибку управления
запуском без воздействия на существующие контейнеры. Вместе с прежними deployment
cases проходят 25 тестов. Evidence и ограничения — в
[AUD-68](../audits/2026-09-05/AUDIT-REPORT.md).

## Bootstrap пользователя и устройства (AUD-78)

`start-dev.ps1` по-прежнему запускает prepared services, а не создаёт всю установку
с нуля. [План пилота](PILOT-ACCEPTANCE.md) задаёт порядок миграций, bootstrap,
browser/APK и VPN проверок. Исправлены функции bootstrap в `full-deploy.ps1/.sh`,
но остальные стадии этих legacy launchers не получили общего sign-off.

Admin и enrollment CLI теперь используют `SPHERE_BOOTSTRAP_ORG_SLUG=default`
по умолчанию; ключ создаётся только после организации администратора. Отсутствующая
конфигурация/ключ, SQL error и конфликт ключа прекращают bootstrap. Реактивации
отозванного ключа или переноса старого `default-org` нет. Реальный SQL/HTTP сценарий
создаёт admin, выполняет login, регистрирует device и читает его той же identity;
Compose, браузер и APK transport в этот прогон не входят.

### Bash full-deploy: исправление аргументов Compose (AUD-79)

`full-deploy.sh` использует array для файлов dev/production Compose и quoted expansion
во всех стадиях. Это устраняет malformed `-f ... -f ...` argument при штатном IFS.
Проверка включает настоящий preamble, build и bootstrap с процессом на границе Docker.
Она не подтверждает остальные стадии полного deployment. [План приёмки](PILOT-ACCEPTANCE.md).
