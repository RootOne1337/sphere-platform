# Инфраструктура, сеть, поставка и восстановление

Исследован рабочий checkout на `94cf7c3a`. Уровни доказательств указаны по карточкам. P1 означает отказ важной эксплуатационной функции или риск потери данных. P2 означает существенную деградацию функции, диагностирования или изоляции. Результаты Compose относятся к указанным наборам файлов. Доступность опубликованного порта за пределами хоста зависит от сети и firewall.

| ID | Приоритет | Наблюдение | Доказательство |
|---|---|---|---|
| OPS-01 | P1 | Включённый staging workflow останавливается на неполном Compose-проекте | Рендер Compose |
| OPS-02 | P1 | Документированная production-команда теряет настройки хранилища скриншотов | Рендер Compose и исходники |
| OPS-03 | P2 | Production публикует n8n и два порта MinIO напрямую | Рендер Compose |
| OPS-04 | P1 | Инициализация TLS расходится по имени тома. Ошибка Certbot оставляет шлюз остановленным | Рендер Compose и исполнение с заглушкой |
| OPS-05 | P1 | Автоматическое обновление сертификата заканчивается на файловой записи | Исходники и изолированное TLS-рукопожатие |
| OPS-06 | P2 | Health-check считает `unhealthy` контейнер здоровым, если процесс запущен | Исполнение с заглушкой |
| OPS-07 | P1 | Операционный backup сообщает успех после отказа snapshot и копирования Redis | Исполнение с заглушкой |
| OPS-08 | P2 | `make monitoring` выбирает legacy-стек с невалидным Alertmanager | Изолированный `amtool` |
| OPS-09 | P2 | Legacy-алерт HTTP 5xx срабатывает при 1% ошибок и показывает 100% | Изолированный `promtool` с тестовыми счётчиками |
| OPS-10 | P1 | Штатный production Compose подставляет bootstrap-роль PostgreSQL, которую API отклоняет при старте | Рендер Compose и реальный production guard на PostgreSQL |
| OPS-11 | P1 | Восстановление с владельцами и правами останавливается на уже существующей роли `postgres` | Полный запуск импортера на синтетическом backup PostgreSQL |
| OPS-12 | P1 | Alembic отклоняет корректный DSN с URL-кодированным паролем | Реальный логин в PostgreSQL и два запуска Alembic |
| OPS-13 | P2 | Шлюз отклоняет допустимый пакет импорта VPN-профилей размером больше 1 МиБ | Backend preflight и отдельный Nginx с подсчётом полученных байтов |
| OPS-14 | P2 | PR preview не проходит рендер Compose при включении | Рендер Compose с синтетическими параметрами, повторная сверка F32-27 |

## OPS-01. Сборка staging без базового файла Compose

