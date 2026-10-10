# Непрерывный ввод: серверный контракт владения и доставки

## Действующее подключение, сверка 9 октября

Контракт подключён в [startup](../../backend/websocket/startup.py) и
[ContinuousRuntime](../../backend/websocket/continuous_runtime.py), включая
relay_native_receipt и scoped delivery. Установленный APIbe803773 и PH011/APK10249
имеют конечную [live приёмку](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-ACCEPTANCE.md).
Обычный viewer посылает MOVE до UP; recording сохраняет дискретный swipe.
Idle native_receipt_timeout и общий арбитраж viewer/task/API остаются OPEN.
[Текущий остаток](../operations/WORK-STATUS.md).

## Исторический компонентный checkpoint до integration

> Исторический checkpoint отдельного компонента до подключения routes.
> Последующая [live integration](../audits/2026-10-08/CONTINUOUS-INPUT-LIVE-INTEGRATION.md)
> и [текущее состояние](../operations/CURRENT-STATE.md) имеют отдельные результаты.

Дата исторического checkpoint: **8 октября 2026**, Asia/Yekaterinburg. Статус: **проверенный отдельный
source-компонент; не подключён к установленным WebSocket routes**. SF26-05
остаётся OPEN; текущий веб3015 отправляет завершённый gesture после pointerup.

Продолжение [APK lifecycle](../audits/2026-10-07/CONTINUOUS-INPUT-APK-LIFECYCLE.md)
и [capture frame v2](VIDEO-CAPTURE-V2.md). Результаты этого этапа:
[evidence](../audits/2026-10-08/CONTINUOUS-INPUT-SERVER-EVIDENCE.json).

## Проблема и результирующее поведение

Общий Redis-клиент приложения настроен на `retry_on_timeout=True`, socket
timeout5s и pool50. Для live touch такой повтор может исполнить прежний ввод
ещё раз после неизвестного результата. Обычный command router также отправляет
сообщение текущему устройству, не сохраняя конкретный APK socket prepared
команды. Новый компонент отделяет эти границы от legacy команд.

Он принимает DOWN/MOVE/UP отдельными публикациями: MOVE не ждёт последующего
UP. Redis обеспечивает одного continuous owner для device между workers.
Команда связана с server-issued nonce, tenant/user, viewer worker/session,
APK socket session и capture epoch/size. Отправка до STARTUP0 от APK запрещена;
факт Redis publication или завершения socket send readiness не создаёт.

Ни startup hook, ни subscription, ни permission grant, ни browser endpoint
этим компонентом не добавлены. Runtime capability остаётся выключена. Его
нельзя вызвать из браузера через существующий discrete protocol.

## Доверие и последовательность подключения

1. Viewer route проверяет действующий JWT, user/org/device ownership и RBAC.
   Он формирует `LeaseBinding` из доверенных server identities. Поля owner,
   user, org, worker и APK session не принимаются от браузера.
2. Browser `touch_open` передаёт только epoch и размер **показанного** кадра.
   До acquire route обязан сопоставить их с текущим APK offer и успешно
   rendered v2 frame; совпадение размеров само по себе недостаточно.
3. Store генерирует случайный owner32hex и атомарно приобретает device key.
   Busy не заменяет прежнего владельца. Даже re-tenanting device использует
   тот же глобальный key, а не два независимых ключа разных организаций.
4. Open публикуется один раз. APK handoff/helper startup выполняются отдельно;
   до соответствующего STARTUP0 разрешён только idle heartbeat.
5. APK receipt проверяется с socket session **из authenticated handler**,
   owner, viewer session и capture epoch. Только injector STARTUP0 разрешает
   движения. INPUT1 означает dispatcher acceptance, не displayed frame.
6. Receiver перед socket send проверяет lease, tenant/device/session, schema
   и срок команды. Затем использует `send_to_session` с тем же captured ID.
   Замена соединения во время Redis await не получает старую команду.
