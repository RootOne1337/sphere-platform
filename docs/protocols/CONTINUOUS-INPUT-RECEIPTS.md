# Scoped подтверждения непрерывного ввода

> Исторический checkpoint receipt boundary до подключения subscribers/routes.
> Последующая [live integration](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-INTEGRATION.md)
> и [текущее состояние](../operations/CURRENT-STATE.md) описаны отдельно.

Дата: **8 октября 2026**, Asia/Yekaterinburg. Статус: **source boundary проверена
отдельно, startup/subscriptions и публичные routes ещё не подключены**.
Продолжает [владение и delivery](CONTINUOUS-INPUT-SERVER.md) и
[pointer/Kotlin приёмку](../audits/2026-10-08/CONTINUOUS-INPUT-POINTER.md).
SF26-05 остаётся OPEN; установленный3015 не включает continuous mode.

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

Проверка local snapshot не заменяет fresh auth/topology lifecycle caller.
Будущая route integration обязана обработать replacement/disconnect между
workers, permission revocation и callback lifetime. Настоящий JWT/RBAC handler
или глобальная online-session topology этим компонентом **не проверены**.

## Атомарность и неизвестные исходы

[Статический Lua](../../backend/websocket/continuous_lease.py) выполняет одним
EVAL state transition и PUBLISH, без fallback/retry:

Будущий handler вызывает `relay_native_receipt` один раз. Он не должен сначала
вызвать старый local transition `store.receipt`, а затем повторить тот же READY
через relay: преждевременный transition уже выведет owner из opening_sent.

| Native receipt | Изменение authority |
| --- | --- |
| STARTUP0 injector | Opening_sent → ready только при свежем auth lease |
| INPUT1/2/3 | Observation; не создаёт ready/release, sequence не выше опубликованной |
| Failure4/5/6 | Fence closing; нет автоматического takeover |
| RELEASE3 injector | Exact owner key удаляется; known release публикуется тем же Lua |
| RELEASE6 | Key остаётся, phase closing |
| Нет viewer subscriber | Admission closing, без offline queue/replay |
| Future/невозможный native input sequence | Fence без публикации невозможного успеха |

PUBLISH>0 означает наличие подписчика, не browser delivery. Pub/Sub outage,
viewer send failure или callback loss должны завершаться отдельным caller fence.
Бюджеты сохранены: Redis/socket250ms, message2048B, доставка500ms, lease/auth1500ms,
dedicated pool8/Retry0. Receipt deadline в браузере —500ms. Нет persistent
receipt history, Redis Streams, org broadcast, frame storage или task-per-receipt.

При timeout/cancellation после возможной публикации helper делает одну bounded
fence attempt, не повторяет receipt publication. Cancellation возвращается
caller. Outage или повторная cancellation могут помешать fence; TTL и native
watchdog остаются обязательными. Authority key expiry **не доказывает** native
release. Если identity уже исчезла до обработки позднего RELEASE, helper
отвергает его: исторический owner из Redis заново не создаётся. Следующая
интеграция должна явно решить known-reset/release reconciliation, не объявлять
expired key доказательством cleanup.

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

Следующий обязательный шаг: один bounded receipt/agent subscriber на worker,
startup/shutdown cleanup, transient probe offer и callback registry с limits,
fresh authorization/revocation, затем viewer route и DeviceStream/Recorder.
Окончательная приёмка — реальный browser→server→APK→render, known reset и
local/remote latency/resource soak. Наличие helper не закрывает эти условия.
