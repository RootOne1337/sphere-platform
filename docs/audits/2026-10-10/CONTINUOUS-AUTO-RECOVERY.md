# Непрерывное управление: автоматическое восстановление и reconnect audit

Дата: 10 октября 2026, UTC+5. Статус этого документа: **source correction**;
установка и реальный Android canary требуют отдельного receipt.
[Текущая установка](../../operations/CURRENT-STATE.md) ·
[Реестр](../../operations/WORK-STATUS.md) ·
[Предыдущий native ICE результат](DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md).

**Следующий source этап:** реальный публичный canary UIa513 подтвердил несколько
idle recovery, но MOVE timeout снова включил manual-only fence. Этот документ
сохраняет контракт предыдущей коррекции; новое поведение pointer timeout после
точного RELEASE и fresh viewer описано в
[отдельной коррекции](CONTINUOUS-POINTER-RECOVERY.md).

## Подтверждённые проблемы

1. `DeviceStream` разрешал только одну автоматическую попытку после idle ACK loss
   за весь эффект видеосессии. Следующий heartbeat timeout включал ручную блокировку,
   даже если Android затем подтверждал освобождение. Это ограничение исходника;
   оно воспроизводится component fixture и не доказывает сетевую причину задержки.
2. Если RELEASE терялся после безопасного idle failure, controller оставался
   `fenced`; дальнейшего автоматического согласования не было, хотя видео продолжалось.
3. При замене WebSocket забывался ранее подтверждённый continuous path. Свежий кадр
   позволял legacy swipe между началом нового capability probe и native STARTUP0.
   Новый тест реально получил такой swipe до исправления. Это не утверждение,
   что пользовательский Android исполнил именно этот сценарий в прошлом.
4. STARTUP5 от `admission` при открытии нового owner означает отказ до готовности
   касания. Он смешивался с injector/input unknown и требовал ручного восстановления.

## Изменение поведения

| Ситуация | Действие | Допуск нового ввода |
| --- | --- | --- |
| Только heartbeat задержался, native RELEASE3 получен | Повторное capability/owner согласование | Только после нового injector STARTUP0 |
| RELEASE после idle loss не получен за 3 секунды | Закрытие только этого viewer WS и новое подключение | Новый нарисованный кадр, capability, owner и STARTUP0; timeout не считается RELEASE |
| Ранее continuous path подтверждён, новый capability не получен за 6 секунд | Ограниченное повторное согласование через новый viewer | Legacy click/swipe заблокированы до свежей готовности |
| STARTUP5 от admission, sequence0, controller opening | Предыдущая сессия может ещё завершаться; новый owner согласуется заново | Касание не отправляется до STARTUP0 |
| Потеря ACK у DOWN/MOVE/UP/CANCEL, injector error или unknown HTTP key/text | Существующий explicit recovery fence | Исходное действие не повторяется автоматически |
| Сервер отклонил ранее подтверждённый control path | Остановка автоматических попыток, управление заблокировано | Новая проверка доступа/подключения; нет fallback в legacy input |
| Просмотр, инспектор, запись, task handoff, blur/hidden | Автоматическое input-согласование приостановлено | Текущий режим и его собственные release/authority gates |

Повторные безопасные попытки имеют интервалы **750 / 1500 / 3000 / 6000 /
12000 / 15000 мс**, затем максимум 15 секунд. Нет лимита «один раз за просмотр».
Backoff сбрасывается только после 30 секунд в ready с успешными native receipts;
открытие WS или получение видео сами по себе его не сбрасывают.

Во время восстановления navigation и legacy input заблокированы. Кнопка
«Восстановить управление» не требуется для автоматического idle recovery.
Probe-подсказка не обещает доступность нажатий: после reconnect она сообщает
только определение возможностей APK, пока готовность Android не подтверждена.
Она сохраняется для неизвестного результата действия или явного отказа сервера:
переподключение не сообщает, был ли исполнен прежний click/key/swipe.
Автоматический retry не исполняет его повторно и не восстанавливает recorder/run.

