# Direct probe: изоляция отказавшего viewer

Дата: 9 октября 2026. Scope: source correction после первого prototype commit
`d5d30a58`; рабочая установка не менялась.

[Первый prototype и оставшиеся gates](DIRECT-PROBE-SOURCE.md) ·
[Действующие работы](../../operations/WORK-STATUS.md).

При дополнительной проверке найден дефект: BrokenPipe или таймаут socket send
в ходе передачи SDP answer могли попасть в общий listener failure handler.
Один неисправный viewer выключал direct diagnostics для остальных пользователей
на том же worker. Это не сбой установленного WebSocket видео или native input;
экспериментальный runtime ещё не установлен.

Ответ конкретному viewer теперь имеет отдельный deadline 1 s. Отказ закрывает
его exact lease/socket и передаёт exact nonce close; shared listener продолжает
работать. Packet operation timeout не включает resubscribe/replay. Отказ самого
PubSub listener по-прежнему закрывает всех его владельцев без replay. Если Redis
недоступен, оставшиеся orphan metadata/native peer ограничены TTL, без renew.

Два регрессионных варианта — BrokenPipe и slow socket — подтверждают удаление
только неисправного viewer и успешный следующий probe на этом же worker/device.
Existing listener-failure test сохраняет fail-closed поведение при общей потере
signaling. Native Android/media/control код этой коррекцией не изменялся.

Локально: 78 backend direct/continuous/stream bridge/keyframe tests passed;
Ruff/mypy passed. Exact-source hosted CI является отдельным gate. Предыдущий
source commit уже прошёл hosted frontend; его backend bootstrap/RLS/security/
lint успешны, full backend/Android ещё выполнялись на срезе этой коррекции.

Live ICE/RTT/native cleanup и installed media/control по-прежнему не приняты.
Продукт 9/41, legacy 7 незакрытых и установленный UI d70f55c6 / API d720232e
остаются прежними. Новая коррекция не объявляет исходный idle timeout исправленным.
