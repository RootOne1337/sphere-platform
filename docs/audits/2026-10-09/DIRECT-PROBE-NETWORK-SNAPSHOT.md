# Direct echo: ограниченный браузерный срез ICE при отказе

Дата: 9 октября 2026. Scope: source diagnostic follow-up после native pilot.
Новый runtime не установлен, новый network canary не проведён.

[Результат двух native попыток](DIRECT-PROBE-PILOT.md) ·
[Текущие работы](../../operations/WORK-STATUS.md).

В пилоте известны авторизованные offer/answer и отсутствие echo, но неизвестны
browser answer installation, состояние ICE checklist и ответы на connectivity
checks. Один `connection_deadline` не разделяет эти этапы. Новый source UI
сохраняет последнюю ограниченную сводку `getStats()` до закрытия peer.

Сводка содержит только число local/remote candidates, число проверяемых,
отказавших и успешных candidate pairs, ICE/DTLS states, aggregate requestsSent
и responsesReceived. Срез имеет время относительно начала проверки и возраст
при остановке. Она не хранит raw SDP, адреса, порты, candidate/session IDs,
credentials, certificate fingerprints или полный RTCStatsReport.

Семантика взята из
[нормативной WebRTC Statistics API](https://www.w3.org/TR/webrtc-stats/):
`requestsSent` — connectivity checks без retransmissions, `responsesReceived`
— полученные ответы. Эти счётчики не являются Android action receipts.
Успешная candidate pair сама по себе не доказывает выбранный transport path;
текущий selector использует только transport-selected candidate pair.

Отсутствующий хотя бы в одной паре счётчик остаётся unknown, а не суммой
доступных полей под видом полного измерения. Ноль отображается только когда
он реально представлен всеми парами. NaN/отрицательные/unsafe integer и сумма
вне safe integer отвергаются. Отсутствующий transport/DTLS остаётся unknown.

**Ресурсные границы:** один getStats in flight, не более32вызовов за
30секундный lifetime. Scheduled sampling начинается только после успешной
установки SDP answer. Проверка, echo и stats используют прежние deadlines;
Stop закрывает peer/socket/channel сразу, не ожидая зависшего diagnostic Promise.
Scheduled timer прекращается, late result не обновляет retired probe.
Хранится один summary, не растущий журнал. Ошибка stats не превращает валидный
answer в отказ и не прерывает echo. Смена устройства/токена очищает старый
snapshot и не запускает новую проверку автоматически.

Source checks: **16 frontend tests /3suites**, TypeScript и scoped ESLint passed
(существующая legacy .eslintrc, ESLINT_USE_FLAT_CONFIG=false; новый lint config
не вводился). Проверены
unknown/zero/privacy projection, startup failure snapshot/age, зависший getStats,
late result, diagnostic rejection, hard32callbudget, cleanup после20echo,
nonce/route binding и смена устройства. Тесты не подменяют реальную сетевую
проверку; native UDP/DTLS/direct RTT этого этапа ещё не измерены.

Следующий сравнительный pilot должен различить: answer installed? есть ли
remote candidates/pairs? уходят ли ICE requests и приходят ли ответы? открыт ли
DTLS/DataChannel? selected pair и echo RTT подтверждены? Только после этого
можно локализовать участок отказа и испытать STUN/TURN, без преждевременного
диагноза firewall/mDNS/NAT или увеличения timeout.

Exact-source hosted CI/delivery новой сводки, real failure UI и mobile layout
остаются отдельными gates. Установка UI d70/API9ad и probeoff/allowlist[] из
пилота сохранены. Product9/41, legacy7 и исходный idle ACK failure OPEN.
