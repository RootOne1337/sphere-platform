# Прямой транспорт браузер ↔ Android: исследование и план проверки

**Последняя доставка 10 октября:** UI/API `ee0d8e6f`; PH030 адресно обновлён до10251, actual package SHA подтверждён. Настоящие RTP-кадры и input ещё не приняты. [Точный текущий receipt](../audits/2026-10-10/DIRECT-VIDEO-READONLY-INSTALLED.md). Датированные срезы ниже описывают предыдущие этапы.

**Дата проверки источников:** 9 октября 2026. **Статус:** архитектура PROPOSED;
последующим запросом пользователя разрешён первый диагностический прототип.
Написан отключённый по умолчанию RTT-only DataChannel canary; media/control,
TURN и рабочая установка не переведены на WebRTC. Это не обещание задержки.
[Точный scope, зависимости, тесты и следующие gates](../audits/2026-10-09/DIRECT-PROBE-SOURCE.md).

**Последующий тест ноутбука:** пользователь получил 20/20 echo от PH030, p95
25,8 мс, NAT/UDP. Это конечное наблюдение прямого канала; localhost, видео и input
им не доказаны. [Отдельный результат](../audits/2026-10-10/PH030-LAPTOP-CHANNEL-USER-OBSERVATION.md).
Подготовлен [read-only RTP video canary](../audits/2026-10-10/DIRECT-VIDEO-READONLY-SOURCE.md)
с отдельным допуском и общим H.264 encoder; установка и живые кадры требуют receipt.

**10 октября, 06:36 UTC — диагностическая панель установлена.** UI и API
`c17332eb` обслуживают 3015 и публичный адрес. Авторизованный доступ разрешён
только PH030; проверены HTTP admission, отображение профилей и мобильная ширина
390 px. Панель запускает конечный echo-тест по явному действию пользователя.
Это ещё не прямые видео и управление: channel/RTT, сетевые топологии и
media/control требуют отдельной приёмки.
[Установка и точные границы проверки](../audits/2026-10-10/DIRECT-ADMISSION-INSTALLED.md).

**Предыдущий срез 10 октября, 05:53 UTC:** PH030 на ноутбуке без VPN обновлён через OTA до
diagnostic1.2.50-dev/10250, фактический SHA совпал. На основном ПК UDP fixture
зависит от выбранного интерфейса; это отдельная топология. TURN REST/TLS template
проверен в isolated fixtures, публичный/native relay ещё не принят. Панель доступа
для обычного веба проверена в source, ожидает установку. Browser-on-laptop channel,
direct media/control и production SLA не подтверждены.
[Свежие измерения, OTA и пределы](../audits/2026-10-10/DIRECT-PROBE-TURN-AND-LAPTOP.md).

**Предыдущий итог10октября04:16UTC:** exact161 прошёл4CI и signed admission.
На одном PH011 три process epochs отправили answer за392/226/243мс; channel0/RTTunknown.
Финальный bounded capture на UID-проверенном APK socket:237исходящих UDP к browser
srflx candidate,0обратных; STUN1/1,239captured/0kernel drops. Это подтверждает
выход с Android interface и STUN exchange, но не достижение Windows/browser или
конкретную NAT/mDNS/VPN/firewall причину. Старый934 setup timeout не повторился,
его причина остаётся UNKNOWN. Original APK restored/probeoff, UI639/API369,
ordinary local11/public2 frames проверены. Диагностика принята только в конечном
scope; direct media/control не подключены. Предыдущие срезы ниже исторические.
[Native stages, packet scope, невалидные попытки и возврат](../audits/2026-10-10/DIRECT-PROBE-NATIVE-PROGRESS-CANARY.md).

Следующий gate: ограниченное наблюдение Windows/browser в том же packet window,
затем контролируемое сравнение authenticated relay. Ни STUN response, ни успешная
публикация SDP не доказывают peer reachability. Timeout не увеличивается ради
сокрытия неизвестного отказа; network/security settings этим этапом не менялись.

