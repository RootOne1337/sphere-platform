# Первый рабочий пилот: что осталось до использования

**12 сентября 2026 · рабочий план, не акт готовности.**

**Продвижение:** [новый стенд](LOCAL-PILOT.md) работает отдельно от старой установки.
Browser login/reload, один установленный APK, 12/12 HTTPS shell `echo` после AUD-92
и автоматический возврат после gateway restart проверены. Полное DAG-задание из UI,
второй экземпляр и постоянные независимые каналы ещё не приняты; рубеж A не закрыт.

[Главная](../../README.md) · [Текущий аудит](../audits/2026-09-05/AUDIT-REPORT.md) ·
[Эксплуатационная матрица](READINESS.md) · [Запуск](STARTUP.md) · [APK](../android-agent.md)

## Ближайший результат

Оператор поднимает подготовленный стек, открывает веб, входит, устанавливает
согласованный APK на один эмулятор, видит именно это устройство, отправляет простое
задание и получает подтверждённый результат. Следующий рубеж добавляет рабочий VPN,
повторный запуск без потери identity и диагностику проблем. AI в эти этапы не входит.

Сборки, компонентные тесты и native shell/reconnect прошли. Полный сценарий
задания из веба на установленном APK ещё не выполнен; поэтому обещание «скачай APK и всё уже работает» преждевременно.
Для первого пилота не требуется закрыть весь исторический security backlog или
сразу доказать ёмкость в тысячу устройств. Требуется пройти конкретные шаги ниже.

## Режим первого пилота

Первый стенд — изолированный `ENVIRONMENT=development` с prepared credentials и
миграциями. Текущий [DB-role guard](../../backend/core/startup_checks.py) в этом
режиме предупреждает о privileged role, но не останавливает API; такое поведение
уже покрыто PostgreSQL regression. Отдельный production RLS rollout не является
новым обязательным этапом перед этим dev smoke. В production отдельные runtime/
migration roles и grants остаются обязательными, guard не отключается.

## Оценка объёма от текущего состояния

| Рубеж | Плановый ориентир | Что должно быть предъявлено |
| --- | --- | --- |
| A. Веб + один APK + простое задание | 1–3 рабочих дня | Версии стека/APK, конфигурация стенда, успешный вход, device ID, task ID и результат на устройстве |
| B. Пилот на нескольких эмуляторах с VPN и recovery | 1–2 недели суммарно | Настоящий handshake/маршрут VPN, основные действия UI, перезапуск и возврат связи, найденный по времени/device/task инцидент |
| C. Измеренный парк: десятки, затем сотни | 3–6 недель суммарно | Ступени нагрузки, p50/p95/p99 reconnect/command latency, CPU/RAM, отказы зависимостей и длительный прогон |

Это грубая оценка инженерного объёма, не SLA и не обещание календарной даты.
Предполагаются доступный разрешённый стенд, выбранный эмулятор, необходимые права
Android и доступный управляемый VPN-router. До первого полного прогона диапазон
имеет низкую уверенность. Новые runtime-дефекты и отсутствие VPN-компонентов могут
увеличить срок; после рубежа A оценку нужно пересчитать.

Прежний запуск API был отклонён автоматической проверкой разрешений; обход не
выполнялся. После новой явной просьбы владельца поднять отдельный локальный проект
12 сентября выполнены Compose/browser smoke, установленный APK shell и gateway
recovery. Эта прежняя блокировка больше не описывает текущее состояние стенда;
in-process HTTP и JVM tests по-прежнему не заменяют остальные native сценарии.

## Порядок приёмки

