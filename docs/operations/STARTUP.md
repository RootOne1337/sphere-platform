# Запуск Sphere: bootstrap, повторный старт и readiness

**Входной путь сверён 21 сентября 2026.** Датированные AUD ниже описывают отдельные проверки, а не общую приёмку всех launchers. [Эксплуатационный план](READINESS.md) ·
[Runbooks](../runbooks/README.md) · [Deployment](../deployment.md).

<a id="first-install"></a>
## Новая установка

Для существующего `sphere-pilot-20260911` сразу переходите к
[Local pilot](LOCAL-PILOT.md): его env/порты/volumes отличаются. Следующие команды —
для **отдельного нового checkout/Compose project**, без старой установки на тех же портах.

Нужны Git, Python 3.12, Docker с Compose v2 и PowerShell 7; для production
overlay нужен Compose 2.24.4 или новее. Сначала прочитайте
[configuration](../configuration.md), выберите свободные host ports и постоянное
имя project. `COMPOSE_PROJECT_NAME` разделяет ресурсы Compose, но сам по себе
не устраняет конфликт опубликованных портов. Для production дополнительно нужны
домен/TLS, runtime DB credentials/grants и собственная приёмка; флаг `-Production`
не подтверждает готовность.

Из корня checkout в PowerShell:

```powershell
# Пример: сначала убедитесь, что проект с этим именем и его данные не существуют.
$env:COMPOSE_PROJECT_NAME = 'sphere-sandbox'
# Генератор перезаписывает файл: остановитесь, если есть любой прежний env.
if ((Test-Path -LiteralPath .env.local) -or (Test-Path -LiteralPath .env)) {
    throw 'Найдена существующая конфигурация; не создавайте новые секреты поверх неё.'
}
# Только в новой установке без прежних env/volumes:
python scripts/generate_secrets.py --output .env.local
if ($LASTEXITCODE -ne 0) { throw 'Генерация конфигурации завершилась ошибкой.' }
```

Откройте созданный файл, настройте адреса и интеграции по
[configuration](../configuration.md), затем убедитесь, что выбранный Compose
project и порты принадлежат новой установке. После этого в той же PowerShell-сессии:

```powershell
./scripts/full-deploy.ps1 -SkipSecrets
```

`full-deploy.ps1` использует base + full для development; с `-Production` — base +
production. Он собирает images, поднимает PG/Redis, применяет Alembic, выполняет
admin/enrollment bootstrap в one-off backend containers, затем запускает приложения
и ждёт readiness. При ошибке последующие стадии прекращаются; данные автоматически
не удаляются. Выбор env: `.env.local` → `.env`, без объединения файлов.