Запись после подтверждённого RELEASE может принять новое явное действие;
ожидавшийся recovery не блокирует этот режим навсегда. Переход в запись до RELEASE
не используется как обход native release fence.

## Границы классификации и ресурсов

- Retryable STARTUP busy требует точных stage/origin/sequence/status и controller
  `opening`. INPUT5, injector STARTUP5, admission unknown6 и ненулевой STARTUP
  сохраняют исходный unknown/rejected fence. Чужая session/owner/capture не принимается.
- Сохраняется максимум один recovery timeout текущего viewer. Cleanup отменяет его;
  callback дополнительно проверяет current socket/controller и действующие mode gates.
- При замене WS требуется его собственный нарисованный кадр. Старый callback или
  RELEASE не активирует нового owner. Движение старого pointer не воспроизводится.
- Нет очереди пользовательских действий, новых per-MOVE логов, постоянного хранения
  или изменения Android/Redis lease deadlines. Во время handshake DOWN не отправляется.
- Новая схема не устраняет причину 500-мс ACK deadline и не повышает его. Video,
  control и receipts на рабочей установке продолжают идти через серверный WebSocket.

## Проверки исходника

Красные fixtures до исправления подтвердили повторный idle limit и отсутствие
restart при потерянном RELEASE. После первой коррекции fixture выявил legacy swipe
до нового STARTUP0; он заблокирован отдельной коррекцией сохранения input path.

Три целевые suites: **167 tests passed**. Они проверяют повторный recovery,
экспоненциальную задержку и её предел, sustained native reset, missing RELEASE,
новый frame/capability/STARTUP0, late old RELEASE, busy admission, server denial,
mode locks, recording handoff и отсутствие replay. TypeScript и scoped ESLint
прошли. Полный локальный frontend run: **1982 tests / 142 suites passed**.
Exact-source CI и установка фиксируются отдельно после завершения.

Новая source capability-recovery часть не означает приёмку всего парка,
input-to-picture SLA, global ownership или стабильной APK1.3.0. Product9/41 и
legacy7 этим документом не закрываются.

## Следующая проверка установленного UI

1. Допустить exact-source CI image и заменить только review-ui; сохранить API,
   APK, schema, OTA и соседние контейнеры. Проверить оба адреса и runtime revisions.
2. В обычном Control без касаний наблюдать idle failure/release/recovery. Записать
   реальные state/counters; не создавать искусственный receipt в живом браузере.
3. Если натурального failure нет, этот сценарий остаётся fixture acceptance.
   Фактическую успешную новую сессию проверить отдельно безопасным жестом и навигацией.
4. После возврата фокуса/режима проверить свежую native readiness; старое видео,
   send completion и timer не являются её доказательствами.

## VPN и прямой транспорт: ответ на дополнительный вопрос

Peer-to-peer означает отсутствие media hop через сервер Sphere; он не означает
обход VPN. При полном VPN-tunnel Windows обычно выбирает VPN default route;
более специфичные маршруты и политика клиента могут оставить отдельные направления
вне туннеля. Split tunnel распределяет направления по маршрутам.
[Microsoft: VPN routing decisions](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/vpn/vpn-routing).

Разные домашние сети требуют Internet/NAT traversal независимо от близости квартир.
WebRTC согласует кандидатов через signaling и проверяет доступный путь. STUN помогает
обнаружению кандидатов; TURN передаёт трафик, если выбран relay path. Ни использование
TCP, ни URL страницы localhost не гарантируют соединение вне VPN.
[WebRTC: peer connections](https://webrtc.org/getting-started/peer-connections).

Предыдущий read-only route snapshot выбрал VPN default для внутреннего guest адреса;
это не packet-loss diagnosis. VPN, firewall и routes в этом этапе не меняются.
Host-only direct canary ещё не открыл канал. Same-PC/LAN/Internet profiles,
selected pair и фактический echo RTT остаются следующим отдельным gate.