| Шаг | Текущий результат | Что ещё сделать / критерий завершения |
| --- | --- | --- |
| 1. Выбрать запуск | AUD-79/80: argv/env selection; AUD-84: сохранение `.env`; AUD-86: generated config проходит Settings | Проверить реальные адреса/параметры и Bash dotenv; запускать один выбранный project |
| 2. Подготовить БД | AUD-82: порядок; migrations/bootstrap в runtime image; AUD-87: default/custom PG init.sql и container restart с сохранением записи | Полный выбранный Compose; recovery старых частичных установок при необходимости. Production дополнительно требует provision roles/grants |
| 3. Создать пользователя и enrollment key | AUD-78/81/83/85: identity и повтор; runtime image выполняет CLI→SQL→полный ASGI lifespan→login/device | Пройти выбранный Compose и browser/APK; текущий image scenario не открывает HTTP listener |
| 4. Открыть веб и подключить APK | Android registration/refresh/ACK/fallback покрыты JVM-тестами | Проверить настоящий browser login, provisioning APK, permissions, `auth_ok`, видимость устройства и версию APK в UI |
| 5. Выполнить задание | Backend dispatch и Android journal/DAG имеют regression tests | Веб → исполнение на эмуляторе → сохранённый результат → UI; отказ/отмена/повторная доставка с тем же task ID |
| 6. Восстановить связь | Сохранены endpoints, intent refresh, checked registration commit | Потеря initial registration response, клонированная identity, backend/сеть/process restart; никакой ручной переустановки |
| 7. Подключить VPN | SQL ownership/intents и router adapter частично проверены | Реальный router, доставка config на APK, наличие совместимых AWG/WG tools, handshake, маршруты, сохранность management-связи при отказе |
| 8. Диагностировать и управлять | Есть backend logs/request ID и APK log upload | Рабочий metrics stack, incident correlation, основные кнопки UI и отсутствие фиктивных показателей |
| 9. Увеличить парк | Аппаратных capacity measurements нет | 1 → несколько → 10–64 на станции → 100/500; следующий уровень только после замеров предыдущего |

Открытый backlog остаётся в [READINESS](READINESS.md). Найденные blockers рубежей
A/B имеют приоритет перед косметическими правками и дальнейшим расширением функций.

## Что означает bootstrap после AUD-78

`scripts/create_admin.py` и `scripts/seed_enrollment_key.py` используют одну
организацию: `SPHERE_BOOTSTRAP_ORG_SLUG`, по умолчанию `default`. Миграции выполняются
до этих команд. Сначала создаётся администратор, затем ключ из эффективного
`AGENT_CONFIG_DIR/environments/{AGENT_CONFIG_ENV}.json`. Seed не создаёт таблицы
через `metadata.create_all()` и не создаёт вторую организацию в обход пользователя.

Повторный seed проверяет существующий ключ: org, active, expiry, device:register.
Конфликт, отсутствие ключа/организации или ошибка SQL прерывают bootstrap. Отозванный
ключ не реактивируется автоматически; существующие ключи и устройства из
`default-org` не переносятся. Для такой установки явно выбирается существующая
организация либо подготавливается новый enrollment key с понятной принадлежностью.

Административные CLI требуют отдельно подготовленных прав БД для bootstrap.
Они не заменяют production RLS runtime-role rollout. Full-deploy использует
`create_admin.py --create-only` и сохраняет existing admin. Прямой CLI без этого
флага обновляет пароль/роль/active; используйте этот режим намеренно. При email в другой
организации команда отказывает, не перепривязывает пользователя.

Bootstrap-функции Windows/Bash передают email/password через environment в
`docker compose run --rm --no-deps -T -e ADMIN_EMAIL -e ADMIN_PASSWORD`, без inline Python с паролем.
При отказе пользователя или ключа функция не показывает якобы рабочие credentials.
PowerShell восстанавливает прежние process env значения. Остальные этапы legacy
`full-deploy.*` — secrets/env selection, migration ordering, readiness, production
credentials, сохранение пароля и autostart — требуют отдельной проверки.

## VPN и телефоны