Для новой административной учётной записи можно задать `SPHERE_ADMIN_EMAIL` и
`SPHERE_ADMIN_PASSWORD` в процессе launcher. Без них используется `admin@example.com`
и сгенерированный пароль. PowerShell показывает пароль после подтверждённого
создания — сохраните его приватно; при существующем admin прежний пароль сохраняется.
Не публикуйте вывод bootstrap. Публичная регистрация не является способом получить
super_admin. [Подробности повторного bootstrap ниже](#повторный-admin-bootstrap-aud-85).

После запуска отдельно проверьте вход в веб, health readyz, регистрацию одного APK,
задание с terminal receipt, новый видеокадр и recovery. Общий recipe не присваивает
порт 18080 автоматически — это адрес специально настроенного pilot.
[Порядок приёмки](PILOT-ACCEPTANCE.md) · [Remote access](REMOTE-PILOT.md).

Для Linux/Bash есть `scripts/full-deploy.sh`; его отличия и ограничения описаны
ниже. В частности, Bash launcher исполняет `.env.local` через shell `source`,
а не передаёт его как `--env-file`: запускайте его только с доверенным файлом,
подходящим для Bash. Он отличается от PowerShell wrapper и может разрешать
значения Compose иначе; не переносите параметры и предположения о приоритете
между ними дословно. Это ограничение исходного кода, а не подтверждение его
безопасности для произвольного dotenv.

## Подготовка к повторному dev-start

Для уже подготовленного отдельного Windows-стенда `sphere-pilot-20260911` используйте
[локальную инструкцию](LOCAL-PILOT.md): другой project/env и порт 18080 позволяют
сохранить старую установку. Описанный ниже общий launcher относится к обычному dev.

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
корректность не подтверждает. `-Tunnel` после запуска стека пытается остановить и
удалить контейнер с фиксированным именем `sphere-tunnel`, собирает образ и создаёт
новый контейнер с фиксированной сетью. `-Down` вызывает Compose `down`, а не
только показывает состояние; его ветка и `-Status` не используют выбранный normal
startup `--env-file`. Не применяйте их, не установив точную область воздействия
и выбранную конфигурацию. Tunnel не используется как принятый резервный LAN
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

### Worker discovery под ограниченной ролью PostgreSQL

После audit migrations фоновые batch/pipeline/task workers требуют отдельных
grants на UUID lookup. Это дополнительные права к уже настроенным runtime CRUD
и auth grants; они не создают роль и не отключают RLS. Мигратор должен владеть
таблицами и функциями. Замените пример `sphere_runtime` фактической доверенной
worker-ролью; HTTP-пользователям эти права не выдаются:

```sql
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.due_batch_admissions() TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.pipeline_work(text) TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.task_dispatch_work(text,uuid) TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.schedule_work(uuid) TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.watchdog_work(integer,integer,uuid) TO sphere_runtime;
```

Применять migrations до запуска совместимого кода. Один HTTP readyz не доказывает,
что фоновые workers видят задания. Проверить canary task/receipt/cancel, pipeline
и batch recovery под фактической ролью. Scheduler исправлен в AUD-136; дополнительно
проверить его SCRIPT/PIPELINE firing, конфликт и recovery после Redis/worker restart.
[Batch](../audits/2026-09-20/BATCH-RECOVERY.md),
[pipeline](../audits/2026-09-20/PIPELINE-RLS.md) и
[task dispatch](../audits/2026-09-20/TASK-DISPATCH-RLS.md),
[scheduler](../audits/2026-09-20/SCHEDULER-RUNTIME.md) описывают rollback,
regressions и ограничения. На существующий pilot эти source fixes ещё не установлены.

Для [watchdog AUD-137](../audits/2026-09-20/WATCHDOG-STOP-RECOVERY.md) дополнительно
проверить native timeout → сохранённый stop → terminal receipt: до результата APK
следующая задача не должна получить исполнение. Нужен APK с durable cancellation
journal из AUD-129 и сверка исторических TIMEOUT rows; старый watchdog нельзя
оставлять параллельно с новым. Nullable marker и lookup добавляет migration
`20260921_watchdog_stop`; один HTTP readyz этот контракт не проверяет.

### Права runtime-роли для каталога профилей приложений

На установке с разделёнными мигратором и runtime-ролью проверьте исходную
ревизию командой `alembic -c alembic/alembic.ini current` под мигратором.
Для перехода с `20261021_vpn_profiles` примените
`alembic -c alembic/alembic.ini upgrade 20261114_application_profiles`.
После применения миграции владелец таблицы выдаёт права фактической runtime-роли
API. В примере замените `sphere_runtime` именем этой роли.

```sql
GRANT SELECT, INSERT, UPDATE ON TABLE public.application_profiles TO sphere_runtime;
```

Права действуют вместе с tenant RLS. Запустите совместимый backend и проверьте
под фактическим runtime-login чтение, создание и изменение тестового профиля в
отдельной организации. Вторая организация видит свой каталог. Для схемы и ACL
используйте ту же процедуру и конфигурацию БД, что при штатных миграциях.
Один успешный readiness не подтверждает права на таблицу.

Для отката сначала переключите backend на прежнюю версию. Миграция добавляет
только каталог профилей, поэтому прежняя версия может работать при сохранённой
таблице. Если требуется вернуть схему к `20261021_vpn_profiles`, сохраните
данные профилей и сверяйте текущую ревизию перед откатом. Из
`20261114_application_profiles` выполните
`alembic -c alembic/alembic.ini downgrade 20261021_vpn_profiles` под мигратором
после остановки потребителей нового каталога. Downgrade удаляет эту таблицу
вместе с её данными и грантами, а существующие аккаунты и устройства остаются
в прежних таблицах. При повторном upgrade выдайте grant заново.

### Привязки устройств и автоматизация по профилям приложений

После `20261114_application_profiles` мигратор применяет
`alembic -c alembic/alembic.ini upgrade 20261114_automation_profiles`. Владелец
объектов выдаёт следующие права фактическому runtime-login. Если API и worker
используют разные роли, права на таблицу нужны обоим, а права на функцию нужны
worker оркестрации. Сохраните ранее выданные права на `application_profiles`,
`devices` и `tasks`.

```sql
GRANT SELECT, INSERT, UPDATE ON TABLE public.application_automation_policies TO sphere_runtime;
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.orchestration_work(uuid) TO sphere_runtime;
```

Функция обнаруживает только идентификаторы организаций для worker. Её доверенный
владелец должен читать источники с `FORCE ROW LEVEL SECURITY` при
`row_security = off`, как для остальных функций `sphere_auth`. Runtime получает
права `USAGE` и `EXECUTE`.

Проверьте чтение привязки и настройку политики в двух тестовых организациях
под рабочими ролями. Для проверки выбора пула заведите два профиля одной
организации с одинаковым именем сервера, привяжите разные тестовые устройства
и проверьте совпадение ключа профиля и точного имени сервера у аккаунта. Для
регистрации и фарма нужны Android package и опубликованный скрипт. После
выключения регистрации и фарма можно изменить Android package. Worker должен
обработать уже полученные терминальные результаты. Readiness проверяет
соединение и предпосылки, поэтому выполните
эти проверки отдельно.

Встроенный профиль Black Russia остаётся виртуальным и работает через прежние
настройки. Привязку можно создать только к профилю, сохранённому в организации.
Существующие устройства и аккаунты продолжают использовать прежние данные до
явного действия оператора. Привязка хранит ключ сервера, а пул аккаунтов
определяется точной парой «ключ профиля, имя сервера». Перед сменой привязки
завершите задачи, запуски пайплайнов и открытые сессии, освободите аккаунт и
проверьте ожидающие волны массового запуска. Волна, ещё не создавшая задачи,
сама по себе устройство не резервирует.

Для отката приостановите запуски и остановите новые процессы после завершения
активных работ и обработки результатов. Снимите резервную копию привязок,
политик и данных оркестрации в `tasks`. До включения прежнего worker отдельно
выключите его legacy-автоматизацию или проверьте состав устройств для неё:
прежняя версия не учитывает новые привязки. При откате схемы мигратор выполняет
`alembic -c alembic/alembic.ini downgrade 20261114_application_profiles`.
Операция удаляет привязки, политики, новые поля оркестрации в `tasks` и функцию
обнаружения work; каталог профилей и базовые записи задач сохраняются. При
повторном upgrade выдайте новые grants заново и восстановите нужные данные
из проверенной копии.

### Квитанции расписаний и лимиты триггеров

Мигратор последовательно применяет `20261114_schedule_fire_keys`,
`20261114_trigger_run_limits` и `20261114_trigger_causality`.
Роли API с доступом к расписаниям нужны права
на хранение и очистку ключей повторов и на запись пропуска при замене
принятого слота. При раздельных ролях API и воркера проверьте права на
`schedule_executions` у обеих ролей.

```sql
GRANT SELECT, INSERT, DELETE ON TABLE public.schedule_fire_requests TO sphere_runtime;
GRANT SELECT, INSERT ON TABLE public.schedule_executions TO sphere_runtime;
```

Миграции добавляют поля происхождения в `pipeline_runs` и `device_events`,
связь задачи с запуском в `tasks` и уникальный ключ приёма события.
Сохранённое время последнего срабатывания продолжает определять cooldown.
Проверьте квитанцию с повторным ключом под runtime-ролью и симуляцию по ID
сохранённого события. При раздельных ролях с доступом по столбцам проверьте
чтение и запись новых полей в путях обработки событий, результатов задач
и пайплайнов.

Перед откатом остановите запросы на запуск и обработку событий. Откат до
`20261114_trigger_run_limits` удаляет причинную цепочку и ключи доставки.
Откат до `20261114_automation_profiles` дополнительно удаляет ключи ручных
запусков и данные часового счётчика. После повторного upgrade проверьте
grants и учитывайте новый старт потерянных окон.

### Outbox вебхуков

Примените `20261114_webhook_outbox` до запуска новой версии API. Выдайте
права фактическим непривилегированным ролям. API читает историю, добавляет
записи результата и переводит одну доставку в повтор. Воркер читает и
обновляет записи в контексте организации. Обоим путям требуется DELETE
для ограниченной истории, а доступ к функции обнаружения нужен воркеру.

```sql
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.webhook_deliveries TO sphere_runtime;
GRANT USAGE ON SCHEMA sphere_auth TO sphere_runtime;
GRANT EXECUTE ON FUNCTION sphere_auth.webhook_work(boolean) TO sphere_runtime;
```

Проверьте старый callback задачи и историю через тестового получателя.
Публикация подписок выключена по умолчанию. Для включения проверьте
сохранённые активные подписки и укажите точные разрешённые origin в
`WEBHOOK_ALLOWED_ORIGINS`. Воркер проверяет origin и активность подписки
перед каждой новой отправкой. Уже начатый HTTP-запрос может завершиться.

Для отката остановите процессы, принимающие результаты и отправляющие
доставки. Сохраните приватную копию outbox, включая ожидающие и прерванные
записи. Downgrade до `20261114_trigger_causality` удаляет журнал и очередь.
Старая версия продолжает отправку новых callback по прежнему пути.
Перед восстановлением отдельно сверяйте неопределённые попытки с
получателем по исходному ID доставки.
[Контракт доставки](N8N-INTEGRATION.md).

### Настройки внешнего вида аккаунта

Перед обновлением веб-клиента примените миграцию `20261114_user_preferences`.
После миграции владелец таблицы выдаёт прикладной роли три права. Если
роль в окружении называется иначе, используйте её фактическое имя.

```sql
GRANT SELECT, INSERT, UPDATE ON TABLE public.user_preferences TO sphere_runtime;
```

Таблица использует обязательный RLS по организации. API читает и изменяет
запись по организации и ID пользователя из текущей сессии. Проверьте
чтение и запись под обычной ролью, в том числе с двумя аккаунтами одной
организации. Откат схемы удаляет сохранённое оформление. Перед откатом
сохраните данные таблицы, если их понадобится восстановить.


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

Если в установке есть `.env`, а `.env.local` отсутствует, оба full-deploy launcher
не генерируют новый затеняющий файл. Это действует также в headless/skip-secrets.
PowerShell wrapper передаёт выбранный файл как `--env-file`; Bash не использует
этот wrapper и при наличии `.env.local` исполняет его через `source` перед сборкой.
Проверяйте фактическое разрешение переменных каждого launcher отдельно. Unattended
повтор не заменяет `.env.local`; при отсутствии обоих files создаётся новый файл.

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

Сценарий packaged SQL/runtime теперь также подтверждён [Linux CI `cbf8f01`](../audits/2026-09-05/evidence/ci-cbf8f01-image-runtime-tests.txt).
Четыре no-network probes и один runtime scenario идут отдельно от общего pytest.
Штатный Compose PostgreSQL init.sql, весь стек, browser и APK этим прогоном не проверяются.

## Optional DEV_SKIP_AUTH и свежая конфигурация

AUD-86: в full overlay отсутствие или пустое `DEV_SKIP_AUTH` передаётся backend
как `false`. Прежняя пустая строка останавливала импорт Settings с `bool_parsing`
даже после штатной генерации конфигурации. Explicit true в development сохраняется;
production overlay всегда задаёт false. Исправляется Compose contract, не ослабляется
валидация backend. При диагностике проверяйте только это поле в effective environment,
не публикуйте полный Compose render с секретами. Восемь generator/Compose/Settings
cases и все 93 deployment tests проходят; полный стек проверяется отдельно.

## POSTGRES_USER и первый запуск PostgreSQL (AUD-87)

Штатный init.sql создаёт n8n от имени пользователя, выбранного `POSTGRES_USER`.
Hardcoded OWNER=sphere удалён: раньше другая роль приводила к exit 3 при первом
init. Оба пользователя теперь проходят свежий init и container restart с сохранением
записи, владельца n8n и расширений. [Повторяемая проверка](../../tests/containers/README.md).

Init.sql не является миграцией существующей установки. Если первый запуск уже
прервался, не считайте последующий running PostgreSQL доказательством завершённого
init: проверьте наличие n8n, владельца и расширений. Не удаляйте volume с данными
для применения этого fix. Восстановление частичной установки требует отдельного
плана; смена POSTGRES_USER в dotenv не переименовывает существующие SQL-роли.
