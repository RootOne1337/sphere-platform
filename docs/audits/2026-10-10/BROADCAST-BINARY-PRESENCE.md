# Broadcast: две причины HTTP 500

Дата отчёта: 10 октября 2026, UTC+5. Фактический срез логов и HTTP:
9 октября 20:56:58 UTC. Статус этого отчёта: SOURCE_FIXED_NOT_INSTALLED.
Действующая установка при подготовке: UI d70f55c6 / API 9ad3481c.

## Доказанный дефект

Пользователь сообщил HTTP 500 на публичном `POST /api/v1/batches/broadcast`.
Ограниченный просмотр backend logs подтвердил пять ошибок 9 октября UTC:
20:40:12.100826, 20:40:17.350319, 20:40:27.736985, 20:40:40.599031,
20:41:07.052794. Request ID последней: `c7f8158c`.

Путь: batches router → BatchService.broadcast_batch → DeviceStatusCache.bulk_get_status
→ Redis MGET → текстовое декодирование. Значения presence хранятся в MessagePack;
текстовый Redis-клиент пытается декодировать первый байт `0xde` как UTF-8 и вызывает
UnicodeDecodeError до проверки отдельных записей. Ошибка возникает до start_batch
и commit: эти traceback не свидетельствуют о создании пяти батчей.

Второй дефект найден в ответе: BroadcastBatchResponse требует online_devices,
но прежний router вызывал model_validate(batch) перед присваиванием этого поля.
Отдельный тест воспроизвёл ValidationError даже при корректном результате service.
В этой ветви service уже мог сохранить план; исправление только Redis оставило бы
возможность HTTP 500 после commit и опасность ручного повторного запуска.

## Исправление

- BatchService использует существующий redis_binary с decode_responses=False.
- Router передаёт online_devices при создании BroadcastBatchResponse; базовые поля
  по-прежнему проверяет BatchResponse. ORM и обязательность поля не ослаблены.
- Комментарии Redis-клиентов исправлены: MessagePack требует бинарного клиента.
- Доставка допускает только три проверенных backend файла дополнительно к прежнему
  allowlist; dependency/action-contract hashes и запрет прочих packaged изменений сохранены.

HTTP 202 подтверждает сохранённый план. Создание отдельных задач выполняет admission
worker; фактическое исполнение Android этим ответом не подтверждается.
Tenant, RBAC, выбор active/online устройств, версия сценария и worker не изменены.

## Проверки исходников

Красный прогон отдельно воспроизвёл UnicodeDecodeError и отсутствие online_devices.
После исправления: 60 focused pytest tests прошли — broadcast, batch service,
lifecycle, device status. Проверены online/busy/offline/missing/corrupt presence,
исключение чужого tenant и inactive устройства, сохранённый план и отсутствие
admission при HTTP 409. Отдельный тест изолирует валидацию успешного ответа.
Ruff и mypy изменённых executable backend файлов прошли.
64 reviewed-delivery unittest tests прошли, включая rejection unreviewed worker
и несовпадающего dependency hash.

Добавлена проверка настоящих PostgreSQL/Redis в tests/production:
двоичный presence, реальная авторизация, HTTP 202, чтение commit из другой сессии,
точный tenant/version/target и последующее создание одной задачи admission worker.
Локально она не запускалась; required exact-source CI и доставка ещё впереди.
Рабочие устройства не использованы для пробного массового запуска.

## CSS предупреждение

Указанный пользователем `599369d853c61df7.css` доступен на 3015 и публичном host:
HTTP 200, text/css, 15772 bytes, SHA-256
`dae1c1338c9a6d70787063786e64b9ffe238de67379ad80f2827c60aa90fddd1` на обоих.
Текущий SSR /scripts ссылается на другие stylesheet chunks; его CSS preload имеет
as=style. Это исключает повреждение проверенных байтов, но не объясняет окончательно
предупреждение после клиентского перехода. Визуальная/console проверка остаётся.
Next preload не отключался без доказательства причины.

## Остаток и границы

Не закрыты: HTTP idempotency/reconciliation при потере ответа; unknown Redis
availability против подтверждённого отсутствия online; admission limit больших
парков; pinned expected-version в broadcast UI. Эти пункты требуют самостоятельных
контрактов и тестов. Product 9/41 и legacy 7 этим локальным исправлением не меняются.
Idle receipt timeout, прямой media/input и APK 1.3.0 не приняты.

Private diagnostic slice: .local-pilot/direct-probe-20261010/broadcast-before.json.
Он содержит ограниченные ошибки и HTTP fingerprints, не является общедоступным
или автоматически обновляемым evidence. Исторический отчёт после установки
не переписывается; результат доставки должен получить отдельный receipt.

## Исходники и действующие указатели

- [Batch service](../../../backend/services/batch_service.py)
- [Router](../../../backend/api/v1/batches/router.py)
- [Binary presence tests](../../../tests/test_services/test_batch_broadcast.py)
- [PostgreSQL/Redis test](../../../tests/production/test_batch_broadcast.py)
- [Текущий статус](../../operations/WORK-STATUS.md)