При `STAGING_ENABLED=true` шаг **Build Docker images** выполняет `docker compose -f docker-compose.production.yml build`. Overlay ссылается на сети и тома, объявленные в базовом Compose. Сервисы postgres/redis в overlay содержат только переопределения. Рендер того же набора файлов с синтетическими переменными завершился кодом 1. Один из диагностированных отказов — у `redis` отсутствует image или build context. При объединении base и production рендер проходит. Push и SSH развёртывание находятся дальше в этом job, поэтому такая конфигурация блокирует доставку через этот workflow. Флаг в GitHub и история живых запусков не проверялись. [Workflow](../../../.github/workflows/deploy-staging.yml#L10), [overlay](../../../docker-compose.production.yml#L6), [base](../../../docker-compose.yml#L186), [результат](evidence/operations-probe.json).

После устранения первой ошибки нужно отдельно проверить идентичность тега: шаг push использует `ghcr.io/${{ github.repository_owner }}/sphere-platform-backend:staging`, а Compose по умолчанию назначает `ghcr.io/local/sphere-platform-backend:latest`. В видимой конфигурации job нет установки переменных, связывающих эти строки. Требуется проверка фактического тега и SHA до SSH. [Workflow](../../../.github/workflows/deploy-staging.yml#L17), [тег образа](../../../docker-compose.production.yml#L55).

## OPS-02. Продакшен-профиль не передаёт настройки хранилища скриншотов

Production-команда из заголовка Compose и из `full-deploy` использует base + production. Синтетические `SCREENSHOT_STORAGE_ENDPOINT`, `...ACCESS_KEY` и `...SECRET_KEY` заданы при рендере. В результате ни один ключ не попал в окружение backend. В base + full + production все три появились, потому что их объявляет full. Параллельно MinIO присутствует в обоих профилях. [Production Compose](../../../docker-compose.production.yml#L1), [full-deploy.sh](../../../scripts/full-deploy.sh#L69), [forwarding в full](../../../docker-compose.full.yml#L28), [сравнение рендеров](evidence/operations-probe.json).

Запрос содержимого скриншота завершённой задачи с допустимым ключом вызывает `get_screenshot_storage()`. Отдельный вызов этой функции без переданных параметров вернул HTTP 503 `Screenshot storage is not configured`. Штатный контейнерный healthcheck проверяет `readyz`. Успешная проверка БД и Redis не покрывает путь чтения скриншота. Снимок конкретного рабочего объекта в MinIO не читался. [Обработчик](../../../backend/api/v1/tasks/router.py#L307), [проверка настроек](../../../backend/services/task_screenshots.py#L27), [healthcheck](../../../docker-compose.production.yml#L37), [результат](evidence/operations-probe.json).

## OPS-03. Production сохраняет прямые публикации n8n и MinIO

Рендер base + production и base + full + production сбросил публикации PostgreSQL, Redis, backend и frontend. Для n8n остался host port 5678, для MinIO — 9000 и 9001. Во всех трёх записях поле `host_ip` отсутствует. Эти публикации обходят правила Nginx для API, TLS и ограничения запросов. Зафиксировано свойство эффективной конфигурации. Сетевые правила хоста и доступ снаружи не проверялись. [Базовые публикации](../../../docker-compose.yml#L131), [сбросы production](../../../docker-compose.production.yml#L6), [результат](evidence/operations-probe.json), [правила публикации Docker](https://docs.docker.com/engine/network/port-publishing/).

## OPS-04. Инициализация TLS использует другой том и оставляет gateway выключенным при ошибке

При отдельном Compose-проекте `audit-config-20261111` том Nginx называется `audit-config-20261111_certbot-data`. `init_ssl.sh` указывает `docker run -v certbot-data:/etc/letsencrypt`. Имена расходятся даже при успешном получении сертификата. Nginx на старте читает свой том и создаёт временный самоподписанный сертификат, когда файл отсутствует. Скрипт печатает утверждение о готовом HTTPS без проверки TLS-рукопожатия. [Инициализация TLS](../../../scripts/init_ssl.sh#L35), [том Compose](../../../docker-compose.yml#L86), [entrypoint шлюза](../../../infrastructure/nginx/docker-entrypoint.sh#L12), [рендер](evidence/operations-probe.json).

В отдельном сценарии подставной Certbot вернул ошибку. Трасса показала `stop nginx`, затем попытку Certbot. Шаг восстановления `up -d nginx` не вызвался из-за `set -e` и отсутствия завершающего обработчика. При успешном `stop` и отказе ACME уже обслуживающий шлюз остаётся выключен до вмешательства. Проверка воспроизвела последовательность с подменой Docker и DNS. Внешний DNS, сертификаты и рабочий шлюз не затрагивались. [Скрипт](../../../scripts/init_ssl.sh#L17), [трасса](evidence/operations-probe.json).

## OPS-05. Автоматическое обновление TLS не загружает новый сертификат в Nginx

Контейнер Certbot каждые 12 часов выполняет `certbot renew --webroot`, потом ждёт следующего интервала. В этой команде нет deploy hook, а в определении контейнера нет шага reload Nginx. В шаблоне Nginx для HTTPS используются статические пути к сертификату и ключу после подстановки домена при старте. Общий том обновляет файлы. Для применения новой пары требуется перезагрузка конфигурации или рестарт Nginx. Ручной `make ssl-renew` отдельно вызывает reload. Если автоматический путь единственный, клиенты рискуют получить старую истёкшую пару после успешного продления на диске. Фактический цикл продления и срок сертификатов рабочего экземпляра не проверялись. [Цикл Certbot](../../../docker-compose.yml#L110), [сертификаты Nginx](../../../infrastructure/nginx/nginx.conf#L141), [ручная цель](../../../Makefile#L155), [обновление Certbot](https://eff-certbot.readthedocs.io/en/stable/using.html#renewing-certificates), [перечитывание Nginx](https://nginx.org/en/docs/control.html#reconfiguration).

В отдельном Nginx 1.29.5 с шаблоном из checkout заменили синтетическую пару на диске. Новое TLS-соединение с loopback продолжало предъявлять первоначальный сертификат. После HUP следующее соединение получило новый сертификат, что подтверждено по SHA-256. Внешний ACME не использовался. [Проверка](evidence/probe-nginx-renewal.py), [результат](evidence/nginx-renewal-probe.json).

## OPS-06. Диагностика скрывает отрицательный healthcheck

`check_docker_health` читает `State.Health.Status`. Для `unhealthy` выполнение проваливается в ветку `State.Running=true`, где результат заменяется на `pass/running`. В синтетическом прогоне HTTP-запросы возвращали 200, Docker отдавал `unhealthy` и `running=true`. Скрипт вывел `15 pass, 0 fail, 0 warn` и код 0. Такой результат может подавить эскалацию оператора при деградации сервиса. Отдельно скрипт проверяет localhost:8000 и localhost:3000, хотя production сбрасывает оба порта. Это делает прямые HTTP-проверки непригодными для штатного base + production без дополнительной привязки. [Логика healthcheck](../../../scripts/health-check.sh#L115), [адреса](../../../scripts/health-check.sh#L149), [probe](evidence/operations-probe.json).

## OPS-07. Старый backup-скрипт завершает неудачный Redis backup с кодом 0

При ошибке `BGSAVE` скрипт продолжает после `|| true`. После фиксированной паузы он копирует `dump.rdb` или AOF, а при обеих ошибках печатает предупреждение и продолжает ротацию. В прогоне с заглушкой Docker оба шага отказали, новых RDB не появилось, вывод содержал «Бэкап завершён», код 0. В той же проверке файл PostgreSQL возрастом 30 дней сохранился, а Redis-файл того же возраста был удалён из-за расположения `-mtime -delete` после второй ветки `find ... -o ...`. Аргументы из комментария `--dir путь --keep 14` также проигнорированы, сценарий создал каталог по умолчанию. [Parser](../../../scripts/backup-database.sh#L34), [snapshot](../../../scripts/backup-database.sh#L67), [ротация](../../../scripts/backup-database.sh#L87), [probe](evidence/operations-probe.json).

Ветка PostgreSQL сохраняет dump одной базы. Отдельный миграционный экспорт включает другие БД, тома и проверку хешей. Его квитанция явно фиксирует `ApplicationConsistentCutover=false` для заявленного режима live capture. Для проверки восстановления нужен единый сценарий с рабочими приложениями, ключами, тестом согласованности и измерением RPO/RTO. [Ветка PostgreSQL](../../../scripts/backup-database.sh#L49), [миграционный capture](../../../scripts/migration/backup_data.py#L83), [квитанция](../../../scripts/migration/export-to-ssd.ps1#L77).

## OPS-08. Команда `make monitoring` выбирает невалидный legacy-профиль

`make monitoring` указывает `docker-compose.monitoring.yml`. В нём Alertmanager получает `alertmanager.yml` через read-only bind mount и запускается без подстановки переменных внутри файла. Для `chat_id` парсер ожидает целое число и получает строковый placeholder. `amtool check-config` из закреплённого в профиле образа v0.26.0 вернул код 1 с ошибкой преобразования в `int64` на строке 46. При таком профиле оператор может увидеть компоненты мониторинга, но маршрутизация уведомлений через Alertmanager не запустится. Текущий рекомендованный opt-in профиль observability имеет другую конфигурацию. Его Prometheus и одно правило прошли `promtool check config`, доставка уведомлений этой проверкой не измерялась. [Цель Makefile](../../../Makefile#L97), [legacy service](../../../infrastructure/monitoring/docker-compose.monitoring.yml#L60), [файл Alertmanager](../../../infrastructure/monitoring/alertmanager.yml#L46), [эксплуатационный профиль](../../operations/OBSERVABILITY.md#изолированный-docker-стек), [результаты](evidence/monitoring-probes.md).

## OPS-09. Legacy-алерт делит частоту 5xx на частоту тех же 5xx

Метрика HTTP экспортируется с меткой `status_code`. Числитель `HighErrorRate` выбирает только 5xx. Знаменатель берёт все series, но деление без агрегации сопоставляет каждую series по её меткам, включая `status_code`. Для положительной серии 500 обе стороны деления поэтому имеют одинаковое значение. Изолированный `promtool` с **99 успешными ответами/с и 1 ошибкой/с** подтвердил срабатывание `HighErrorRate` с текстом **100%** при фактической доле 1%. Условие проявляется при активации этого набора legacy rules и наличии соответствующих метрик. [Правило](../../../infrastructure/monitoring/alert-rules.yml#L98), [метрика](../../../backend/metrics.py#L31), [фикстура](evidence/prometheus-error-rate.yml), [результат](evidence/monitoring-probes.md).

<a id="ops-10"></a>
## OPS-10. Production Compose назначает API bootstrap-роль PostgreSQL

При первой установке production launcher выбирает base + production. Backend DSN собирается из тех же `POSTGRES_USER` и `POSTGRES_PASSWORD`, которыми официальный entrypoint инициализирует PostgreSQL. Передача отдельного `POSTGRES_URL` через окружение launcher не меняет DSN контейнера. В синтетическом рендере это наблюдалось даже при явно заданном URL с другим пользователем. Затем реальный backend guard подключился к свежему PostgreSQL 15 под сформированной bootstrap-ролью. SQL подтвердил `rolsuper=true`, после чего `check_db_role_not_superuser()` отклонил старт при `ENVIRONMENT=production`. Для прогона хост DSN был перенаправлен на случайный loopback-порт тестовой БД. [Production launcher](../../../scripts/full-deploy.sh#L69), [bootstrap и DSN](../../../docker-compose.production.yml#L7), [DSN backend](../../../docker-compose.production.yml#L61), [startup](../../../backend/main.py#L32), [guard](../../../backend/core/startup_checks.py#L50), [результат](evidence/production-database-probe.json).

На чистом штатном профиле этап миграций может работать под bootstrap-ролью, а API после этого не проходит startup и healthcheck. Известный риск F-12 подтверждён исполнением. Для закрытия дефекта чистый профиль должен мигрировать под владельцем схемы, затем запускать production API под отдельной runtime-ролью и проходить readiness с той же конфигурацией. [Предыдущий F-12](../2026-11-01/FINDINGS-REGISTER.md#f-12), [описание ролей](../../deployment.md#configuration-sources).

## OPS-11. Импорт globals с ролью `postgres` блокирует восстановление

Режим Restore всегда передаёт `--preserve-roles`. Импортёр запускает новый PostgreSQL с bootstrap-ролью `postgres`, затем применяет полный `pg_dumpall --globals-only` с `ON_ERROR_STOP=1`. Если backup снят с кластера, где существует роль `postgres`, стандартный globals dump содержит её создание. Новый кластер уже имеет одноимённую роль. [Снятие globals](../../../scripts/migration/backup_data.py#L91), [Restore](../../../scripts/migration/new-install.ps1#L225), [порядок импорта](../../../scripts/migration/restore_data.py#L105).

Оригинальный CLI запущен с синтетическим backup из PostgreSQL 15, содержащим роль `postgres`. PostgreSQL вернул `role "postgres" already exists` на применении globals. Восстановление базы ещё не началось. В том же тесте импорт без сохранения ролей восстановил базу из тех же байтов. Этот контроль проверяет исправность dump, а сохранение владельцев и прав требует отдельного успешного сценария. Предыдущая успешная приёмка восстановления относится к дампу конкретного пилота. [Результат](evidence/production-database-probe.json), [предыдущая приёмка](../../operations/migration-2026-11-02/DATA-RECOVERY.md).

## OPS-12. Alembic обрывает миграционный вход на экранированном пароле

`alembic/env.py` передаёт DSN в `Config.set_main_option()`. Используемый `ConfigParser` интерпретирует `%` как начало подстановки. Корректный PostgreSQL DSN с percent-encoding для символов в пароле попадает туда без экранирования для формата INI. В тесте тот же DSN с синтетической ролью успешно выполнил `SELECT 1` через asyncpg. `alembic current` с ним завершился кодом 1 и `invalid interpolation syntax`. Контроль с URL без percent-encoding завершился кодом 0. Оба случая идут через общий `env.py`, поэтому ошибка возникает ещё до выполнения `upgrade head`. [Конфигурация Alembic](../../../alembic/env.py#L33), [миграционная команда](../../../scripts/full-deploy.sh#L274), [результат](evidence/production-database-probe.json).

Условие касается корректно закодированных DSN с такими символами. Штатный генератор выдаёт URL-safe пароль. При использовании внешнего секрета или ротации оператор может столкнуться с отказом Alembic при рабочем подключении приложения. Критерий закрытия — одинаково успешная обработка двух DSN в чтении текущей ревизии и штатном upgrade на отдельной БД. [Генератор](../../../scripts/generate_secrets.py#L43), [воспроизводимая проверка](evidence/probe-production-database.py).

<a id="ops-13"></a>
## OPS-13. Nginx отклоняет допустимый пакет VPN-профилей

Веб принимает до 100 файлов общим размером до 3 МиБ и формирует JSON до 4 МиБ. Backend batch preflight и импорт также допускают тело до 4 МиБ. В используемом production-шаблоне Nginx `client_max_body_size` для `/api/` не повышен. Remote gateway допускает 32 МиБ на первом hop и пересылает запрос к этому же шаблону на порт 8081. [Лимиты веба](../../../frontend/src/features/vpn/VpnProfileBatchImport.tsx#L45), [лимиты API](../../../backend/api/v1/vpn/profile_router.py#L65), [production ingress](../../../infrastructure/nginx/nginx.conf#L169), [внутренний ingress](../../../infrastructure/nginx/nginx.conf#L72), [remote hop](../../../infrastructure/nginx/remote-pilot.conf#L23).

Синтетический пакет из 96 допустимых профилей занимал **1 206 818 байт**. Реальный backend preflight напрямую принял все 96 и вернул `config_valid=true`, без сохранения. Изолированный Nginx с исходным шаблоном вернул **413** до обращения к upstream на обоих входах, 443 и 8081. Контроль из двух профилей доставил upstream все **951 байт** на обоих входах. VPN не включался, upstream для проверки прокси только считал байты. Для оператора эффект ограничен пакетами выше лимита шлюза. Критерий закрытия — проверка и сохранение допустимого пакета через оба ingress, с согласованным отказом выше задокументированного предела. [Проверка](evidence/probe-ingress-contracts.py), [наблюдение](evidence/ingress-contracts-probe.json).

<a id="ops-14"></a>
## OPS-14. Текущий шаблон PR preview отвергается до запуска

Deploy job запускается при `PREVIEW_ENVIRONMENTS_ENABLED=true`. На хосте он копирует `docker-compose.preview.yml`, записывает значения в `.env` и передаёт шаблон прямо Compose. Верхнеуровневый ключ тома содержит выражение `preview-${PR_NUMBER}-pgdata`. При синтетическом `PR_NUMBER=411` и остальных заполненных переменных Compose 5.1.0 вернул код 1 и `volumes additional properties ... not allowed`. Это повторная проверка ранее описанного F32-27. Состояние флага и внешнего хоста в этот прогон не входило. [Шаблон](../../../docker-compose.preview.yml#L148), [условие запуска](../../../.github/workflows/preview-deploy.yml#L12), [команды deploy](../../../.github/workflows/preview-deploy.yml#L133), [предыдущая запись](../2026-09-20/REDIS-MEMORY.md#дополнительно-f32-27--p1-preview--medium), [результат](evidence/ingress-contracts-probe.json).

После успешного рендера отдельной проверки потребует конфигурация backend. Шаблон передаёт `DATABASE_URL`, а приложение и Alembic читают `POSTGRES_URL`. Критерий закрытия — валидный рендер, миграция чистой preview БД и проверка готовности на фактически развёрнутом preview. [Окружение preview](../../../docker-compose.preview.yml#L51), [Settings](../../../backend/core/config.py#L19), [Alembic](../../../alembic/env.py#L33).

## Покрытие и фактические запуски

| Поверхность | Выполнено | Следующее требуемое свидетельство |
|---|---|---|
| Base/full/production и local pilot | Рендер с тестовыми переменными, локальные тесты мерджа, секретов и настроек | Чистый build и запуск точного SHA, ресурсные пределы под нагрузкой |
| Nginx production / remote / review | Проверены production vhost, TLS и лимит batch-запроса, выполнены отдельные gateway regressions для remote/review | Публичная цепочка DNS/TLS, прохождение WebSocket и маршрутов через конкретный ingress, ротация сертификата |
| PostgreSQL, Redis, MinIO | Состав профилей, схема readiness, конфигурация хранения артефактов, backup | Деградация Redis под давлением, failover, отказ S3, согласованность после рестарта |
| Туннели, TURN, VPN, Traefik | Точки входа в [tunnel Compose](../../../docker-compose.tunnel.yml), [remote pilot](../../../docker-compose.remote-pilot.yml), [TURN](../../../infrastructure/turn/compose.yml), [Traefik](../../../infrastructure/traefik/docker-compose.traefik.yml). Quick-tunnel regressions в отчёте интеграций | Проверка правил маршрутизации, NAT и переподключения, multi-device нагрузка, TURN-кандидаты и VPN-интероп |
| Сборка, staged deploy, release и preview | Проверены staging-последовательность, production-конфигурация и рендер preview. Проверки версии, подписи и публикации APK сверены по [release workflow](../../../.github/workflows/release.yml) | Прослеживаемость build/promotion по digest, развертывание и откат, preview cleanup, доказательство подписанного артефакта |
| Наблюдаемость | Проверены health-check, парсинг legacy Alertmanager и новой коллекции, legacy rules и ложный HTTP-алерт | Проверить фактическую маршрутизацию метрик, правила и панели, рассылку тестового алерта, размерность под нагрузкой |
| Backup, restore, миграция | Отказ backup, коллизия при restore с globals, production-роль и отказ Alembic воспроизведены. Миграционные локальные тесты прошли | Изолированное восстановление полного комплекта с реальными аналогами данных и метриками RPO/RTO |

[Воспроизводимая проверка конфигурации и сценариев](evidence/probe-operations.py). Изолированный pytest-прогон на Windows с `--noconftest -p no:cacheprovider` по `test_compose_{production,runtime_settings,local_pilot}.py`, `test_remote_gateway_host.py`, `test_review_gateway_redirect.py` и пяти миграционным модулям дал **43 passed, 4 subtests passed**. Это включает два gateway-теста с отдельными временными Docker-ресурсами. Сценарии доказательств выше дополнены отдельным прогоном, поскольку существующие тесты не утверждают их ожидаемое поведение.
