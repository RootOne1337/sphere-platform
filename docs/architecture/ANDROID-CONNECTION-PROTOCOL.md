# Подтверждение подключения Android APK

**Контракт AUD-72 · 10 сентября 2026 · backend обновляется раньше APK.**

[Документация](../README.md) · [Эксплуатационная готовность](../operations/READINESS.md) ·
[APK](../android-agent.md) · [Refresh recovery](../security/device-refresh-recovery.md) ·
[Аудит](../audits/2026-09-05/AUDIT-REPORT.md)

## Когда канал считается подключённым

Открытый WebSocket подтверждает транспорт. Для `isConnected=true` APK дополнительно
должен получить от backend подтверждение авторизации **своего device ID**. До этого
отправляется только auth frame; отправка JSON-команд, результатов и видео закрыта,
входящие команды и бинарные данные не передаются исполнительному коду.

Первое сообщение APK, без credentials в URL:

```json
{"token":"<device access token>"}
```

После проверки identity, tenant, target device и активности backend закрывает
auth DB session и отправляет:

```json
{
  "type": "auth_ok",
  "device_id": "d4b781b0-6571-4e94-9183-a7c36715e7e2",
  "protocol_version": 1
}
```

`device_id` должен точно совпадать с ID текущей попытки подключения; версия — JSON
число `1`, не строка. Подтверждение не содержит токенов. Backend отправляет его
**до публикации socket в ConnectionManager**, потому что после публикации команды
могут приходить немедленно от другого producer. Ошибка/тайм-аут отправки ACK
не публикует новое соединение и не вытесняет прежний сеанс из registry.

```mermaid
sequenceDiagram
    participant A as APK
    participant B as Backend
    participant D as PostgreSQL / auth
    participant M as ConnectionManager
    A->>B: WebSocket open
    Note over A: Ожидание auth_ok; приложение ещё offline
    A->>B: token
    B->>D: Проверить identity и target device
    D-->>B: Разрешённый target
    B-->>A: auth_ok + device_id + protocol_version
    A->>A: isConnected; onConnected один раз
    B->>M: Опубликовать socket
    Note over A,B: Далее команды, heartbeat и повторная доставка результатов
```

`auth_ok` подтверждает identity в момент авторизации. Это **не** гарантия доступности
всех backend services, завершённого PubSub subscribe или сохранения результата
задания. SQL-фиксацию результата подтверждает отдельный `result_ack`; APK сохраняет
журнал до него. Server setup после auth и фактический recovery при отказах остаются
отдельными эксплуатационными проверками.

## Дедлайны, ошибки и поздние callbacks

| Событие | Поведение |
| --- | --- |
| Нет transport open или `auth_ok` | Общий дедлайн 20 s на эту WS-попытку, затем cancel и paced reconnect |
| Валидный первый ACK | Однократный `onConnected`, после которого dispatcher повторяет незавершённые результаты |
| Повторный ACK активного канала | Игнорируется, не запускает повторную отправку журнала и не попадает в команды |
| Неподходящий device/version, malformed JSON или команда/binary до ACK | Попытка завершается с protocol error; до приложения данные не доходят |
| Close 4001/4003/4004/4008 до ACK | Auth-rejection path сразу очищает access-token expiry cache; ожидание 20 s не требуется |
| Сервер закрывает канал до ACK иным кодом | Ошибка подключения и обычный backoff |
| Parent cancellation | Socket отменяется; callback от завершённой попытки не восстанавливает connected state |
| Callback во время backoff | Generation уже недействительна, данные игнорируются |
| Ошибка и поздний ACK до запуска coroutine cleanup | Первая terminal completion сохраняется; поздний ACK не делает попытку успешной |

Backend ограничивает ожидание первого auth frame 10 s, отправку `auth_ok` — 5 s.
Клиентский WS-дедлайн начинается после получения access token; [HTTP refresh](../security/device-refresh-recovery.md#тайм-аут-и-остановка-refresh-aud-71)
имеет собственный бюджет. Это не общий SLO запуска APK, DNS/диска или всего reconnect.
Существующие jitter/backoff/circuit policies сохраняются.

## Совместимость и обновление

1. Обновить **все backend workers и все потенциальные маршруты** до версии,
   отправляющей `auth_ok`. Новая миграция для AUD-72 не нужна.
2. На изолированном устройстве проверить token → корректный ACK → команды/результат,
   затем недействительный token, silent auth и reconnect.
3. Обновить APK с сохранением app data, device identity и signing identity.
4. При rollback сначала вернуть предыдущий APK; затем backend, если это требуется.

| Backend | APK | Совместимость |
| --- | --- | --- |
| С `auth_ok` | Новый | Полный контракт выше |
| С `auth_ok` | Предыдущий код APK из audit branch | Неизвестный frame отклоняется command parser с warning; прежний ранний `isConnected` остаётся до обновления APK |
| Без `auth_ok` | Новый | Канал не подтверждается и переподключается после дедлайна; автоматического обхода проверки нет |

Это необходимая часть оценки рабочего маршрута, но **резервный endpoint и
локальное discovery ещё не реализованы**. Два адреса одной установки должны
поддерживать одинаковый протокол и durable state; ACK сам по себе не создаёт HA.

## Доказательства и пределы

- [Backend baseline](../audits/2026-09-05/evidence/backend-auth-ack-before.txt):
  5 failures / 3 controls. Восемь новых ASGI cases используют реальный non-owner
  PostgreSQL auth: device/refreshed/enrollment/user credentials, reconnect,
  ordering перед публикацией, loss при отправке, foreign/inactive/invalid denial.
- [Android baseline](../audits/2026-09-05/evidence/android-auth-ack-before.txt):
  первые 12 cases — 10 failures / 2 controls. Итоговые 16 новых cases добавляют
  гонки callbacks до cleanup и binary-before-ACK. Отдельно воспроизведён
  [callback во время transport teardown](../audits/2026-09-05/evidence/android-auth-ack-cleanup-before.txt);
  generation инвалидируется до `socket.cancel()`.
- [Android XML summary](../audits/2026-09-05/evidence/android-auth-ack-summary.json):
  **378 tests / 30 suites**, без failures/errors/skips. Прежние lifecycle fixtures
  теперь подтверждают ACK, чтобы backpressure и clean-close тестировались на
  авторизованном соединении.

ASGI вызывается внутри процесса; WebSocket callbacks/доставка и Android OS
подменены. Это не APK↔listening-backend, физический телефон, 1000 клиентов, измерение
latency или подтверждение readiness PostgreSQL/Redis/сети при произвольном отказе.