**Последующий native pilot9октября:** exact9ad прошёл все4CI. Две попытки
подтвердили JNI/SDP answer, но host ICE не установил канал, RTT неизвестен.
Прежний APK восстановлен, probe off/allowlist[]; media/control остаются server WS.
Это отрицательное доказательство и основание для проверки candidate reachability,
а не приёмка direct path или доказанный диагноз NAT/mDNS.
[Пилот, ограниченные ресурсы и следующий gate](../audits/2026-10-09/DIRECT-PROBE-PILOT.md).

**10 октября — реальный browser ICE срез:** две checking пары,177requests/0responses,
DTLS connecting,0echo/RTT; точная причина потери сетевого пути ещё UNKNOWN.
Срез получен во временном loopback diagnostic UI, compile gate стандартного
frontend выключен. Original APK восстановлен, API probeoff; ordinary public video
вернулся9frames без decode/render errors. [Receipt](../audits/2026-10-10/DIRECT-PROBE-NETWORK-CANARY.md).

**Следующий этап выполнен в конечном диагностическом scope:** исправленный source
`8447c907` прошёл четыре CI и signed admission. APK на одном PH011 выдал 12 native
отчётов: remote candidates 0, pairs 0, DTLS `new`; packet counters неизвестны.
Callback ограничен 32 запросами, одним pending callback и локальным canary logcat;
адреса и ключи исключены. Исходный APK восстановлен, probe выключен. Прямой канал
не подтверждён. [Source/test scope](../audits/2026-10-10/DIRECT-PROBE-NATIVE-NETWORK-SOURCE.md) ·
[Фактический callback и возврат](../audits/2026-10-10/DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md).

**10 октября — public-STUN prerequisite и native pilot завершены.** По одному
Windows/Android shell UDP binding получили32-byte ответы. Exact934 CI/signed APK
затем проверен на PH011: browser offer host1+srflx1, но до close7,989s answer нет;
echo/RTT/selected pair не получены. Это setup failure UNKNOWN, не доказанный NAT/
VPN/TURN диагноз. Original APK восстановлен, рабочий probeoff, обычный просмотр
на обоих адресах вернулся. Stats934 начинались только после answer; последующий
source добавляет bounded pre-answer stages/stats, новый callback gate остаётся OPEN.
[Измерение и возврат](../audits/2026-10-10/DIRECT-PROBE-PUBLIC-STUN-CANARY.md) ·
[Source диагностики](../audits/2026-10-10/DIRECT-PROBE-NATIVE-PROGRESS-SOURCE.md).

[Действующие работы](../operations/WORK-STATUS.md) ·
[Установка](../operations/CURRENT-STATE.md) ·
[Подтверждённый текущий путь и сбой](../audits/2026-10-09/IDLE-CONTROL-RELAY-REVIEW.md) ·
[Первоначальная идея](../audits/2026-10-09/BROWSER-DIRECT-TRANSPORT-INTENT.md).

## 1. Требование и предлагаемый выбор

Пользователь входит в HTTPS-веб Sphere и устанавливает APK на свои Android или
эмуляторы. Для работы не требуется отдельный клиент на Windows/Linux. Сервер
хранит каталог, проверяет доступ, согласует сессии, выдаёт ограниченное разрешение
на управление и принимает результаты заданий. Сценарий продолжает исполняться
внутри APK независимо от наличия открытой вкладки.

