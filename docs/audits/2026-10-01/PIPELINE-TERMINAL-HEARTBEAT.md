# Pipeline: heartbeat после commit терминального результата

Дата: **1 октября 2026**, Asia/Yekaterinburg. Исходная проверка:
[backend CI ae4caf3 / 36854056782](https://github.com/RootOne1337/sphere-platform/actions/runs/36854056782).
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

## Подтверждённая проблема

В CI упал `test_heartbeat_renews_live_owner_and_cannot_renew_expired_generation`:
`CancelledError` при выходе из SQL session. В том прогоне **2134 passed / 15 skipped /
1 failed**. Прежний зелёный прогон не исключал эту гонку.

После commit последнего step статус уже COMPLETED или FAILED, однако coroutine
runner ещё закрывает SQL session. Heartbeat прежнего владельца видел `False`
от `renew_lease()` для терминального статуса и отменял worker. Это ошибочно
приравнивало собственный сохранённый результат к потере lease.

## Контракт исправления

В `backend/services/orchestrator/pipeline_recovery.py` внутренний результат renewal
теперь различает RENEWED, FINISHED и LOST. FINISHED допустим только для того же
owner/generation, терминального статуса и сохранённой границы вне `in_flight`.
Heartbeat завершается без отмены такого worker. Публичный `renew_lease()` сохраняет
bool-контракт: терминальный run по-прежнему не получает продление.

Чужой owner, новая generation, отменённый `in_flight`, ошибка БД и timeout
продолжают отменять локальный worker. Исправление не создаёт FAILED, не повторяет
Android-команду и не утверждает, что Android прекратил уже отправленное действие.
Схема БД и миграции не меняются.

## Доказательства и ограничения

- Два новых SQL regression tests задерживают cleanup **после фактического commit**,
  затем запускают heartbeat через события: success и failure. На прежнем коде оба
  воспроизводят `CancelledError`; таймауты теста не увеличены для обхода сбоя.
- Три отрицательных SQL сценария подтверждают, что terminal status не освобождает
  foreign owner, replacement generation и cancelled in-flight worker от fencing.
- Изолированный PostgreSQL: recovery + cancel-intent + admission — **58 passed**.
  Ruff и mypy исправленного модуля прошли. Тестовая БД отделена от работающего pilot.
- Полный CI 68155c1: **2139 passed / 15 skipped / 1 failed**. Единственный failure
  — RLS test, который наблюдал прежний bool renewal hook вместо нового внутреннего
  результата heartbeat. Test hook обновлён, с явной проверкой двух RENEWED и
  запретом LOST. Таймаут не увеличен; RLS policy и runtime права не ослаблены.
  Локальный повтор recovery + cancel-intent + admission + RLS: **71 passed**,
  с настоящей non-owner PostgreSQL role и повторной tenant binding после commit.
- Это исправление оркестратора; оно не доказывает причину remote video gaps.
  Установка текущего кода в runtime и полный CI фиксируются отдельно в
  [CURRENT-STATE](../../operations/CURRENT-STATE.md).
