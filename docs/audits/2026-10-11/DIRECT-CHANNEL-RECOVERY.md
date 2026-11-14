# Восстановление прямого канала после отказа ввода и допуска

11 октября 2026. Проверенный source: `500186e2a18378f82e55ddcab5c8700d41e29a5a`.
Изменения подготовлены; рабочие API/UI на 3015 и Tuna остаются `6ee80c1f`.
APK55 не собран, не подписан и не установлен. Production-приёмка отсутствует.

## Воспроизведённые пробелы

1. В подготовленном direct-input source закрытие `sphere-control-v1` отзывает
   callback ввода, но оставляет media peer живым. Канал с закрытым SCTP stream
   самостоятельно не открывается заново; очередная попытка primary media также
   не запускается. Изображение может продолжать идти, прямой ввод не возвращается.
2. Отказ авторизации primary signaling до создания viewer классифицируется
   как постоянный reject. После создания viewer любой HTTPException также
   считается потерей права. Временный HTTP429/503 поэтому мог запрещать retry.
3. Начальный capability GET не повторяется после краткого сетевого отказа.
   Без нового lifecycle/query event mounted viewer остаётся без primary attempt.
4. Предыдущие неуспешные setup attempts остаются в backoff window после длительной
   работы видео. Следующий изолированный отказ мог сразу давать минуту fallback.

Это воспроизведение по коду и тестам, а не атрибуция всех наблюдаемых пользователем
обрывов. Подготовленный direct-input ещё не включён в установленном API/UI.
Последний доступный PH010 journal отдельно содержит ICE `connection_deadline`;
изменения этого этапа не доказывают устранение его сетевой причины.

## Исправленное поведение

Закрытие, ошибка или неверный wire message control DataChannel завершает exact
peer grant. Старый endpoint немедленно становится непригодным для ввода;
callbacks и listeners от него не могут воскресить handle. CLOSE идёт по отдельному
server path, с сохранением native RELEASE/CANCEL и существующей проверки owner.
Main renderer использует server fallback; primary component автоматически
согласует новый peer и новый control channel. DOWN/MOVE/UP не переотправляются.

Сохранён bounded backoff: четыре primary attempts в окне, затем60s fallback;
обычные задержки повторов1/2/4s. Отображавшийся не менее30s peer начинает новое
окно отказов. ICE-connected без реально отображённого кадра не сбрасывает window.
Поздние callbacks завершившейся попытки не выдают channel следующему controller.

HTTP401/403 и подтверждённая смена identity прекращают retry. HTTP429/503 на
initial authorization или recheck возвращают1013 и `direct_video_retry`;
прежний lease при этом отзывается. Никакой отказ не разрешает неавторизованный
SDP или Android input. Конечный read-only diagnostic сохраняет прежний протокол.

Capability read делает максимум четыре попытки при HTTP408/429/5xx или известных
Axios network/timeouts:1/2/4s. HTTP401/403, отмена запроса и invalid successful
admission автоматически не повторяются. После исчерпания бюджета нет нового
периодического capability polling; reconnect/lifecycle остаются штатными query
сигналами. В hidden/recording/inspection сценариях media eligibility по-прежнему
обязательна. Read-only GET не выдаёт native ownership.

История принимает только три новые enum-причины: `control_channel_closed`,
`control_channel_failed`, `invalid_control_message`. Лимиты10 sessions/device,
32KiB/session и7d сохраняются. SDP, адреса, ввод и exception text не добавляются.

## Проверки и технические основания

- До исправлений5 transport regressions и4 initial-auth cases падали.
- После исправлений7 frontend suites /192 tests прошли; среди них настоящие
  TanStack Query retries, exact peer retirement, late callbacks, no replay,
  RELEASE перед сменой маршрута, integration ввода и bounded history.
- Полная локальная WebSocket suite:690 tests +44 subtests; в том числе
  initial/recheck denial vs retry, удаление exact lease и history enums.
- TypeScript, scoped ESLint/Ruff, mypy двух затронутых серверных modules,
  `git diff --check` и generated OpenAPI/catalog reconciliation прошли.
- GitHub CI запущен для exact source; его результат фиксируется отдельно.
  Local unit/integration fixtures не являются native runtime/soak acceptance.

Основание lifecycle: [W3C RTCDataChannel closing procedure](https://www.w3.org/TR/webrtc/#closing-procedure)
и [RFC8832 Data Channel Establishment Protocol](https://www.rfc-editor.org/rfc/rfc8832.html).
Повторное согласование fresh grant — наш выбор реализации; стандарт не требует
закрывать весь media peer при каждой ошибке control channel. Это позволяет
сохранить уже проверенные exact-peer/owner fences до отдельного channel-resume
протокола. Цена решения — временный server fallback при таком восстановлении.

[Официальное руководство WebRTC](https://webrtc.org/getting-started/peer-connections)
описывает ICE/STUN/TURN и signaling. [TURN](https://webrtc.org/getting-started/turn-server)
нужен для резервного маршрута, когда прямой путь недоступен. На текущем стенде
TURN не настроен; direct-only WAN без доступного ICE path не объявляется надёжным.
WebRTC network RTT не равен capture-to-display или Android input latency.

## Фактический стенд и следующий допуск

Read-only проверка14:46 UTC: оба origin возвращают API revision6ee и readiness
PostgreSQL/Redis OK. API сообщает PH01010254, PH01110253, PH02510252; все online.
Это reported versions, не новая проверка installed APK SHA. Capabilities старого
API не содержат `direct_input_enabled`/`native_history_enabled`; отсутствие поля
не считается подтверждением нового допуска. История содержит9/9/10 sessions,
в последних доступных записях server route и0 direct frames. Новая peer attempt
этой read-only проверкой не запускалась. PH030 выключен и не проверялся.

Windows preflight14:45 UTC: C: Warning /Full Repair Needed. Runtime install,
Docker image load, APK build/OTA, VPN/firewall mutation и reboot не выполнялись.
После подтверждённого ремонта и восстановления Git нужны новый reviewed API/UI,
signed APK55 canary, затем проверка direct native DOWN/MOVE/UP/ACK на PH010 и PH025.
Следом: control-only close → fresh grant, held CANCEL/known RELEASE, permission
revocation, multiple viewers, localhost/LAN/WAN/TURN и длительный soak.

[Результат и границы](DIRECT-CHANNEL-RECOVERY.json) ·
[Ремонт и сохранённые копии](HOST-REPAIR-1216.md) ·
[Native journal и APK55](NATIVE-DIRECT-DIAGNOSTICS-SOURCE.md) ·
[Рабочий реестр](../../operations/WORK-STATUS.md).