Предлагается проверить **браузерный RTCPeerConnection ↔ Android libwebrtc**:
видео через WebRTC media, интерактивные команды и native receipts через DataChannel.
ICE определяет достижимый путь; STUN помогает обнаружению адресов, TURN служит
резервным relay. Signaling проходит через существующий авторизованный сервер.
WebRTC отделяет согласование от обмена данными; signaling не задаётся самим
стандартом. [Официальная модель WebRTC](https://webrtc.org/getting-started/peer-connections).

Это инженерная рекомендация для прототипа. Она не основана на сравнительном
benchmark Sphere: такой benchmark ещё не выполнен. Новый транспорт должен
сначала пройти конечную проверку на PH011 и сетевую матрицу ниже.

Обычный TCP-туннель сам по себе не обеспечивает browser↔APK discovery, NAT
traversal, media congestion control, frame deadlines или native input ownership.
Для WebRTC предусмотрены ICE и защищённый media/data transport; TCP/TLS может
использоваться на резервных участках. Это не основание делать TCP обязательным
для самого быстрого пути. [RFC 8835](https://www.rfc-editor.org/rfc/rfc8835.html).

### Уточнения сети и Android compatibility — 10 октября

На проверочном PH011 read-only `getprop` вернул Android9/API28; текущий source
targetSdk/compileSdk35. Новая защита локальной сети Android17 применяется при
targetSdk37+: потребуется отдельный runtime permission/denial/revocation flow.
Для target35 добавлять или запрашивать `ACCESS_LOCAL_NETWORK` сейчас не нужно.
Это будущий compatibility gate, не объяснение нынешнего отказа API28.
[Актуальная инструкция Android, обновление2октября2026](https://developer.android.com/privacy-and-security/local-network-permission).

Имя mDNS в offer само по себе не доказывает отказ: upstream WebRTC tests
предусматривают установление связи через peer-reflexive candidate при отсутствии
resolver. Этот test block исключён для Android и не является проверкой нашего
pinned JNI. Полученные native counters не заменяют проверку достижимости; нельзя объявлять
«сломанный mDNS» только по SDP.
[Upstream test и его Android guard](https://webrtc.googlesource.com/src/+/refs/heads/main/pc/peer_connection_histogram_unittest.cc).

Следующее сравнение сохраняет одинаковые peer/wire/TTL и отличается только
явным ICE profile: host-only baseline, затем контролируемый STUN, затем TURN.
Для STUN/TURN фиксировать владельца endpoint, краткоживущие credentials, network
path и результат selected pair; секреты и адреса не отправлять в публичный receipt.
Relay near peers может дать короткий путь, но не должен называться P2P. Изменение
firewall, запуск публичного listener или разрешений Android не является скрытой
частью диагностического профиля. Production media/control остаётся отдельным gate.

Конечный corrected-source canary8447 снял12native reports: remote candidates0,
pairs0, DTLSnew; все4packet counters unknown. Browser показал177/0.
Это подтверждает работу диагностического callback и отсутствие native pair rows,
но не причину mDNS resolution или packet loss. Windows route для guest выбирает
VPN default; Android использует interface policy table. Следующий controlled
STUN/numeric-candidate profile должен сравнить именно эти показатели.
[Receipt и границы](../audits/2026-10-10/DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md).

## 2. Подтверждённая текущая архитектура

### VPN, same-PC, LAN и Internet

Прямой peer path исключает сервер Sphere из media forwarding, но подчиняется
маршрутам ОС и VPN policy. Full tunnel обычно выбирает VPN default route;
более специфичный физический route или split tunneling может выбрать другой
interface. TCP сам по себе VPN не обходит. Расстояние между квартирами не меняет
NAT topology двух отдельных домашних сетей.
[Microsoft: VPN routing decisions](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/vpn/vpn-routing).

Приёмка должна отдельно фиксировать selected ICE pair и OS route: host candidate
не доказывает localhost, а srflx не доказывает путь вне VPN. При relay выбран TURN;
это не P2P. Ни рабочий localhost URL веба, ни близость эмулятора не заменяют измерение.
[Finite route/counter evidence](../audits/2026-10-10/DIRECT-PROBE-NATIVE-COUNTERS-CANARY.md).

**Уточнение проверки 10 октября:** браузер и Android на одном физическом ноутбуке
могут находиться в разных сетевых пространствах. Android Emulator документирует
виртуальный router и отдельный guest loopback; эти адреса нельзя автоматически
переносить на LDPlayer. LDPlayer отдельно документирует режим bridge с выбором
сетевого адаптера и DHCP. Наличие ноутбука в той же Wi-Fi сети само по себе не
доказывает достижимость guest host-кандидата. Это основание проверять фактическую
ICE-пару, а не установленная причина нынешнего отказа PH030.
[Android Emulator: адреса и ограничения](https://developer.android.com/studio/run/emulator-networking-address),
[LDPlayer: режим bridge](https://www.ldplayer.net/support/how-to-set-up-network-bridging-on-the-android-emulator-ldplayer.html).

STUN помогает обнаружить адрес; он не становится ретранслятором видео. Для
рабочего продукта нужны прямой достижимый маршрут и резервный TURN, когда
сетевые ограничения исключают P2P. Trickle ICE сокращает время установления,
но не является доказательством уменьшения задержки уже работающего видео.
Текущие конечные проверки используют полный bounded SDP; переход к Trickle ICE,
изменение bridge/VPN/firewall и постоянный primary media требуют своих проверок.
[WebRTC: signaling, ICE и Trickle ICE](https://webrtc.org/getting-started/peer-connections).

| Участок | Что существует сейчас | Следствие |
| --- | --- | --- |
| APK → сервер | Один OkHttp WS для binary video и JSON, включая input ACK | ACK может ждать ранее поставленные video bytes |
| Сервер | Stream bridge / Redis worker routing / ownership store | Каждый текущий кадр и continuous input проходит серверный путь |
| Сервер → browser | Stream WS, H.264 decoder/WebCodecs/canvas | Адрес веба localhost не доказывает локальный путь APK |
| Native Android | Root helper, bounded mailbox, monotonic sequences, lease watchdog | Transport send не равен native execution receipt |
| Recorder / task | Отдельные завершённые действия и APK task receipts | Их нельзя подменять новым video ACK |

Проверенные исходники:

* [DeviceStream](../../frontend/components/sphere/DeviceStream.tsx),
  [ContinuousPointer](../../frontend/src/features/stream/continuousPointer.ts),
  [H264Decoder](../../frontend/lib/h264-decoder.ts).
* [SphereWebSocketClient](../../android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt),
  [ContinuousTouchSupervisor](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousTouchSupervisor.kt),
  [RootTouchPipeFactory](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/RootTouchPipeFactory.kt).
* [Stream router](../../backend/api/ws/stream/router.py),
  [Continuous runtime](../../backend/websocket/continuous_runtime.py),
  [Continuous delivery](../../backend/websocket/continuous_delivery.py).

Текущий APK допускает до 1 MiB queued outbound bytes перед отправкой видео или
receipt. Это предел памяти, не гарантированный срок доставки. При доступной
скорости 2 Mbit/s передача 1 MiB payload занимает около 4,19 секунды без overhead;
пример иллюстрирует риск, а не измеряет текущую очередь или канал пользователя.
Уже поставленные WebSocket сообщения нельзя сделать приоритетными новой кнопкой UI.

Публичная idle canary 9 октября дала ACK RTT 518 ms и heartbeat deadline age
503 ms без удержания пальца/неизвестного terminal. Источник задержки не установлен:
сеть, очереди, APK и native helper остаются кандидатами. Предыдущие server spans
<25 ms не покрывают весь путь и не относятся к конкретной sequence этой проверки.
Новый транспорт не является доказанным исправлением native или capture дефекта.

## 3. Схема согласования и путей

```text
 Browser ── HTTPS/WSS: login, device/session grants, signaling ── Sphere API
    │                                                              │
    │                    authenticated agent WS                    │
    │                              ┌───────────────────────────────┘
    │                              ▼
    ├──────── WebRTC direct ───── APK / Android
    │       video + input/ACK       │
    └──── TURN relay when needed ───┘

 APK task execution/results ── existing server task contract
```

При direct сервер не принимает каждый media packet или MOVE. При TURN media/data
проходят relay, что видно оператору. API и signaling остаются доступны независимо
от выбранного пути. Нельзя обозначать TURN как «прямое соединение».

Физически один ПК не гарантирует host-candidate connectivity: эмулятор находится
в виртуальной сети/NAT, firewall и маршруты могут исключать нужный путь. Официальная
документация Android Emulator описывает отдельное виртуальное сетевое окружение;
её адреса нельзя автоматически переносить на LDPlayer.
[Android Emulator networking](https://developer.android.com/studio/run/emulator-networking).

В прототипе проверять фактически выбранную ICE pair и байтовые counters. Наличие
двух адресов в одной подсети, online badge или успешный STUN само по себе не
доказывает direct connectivity либо низкую задержку.

## 4. Готовые решения и причины выбора

| Кандидат | Подходящая роль | Решение для Sphere |
| --- | --- | --- |
| Browser WebRTC + Android libwebrtc | Конечные участники direct media/data | Основной кандидат для одного viewer и одного APK |
| Pion WebRTC | Go endpoint, специализированный gateway, SFU/протокольные fixtures | Резерв для отдельной обоснованной Go-роли; не обязательный VPS-hop |
| coturn | STUN/TURN fallback | Основной кандидат relay; отдельные квоты/credentials/регион |
| LiveKit | Готовый SFU и SDK для многопользовательского media | Рассматривать для fan-out, совместного просмотра, записи; не исходный direct путь |
| Tailscale / NetBird | Overlay между узлами с установленным клиентом | Дополнительная управляемая сеть; не требование для пользователя с одним браузером |
| Raw local WS/TCP gateway | Локальный native companion | Меняет требование «только browser + APK», требует установки/обновлений/TLS |

Pion — Go-реализация WebRTC; официальная latest release при проверке —
**v4.2.23**, tag/commit указан в upstream release. Лицензия MIT. Добавление Pion
на сервер ради перекладки каждого кадра сохранило бы лишний media hop; это наш
архитектурный вывод, а не ограничение самой библиотеки.
[Pion](https://github.com/pion/webrtc),
[release v4.2.23](https://github.com/pion/webrtc/releases/tag/v4.2.23),
[лицензия тега](https://github.com/pion/webrtc/blob/v4.2.23/LICENSE).

coturn реализует STUN/TURN и поддерживает time-limited REST credentials.
Проверенная latest Docker release — **docker/4.18.0-r0**; это Docker tag,
не обещание текущего distro package или выбранного immutable image digest.
Лицензия исходника — BSD 3-clause. Перед установкой нужны review зависимостей,
точный digest и конфигурация; latest не используется в production manifest.
[coturn README](https://github.com/coturn/coturn),
[release](https://github.com/coturn/coturn/releases/tag/docker/4.18.0-r0),
[лицензия тега](https://raw.githubusercontent.com/coturn/coturn/docker/4.18.0-r0/LICENSE).

LiveKit описывает себя как SFU: участники передают media через серверную структуру.
Это полезно для нескольких viewers одного APK, но не выполняет исходное требование
убрать обязательный server media hop. Выбор не означает оценку качества LiveKit.
[Официальная архитектура](https://docs.livekit.io/reference/internals/livekit-sfu/).

Документация Tailscale/NetBird предполагает установку клиентов для участия обычных
узлов в overlay. Browser-only продукт не должен заставлять каждого пользователя
устанавливать ещё один системный VPN; overlay можно поддержать как отдельный режим
инфраструктуры. Их performance, тарифы и licensing здесь не сравнивались.
[Tailscale Windows](https://tailscale.com/docs/install/windows),
[NetBird installation](https://docs.netbird.io/get-started/install).

## 5. Android dependency и capture integration

Upstream libwebrtc имеет BSD-style лицензию; её third-party код требует собственного
набора notices. Официальный Android workflow предполагает Linux build и поддерживает
arm/arm64/x86/x64 GN targets. Не следует брать случайный Maven AAR только из-за
совпадающего имени. Нужны commit, build recipe, provenance, ABI/API и SBOM.
[Upstream license](https://webrtc.googlesource.com/src/+/refs/heads/main/LICENSE),
[Android build documentation](https://webrtc.googlesource.com/src/+/refs/heads/main/docs/native-code/android/).

Для первого RTT canary выбран `io.getstream:stream-video-webrtc-android:146.7.0`;
Maven Central AAR inspected и SHA-256 закреплён в Gradle verification metadata.
Это бинарная зависимость, не утверждение о воспроизводимости её native build.
Обычный APK не включает этот AAR; отдельный debug source set требует флаг canary.
Полная supply-chain/native resource приёмка остаётся отдельным gate. Перед media admission:

1. Проверить upstream source revision, notices, build dependencies и advisories.
2. Получить воспроизводимый Linux CI artifact для нужных ABI; зафиксировать hashes.
3. Проверить x86/x64 LDPlayer и arm64 physical Android отдельно.
4. Сверить minSdk, targetSdk, root/non-root capture и foreground service lifecycle.
5. Измерить APK size, installed size, native RSS, encoder count и cleanup.
6. Только после этого включать canary feature flag.

Не скачивать многогигабайтный native checkout на проблемный Windows SSD ради
исследования. Source/build/cache/retention размещать в ограниченном CI workspace;
дополнительный локальный Docker image не требуется для этого документа.

Существующий capture owner остаётся единственным. Прототип должен доказать один
захват и один разумно ограниченный encode pipeline на активный device view.
Предпочтительно передавать capture frames аппаратному encoder libwebrtc. Reuse
нынешних H.264 NAL через custom encoder adapter — отдельная проверяемая альтернатива,
не гарантированная совместимость и не raw NAL send через DataChannel.

Начальный codec candidate — совместимый H.264 profile; проверять фактические
SDP/codec/MediaCodec результаты. RFC требует поддержки VP8/H.264 в соответствующих
WebRTC endpoints, но это не гарантирует аппаратный encoder в каждом эмуляторе.
[RFC 7742](https://www.rfc-editor.org/rfc/rfc7742.html).

Проверять keyframe request, SPS/PPS/rotation, timestamps, pacing, loss recovery,
encoder restart и renderer generation. Изменение transport не должно обнулять
проверки geometry/capture epoch. Эталонные PNG остаются отдельным Android capture.
Audio не требуется, media transceiver для него не создаётся.

## 6. Input и native receipts

Перенос только видео недостаточен: MOVE и подтверждения тоже должны получить direct
путь. DataChannel доставляет данные между участниками WebRTC, поддерживает ordered/
unordered и различную надёжность; native application semantics остаётся задачей
Sphere. [RFC 8831](https://www.rfc-editor.org/rfc/rfc8831.html).

Для первой проверяемой версии предлагается один небольшой ordered reliable control
channel с ограниченными размером сообщения, bufferedAmount, сроком команды и очередью.
На перегрузке движение coalesce до отправки; DOWN/UP/CANCEL не воспроизводятся после
неизвестного результата. Нельзя отправлять изображения/логи по control channel.
Reliable transport может задерживать последующие сообщения при потерях; тест loss
обязателен. Отдельный unordered MOVE channel — последующая оптимизация с новым
cross-channel ordering contract, а не безопасное изменение одного флага.

Application envelope связывает protocol version, session generation, authorized
device, owner, capture epoch, gesture, sequence, action и срок. Mapping к native
mailbox сохраняет monotonic sequence и immutable capture binding. Native ACK
содержит origin/stage/status/sequence; DataChannel send/OPEN/DTLS connected никогда
не обозначаются Android success. Реальные wire fields требуют отдельной schema.

Обязательные переходы:

| Ситуация | Требуемое поведение |
| --- | --- |
| Потеря ACK без касания | Отличить connection loss от неизвестной touch-команды; bounded reconciliation после known release |
| Неизвестный DOWN/UP/CANCEL | Fence; никакого автоматического replay или перехода в discrete |
| ICE restart / path migration | Старый generation становится недействительным; не переносить pending input |
| Browser blur/suspend | Освободить owner; native watchdog продолжает работать без браузера |
| Capture rotation/restart | Новый epoch и согласование geometry до нового input |
| Task/recorder/inspector | Подтверждённая передача единого input ownership; не второй независимый owner |
| Close transport | Bounded cleanup; отдельный known/unknown native release |

Существующие deadline 500 ms и native watchdog 1500 ms не повышаются ради
маскировки проблемы. Prototype может предложить новый versioned budget только
с обоснованными latency/loss measurements и native safety review.

## 7. Server authority при прямом input

Direct connectivity не даёт права управлять устройством. Grant выдаётся только
после существующих organization/device/RBAC checks и согласования единого owner.
APK проверяет подпись/срок/audience/version/device/owner/capture generation;
не доверяет metadata, которые viewer прислал самостоятельно.

Signaling bind связывает конкретные endpoints, grant и DTLS fingerprints;
подмена SDP/candidate из соседней организации отвергается. Access JWT не передаётся
в DataChannel и не используется как долговечный TURN password. Grant replay,
expiry, reconnect и changed role имеют отдельные негативные тесты.

Серверу не нужно синхронно разрешать каждый MOVE. Но direct owner обязан иметь
ограниченный срок authority, renewal и revocation. При потере server coordination
он не может управлять бесконечно за счёт одних browser heartbeats. Максимальный
partition/revocation delay и renewal interval должны стать явными параметрами
контракта до реализации. Native touch lease и server authority — разные сроки.

TURN credentials краткоживущие, с tenant/user/session quotas, allocation lifetime,
bandwidth limits и запретом доступа к metadata/loopback/internal management targets.
На signaling нужны bounded SDP/candidates/rate/timeouts и origin checks. Candidate
IP/SDP могут раскрывать сеть пользователя: не хранить их в общих logs/metrics.
DTLS/SRTP защищает transport, но не заменяет application authorization.

## 8. UI и наблюдаемость

Единый viewer используется карточкой устройства и Studio. Раздельные реализации
direct video в двух местах недопустимы. В UI показываются фактические состояния:
connecting, direct, TURN relay, legacy server relay, disconnected, unknown.
Пользователю не нужно выбирать технологию перед обычным подключением.

Расширенная диагностика показывает выбранный transport/protocol, RTT, loss,
bitrate, resolution, codec, decoded/rendered FPS, freeze и input ACK. Не смешивать
ICE RTT с input-to-native ACK или input-to-visible-response. W3C stats предоставляет
selected candidate pair, candidate type и RTT, но не Android execution receipt.
[WebRTC stats](https://www.w3.org/TR/webrtc-stats/).

Серии Prometheus имеют конечные transport/reason/outcome labels без user/device/
session/candidate IP. Временный per-session diagnostic export ограничен размером,
сроком и доступом. Никакого автоматического сохранения видео/скриншотов/траекторий
для каждого viewer. TURN/container logs имеют rotation и disk quotas.

## 9. План измерений и предлагаемые цели

Цели ниже — **предложение для admission**, не достигнутые значения или SLA.

| Метрика | Предлагаемая local/LAN цель | Что измеряется |
| --- | --- | --- |
| Input → native ACK | p95 ≤100 ms, p99 ≤250 ms | Один browser monotonic clock, exact sequence |
| Input → видимое изменение | p95 ≤200 ms | Разрешённый synthetic target, correlated visual response |
| Idle ownership | 30 min без необъяснённого fence | ≥1000 heartbeats, clear outcome counters |
| Reconnect | ≤5 s после восстановления достижимости | Fresh frame + separately admitted owner; без replay |
| Cleanup | Нет второго encoder/owner после 100 cycles | Native resources, socket count, retained memory |

Для WAN/TURN цели назначаются после измерения маршрутов; локальный результат не
переносится на Интернет. Не обещать «кадр в кадр без задержки»: capture, encode,
network, decode и display имеют ненулевую длительность.

Baseline снимается на одном APK, одном browser, одинаковой resolution/FPS/scene
в последовательных контрольных окнах legacy и prototype. Сохранять exact builds,
server location, selected pair, CPU/RSS, байты и elapsed clocks. HTTP readyz/TLS
handshake не является заменой native ACK или media latency benchmark.

Не вычитать Android uptime из browser performance.now: часы независимы. Локальные
stage durations и сквозной RTT измерять отдельно. Для visual correlation нужны
явный sequence/target response и frame identity, которых текущий общий video/
receipt path пока не предоставляет.

Матрица обязательных проверок:

| Сеть/событие | Проверка и доказательство |
| --- | --- |
| Same PC, LDPlayer | Candidate pair и фактический путь; повторить NAT/firewall варианты |
| LAN, разные hosts | Direct connection, no VPS media bytes, endpoint RSS/CPU |
| WAN, обычный NAT | Direct либо честный relay; время setup и input/native/visual latency |
| CGNAT/symmetric NAT | Рабочий TURN fallback; relay traffic/quotas/expiry |
| UDP blocked | TCP/TLS TURN fallback либо явный unsupported, без бесконечного spinner |
| IPv4/IPv6/mixed | Reachability, no false direct, bounded failed candidates |
| Wi-Fi/VPN route change | ICE restart + owner fence + no stale gesture |
| Offline/revoked token | No continued unauthorized input, bounded partition policy |
| Packet loss/jitter/congestion | Queue age, terminal handling, video recovery |
| Mobile portrait/landscape/background | Correct geometry, no hidden held touch or leaked capture |
| Two to four emulators | Aggregate CPU/GPU/RAM/network, fair control, no unlimited peers |
| Multiple viewers/task | One input owner, separate view permissions, predictable fan-out |

Без direct/relay/native measurements прототип не проходит gate, даже если один
скриншот и один click работают. Fixture tests проверяют protocol, но не заменяют
реальные браузеры, Android, NAT или sustained capture.

## 10. Ресурсы и стоимость relay

Планировать серверную нагрузку по **одновременным** views и bitrate. Например,
один relay stream 2 Mbit/s даёт около 0,9 decimal GB payload в час на принимающем
участке и столько же на передающем. Четыре таких stream — около 3,6 GB/hour в
каждом направлении. TURN/network overhead и тариф учёта добавляются отдельно.
Это арифметический сценарий, не текущий bitrate парка или облачная цена.

Direct уменьшает обязательный VPS media traffic, но не encode/decode нагрузку
эмулятора/браузера и не дисковые расходы Docker build/cache. Много direct viewers
одного APK повышает fan-out; сначала ограничить peer count, затем оценивать SFU.
Thumbnail wall на 128 устройств не должен создавать 128 полноценных encode peers.

До пилота задать caps peers/device/viewer/org, encoder instances, TURN allocation,
signaling buffer, stats retention, diagnostic export и image/cache storage. Проверять
рост RSS/handles/disk после циклов, не только instantaneous free memory.

## 11. Порядок реализации и откат

1. **Baseline / reliability:** локализовать текущий idle ACK и capture behavior;
   текущая UI-коррекция сообщений не закрывает эту задачу.
2. **Contracts / admission:** grant/ownership/revocation/transport generations,
   negotiated capability/schema, resource budgets, dependency provenance.
3. **Isolated media prototype:** один PH011, feature flag default off, view only;
   APK libwebrtc и browser PeerConnection, authenticated signaling, no fleet OTA.
4. **Direct control adapter:** существующий native supervisor и exact receipts;
   control/task/recorder ownership, failure injection и no replay.
5. **TURN / network matrix:** restricted networks, auth expiry/quotas и measured costs.
6. **Viewer integration:** DeviceStream/Studio shared transport selection,
   mobile layouts, diagnostics, fallback and known/unknown error semantics.
7. **Finite pilot / soak:** pinned builds, 2–4 authorized emulators, resource
   baseline/delta, explicit criteria and rollback rehearsal.

На каждом этапе отдельный source/test/artifact/install/live receipt. Production
приёмка требует gate всего workflow, не окончания всех будущих 41 продуктовых задач.
Нельзя считать этот документ разрешением открыть public TURN или сделать mass OTA.

При откате выключается feature flag для новых сессий; активный direct input
сначала retire/release с известным или явно unknown результатом. Новый legacy
owner создаётся после проверки release/expiry. Не переносить gesture, MOVE,
text или native receipt между transport generations. Старый серверный просмотр
остаётся резервом, но ухудшение маршрута явно показывается пользователю.

## 12. Открытые решения до production

* libwebrtc source/AAR/ABI admission, hardware encode capability и APK размер.
* Capture adapter: новый media encoder или доказанный existing H.264 integration.
* Authority TTL/renewal/revocation partition bounds и общий task/API/viewer owner.
* Actual same-PC LDPlayer reachability, restricted network/TURN topology/region.
* Wire schemas, priorities, single/multiple control channels и stale packet handling.
* Measured latency, video quality, cost, CPU/RSS/disk limits и browser compatibility.
* Общий frame/action correlation для playback/recorder и visual assertions.

**Итог статуса:** исследование, план и diagnostic echo prototype подготовлены.
Direct media/control не реализован и не установлен; SF26-05 / EP-020 / EP-029 остаются OPEN.
Первоначальный deferred brief сохраняет свою дату; текущий указатель ведёт сюда.