7. На завершении закрывается admission. Close может отправить одну отмену
   даже после auth expiry/fence. Key удаляется раньше TTL только по проверенному
   injector RELEASE3; неизвестный RELEASE6 оставляет fence.

Это требования к следующему route integration. Текущие routes эти операции
**ещё не вызывают**. Создание binding в unit test не проверяет настоящие JWT/RBAC.

## Wire boundaries

[continuous_protocol.py](../../backend/websocket/continuous_protocol.py) выдаёт
immutable objects, отвергает лишние identity fields, bool/float/string вместо
JSON integers, nil/noncanonical UUID и несуществующие actions.

| Browser message | Допустимые поля кроме type |
| --- | --- |
| `touch_open` | capture_epoch, frame_width, frame_height |
| `touch_event` | sequence, gesture, action, x, y |
| `touch_close` | отсутствуют |

Action0/1/2/3/4 = DOWN/UP/MOVE/CANCEL/HEARTBEAT, как в APK canary. Sequence
1…2147483647 возрастает; пропуски допускаются, повтор и обратный порядок
останавливают owner. Gesture0 допустим только для idle heartbeat. Остальные
gesture1…2147483647: DOWN создаёт новый, MOVE/terminal принадлежат текущему,
повтор закрытого gesture запрещён. Координаты frame проходят проверку без clamp.
Ширина/высота1…16384; точка на width/height уже за пределом. Physical mapping
остаётся у APK CaptureInputSession.

Gesture ограничен31битами также для точности Lua cjson: native Long или
JavaScript safe integer сами по себе не доказывают точный JSON roundtrip через
cjson. Maximum2147483647 проверен на реальном Redis. Device uptime имеет
отдельный safe integer bound и не участвует в server lease clock.

Внутренний envelope `_continuous_input_v1` содержит canonical identity,
`expires_at_ms` и одну проверенную native command. Никаких произвольных shell,
metadata passthrough или offline queue. Receiver проверяет текущий scope и
исходный набор native fields; internal JSON не может заменить identity socket.

## Сроки, ограничения и неизвестный результат

| Предел | Значение / смысл |
| --- | --- |
| Lease | 1500ms с последнего принятого open/event |
| Authorization | 1500ms после отдельной свежей проверки caller |
| Delivery age | 500ms, часы Redis TIME |
| Redis operation/socket send | 250ms на одну попытку каждого этапа |
| Redis pool | не более8 connections на worker |
| Envelope | не более2048 UTF-8 bytes |
| Stored state | один короткий hash device, TTL1500ms, без trajectories/frames |

Event обновляет lease, **не authorization**. Отдельный `authorize` обновляет
auth, **не lease**: серверная проверка прав не удерживает умерший viewer.
После обнаруженного expiry/failure owner нельзя resurrect. Отсутствующий key,
Redis restart или TTL не доказывают завершение Android helper; native watchdog
и ownership/fence остаются независимыми обязательными границами.

[continuous_lease.py](../../backend/websocket/continuous_lease.py) создаёт
dedicated pool с Retry0 и отклоняет существующий реальный Redis-клиент, если
его retry/timeout/pool не соответствуют контракту. URL query options запрещены,
чтобы `from_url` не переопределил эти kwargs. Проверка private retry count
привязана к shipped redis-py5.0.3; несовместимое обновление должно отказать
закрыто и пройти новую проверку, а не молча включить retry.

Lua script статичен, значения идут аргументами. Acquire, state transition и
PUBLISH проверяются атомарно одним Redis. Используется EVAL без повторяющего
fallback; dynamic scripts, persistent event lists, Streams и task-per-MOVE
не добавлены. Subscriber count >0 означает лишь наличие подписчика. Ноль
закрывает admission; uncertain Redis result не повторяется и не считается успехом.

