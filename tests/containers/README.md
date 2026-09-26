# Проверки поставляемого backend-образа

Проверки запускаются в обязательном job `Production image bootstrap`.
Они считаются отдельно от pytest suite и не требуют установленной APK.

| Проверка | Что выполняется | Граница доказательства |
| --- | --- | --- |
| `backend_bootstrap_probe.py` — 4 cases | Validation обоих CLI, единственный migration head, запрет записи в `/app` | Без сети и SQL |
| `backend_runtime_probe.py` — 1 составной scenario | Пустая PostgreSQL → настоящие миграции → admin/key CLI → приложение → login/registration/visibility → повтор | Реальные SQL/Redis и два процесса с полным ASGI lifespan; без API listener, frontend, APK и VPN |
| `postgres_init_probe.py` — 2 cases | Штатный init.sql для default/custom POSTGRES_USER; владелец n8n, расширения и container restart с сохранением записи | Отдельный настоящий PG entrypoint и новый disposable volume; без полного Compose/APK |

## Локальный запуск runtime scenario

Нужны Python 3.10+, Docker и подготовленный образ. Из корня репозитория:

```sh
docker build -f backend/Dockerfile -t sphere-backend-runtime-audit .
python tests/containers/run_backend_runtime_probe.py --image sphere-backend-runtime-audit --evidence-dir runtime-evidence
```

Runner фиксирует immutable image ID, создаёт Docker-сеть с `--internal`, отдельные
PostgreSQL 15 и Redis 7.2 без host ports. Данные находятся в tmpfs. Приложение работает
от штатного non-root пользователя с read-only root filesystem; подключается только
файл probe. Код приложения, Settings, registry и SQL dependencies не подменяются.

Проверяются readiness PostgreSQL/Redis, успешный login, регистрация синтетического
устройства и доступ оператора к его реальной SQL-записи. Повтор миграций и bootstrap
с другим candidate password сохраняет исходный вход. Второй процесс заново запускает
приложение и видит то же устройство. Ошибки уровня error/critical в JSON stdout
фаз приложения приводят к падению проверки; lifecycle diagnostics сохраняются.

`image-runtime-probe.txt` содержит результат и логи фаз без HTTP response bodies;
`image-runtime-summary.json` — image ID, границы сценария, exit code и cleanup status.
Runner в `finally` удаляет только созданные им контейнеры и сеть после проверки
immutable ID и уникального ownership label. При принудительном убийстве самого
runner cleanup не гарантирован; оставшиеся ресурсы имеют label `sphere.audit.runtime`.
Существующие контейнеры, базы и volumes не используются.

## Что остаётся проверить отдельно

Это `ENVIRONMENT=development`; production DB roles/grants не тестируются этим probe.
Перезапускаются процессы приложения, PostgreSQL/Redis остаются работающими до cleanup.
Нет Gunicorn multi-worker, полного Compose, crash/reboot, отказа сети/БД, browser,
установленной APK, выполнения задания, VPN handshake или измерения ёмкости парка.
Успех сценария не закрывает [полный пилот](../../docs/operations/PILOT-ACCEPTANCE.md).

## Штатный PostgreSQL entrypoint и persistent-volume restart

```sh
python tests/containers/postgres_init_probe.py --evidence-dir postgres-init-evidence
```

Два cases используют официальный PostgreSQL 15 и настоящий
`infrastructure/postgres/init.sql` с `POSTGRES_USER=sphere` и
`POSTGRES_USER=sphere_audit_operator`. Каждый создаёт отдельный named volume с
уникальным label, контейнер с `--network none` и без host ports. Проверка ждёт
финальный TCP server внутри контейнера, чтобы temporary init server не считался
готовой БД; ошибка первого init проваливает case до любого restart.

SQL проверяет выбранного пользователя, владельца n8n, доступ к n8n и три расширения
основной БД. После этого создаётся marker, выполняется настоящий container restart
и проверяется сохранение marker, владельца и расширений. В `finally` удаляются
только созданные этим запуском контейнер/volume после проверки ID/name/label.
Логи и JSON summary содержат результат обеих фаз и cleanup. При убийстве runner
cleanup не гарантирован; оставшиеся ресурсы имеют label `sphere.audit.init`.
Существующие volumes не используются. Проверка не подтверждает восстановление
частично инициализированной старой установки или полноценный Compose rollout.