Текущий [SphereVpnManager](../../android/app/src/main/kotlin/com/sphereplatform/agent/vpn/SphereVpnManager.kt)
вызывает root `wg-quick`; запасной `VpnService` в этом менеджере не реализован.
Наличие APK на Android 8+ не означает поддержку VPN без root. Для раннего пилота
нужно явно зафиксировать root/tooling эмулятора и совместимость конфигурации AWG.
Backend ожидает отдельный HTTP-router по `WG_ROUTER_URL`; настоящее создание peer,
handshake и маршрутизация ещё не подтверждены. Static `/vpn/health` и нулевые
графики не являются доказательством туннеля. [VPN runbook](../runbooks/02-vpn-incident.md).

## Будущий AI

[Архитектурный анализ](../architecture/AI-READINESS.md) подтверждает наличие основы
для отдельной AI-станции: экран, primitives управления, DAG и receipts. Необходимо
спроектировать observation/action timing, mapping игры, ownership и stop/deadlines.
Это возможность дальнейшей разработки, не подтверждение управления сотнями игр.
Модель, weights, новые AI-сервисы и игровая интеграция сейчас не добавляются.

## Штатные credentials для первого входа

AUD-78 заменяет default `admin@sphere.local` (API отвергает `.local` email) на
`admin@example.com`. CLI проверяет email/password той же схемой `LoginRequest`
до записи в БД и сохраняет нормализованный email. Введите собственный подходящий
email через `SPHERE_ADMIN_EMAIL` у launcher или `ADMIN_EMAIL` у CLI. Отправка писем
этим bootstrap не выполняется. Существующие `.local` users автоматически не меняются.

Число коммитов не является процентом готовности: в PR отдельно сохраняются runtime,
регрессии, доказательства и документация. До первого пилота оставшийся объём,
вероятно, меньше уже сделанного, но сроки аппаратных/сетевых прогонов нельзя
экстраполировать из скорости коммитов. Переоценка — после первого полного сценария.

## Дополнительная проверка запуска: AUD-79

Исправлен прямой blocker Bash full-deploy: `IFS` превращал строку параметров Compose
в один аргумент. Оба overlay теперь хранятся в array; все file options передаются
по отдельности. Четыре новых сценария сохраняют настоящий preamble/option parsing,
а весь deployment набор содержит 37 passing cases. Это ещё не запуск полного стека:
следом требуется проверить env-file, порядок migrations/API и настоящую готовность.

## Контрольная точка после AUD-78/79

На `ac7a11f` полный Linux CI: **1417 tests / 69.37%**, включая 505
PostgreSQL/Redis и 37 deployment cases. Backend/frontend/Android проходят;
preview deployment пропущен. [Доказательства](../audits/2026-09-05/evidence/ci-ac7a11f-tests.txt).
Для приёмки по-прежнему нужны шаги 1–9 выше. Конфигурация запуска и migrations/API
идут следующими, до внешнего вида UI и большой нагрузки.

### APK artifact и сохранение identity

Два настоящих debug APK из CI `0da40f1` проверены: около 8,35 MB каждый,
minSdk 26 / targetSdk 35, versionCode 10200, ZIP CRC и v2 signatures проходят.
[Фактические package IDs, хеши и подпись](../audits/2026-09-05/evidence/apk-0da40f1-inspection.json).
Размер файла не доказывает CPU/RAM, latency или VPN. Перед длительным пилотом
нужно выбрать один package и постоянную managed signing identity, проверить update
без потери app data. CI пока выдаёт debug artifacts; готовый release/update channel
этим не подтверждается. На эмулятор или телефон эти APK не устанавливались.

## Windows configuration: AUD-80

Full-deploy wrapper и штатный start-dev config/build/up теперь явно передают
`.env.local` (приоритет) или `.env` из checkout. Файлы не объединяются, process env
сохраняет приоритет. Проверены настоящий Compose renderer на synthetic configuration
и launcher subprocess; все 44 deployment cases проходят. Это закрывает доказанное
расхождение выбора файла в этих Windows paths. Bash dotenv parsing, legacy branches,
secrets lifecycle и настоящие настройки стенда ещё требуют проверки.

## Следующий проверяемый рубеж после AUD-80

