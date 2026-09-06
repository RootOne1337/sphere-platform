# Доступ к credentials игровых аккаунтов

Обновлено 6 сентября 2026. Это описание текущей защиты и её границ, не sign-off
хранения secrets. Связанный finding: AUD-31 в audit report.

Обычный `GET /api/v1/game-accounts/{id}` требует `account:read` и не возвращает
поле password. Параметр `show_password=true` дополнительно требует отдельного
права `account:credentials:read`: оно дано org_admin, org_owner и super_admin.
Viewer, script_runner и device_manager получают 403 при запросе раскрытия.
Проверка org_id в service сохраняется; даже разрешённая роль не читает пароль
аккаунта другой организации. Право account:write само по себе не разрешает reveal.

Ответ с credentials имеет `Cache-Control: no-store`. Это указание HTTP caches,
а не удаление уже полученных копий из памяти клиента, browser extension, logs
или файлов экспорта. Вызывающие клиенты не должны сохранять пароль в длительном
query cache и обязаны очищать свои данные при смене пользователя/организации.

Текущий endpoint принимает пользовательский JWT через get_current_user. Наличие
нового имени permission в scope catalog не добавляет API-key authentication этому
маршруту. Автоматизация получает необходимые данные через отдельный task/device
контракт; этот API-fix не ограничивает все косвенные способы доступа оператора,
которому уже разрешено создавать и выполнять произвольные скрипты.

## Что ещё не исправлено

`GameAccount.password_encrypted` пока хранит входную строку без шифрования на
уровне приложения. Имя столбца не является гарантией encryption. Нужны отдельный
управляемый ключ, versioned storage format, безопасная миграция существующих
значений, rotation и проверка всех потребителей task/account credentials.

Общий audit middleware логирует только mutating HTTP methods. Отдельный
долговечный журнал reveal GET, retention/redaction, credential-bearing task DAG/cache,
frontend query cleanup и весь поток export ещё требуют проверки.

Regression suite `tests/production/test_account_credentials.py` использует
реальную JWT/RBAC авторизацию, изолированный PostgreSQL и ASGI API; проверяет
запрещённые/разрешённые роли, no-store, обычное чтение и tenant boundary.