[continuous_delivery.py](../../backend/websocket/continuous_delivery.py) даёт
раздельные `rejected`, `socket_sent`, `unknown`. Failed/timed-out send делает
одну bounded fence attempt, без повторного ввода. Cancellation после начала
write также пытается fence и затем сохраняет cancellation для caller. Повторная
cancellation/Redis outage может помешать fence; в этом случае TTL/watchdog
остаются последней защитой, известное native освобождение не заявляется.

Redis hash metadata может попадать в AOF/replication в соответствии с политикой
Redis. «Нет истории trajectories» не означает нулевые disk writes; перед live
soak нужны текущие AOF/rewrite/retention и resource checks. PUBLISH не превращается
в durable replay. Этот контракт рассчитан на **одну Redis authority**; Redis
Cluster, split brain/failover и глобальное exactly-once исполнение не заявлены.

Основание атомарности: [официальный Redis Lua contract](https://redis.io/docs/latest/develop/programmability/eval-intro/).
Смысл ответа publication: [официальный PUBLISH](https://redis.io/docs/latest/commands/publish/).

## Проверка и открытая приёмка

**96 различных новых cases**:44 protocol и52 lease/delivery. Они прошли в
fakeredis Lua и на настоящем Redis; это два исполнения одних96 cases, не192
различных сценария. Настоящий Redis использовал random `audit:continuous:<uuid>`
namespace, собственные device fixture IDs, TTL и cleanup только exact keys.
Не выполнялись database flush, scan, SQL, команды Android или agent channels.
Source временно загрузили в отдельный pytest process существующего backend
container с shipped dependencies; application files/image/process не заменялись.
Временный каталог удалён при завершении. Socket tests используют mocks и настоящий
ConnectionManager; это **не живая доставка команды APK**.

Проверены20 competing acquisitions, global re-tenanting exclusion, неготовый
инжектор, движение до UP, foreign bindings, repeated sequence/gesture, heartbeat,
auth/lease separation, expiry, old receipts, known/unknown release, socket
replacement, неправильный tenant/device/PC, malformed envelopes, stale/future
clock, no subscribers, timeout, cancellation и refusal retrying pool. Первая
real проверка выявила неверное ожидание fixture, что20 запросов обязаны вместиться
в8 connections; исправление учитывает отказ overload и ждёт все попытки до cleanup.
Лимит pool и отсутствие retry сохранены.

Ruff/mypy прошли. Exact server source0a8cd9 затем прошёл все четыре hosted
runs: Android, frontend, backend и preview. Backend3268passed/37skipped/
229subtests, frontend1753tests/136suites плюс types/build; точные run URLs
сохранены в evidence followup. Предыдущий frame source3dc2456 прошёл Android
push/PR, frontend, backend и preview:
[точная приёмка предыдущего source](../audits/2026-10-08/VIDEO-CAPTURE-V2-CI.json).

Следующая поставка должна подключить subscriptions и transient scoped receipts
между workers; fresh authorization cadence/revocation; DAG/manual exclusion
на сервере; failure/shutdown cleanup; browser pointermove/coalescing/backpressure
и blur/visibility/lostpointercapture; recorder trajectory/uncertainty. Browser
controller и отдельный реальный Kotlin pipe теперь проверены в
[следующем этапе](../audits/2026-10-08/CONTINUOUS-INPUT-POINTER.md), но routes
и установленный UI ещё их не вызывают. Fake capture этого canary не является
frame acceptance. Далее обязательны live APK/frame приёмка, known reset, local/remote
end-to-end и latency/resource soak. Наличие этих модулей не закрывает SF26-05
и не меняет ledger9 accepted /41 open.

**Followup8 октября:** [scoped receipt boundary](CONTINUOUS-INPUT-RECEIPTS.md)
проверена34 новыми случаями; полный leaf130 прошёл fake/real Redis. Атомарный
native state transition/PUBLISH, worker/local lease validation и integer
precision теперь реализованы отдельно. Startup/subscriptions и routes всё ещё
не подключены; этот followup не является подтверждением live deployment.
