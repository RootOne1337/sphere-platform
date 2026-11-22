# Pipeline heartbeat: наблюдение commit вместо fixed sleep

6 октября 2026, Asia/Yekaterinburg. Отдельный test-only follow-up к
[Script Studio этапу A](SCRIPT-STUDIO-FOUNDATION.md). Установленные API `c2b91e32`
и UI `952b5e2f` этим исправлением не заменяются.

## Подтверждённый CI failure

Backend source `952b5e2f`, [run 37376861819](https://github.com/RootOne1337/sphere-platform/actions/runs/37376861819):
**1 failed / 2842 passed / 30 skipped**, coverage **80,17%**. Упал только
`test_heartbeat_renews_live_owner_and_cannot_renew_expired_generation`.
После `asyncio.sleep(0.16)` значения initial/current deadline оказались одинаковыми:
`2026-10-05T21:42:56.948396Z`. Тест не дожидался результата heartbeat commit.
Frontend, Android, backend lint/security/bootstrap/RLS этого source прошли;
общий backend CI не прошёл. Успешные scoped image tests не скрывают этот failure.

Код [renewal](../../../backend/services/orchestrator/pipeline_recovery.py) получает
row lock, сравнивает owner/generation/live deadline, читает PostgreSQL clock после
lock и подтверждает RENEWED только после настоящего commit.
[Fencing](../../../backend/services/orchestrator/pipeline_ownership.py) использует
`clock_timestamp`, а не зафиксированное время начала транзакции. Этот failure не
доказывает runtime ошибку heartbeat; воспроизведена ненадёжная synchronization теста.

## Изменение и сохранённые assertions

[Тест](../../../tests/production/test_pipeline_recovery.py) сначала фиксирует initial
lease и только затем допускает первый реальный renewal. Wrapper вызывает исходный
`_renew_lease_result`, не подменяет DB result или clock. Event выставляется лишь после
RENEWED; ожидание ограничено 3 s, как и heartbeat I/O budget. Вместо fixed 160 ms
проверяется результат SQL commit. Два варианта: normal и delayed-first-renewal 250 ms.

Оба должны подтвердить: deadline строго увеличился; owner/generation сохранились;
второй recovery worker не запустил то же задание; после завершения прежний owner
не может продлить terminal lease. Реальные lock/fencing semantics не mock-ятся.
Sleep 250 ms только моделирует задержку внутри теста; он не является assertion
или production heartbeat interval. CI test timeout/coverage threshold не ослабляются.

## Проверка

Регрессия recovery + admission запускается на уже существующих dedicated audit
PostgreSQL/Redis, только loopback. Production DB, Android, туннели и контейнеры
не перезапускаются; БД не reset-ится. Новые test worlds имеют случайные tenant UUID.
**47 passed / 0 failed / 0 errors / 0 skipped**, включая оба heartbeat варианта,
на реальных audit PostgreSQL/Redis. Время pytest 40,52 s; local run сообщил 573
warnings, они не объявляются устранёнными. Local Ruff изменённого теста прошёл;
дальнейший source CI имеет отдельный статус. [Execution-file hash и counters](evidence/script-studio/pipeline-regression.json)
и [sanitized JUnit](evidence/script-studio/pipeline-regression.xml) сохранены отдельно
от failed CI исходного source и packaged Studio tests. Не суммируются повторные runs.

Это test reliability, а не закрытие production lease/recovery/load gates или всех
Studio критериев. Общий backlog остаётся **9 принято / 41 открыто**.
