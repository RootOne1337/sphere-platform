# Native setup: конечная диагностика до ответа

Source base `934f46a8`,10 октября2026. Не установлено; новый native pilot требуется.
Прошлый canary не получил answer, а getStats начинался только после answer.
Этот диагностический пробел исправлен без изменения wire/deadline/peer ownership.

Фиксированные enum этапы показывают offer, factory, peer, remote description,
answer creation, local description, gathering, answer sent и DataChannel.
Failure/close/expiry — terminal: поздние callback не добавляют успешный этап.
Каждый этап пишется максимум один раз;19events/peer, без SDP/IP/session/SSID/
credentials и произвольного native error text. Monotonic elapsed ограничен30s.

getStats теперь собирается при setup, включая gathering, с прежним budget32,
одним outstanding callback и generation/lease fencing. В агрегате добавлен
answerSent, чтобы не смешивать pre-answer и post-answer наблюдения. Никакого
media/input по этому каналу и непрерывного fleet log export не добавлено.

Dev/Enterprise unit suites и Dev lint прошли; точные counts/source hashes в JSON.
Тесты проверяют10000повторных callback, все terminal states, регрессию часов,
конечное время и поздние сообщения. Hosted CI/signed artifact и real callback
следуют отдельно. Это observability fix, не доказанное устранение native отказа.

[Source/test receipt](DIRECT-PROBE-NATIVE-PROGRESS-SOURCE.json) ·
[Отрицательное измерение](DIRECT-PROBE-PUBLIC-STUN-CANARY.md) ·
[Текущие работы](../../operations/WORK-STATUS.md).
