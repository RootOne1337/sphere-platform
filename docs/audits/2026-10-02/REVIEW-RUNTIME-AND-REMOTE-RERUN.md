# Проверяемый веб в Docker и повтор задания на удалённом Android

**Дата:** 2 октября 2026, Asia/Yekaterinburg (UTC+5).<br />
**Установленный review UI:** `0f4530cefb33c32822959e65de715ef7625fc145`.<br />
**Работающий backend:** `5fcf18a87f9a2ab198b1d145eae485218871bc01`.<br />
**Android canary:** remote `auto-ph-025`, `1.2.40-dev / 10240`.

[Текущее состояние](../../operations/CURRENT-STATE.md) · [Журнал F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md) · [F16/F17 contracts](TASK-ARTIFACTS-AND-RERUN.md) · [Allowlisted evidence](REVIEW-RUNTIME-AND-REMOTE-RERUN-EVIDENCE.json) · [PR19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Проблема runtime и установленное исправление

Ранее подтверждённые Next772/UI3030 и relay13680/UI3015 перестали существовать; оба порта не слушали. Backend, Grafana, Prometheus и туннели оставались работающими. В доступных журналах не найдено объяснение завершения native процессов; связь с получением нового сообщения не доказывает причину. Первая попытка Android canary остановилась на отказе соединения при login: задания ещё не создавались.

Review теперь работает в отдельном Compose project `sphere-review-20261002`. В **04:50:20 UTC+5** проверены оба healthy контейнера; после их контролируемого перезапуска в **04:51:19** повторены проверки. URL: [3015](http://127.0.0.1:3015/). Host binding строго `127.0.0.1:3015`; этот project не публикуется через туннель.

- UI собран из отдельного `git archive`, с исходным production Next config и compiled SHA; build context не содержит private runtime файлов.
- Next standalone использует Node **v24.21.0**, Nginx передаёт `/api/v1/` и `/ws/` существующему backend. API authentication/Grafana session остаются server-side.
- Оба контейнера: non-root, read-only filesystem, dropped capabilities, `no-new-privileges`, memory/CPU/PID limits, ограниченные tmpfs и журналы `5m × 3`.
- `unless-stopped` сохраняет запуск под управлением Docker. `healthcheck` показывает состояние; сам по себе он не перезапускает зависший healthy/unhealthy процесс. Не проверялся restart Docker Desktop или Windows.
- Server-only observability secret переиспользован из ignored runtime. Grafana/Prometheus доступны UI через дополнительную private Compose overlay/network. Secrets и login credentials не включены в commit или evidence.
- Nginx использует динамическое Docker DNS разрешение и не переигрывает неясные mutation requests через следующий upstream.
- Все **14 ранее работающих контейнеров** сохранили IDs, image IDs и StartedAt. APK, OTA, public frontend, database, backend, tunnels и сами Android-устройства не перезапускались.

Источники конфигурации: [review Compose](../../../docker-compose.review.yml), [Nginx](../../../infrastructure/nginx/review.conf), [frontend Dockerfile](../../../frontend/Dockerfile). Сборка `cc3d13b` прошла, но запуск config-test обнаружил ошибку: flow-list YAML разбил некавыченный tmpfs на несколько mounts. Commit `0f4530c` исправляет строку; config expansion, `nginx -t`, build, запуск и проверка restart прошли именно после исправления. Этот контрпример сохранён; первая сборка не объявляется рабочим deployment.

## Проверки до и после restart

| Проверка | Результат обоих прогонов |
| --- | --- |
| Настоящий login и same-origin device API | HTTP200, 19 записей, reported online14 / offline5 |
| Backend build revision | `5fcf18a`, readiness healthy |
| Compiled frontend SHA и production static asset | `0f4530c`, файл отдаётся через gateway |
| Observability без авторизации | HTTP401 |
| Авторизованный Prometheus snapshot | HTTP200, `sphere-backend` target up |
| Grafana session / health | HTTP200, HttpOnly/SameSite=Strict cookie, database=ok |
| Events WebSocket | Upgrade, авторизованный snapshot, ping/pong |
| Review контейнеры после restart | healthy, те же image IDs и loopback binding |

Это HTTP/WS/runtime evidence. Browser visual acceptance остаётся **OPEN_URL_POLICY_BLOCKED**; просмотр запрещённого URL не обходился. Static asset и API200 не доказывают качество верстки, а events WebSocket не измеряет video FPS/input latency. Каталог — конечный срез, не uptime SLA и не подтверждение всех ожидаемых 23 устройств.

## F17: настоящий конечный canary на PH025

**04:45:34–04:45:41 UTC+5**, напрямую через действующий API18080, до установки нового review UI. Guard: устройство online, APK10240, активных заданий нет. Выполнены только `set_variable` и `get_variable`; UI, аккаунты, shell/root/network actions не менялись. Автоматические POST retries выключены.

1. Создан отдельный диагностический script/version v1 с уникальным текстовым marker; DAG ограничен двумя nodes и timeout10s.
2. Original task `c82b0d7d-6ba6-437d-abdb-dc507e5288d6` завершён Android: completed/success, оба node outputs содержат marker v1.
3. Latest version script изменена на v2 с другим marker; GET script подтвердил новую current version.
4. `POST /tasks/{original_id}/rerun` создал task `d76a87c9-b613-4cb1-82b5-f31b1d84cb23`. Он привязан к **v1**, а не latest v2; input params и priority3 совпали.
5. Android завершил повтор completed/success; оба outputs снова содержат **marker v1**, marker v2 отсутствует. Device остался reported online/10240.
6. После двух terminal results архивирован только собственный diagnostic script. Versions/task results сохранены; посторонние сценарии и задания не изменялись.

Первый task: created23:45:34.810Z → started23:45:35.723Z → finished23:45:35.753Z. Повтор: created23:45:36.879Z → started23:45:40.551Z → finished23:45:40.616Z. Эти server timestamps описывают finite dispatch/execution; они не являются input-to-visible/video latency или межмашинным SLA.

Таким образом подтверждён один реальный remote execution и один pinned rerun. Custom timeout, account binding и concurrent replay защищены source/PostgreSQL tests; этот canary не проверял их на Android. Не проверены произвольные сценарии, массовая очередь, offline replay или screenshot upload. N01 Android-local screenshot → storage остаётся открытым; два variable nodes не заменяют этот gate.

## CI, воспроизводимость и следующие gates

Published verification head `77e96a4`: [backend36924906048](https://github.com/RootOne1337/sphere-platform/actions/runs/36924906048), [frontend36924906017](https://github.com/RootOne1337/sphere-platform/actions/runs/36924906017), [Android36924905908](https://github.com/RootOne1337/sphere-platform/actions/runs/36924905908) — success. Backend jobs Tests, production bootstrap, RLS, lint/security и Alembic passed; это отдельный завершённый run после прежнего stale OpenAPI failure. Число 2165/16 относится к сохранённому предыдущему run, а не восстановленному log этого head.

Packaging head `0f4530c` опубликован отдельно; его CI отслеживается по собственному SHA. Local Docker production build и реальное восстановление review проверены, но они не подменяют полный CI этого head. При повторном запуске задаются полный `SPHERE_REVIEW_BUILD_SHA`, существующая `SPHERE_REVIEW_API_NETWORK`, loopback port и private server-only observability env/network. Общие Compose stop/down/update команды не применялись.

Открыты 17 исходных findings и N01. Следующие группы: discovery request ownership/contract (F19/F20), операторские формы/workflows, затем video/XPath/quality, browser visual walkthrough и 20–30 устройств. Public rollout и merge PR19 этим batch не выполнялись.

Официальные основания: [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/), [Compose tmpfs](https://docs.docker.com/reference/compose-file/services/#tmpfs), [Node release lifecycle](https://nodejs.org/en/about/previous-releases). Новые UI assets не добавлены; AdminCN attribution остаётся прежним.
