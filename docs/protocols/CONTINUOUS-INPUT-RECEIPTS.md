# Scoped подтверждения непрерывного ввода

## Подключение в исходниках и историческая сверка 9 октября

Контракт подключён в [startup](../../backend/websocket/startup.py) и
[ContinuousRuntime](../../backend/websocket/continuous_runtime.py), включая
relay_native_receipt и scoped delivery. На проверенном стенде API `be803773` и PH011/APK10249
имели конечную [live приёмку](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-ACCEPTANCE.md).
Обычный viewer посылает MOVE до UP; recording сохраняет дискретный swipe.
Idle native_receipt_timeout и общий арбитраж viewer/task/API в том срезе оставались открытыми.
Текущую установку и остаток проверяйте отдельно: [CURRENT-STATE](../operations/CURRENT-STATE.md),
[WORK-STATUS](../operations/WORK-STATUS.md).

## Исторический компонентный checkpoint до integration

> Исторический checkpoint receipt boundary до подключения subscribers/routes.
> Последующая [live integration](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-INTEGRATION.md)
> и [текущее состояние](../operations/CURRENT-STATE.md) описаны отдельно.

Дата исторического checkpoint: **8 октября 2026**, Asia/Yekaterinburg. Статус: **source boundary проверена
отдельно, startup/subscriptions и публичные routes ещё не подключены**.
Продолжает [владение и delivery](CONTINUOUS-INPUT-SERVER.md) и
[pointer/Kotlin приёмку](../audits/2026-10-08/CONTINUOUS-INPUT-POINTER.md).
На этом checkpoint SF26-05 оставался OPEN, а тогдашний установленный3015
не включал continuous mode; последующая интеграция указана выше.

## Проблема и поведение

APK socket и viewer могут принадлежать разным HTTP workers. Injector STARTUP,
INPUT и RELEASE нельзя рассылать всей организации, заменять фактом socket send
или доставлять новому viewer после исчезновения прежнего. Новый
[receipt boundary](../../backend/websocket/continuous_receipts.py) пересылает
один проверенный ответ на `input:continuous:v1:viewer:<viewer_worker>`.
Внутренний envelope несёт **полную immutable identity**, срок и исходный JSON
native receipt. Получающий worker проверяет **собственный** worker ID и точный
локальный InputLease. Он не выбирает другой callback по owner из входа.

`relay_native_receipt` получает agent_session из authenticated Android handler.
Проверены in-process ConnectionManager snapshot, device, tenant, Android type
и session; после Redis lookup они проверяются снова. Tenant/socket metadata
не извлекается из native JSON. Scope существующего Redis owner тоже должен
совпасть. Wrong owner/viewer session/epoch не меняет состояние и не освобождает
device. Замена owner между lookup и Lua operation закрыта identity CAS.

Проверка local snapshot сама по себе не заменяет fresh auth/topology lifecycle
caller. В текущем source [stream router](../../backend/api/ws/stream/router.py)
проверяет права и состояние устройства, а
[runtime](../../backend/websocket/continuous_runtime.py) управляет viewer lifetime
и пересылает scoped receipts. Это не подтверждает текущий runtime и не доказывает
общий exactly-once ввод; см. [границы server protocol](CONTINUOUS-INPUT-SERVER.md).

## Атомарность и неизвестные исходы

[Статический Lua](../../backend/websocket/continuous_lease.py) выполняет одним
EVAL state transition и PUBLISH, без fallback/retry:

Текущий runtime вызывает `relay_native_receipt` для сообщения один раз. Он не должен сначала
вызвать старый local transition `store.receipt`, а затем повторить тот же READY
через relay: преждевременный transition уже выведет owner из opening_sent.

| Native receipt | Изменение authority |
| --- | --- |
| STARTUP0 injector | Opening_sent → ready только при свежем auth lease |
| INPUT1/2/3 | Наблюдение действия/heartbeat; не создаёт ready/release. Для relay sequence не выше опубликованной; direct имеет отдельный транспорт |
| Startup5 от admission до native owner | При подтверждённом pre-owner refusal exact key удаляется; это отказ, не STARTUP0 и не RELEASE3 |
| Другие Failure4/5/6 | Fence closing; нет автоматического takeover |
| RELEASE3 injector | Exact owner key удаляется; known release публикуется тем же Lua |
| RELEASE6 | Key остаётся, phase closing |
| Нет viewer subscriber | При ещё существующем matching authority — closing; без offline queue/replay. Для уже удалённого key это не подтверждает доставку cleanup |
| Future/невозможный native input sequence | Fence без публикации невозможного успеха |

