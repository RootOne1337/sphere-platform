# Снимок последнего сбоя непрерывного управления

9 октября2026. EP-020/029, SF26-05 остаются OPEN. Это source diagnostics,
а не исправление idle timeout или подтверждение нового runtime.
[Локальная проверка и fingerprints](CONTINUOUS-FENCE-DIAGNOSTICS.json).

## Подтверждённый пробел

ContinuousPointer.retire очищал pending receipts, terminal и held pointer
до перехода в fenced. В вебе оставался код причины и последний throttled ACK,
но исчезали возраст и тип ожидавшей команды. После RELEASE/одного idle recovery
невозможно было различить heartbeat-only silence и неизвестный terminal outcome
по доступной диагностике. Датированный idle failure ранее воспроизведён:
[STUDIO-IDLE-RECEIPT-FOLLOWUP](../2026-10-08/STUDIO-IDLE-RECEIPT-FOLLOWUP.md).

## Изменение

Перед очисткой создаётся один immutable scalar snapshot. Observer получает его
уже после fencing; исключение observer не блокирует единственный touch_close.
Снимок не содержит owner/session/capture IDs, координат, текста, кадров или
траекторий. Хранится только последнее диагностическое событие текущего viewer.

Поля: причина и фаза; offered/acknowledged sequence; количество pending;
oldest sequence/action/send-age/deadline-age; точный unacknowledged terminal
и его возраст; held flag; разрыв browser tick; время с send; последний actual
ACK RTT/age; WebSocket state/buffer; heartbeat-only classification.
Неизмеренные значения имеют null, а не искусственный ноль.

Проверка deadline теперь происходит до обновления lastTickAt: snapshot
сохраняет реальный разрыв тиков, а не freshly-reset0. Бюджеты не изменены:
heartbeat250ms, receipt500ms, scheduling gap500ms, startup6000ms,
32pending scalars,1024B browser send buffer. Input/heartbeat не воспроизводятся.

В существующем «Диагностика» выбранного стрима добавлен раскрываемый блок
«Последний сбой управления». Он сохраняет failure после known RELEASE и
повторного согласования на том же socket; нормальные View/Control/inspection
releases не заменяют его уведомлением о смене режима. Device/auth/socket
замена очищает/scopes report; устаревший callback не меняет новый viewer.
Нет нового polling, persistent storage, глобального журнала или per-MOVE logs.

## Проверка

- 136 tests /2suites continuous-pointer и pointer-control проходят.
- Полный frontend:1947tests/139suites,85.629s, all passed.
- Nonincremental TypeScript: tsc --noEmit --incremental false, exit0.
- Девять новых regressions: idle snapshot до очистки и single immutable event;
  scheduler starvation; actual ACK RTT несмотря на throwing observer;
  cold-start send age отдельно от READY deadline; exact terminal после более
  позднего heartbeat; throwing fence observer не блокирует close/retain MOVE;
  invalid clock сохраняет unknown ages; UI snapshot после RELEASE и очистка
  при смене устройства; normal inspection не создаёт ложный failure.

## Доставка и дальнейшая работа

На момент source receipt новый UI ещё не установлен. Записанный прежний UI
60be6ecd/APIbe803773 сохранён. CI/runtime/finite browser receipt фиксировать
отдельно после exact-source delivery; APK protocol не менялся.

Snapshot описывает браузер в момент fencing. RTT включает весь путь до
подтверждения Android, но не определяет, виноваты ли browser event loop,
Redis forward, transport, APK queue или native injector. Для исправления idle
нужна корреляция этих слоёв и finite idle canary, затем soak/fleet acceptance.
SF26-05 не закрывать по успешным unit tests или добавлению метрик.
Recorded MOVE/context bundle, global native owner и WebRTC остаются отдельными
открытыми работами; ledger9accepted/41open не меняется.
