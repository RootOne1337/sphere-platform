# Первый рабочий пилот: что осталось до использования

**11 сентября 2026 · рабочий план, не акт готовности.**

[Главная](../../README.md) · [Текущий аудит](../audits/2026-09-05/AUDIT-REPORT.md) ·
[Эксплуатационная матрица](READINESS.md) · [Запуск](STARTUP.md) · [APK](../android-agent.md)

## Ближайший результат

Оператор поднимает подготовленный стек, открывает веб, входит, устанавливает
согласованный APK на один эмулятор, видит именно это устройство, отправляет простое
задание и получает подтверждённый результат. Следующий рубеж добавляет рабочий VPN,
повторный запуск без потери identity и диагностику проблем. AI в эти этапы не входит.

Сборки и компонентные тесты уже проходят. Полный сценарий на установленном APK
ещё не выполнен; поэтому обещание «скачай APK и всё уже работает» преждевременно.
Для первого пилота не требуется закрыть весь исторический security backlog или
сразу доказать ёмкость в тысячу устройств. Требуется пройти конкретные шаги ниже.

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

Прежний запуск локального API был отклонён автоматической проверкой разрешений
с причиной `blocked by policy`. Это конкретное ограничение аппаратного/API smoke;
обход не выполняется. Разрешённые in-process HTTP и выделенные PostgreSQL/Redis
проверяют часть цепочки, но не заменяют установленный APK и настоящий браузер.

## Порядок приёмки

| Шаг | Текущий результат | Что ещё сделать / критерий завершения |
| --- | --- | --- |
| 1. Выбрать запуск | AUD-79: Bash argv; AUD-80: Windows `.env.local` → `.env` и explicit file | Проверить Bash dotenv, реальные адреса/обязательные параметры, selected project и оставшиеся legacy ветки |
| 2. Подготовить БД | Миграции и отдельные RLS fixes проверены изолированно | Пройти fresh-volume bootstrap, schema head, роли/grants, правильный порядок migration→API; проверить повторный запуск |
| 3. Создать пользователя и enrollment key | AUD-78 исправляет CLI/imports, передачу credentials и организацию ключа; реальные SQL/HTTP проверки | Подтвердить те же действия внутри выбранного полного Compose; текущий fix не проверяет остальные этапы full-deploy |
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
Они не заменяют RLS runtime-role rollout. Повтор `create_admin.py` с существующим
email обновляет пароль и роль; используйте этот режим намеренно. При email в другой
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
3. [`ensure_enrollment_key`](../../backend/tasks/ensure_enrollment_key.py) при dev startup
   выбирает первую org и фиксированный dev key, независимо от выбранной bootstrap org.
   Нужен отдельный SQL/lifespan сценарий для повторного запуска и нескольких org.

После закрытия blockers этого рубежа — настоящий login → установленный APK →
device/task/result и recovery/VPN. Оценка сроков всё ещё условна; число коммитов
не снимает эти критерии приёмки.

## Приёмка после изменения порядка запуска

AUD-81/82 закрывают отсутствие packaged CLI и порядок запуска до schema/bootstrap.
Доказательства: настоящий image probe без сети (4 cases) и полный main flow обоих
shell на процессе Docker double, включая отказы (65 deployment cases). Следующие
условия первого живого запуска: разделённые DB roles/grants, подготовленные config/key,
legacy dev-key hook, сохранение секретов при повторе и fresh-volume bootstrap.
Уже работающие workers скрипт не останавливает; несовместимая migration требует
отдельного cutover. Полная цепочка веб/APK/task и VPN пока не принята.