Точный CI `ea8e606`: **1424 / 69.38%**, backend/frontend/Android проходят;
preview deployment пропущен. [Вывод](../audits/2026-09-05/evidence/ci-ea8e606-tests.txt).
44 deployment cases локально проходят. Это завершает проверку конкретных bootstrap,
Compose argv и Windows env fixes, но не весь запуск.

Следующие участки требуют отдельных проверок; состояние каждого указано ниже:

1. **AUD-82: порядок launcher исправлен.** [`PS`](../../scripts/full-deploy.ps1) /
   [Bash](../../scripts/full-deploy.sh): PostgreSQL/Redis → one-off migration/admin/key
   → приложения с Compose wait. Production probes проверяют API/login; host fallback
   удалён. 65 deployment cases проходят; настоящий fresh-volume SQL/daemon rollout,
   runtime roles и уже работающие workers ещё требуют проверки.
2. **AUD-81: отсутствие CLI закрыто.** [`backend/Dockerfile`](../../backend/Dockerfile)
   теперь включает admin/enrollment scripts. Настоящий image probe: 2 failures до
   исправления, 4 passing cases после; [evidence](../audits/2026-09-05/evidence/image-bootstrap-summary.json).
   Реальное SQL bootstrap внутри image остаётся отдельным критерием.
3. **AUD-83: identity dev-hook согласована с CLI.** [Hook](../../backend/tasks/ensure_enrollment_key.py)
   использует configured key и exact bootstrap org; параллельные workers сериализованы.
   SQL/ASGI проверяют registration/tenant visibility и повторный bootstrap; Compose
   передаёт выбранный slug. Полный process lifespan/installed APK ещё не принят.

После закрытия blockers этого рубежа — настоящий login → установленный APK →
device/task/result и recovery/VPN. Оценка сроков всё ещё условна; число коммитов
не снимает эти критерии приёмки.

## Приёмка после изменения порядка запуска

AUD-81/82 закрывают отсутствие packaged CLI и порядок запуска до schema/bootstrap.
Доказательства: настоящий image probe без сети (4 cases) и полный main flow обоих
shell на процессе Docker double, включая отказы (65 deployment cases). Следующие
условия первого живого запуска: разделённые DB roles/grants, подготовленные config/key,
сохранение секретов при повторе и fresh-volume bootstrap. Legacy dev-key hook
согласован с CLI в AUD-83; старые credentials не мигрируются автоматически.
Уже работающие workers скрипт не останавливает; несовместимая migration требует
отдельного cutover. Полная цепочка веб/APK/task и VPN пока не принята.

## Сохранение `.env` при повторе: AUD-84

Закрыта доказанная ошибка: full-deploy создавал новые секреты поверх установки,
настроенной только через `.env`. Оба shell теперь сохраняют этот файл как active
configuration; 4 baseline failures / 6 controls, все 77 deployment cases проходят.
Это не подтверждает весь secret lifecycle: admin password updates, explicit
rotation, восстановление backup и настоящий persistent-volume restart ещё нужны.
Admin credentials при повторе проверены в AUD-85. Следующий gate development-пилота —
fresh SQL/bootstrap выбранного полного стека, затем установленный APK/task/result. Roles/grants остаются отдельной
обязательной частью production rollout. [Контракт повторного запуска](STARTUP.md).

## Проверенная контрольная точка AUD-81–84

`b9a3518`: **1476 Linux cases / 69.66%** и отдельные 4 production-image
probes, все PR workflows успешны с первой попытки. [Evidence](../audits/2026-09-05/evidence/ci-b9a3518-tests.txt).
Локальный полный прогон AUD-83 дал 1466 passing cases; после AUD-84 отдельно
все 77 deployment cases проходят. Это закрывает описанные
bootstrap defects; первый installed-APK/task/result smoke всё ещё требуется.
Никакого изменения общей оценки сроков только по росту числа тестов/коммитов нет.

## Admin restart: AUD-85

