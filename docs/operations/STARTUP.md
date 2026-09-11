# Запуск development-стека и значение readiness

**Сверено 11 сентября 2026 · AUD-68/78–80.** [Эксплуатационный план](READINESS.md) ·
[Runbooks](../runbooks/README.md) · [Deployment](../deployment.md).

## Подготовка

Нужны PowerShell 7, Docker с Compose v2, поддерживающим `up --wait --wait-timeout`,
и заполненный `.env.local` либо `.env` в корне checkout. Для production overlay уже требуется
Compose 2.24.4+ из-за `!reset`. Параметры перечислены в
[configuration guide](../configuration.md); этот launcher использует base + full,
а не production overlay. Не запускайте его поверх другого deployment project.

Приоритет: `.env.local`, затем `.env`; выбранный абсолютный путь передаётся
через `--env-file` во все штатные config/build/up команды. Файлы не объединяются.
Явный process environment по-прежнему имеет приоритет Compose. Если отсутствуют
оба файла, скрипт копирует `.env.example` в `.env` и заканчивает работу с
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

### Windows env selection (AUD-80)

`full-deploy.ps1` использует тот же приоритет `.env.local` → `.env` для каждого
вызова wrapper, включая build/migration/bootstrap; без файла Compose не вызывается.
Абсолютные YAML/env paths не зависят от caller directory. Подготовка env не означает
проверку DB roles/migration ordering/readiness. Legacy Status/Down/Tunnel start-dev
по-прежнему не входят в принятый штатный startup path.

### Production image bootstrap (AUD-81)

Production image теперь содержит `scripts/create_admin.py` и
`scripts/seed_enrollment_key.py`; full-deploy не зависит от dev bind-mount для этих
команд. Отдельный backend CI job строит image и проверяет entry points без сети,
с read-only rootfs от обычного пользователя. Это проверка packaged CLI, не успешной
SQL инициализации или полного deployment. [План пилота](PILOT-ACCEPTANCE.md).

## Full-deploy: порядок первого запуска (AUD-82)

Оба `full-deploy.ps1/.sh` выполняют:

1. Проверку инструментов, подготовку конфигурации и build.
2. `up -d --wait --wait-timeout 180 postgres redis` выбранного project.
3. Migration, admin и enrollment key как отдельные `run --rm --no-deps -T backend`
   команды с теми же Compose files/env. API не требуется для этих команд.
4. Полный `up -d --wait --wait-timeout 300`, затем `ps --all` того же project.

Ошибка любой стадии останавливает дальнейшие. Host Alembic fallback удалён.
Production overlay также содержит backend `/api/v1/health/readyz` и frontend `/login`
healthchecks внутри контейнеров; они не зависят от опубликованных host ports.
Таймауты 180/300 s относятся к Compose readiness, не ко всему build/pull/startup.
Результат подтверждает running/healthy по имеющимся probes; дополнительные сервисы
без probes, ingress/TLS, login/device/task и VPN проверяются отдельно.

Этот порядок не останавливает уже запущенные workers и не заменяет coordinated
migration/runtime-role rollout. Launcher не создаёт разделённые роли/grants.
Full-deploy сохраняет existing admin (AUD-85); direct CLI без `--create-only`
может обновить пароль. Не перегенерируйте secrets существующей
установки без отдельного плана. Secret lifecycle и legacy branches ещё проверяются.
Регрессии: полный main обоих shell с процессом вместо Docker, реальные Compose merges
и выражения probes с HTTP double; локально 65 deployment cases проходят.

## Единая enrollment identity при старте (AUD-83)

CLI и development hook используют один configured key и
`SPHERE_BOOTSTRAP_ORG_SLUG` (default: `default`). Оба Compose overlay передают этот
slug backend; сохраните его в выбранном env-файле, чтобы autostart использовал ту
же организацию. Для прямого host CLI задайте переменную в окружении процесса.
Организация создаётся administrator bootstrap заранее; первая попавшаяся org
больше не используется. Параллельные workers используют одну SQL row lock.

Hook действует только в `development`/`dev`/`local`. При известной ошибке config,
отсутствующей org или конфликтующем key он пишет `enrollment_bootstrap_unavailable`
с `reason` и оставляет API доступным; explicit seed CLI завершается ошибкой.
`enrollment_bootstrap_ready` содержит key ID/org ID, без key material. Поэтому
readiness API не заменяет регистрацию тестового устройства. Автоматического
переноса старых devices/keys, выдачи новых прав и реактивации revoked key нет.
DB failure не маскируется как предупреждение о настройке.

## Существующая конфигурация при повторе (AUD-84)

Если в установке есть `.env`, а `.env.local` отсутствует, full-deploy использует
существующий `.env` и не генерирует новый затеняющий файл. Это действует также в
headless/skip-secrets. При наличии `.env.local` он сохраняет приоритет; unattended
повтор его не заменяет. Fresh generation происходит при отсутствии обоих files.

Это защита выбора конфигурации, не ротация. Interactive overwrite `.env.local`
остаётся явным отдельным действием; смена пароля в dotenv не меняет пароль уже
инициализированного PostgreSQL. Full-deploy сохраняет existing admin (AUD-85); direct CLI без `--create-only`
намеренно обновляет user password. Полный reboot,
restore и persistent-volume acceptance всё ещё требуются.

## Повторный admin bootstrap (AUD-85)

Full-deploy вызывает `python scripts/create_admin.py --create-only`. При наличии
active super_admin в выбранной организации пароль, роль и MFA сохраняются, даже
если candidate `SPHERE_ADMIN_PASSWORD` отличается. Он используется только для
нового пользователя; новый случайный candidate при повторе не меняет login.
Отключённая учётная запись, другая роль или другая org — явная ошибка, не автопочинка.

CLI выдаёт ровно один `SPHERE_ADMIN_BOOTSTRAP=created|existing` после commit.
При `created` launcher показывает initial credentials до enrollment; Bash также
записывает `.admin-credentials` (chmod 600). Поэтому последующий enrollment failure
не скрывает уже созданный пароль. При `existing` кандидат не показывается и файл
не перезаписывается. Неизвестный/отсутствующий/двойной outcome останавливает запуск.
Этот вывод подтверждает только admin stage, не готовность остальных сервисов.

Для намеренного восстановления пароля используйте direct `scripts/create_admin.py`
без `--create-only` с выбранными `ADMIN_EMAIL`, `ADMIN_PASSWORD` и bootstrap org.
Этот режим также возвращает super_admin/active; применяйте его только к выбранной
административной identity. Полный CLI и launcher должны быть одной версии образа.
При потерянном ответе commit не делайте вывод, что пользователь не создан: сохраните
исходный candidate и проверьте identity перед явным reset. Автоматического разрешения
неизвестного commit и защищённого secret-store этим изменением не добавлено.

## Проверка bootstrap в собранном образе

Помимо четырёх no-network проверок CLI/metadata/permissions, image job получает
один составной SQL/runtime scenario. Он создаёт отдельные PostgreSQL/Redis на
внутренней Docker-сети, выполняет миграции/admin/key и проверяет полный ASGI
lifespan, login, registration/visibility и повтор в новом процессе. Локально
`08338d3` проходит; API listener и полный Compose не запускаются.
[Команда, evidence и cleanup contract](../../tests/containers/README.md).