PUBLISH>0 означает наличие подписчика, не browser delivery. Pub/Sub outage,
viewer send failure или callback loss должны завершаться отдельным caller fence.
Бюджеты сохранены: Redis/socket250ms, message2048B, доставка500ms, lease/auth1500ms,
dedicated pool8/Retry0. В текущем browser controller deadline обычного action —
500ms, idle heartbeat и shared action — 1250ms, startup — 8000ms. Это разные
ограничения ожидания, не обещание доставки или physical execution. Нет persistent
receipt history, Redis Streams, org broadcast, frame storage или task-per-receipt.

При timeout/cancellation после возможной публикации helper делает одну bounded
fence attempt, не повторяет receipt publication. Cancellation возвращается
caller. Outage или повторная cancellation могут помешать fence; TTL и native
watchdog остаются обязательными. Authority key expiry **не доказывает** native
release. После известного `close` предусмотрен отдельный cleanup route: до 30s,
не более восьми записей на device. Он может передать только точный authenticated
RELEASE3 прежнему viewer после истечения authority, не восстанавливая её и не
изменяя нового owner. Без подходящего route, при его истечении или иных identity/
session receipt отвергается; наличие route не гарантирует доставку в браузер.

Отдельно `touch_close` с `cancel_unstarted: true` может получить `touch_cancelled`
только когда atomic delivery claim подтверждает, что отправка OPEN в APK socket
ещё не началась. Это доказательство отсутствия начатой доставки, не native ACK;
потерянный ответ Redis или отсутствие STARTUP сами по себе такого доказательства
не дают. При неизвестной очистке сохраняется fence/неопределённость.

Known RELEASE удаляет key до публикации. Поэтому `viewer_receipt` сопоставляет
ответ с точным локальным lease, а не заново ищет отсутствующий key. Expiry
проверяется по Redis TIME; время Android используется только как device uptime.
Foreign worker/identity, extra fields, malformed JSON, oversize и expired/future
envelopes отклоняются. Этот helper возвращает один native message, не отправляет
его в socket и не выдаёт permission grant.

## Точность Android uptime

Lua cjson по умолчанию может округлять большие JSON numbers. Сравнение stage/
status/31-bit sequence выполняется в Lua, но native message пересылается как
**receipt_json string**. Python восстанавливает исходные integers; приёмка
подтвердила точный roundtrip **9007199254740991** через реальный Redis. Вложенное
escaping учтено в2048B budget до EVAL. Global cjson precision не изменялась.
Это транспортная точность, не синхронизация clocks браузера/сервера/Android.

## Проверки и runtime граница

**34 новых cases**; полный leaf набор стал **130 distinct cases**:
44 protocol и86 lease/delivery/receipt. Одни и те же130 прошли в fakeredis Lua
и реальном Redis, не260 разных случаев. Есть атомарный READY/release, отсутствие
subscriber, unknown cleanup, foreign scope, replacement/mutation во время await,
max uptime, expiry, auth loss, unknown publication/cancellation без replay,
malformed viewer envelope и clock timeout. Ruff и mypy прошли.

Все real Redis keys/channels принадлежат random audit namespace и fixture
device IDs; cleanup только exact keys, TTL1500ms. Source тестируется во временном
отдельном pytest process существующего backend container с shipped dependencies.
Рабочие application files/image/process не заменялись; временный каталог удалён.
ConnectionManager настоящий, sockets mock; Android команд нет.

[Sanitized evidence и hashes](../audits/2026-10-08/CONTINUOUS-INPUT-RECEIPTS-EVIDENCE.json).
CI browser sourcea979bc9 подтвердил все четыре runs: frontend, preview,
Android и backend. Новые receipt changes требуют собственного exact CI.
Ни UI/API deploy, ни рабочий APK install этим этапом не выполнялись.

На историческом checkpoint следующим шагом были один bounded receipt/agent subscriber на worker,
startup/shutdown cleanup, transient probe offer и callback registry с limits,
fresh authorization/revocation, затем viewer route и DeviceStream/Recorder.
Окончательная приёмка — реальный browser→server→APK→render, known reset и
local/remote latency/resource soak. Наличие helper не закрывает эти условия.

## Граница source-сверки

1 ноября 2026 сопоставлены [receipt helper](../../backend/websocket/continuous_receipts.py),
[lease](../../backend/websocket/continuous_lease.py), [runtime](../../backend/websocket/continuous_runtime.py),
[browser controller](../../frontend/src/features/stream/continuousPointer.ts) и
[Android supervisor](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousTouchSupervisor.kt).
Примеры regressions: [lease tests](../../tests/test_ws/test_continuous_lease.py) и
[runtime tests](../../tests/test_ws/test_continuous_runtime.py). Исторические
результаты выше не повторялись; реальный ввод, сети и устройства не проверялись.