Повторный full-deploy сохраняет рабочий пароль; после новой записи initial
credentials доступны до возможного отказа enrollment. Это проверено настоящими
PS/Bash functions → CLI → PostgreSQL → ASGI login; Docker/enrollment — process
boundaries. Девять before failures / четыре controls, общий Windows **1498 / 69.67%**.
Следующий P0 — fresh bootstrap полного выбранного стека и установленный APK/task/result.
Результаты по образу, транспортам и OS всё ещё отделены от component proof.

## Поставляемый образ: SQL и повтор процесса

Runtime `08338d3` прошёл локальный сценарий с пустой PostgreSQL, Redis, настоящими
CLI и полным lifespan приложения. После повторного bootstrap новый процесс принимает
прежний пароль и видит то же устройство. Данные SQL не подменяются; HTTP выполняется
через ASGI. [Evidence](../audits/2026-09-05/evidence/packaged-runtime-08338d3/image-runtime-probe.txt),
[runner](../../tests/containers/README.md). Это сокращает пробел packaged bootstrap,
но не заменяет полный Compose, browser, установленный APK/task/result и VPN.
Сроки пересматриваются после настоящего рубежа A, не по числу прошедших тестов.

### Linux CI для packaged runtime

`cbf8f01`: **1498 / 69.66%**, четыре no-network image probes и отдельный
SQL/runtime scenario проходят с первой попытки во всех PR workflows. [Evidence](../audits/2026-09-05/evidence/ci-cbf8f01-image-runtime-tests.txt).
Так закрывается проверка SQL bootstrap внутри поставляемого backend-образа.
Проверка полного Compose должна дополнительно использовать штатный PostgreSQL
init.sql: его OWNER=sphere при configurable POSTGRES_USER требует воспроизведения.
Browser/installed APK/task/result и VPN остаются следующими критериями приёмки.

## Свежий dotenv проходит импорт backend: AUD-86

Устранён подтверждённый блокер до SQL: full Compose больше не подставляет пустой
boolean DEV_SKIP_AUTH для штатно сгенерированной конфигурации. Два исходных падения /
шесть controls, восемь retained cases, **93 deployment tests проходят локально**.
Это часть шага 1, отдельная от проверки образа с SQL. PostgreSQL init.sql и полный
выбранный Compose/browser/installed APK/task/result остаются в очереди приёмки.

### Подтверждение AUD-86 в CI

`8932e49`: **1506 / 69.66%**, 538 production-directory / 93 deployment,
отдельно image **4 + 1**. Все PR workflows прошли с первой попытки.
[Точные результаты](../audits/2026-09-05/evidence/ci-8932e49-tests.txt).
Это закрывает подтверждённые admin-repeat и generated-config blockers. Полный
Compose/init.sql, browser/installed APK/task/result и VPN остаются открыты;
условные сроки не сокращаются автоматически по числу коммитов или тестов.

## Штатный PostgreSQL init.sql: AUD-87

Предыдущее наблюдение о OWNER=sphere теперь воспроизведено и исправлено: новая
установка с другим POSTGRES_USER больше не падает на создании n8n. Отдельные
контейнерные cases проверяют default/custom user, владелец/extensions и container
restart с сохранённой записью. [Evidence](../audits/2026-09-05/evidence/postgres-init-final-after/postgres-init-summary.json).
Это покрывает init.sql отдельно от Alembic/image scenario. Полный выбранный Compose,
browser/установленная APK/task/result и VPN ещё нужны; частичный старый init не лечится автоматически.

### PostgreSQL init/restart в Linux CI

`a5209ba`: **1506 / 69.71%**, отдельно container **4 + 1 + 2**, все
четыре workflows проходят с первой попытки. [Оба PG cases](../audits/2026-09-05/evidence/ci-a5209ba-postgres-init-tests.txt).
Таким образом init.sql и сохранение записи после container restart проверены
для default/custom user. Следующий P0 — весь выбранный Compose/browser/installed APK/
task/result, затем VPN/recovery. Частичные старые volumes не изменялись; наличие n8n
DB не доказывает работоспособность его workload.
