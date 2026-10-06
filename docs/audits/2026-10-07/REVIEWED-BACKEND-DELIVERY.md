# Backend: доставка того же проверенного production image

Дата: **7 октября 2026, Asia/Yekaterinburg**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Статус при записи: source implementation; hosted artifact/runtime admission ещё
не подтверждены. Installed API **eb7a7c26**, UI **b50d6ae**, APK сохранены.
Общий product ledger **9 accepted / 41 open** не изменён.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Action contract](../2026-10-06/STUDIO-ACTION-PARAMETERS.md) ·
[Проверенный UI и открытые границы](STUDIO-RESIZE-INSTALLED-ACCEPTANCE.json).

## Подтверждённый разрыв доставки

От installed eb7a7c26 до source 0b889a4 изменены шесть backend-файлов:
router, script service, DAG/response schemas и два новых файла action contract.
Requirements, Alembic и Dockerfile в этой разнице не менялись. Новый frontend
явно сообщает, что старый сервер подтвердил только структуру/Lua safety.
Прямой API-клиент старого сервера может передать tap без x/y; новый publication
guard уже реализован и прошёл source CI, но source success не обновляет live API.

Backend CI собирал и проверял production image, затем сохранял только отчёты.
Повторная локальная сборка увеличивала Docker footprint на incident SSD и не
являлась тем же артефактом, который проходил packaged probes.

## Изменение CI и артефакт

[Workflow](../../../.github/workflows/ci-backend.yml) checkout каждого job закреплён
за PR head/push SHA; persist-credentials отключён. Image bootstrap строит один
Linux/amd64 image `sphere-reviewed-backend:<full source>` с SPHERE_BUILD_SHA,
OCI revision и CI run/attempt labels. Остальные tests/lint/security/RLS/Alembic
проверяют тот же checkout. Старые receipts сохраняют свои run/head facts.

После packaged bootstrap, disposable PostgreSQL/Redis runtime, multiprocess
metrics и PostgreSQL init probes [packager](../../../tests/containers/package_reviewed_backend.py)
сохраняет **тот же image ID**, без второго Docker build или pip install.
Проверяются exact image IDs в обоих structured probe receipts, cleanup,
отсутствие host ports/source mount и один packaged migration head.

Новый [runtime probe](../../../tests/containers/backend_runtime_probe.py) после
реального login проверяет GET action-contract: 32 actions, version 1.0,
no-store, 401 без auth и false capability/execution flags. POST validate
принимает корректный sleep и отвергает структурно допустимый tap без координат.
Обе проверки повторяются в новом process после повторной bootstrap-инициализации.
Это disposable development ASGI, не live production-role/Android проверка.

Artifact `sphere-reviewed-backend-<full source>` содержит только:

- `image.tar.gz`: Docker-save stream → gzip level 1, без промежуточного tar;
  максимум **300 MiB compressed / 1 GiB uncompressed**, timeout save 180 s.
- `receipt.json`: source/repository/run/attempt, config ID, platform,
  archive bytes/hash, requirements/action-contract hashes, migration head и
  scope packaged probes. Полные environment/config/token/logs не копируются.

Официальный Docker поддерживает потоковый save и gzip; это Docker-save archive,
а не новый собственный image format. [Docker image save](https://docs.docker.com/reference/cli/docker/image/save/).
Retention в GitHub — **3 дня**, upload compression 0, immutable artifact name,
action закреплён тем же v7 commit, который уже используется frontend workflow.
[Upload options](https://github.com/actions/upload-artifact#inputs).
Local Docker image/volume retention этим не изменяется. Generated artifacts
исключены из Git и Docker context; `.local-pilot` по-прежнему приватен.

## Read-only admission

[`reviewed_backend_artifact.py`](../../../scripts/pilot/reviewed_backend_artifact.py)
использует [общий bounded reader](../../../scripts/pilot/reviewed_image_archive.py)
с существующим UI admission: digest, exact single manifest/tag/config,
budget, traversal/link/duplicate rejection, наличие именно regular layer files.
Архив не извлекается, Docker не вызывается, ничего не устанавливается.
UI policy и backend policy отдельны: backend требует shipped user `sphere`,
gunicorn/entrypoint, один SPHERE_BUILD_SHA и совпадающие source/run/attempt labels.

Artifact receipt не является подписью. Перед load требуется отдельно получить
repository/workflow/head/run/attempt и успешное завершение **всего CI workflow**,
проверить independent image ID из authenticated CI log и artifact digest.
Успешный image-bootstrap job при failed/cancelled tests не допускает установку.
Флаги liveApiVerified, productionRoleRolloutVerified, androidExecutionVerified
и runtimeInstalled в artifact остаются false.

## Проверки и оставшиеся gates

### Установщик без миграций

[`install_reviewed_backend.py`](../../../scripts/pilot/install_reviewed_backend.py)
по умолчанию создаёт только read-only план. Требует independent CI config ID,
полный успешно завершённый backend workflow, ожидаемый installed SHA, live Compose
owner/config/env, совпадающий SQL head и только шесть разрешённых action-contract
source changes. Requirements, migrations и bootstrap changes этим путём запрещены.
Единственный допустимый Compose delta — backend image и удаление build recipe;
четыре существующих mount targets (включая отдельный OTA bind) сохраняются, source overlay/entry/user/ports override
не допускаются. Полные environment/SQL URL не выводятся.

Явный `--apply` после host guard загружает admitted archive и выполняет только
`backend up --no-deps --no-build --pull never`: shutdown grace 35 s, readiness
90 s. До и после проверяет identity/epoch/status всех остальных контейнеров,
SQL head, OTA catalog hash и exact revision через gateway 3015. Краткая повторная
проверка health выполняет только GET, до 8 попыток с timeout 2 s и паузой 2 s,
чтобы пережить resolver valid=10s существующего gateway; команды управления/Android не повторяет.
При сбое возвращает прежний image только при сохранённой ownership границе;
чужой runtime не останавливает, database rollback не выполняет. После установки
liveContractVerified и agentReconnectVerified остаются false до отдельного canary.

**51 local unittest methods passed**: прежние 35 плюс 16 operational installer
regressions. Проверены read-only plan, отказ до image load при volume warning или
SQL mismatch, изменение зависимого сервиса/env/mount, CI partial/cancelled/foreign,
canonical Git bytes, health revision/budget, успех с сохранением dependencies,
owned rollback и запрет остановки чужого image. Scoped Ruff passed.
Hosted run для commit `114775a` и live update ещё ожидаются; source tests не
подменяют проверку настоящего runtime.

**35 local unittest methods passed:** 22 существующих UI/archive/installer
и 13 backend/archive/packager; внутри методов отдельные негативные subcases.
Проверены неправильные source/CI/platform/entry, непроверенный live claim,
hash tamper, traversal/link/duplicate/second image, directory вместо layer,
byte budgets, short SHA, mismatch probe receipts, stream preservation,
failed save cleanup и сохранность уже существующего файла при exclusive-open failure.
Локальная тяжёлая сборка/установка не выполнялась.

Следующий шаг: exact hosted CI → скачать admitted artifact → read-only plan
по live Compose owner/config/env, версии SQL и source/dependency delta → bounded
backend-only install/rollback → реальные authenticated contract/negative validate,
catalog/task read и agent reconnect. UI, PostgreSQL, Redis, APK, OTA и gateway
не должны менять image/env/volumes/identity этим обновлением. Новый schema head
нельзя мигрировать скрыто; текущий кандидат не содержит schema/dependency change.
Continuous input, rich recording, fleet soak и причина роста storage остаются
отдельными работами. Этот документ не объявляет их завершёнными.
