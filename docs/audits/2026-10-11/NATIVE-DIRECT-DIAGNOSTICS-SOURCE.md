# Автоматическая диагностика прямого соединения со стороны APK

11 октября 2026. Это подготовленный source для следующего кандидата
**1.2.55 /10255**, а не запись об установленной версии или production-приёмке.
Рабочий API/UI остаётся `6ee80c1f`; проверенный PH010 использует10254.
[Фактическая установка](CURRENT-STREAM-DELIVERY.json) не переписывается.
Обновление API/UI остановлено до загрузки Docker image из-за Windows C:
`Full Repair Needed`. CI нового кандидата и installed SHA ещё не подтверждены.

## Какой пробел устранён в исходном коде

История последних10 сеансов уже сохраняет браузерные счётчики, ошибки управления
и Android capture telemetry. Однако native ICE/progress установленного APK54
нужно читать отдельно из локального canary log. История не содержит вторую
сторону ICE-обмена автоматически. Без неё отсутствие ответа нельзя точно
отделить от отсутствия измерения на APK.

Новый APK сообщает компактные aggregates по существующему authenticated
Android WebSocket. Сервер связывает их с конкретным активным просмотром,
а веб показывает сведения APK в раскрываемой секции того же сеанса.
Нажимать отдельную кнопку диагностики для этого не требуется.
Инструментация не чинит сетевой маршрут и не подтверждает direct input.

## Данные и их смысл

| Поле | Что измеряется | Что оно не доказывает |
|---|---|---|
| stage | Последний фиксированный этап WebRTC на APK | Исполнение tap/swipe Android |
| answer_sent | Ответ принят локальной исходящей WS-очередью | Получение ответа браузером |
| elapsed_ms | Монотонное время от получения offer этим peer | Пинг или задержка видео |
| network_sample_elapsed_ms | Относительное время начала native getStats | Синхронизацию часов с браузером |
| network_sample_age_ms | Время от начала запроса getStats до отправки отчёта | Внутренний timestamp/caching RTCStats или задержку видео |
| local/remote_candidates | Число соответствующих RTCStats rows | Различные IP или доказанный loopback |
| checking/failed/succeeded_pairs | Состояния candidate-pair rows | Выбранный транспортный маршрут |
| requests/responses sent/received | Агрегаты ICE-обмена | Полную задержку от экрана до экрана |
| dtls_state | Измеренный native DTLS state или null | Наличие декодированных видеокадров |
| received_at | Время приёма сервером | Время native захвата кадра |

Неизвестные counters остаются **null**, измеренный0 остаётся0. Native64-bit
counter вне точного диапазона JavaScript также становится null. Итог при закрытии
сохраняет первоначальное время запроса getStats; повторная публикация не делает
его новым. Внутренние native RTCStats timestamps отдельно не измерены: нельзя
исключить кеширование статистики реализацией getStats. Начальный/failure report
может содержать stage без network snapshot.

Смысл stats сверён с [W3C WebRTC Statistics](https://www.w3.org/TR/webrtc-stats/#dom-rtctransportstats-selectedcandidatepairid)
11октября2026. Выбранная пара определяется transport-level reference;
показанные здесь aggregates не объявляются выбранным маршрутом. Документ W3C
имеет статус Candidate Recommendation Draft, а не окончательной рекомендации.

## Расход ресурсов и отказ записи

Finite read-only probe сохраняет прежний бюджет32 getStats callbacks.
Для renewable primary video используются32 setup attempts с интервалом не менее1s,
далее не чаще одного native getStats за10s. Всего не более2912 attempts/peer
в пределах8h grant и один terminal report. Одновременно допускается только один
незавершённый callback; timeout не запускает второй JNI запрос поверх первого.

Native actor использует прежнюю cadence. Новых callback threads, polling timers,
media buffers или захватов экрана не добавлено. Подробный local Logcat aggregate
по-прежнему ограничен первыми32 reports; sparse telemetry не превращается
в многотысячный локальный файл. Каждый wire report не больше2048B и отбрасывается,
если исходящая очередь уже превышает отдельный8KiB diagnostic budget.
Неуспешная отправка отчёта не закрывает peer и не повторяется.

Android WS router проверяет report и помещает его в очередь максимум4 items
без Redis await. Отдельный writer проверяет действующий peer/agent generation
и пишет journal с timeout. Сбой/переполнение отбрасывает optional report,
не задерживает native input ACK и не отменяет video/input lease.

Сохранены общие лимиты: **10 sessions/device,32KiB/session,7 days**,
максимум15 retained native samples и atomic byte eviction вместе с остальной
диагностикой. Это агрегаты, а не видеозапись или трасса каждого кадра.
Нет обещания доставки каждого диагностического отчёта при потере связи.

## Привязка и совместимость

`history_session` — отдельная read-only привязка16hex. Она не выдаёт права ввода
и не заменяет `control_session`. Сервер проверяет peer32hex, org/device,
authenticated user, текущую agent generation, exact Redis lease и active
history record. Owner user хранится только внутри записи; history API его
не возвращает. Late/duplicate/out-of-order reports не могут оживить закрытый
или вытесненный сеанс. При хранении сохраняется первоначальный `received_at`.

`native_history_enabled` в capabilities становится true только при admitted
video и online APK>=10255. Старый API без этого поля и APK54 получают прежний
signaling payload. Отсутствующие historical native samples показываются
«нет данных», без backfill, нулей или выдуманной исправности.

Не сохраняются SDP, candidate IDs/addresses, ICE credentials, certificates,
ввод, изображения или native exception text. Сохраняемый peer nonce служит
корреляции попыток, не является RTCStats ID и сам по себе не даёт доступа.

## Проверки этого этапа

Повторный local прогон WS, documentation status и image-retention suites:
**734 tests +107 subtests**. Включены history+input binding и retirement
во время Redis await. Frontend stream/probe suite:26 suites/553 tests.
TypeScript, scoped ESLint/Ruff и mypy прошли; OpenAPI пересоздан из pinned API.
Новые pure Kotlin tests покрывают preserved age, unknown/overflow counters,
квоту, sparse sampling, clock/terminal/callback fences; Android build ожидает CI.

Панель проверена через настоящий браузер на source fixture:1280×720 и390×844.
Использованы текущие theme tokens и CSS установленного веба. Раскрытие reports,
перенос строк и отсутствие горизонтального overflow проверены. Fixture содержит
явную отметку тестовых данных. Это визуальная проверка подготовленного component,
а не установленного3015 или native runtime.

## Следующий допуск

Нужны exact-source Android/API/UI CI, signed canary, здоровый Windows volume,
reviewed runtime install, адресная OTA и совпадение installed SHA. Затем требуется
реальный сеанс с автоматически полученными native reports без ручного Logcat,
reconnect/held CANCEL, проверка PH025 и localhost/LAN/WAN/TURN/soak.
APK55, stable1.3 и production route сейчас не объявляются установленными/принятыми.

## Связанный source

- [Native scalar journal](../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeTelemetry.kt)
- [Native getStats budget](../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeNetwork.kt)
- [Native transport](../../../android/app/src/directProbe/kotlin/com/sphereplatform/agent/direct/DirectProbeTransport.kt)
- [Строгий backend wire DTO](../../../backend/websocket/direct_probe_telemetry.py)
- [Fenced runtime / bounded writer](../../../backend/websocket/direct_probe_runtime.py)
- [Atomic history](../../../backend/websocket/stream_session_history.py)
- [UI истории](../../../frontend/src/features/stream/StreamSessionHistoryPanel.tsx)
- [Regression tests](../../../tests/test_ws/test_direct_probe_telemetry.py)
