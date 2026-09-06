# Доступ к credentials игровых аккаунтов

Обновлено 6 сентября 2026. Это описание текущей защиты и её границ, не sign-off
всего потока secrets. Findings: AUD-31 и AUD-32 в audit report.

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

## Хранение и использование

Новые create/update/import и auto-registration шифруют пароль **до flush** в
`GameAccount.password_ciphertext`. Используется Fernet из установленного пакета
cryptography; authenticated JSON envelope version 1 содержит пароль и UUID
организации/аккаунта. Расшифровка проверяет обе идентичности: копирование токена
в другую строку/tenant отклоняется. Старый `password_encrypted` очищается в той же
транзакции; CHECK запрещает непустой legacy столбец вместе с ciphertext.

`ACCOUNT_CREDENTIAL_KEYS` — от 1 до 8 независимых Fernet keys через запятую,
новый ключ первым. Первый шифрует, остальные позволяют читать старые записи.
Храните набор в secret manager отдельно от БД, JWT и VPN ключей. Приложение не
генерирует постоянный ключ на startup и не использует JWT как fallback.
Поле Settings имеет SecretStr, но окружение контейнера доступно администраторам
хоста; это не интеграция с KMS/HSM. Семантика key ring соответствует
[MultiFernet](https://cryptography.io/en/latest/fernet/).

Без ключа, при неверном ключе/повреждённом токене/неподдерживаемом envelope или
legacy строке раскрытие возвращает общий 503. Обычные metadata reads работают.
Dispatch не публикует команду и сохраняет задачу для повторной попытки; plaintext
fallback отсутствует. Для валидной записи decrypt выполняется только при reveal
или построении account variables для DAG. В команду идёт исходный пароль,
а не encryption token; в новые task input_params он не копируется.

## Первичное включение и перенос

Это **maintenance rollout**: остановите API account writers, orchestrator и task
dispatch, включая старые версии. Не включайте смешанный old/new rollout.
Подготовьте защищённую резервную копию и проверьте восстановление БД вместе с
ключами. Потеря последнего подходящего ключа означает потерю доступа к паролям.
Автогенератор прежних JWT/DB secrets не создаёт этот key ring; provision его
отдельно. Не запускайте генератор всех secrets для обновления работающей системы.

1. Настройте `ACCOUNT_CREDENTIAL_KEYS` из secret store для нового backend и
   отдельного maintenance process. Не передавайте реальные ключи в CLI arguments,
   историю shell, PR, логи или Git. Compose full/production передают эту переменную.
2. Примените schema migration `20260906_account_ciphertext` из новой ревизии:
   `python -m alembic -c alembic/alembic.ini upgrade head`.
   Она добавляет nullable ciphertext и сохраняет старые значения; сама secrets
   не переносит и ключей не требует.
3. Выполните проверку, перенос, затем повторную проверку командами ниже.
   CLI поставляется в backend image, запускается из `/app` с теми же settings.
   Используйте maintenance DB role, видящую все нужные организации. Сопоставьте
   scanned с заранее известным количеством аккаунтов; нулевой результат или
   неполная видимость RLS не доказывают полный перенос.
4. Возобновляйте новый backend только после zero legacy и успешной проверки всех
   токенов. Контролируемо проверьте reveal и один account task. Старые writers
   после этого запускать нельзя.

```bash
# Default — только проверка, без изменения строк.
python -m backend.cli.account_credentials
# Перенос: независимые транзакции не более 200 строк (настраивается 1..1000).
python -m backend.cli.account_credentials --apply --batch-size 200
python -m backend.cli.account_credentials
```

`--org-id <UUID>` ограничивает scope; проверка одной организации не является
sign-off всей БД. Exit 0 означает успешное завершение указанного режима/scope,
1 — read-only проверка нашла legacy, 2 — ошибка, 130 — прерывание.
Вывод содержит только счётчики и scope, без ключей, паролей или SQL parameters.
Каждая успешная пачка коммитится; при ошибке текущая пачка откатывается,
предыдущие сохраняются. Если подтверждение commit потерялось в сети, исход пачки
неизвестен: после восстановления повторите скан с начала. Уже перенесённые строки
проверяются и не шифруются повторно обычным `--apply`. Старые строки определяются
по NULL нового столбца, а не по похожему на ciphertext префиксу пароля.

## Смена ключа и rollback

Во время остановки writers добавьте новый ключ первым, сохранив старые ключи
в key ring. Выполните `python -m backend.cli.account_credentials --apply --rotate`,
затем проверьте весь scope с **одним новым ключом**. Только после этого удаляйте
старые ключи из рабочих процессов. Отдельно сохраняйте необходимые старые ключи
для зашифрованных backups согласно retention policy. Rotation повторно шифрует
аутентифицированное значение; прерванный прогон безопасно запускается заново.

Downgrade schema запрещён, если есть хотя бы одна encrypted строка: миграция не
удаляет ciphertext и не возвращает plaintext автоматически. План rollback —
совместимая ревизия либо согласованное восстановление БД и её ключей, а не слепой
`alembic downgrade`. Корректность production restore ещё не подтверждена.

## Остаточные риски

Перенос очищает текущую строку, но не уничтожает plaintext в старых backups,
WAL, MVCC/dead tuples, выгрузках и уже полученных копиях. Доступ к БД вместе с
ключом или к памяти работающего backend позволяет получить пароль. Компрометация
ключа требует отдельной оценки смены самих игровых паролей, а не только rewrap.
Envelope защищает от подмены идентичности, но не от replay старого ciphertext
для того же аккаунта привилегированным DB writer.

Общий audit middleware логирует только mutating HTTP methods. Отдельный
долговечный журнал reveal GET, retention/redaction, credential-bearing task DAG/cache,
frontend query cleanup и весь поток export ещё требуют проверки.

AUD-33 устраняет подтверждённую запись raw/encoded пароля из Android `typeText`
в Timber. File logger активен и в release, его содержимое включается в uploads.
После обновления старые файлы/серверные копии не исчезают: обработайте их по
согласованной retention policy и оцените смену затронутых паролей. Остальные
action outputs и диагностические источники этим изменением не сертифицируются.

Regression suite `tests/production/test_account_credentials.py` использует
реальную JWT/RBAC авторизацию, изолированный PostgreSQL и ASGI API; проверяет
запрещённые/разрешённые роли, no-store, обычное чтение и tenant boundary.
`test_account_secret_storage.py` проверяет все четыре writers и dispatch;
`test_account_credential_migration.py` — реальные SQL transactions, отказ commit,
cancel, restart, CLI и rotation; `test_account_schema_migration.py` — upgrade/check/
downgrade в rollback schema. `tests/test_account_cipher.py` — tampering, binding
и key-ring contract. Реальный APK runtime этими тестами не подтверждается.
