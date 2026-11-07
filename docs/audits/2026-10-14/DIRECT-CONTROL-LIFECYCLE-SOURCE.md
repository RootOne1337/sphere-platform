# Direct-first: обнаруженные границы управления и ICE

Исходники от14 октября2026; текущая установленная версия на момент расследования —
APK72/UI375/APIbe. Этот документ описывает исправления следующего кандидата73,
не объявляет его установленным до подписанной сборки, OTA и живой проверки.

В свежей истории PH030 обнаружены несколько `signaling_deadline` и последующие
длительные `probing` при продолжающемся серверном видео. Ранее тот же эмулятор
держал один прямой peer. По этой истории нельзя установить физический маршрут
каждой вкладки или объявить все отказы именно потерей ICE: signaling ещё не закончен.

Подтверждённые ошибки кода:

1. Shared admission заставлял ждать direct peer и после завершившейся неудачной
   попытки. Резервный ввод не запускался. Теперь failed/stopped попытка допускает
   новый server input OPEN с обычными проверками прав/cleanup. Работающий fallback
   owner сохраняется до готового прямого endpoint и собственного точного RELEASE.
2. Видеоканал снимал общий setup deadline, даже когда control DataChannel ещё
   connecting. Теперь ввод имеет собственный шестисекундный deadline после media
   SCTP OPEN; неопределённый peer закрывается и согласуется заново. Видео, SCTP OPEN
   и native READY являются разными наблюдениями.
3. Прямой shared input ожидал дополнительный `touch_probe` через сервер, хотя
   авторизованный endpoint уже содержит exact capture binding. Новый OPEN отправляет
   напрямую; участник всё равно обязан получить identity и native READY.
4. При появлении shared endpoint незавершённый предыдущий capability probe мог
   оставить viewer помеченным как уже проверенный. Теперь отсутствие native owner
   позволяет отменить только этот probe и открыть ввод на новом endpoint.
5. Android callback сообщения SCTP мог опередить queued callback OPEN. Authenticated
   shared grant теперь проверяется до первого сообщения. Это устраняет потерю OPEN;
   нового права по одному имени канала не выдаётся.
6. Android ждал полного ICE gathering перед SDP answer. Новый согласуемый Trickle ICE
   передаёт answer после local description и найденные UDP candidates по мере появления.
   Браузер начинает с первого usable host candidate; поздний srflx не теряется.
   Старый APK сохраняет прежний batch protocol; возможность объявляется с10273.

Trickle signals идут через текущие authenticated leases и session nonces, между
точными worker/agent generations. Каждый peer ограничен64 candidates на направление,
кандидат —2048bytes. Они не сохраняются в истории/метриках; произвольные DNS-имена,
owner metadata и новые commands запрещены. ICE/DTLS самостоятельно подтверждают путь.
Кандидаты, пришедшие до remote description, удерживаются в ограниченной setup очереди,
затем применяются к тому же peer. Содержимого Android input в ней нет.

Телеметрия добавляет отдельные control DataChannel state и elapsed time плюс конкретный
`control_channel_deadline`; прежние native READY, pending ACK, failure и capture
счётчики остаются. Перед публикацией нужны local/Tuna tests, естественный/принудительный
fallback→direct, control loss, повторное открытие и несколько участников.

Полноценные keyboard/IME, default-off audio, автономность при потере broker и реальный
телефон/hotspot остаются отдельной незавершённой работой.

[WebRTC: Trickle ICE](https://webrtc.org/getting-started/peer-connections) ·
[DataChannel readiness](https://developer.mozilla.org/en-US/docs/Web/API/RTCDataChannel/readyState) ·
[Установленная версия72](DIRECT-SYSTEM-INPUT72-DELIVERY.md).
