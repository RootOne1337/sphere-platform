# Обычный Chromium, виртуальная сеть Android и прямой WebRTC

Дата проверки: 12 октября 2026, время измерений UTC.
Статус: подтверждённый прототип и проверяемое исправление; установка API ещё не подтверждена.

## Что проверено

На PH010 обычный Chrome с mDNS и без изменения браузерных флагов установил
WebRTC с APK59 после разрешения ровно его временного имени на Windows.
Видео и непрерывный ввод шли по этому peer; помощник участвовал только в
согласовании адреса. Все 14 DOWN/MOVE/UP получили native input ACK, включая UP;
серверных событий касания в проверке не было.

Числа зафиксированы в [отдельном срезе прототипа](DIRECT-MDNS-PROTOTYPE-OBSERVATION.json).
Это был принадлежащий проверке браузер с перехватчиком исходящего SDP;
пользовательские вкладки не изменялись. Срез не принимает установленный API,
локальную сеть ноутбука, WAN, физическую смену сети или готовность production.

Ранее [обычный Chrome без помощи](STREAM59-ORDINARY-CHROME-OBSERVATION.json)
не получил прямых кадров. Его native ICE посылал запросы без ответов;
серверный WebSocket продолжал работать. Успешный numeric-ICE тест APK59
оставался отдельным результатом и не подтверждал готовность обычной вкладки.

## Причина, которую удалось воспроизвести

Chromium скрывает локальный host candidate временным UUID `.local`.
Значение содержит действительный UDP-порт, но Android должен сначала
получить IP этого имени. В виртуальной сети эмулятора этот шаг не равнозначен
проверке Windows `localhost` или наличию доступа к Интернету.

Правильная проверка Windows получила ровно один A-ответ на собственное имя
Chrome. Он соответствовал тому же локальному интерфейсу, который успешно
использовал numeric-ICE контроль. Проверка из одного локального Android
эмулятора не получила этот A-ответ, в том числе с временным MulticastLock.
Lock освобождён; диагностический DEX удалён. Эта диагностическая среда
не заменяет измерение из процесса APK на каждой машине.

Затем в обычном Chrome заменили только адресный токен этого host candidate
результатом действительного Windows mDNS lookup. UDP-порт, ICE credentials,
DTLS fingerprint, кодек, режимы media и Android capture binding сохранились.
После этого прошли ICE, DTLS, видео и native input ACK. Это подтверждает
практическую причину отказа в проверенной конфигурации; оно не доказывает,
что mDNS является единственной причиной всех отказов на других сетях.

## Почему прежние диагностические отрицательные результаты недостаточны

У Chromium responder поддерживается одна DNS question в пакете. Ответы
передаются multicast; приём только на произвольном исходящем порту может
потерять ответ. Пакет A+AAAA с двумя questions не является корректным
отрицательным контролем этого responder.

В Android toybox `nc` данной сборки фактически не поддержал UDP. Его ошибка
не означает сетевой запрет. Новая проверка использовала DatagramSocket и
MulticastSocket, один A-вопрос, порт приёма 5353 и ограниченный срок.

Исправленная Windows-проверка послужила положительным контролем. Имена,
адреса, SDP, сетевые ключи и посторонние DNS-пакеты не включены в публичный
срез. Нельзя переносить вывод из недействительного теста в статус проблемы.

## Что делают готовые решения

| Решение | Подтверждённый механизм | Применимость к Sphere |
| --- | --- | --- |
| Parsec | Backend для согласования, STUN и encrypted peer UDP; предусмотрен enterprise relay | Подтверждает разделение согласования и media; не гарантирует P2P за любым NAT |
| AnyDesk | Прямые соединения зависят от разрешённых портов; LAN discovery использует multicast | Discovery и готовый транспорт не отменяют ограничения виртуальной сети/VPN |
| RustDesk | Native peer/relay архитектура; документированный WebSocket режим поддерживает relay | Перенос native клиента в браузер не обеспечивает тот же сетевой путь автоматически |
| Google android-emulator-webrtc | React/WebRTC и интерактивный ввод через Emulator Gateway | Готовый пример интерфейса/переподключения; gateway является отдельным компонентом |
| Pion WebRTC / mDNS | Готовые ICE/SRTP/SCTP и mDNS библиотеки | Возможный host/edge инструмент; замена Android движка сама по себе не переносит multicast через NAT |
| Текущий Sphere SDK | GetStream WebRTC 146.7.0, H.264 и DataChannel | Уже переносит видео и подтверждённый native ввод; исправляется discovery, а не весь движок |

Первоисточники, просмотренные при проверке:

- [Parsec connectivity requirements, обновление 8 июля 2026](https://support.parsec.app/hc/en-us/articles/32381460716180-Parsec-Connectivity-Requirements).
- [AnyDesk firewall, обновление 21 января 2026](https://support.anydesk.com/v1/docs/firewall).
- [AnyDesk unexpected session termination](https://support.anydesk.com/session-has-ended-unexpectedly).
- [RustDesk WebSocket restrictions](https://rustdesk.com/docs/en/self-host/client-configuration/advanced-settings/#allow-websocket).
- [Google Android Emulator WebRTC](https://github.com/google/android-emulator-webrtc).
- [Pion mDNS](https://github.com/pion/mdns).
- [Pion maintainer discussion о NAT candidates](https://github.com/pion/webrtc/issues/835).
- [Chromium mDNS responder source](https://chromium.googlesource.com/chromium/src/+/HEAD/services/network/mdns_responder.cc).
- [IETF mDNS ICE draft, §3.1–3.2](https://datatracker.ietf.org/doc/html/draft-ietf-mmusic-mdns-ice-candidates-03).
- [RFC 8445, ICE](https://www.rfc-editor.org/rfc/rfc8445).
- [dnspython message parser](https://dnspython.readthedocs.io/en/stable/message.html).

Обсуждения поддерживающих проекты разработчиков используются для механизмов
и ограничений. Сообщения пользователей на форумах служат гипотезами, а не
доказательством причины в нашем runtime. Старый IETF draft описывает mDNS;
он не представлен как новый стандарт 2026 года.

## Исправление в коде

Backend вызывает discovery только после авторизованного резервирования
конкретного device/session. Оператор явно задаёт локальный helper URL и
отдельный SecretStr-ключ; пустая конфигурация сохраняет прежнее поведение.
URL не берётся из SDP или клиентских параметров.

Helper получает версию, session nonce и не более четырёх уникальных canonical
UUID `.local`. Он не получает SDP, video, touch, ICE password, fingerprint
или пользовательский JWT. HTTP слушает Windows loopback; соединение из
действующего Docker API отдельно проверено через `host.docker.internal`.

Resolver использует готовый dnspython parser, обрабатывает mDNS cache-flush
bit, игнорирует посторонние имена и разрешает только RFC1918 IPv4.
DNS-приём ограничен 8192 байтами, 64 пакетами и коротким deadline. HTTP имеет
ограниченные body, четыре обработчика и 60 запросов в минуту. Нет файлового
кэша кадров, SDP, DNS-имён или сырых пакетов.

Backend проверяет размер ответа, тот же session nonce, исходные имена и
отсутствие лишних полей. Он меняет только candidate address token. После
await заново проверяются действующий owner и exact Redis lease; поздний
ответ закрытого или заменённого viewer не публикуется Android.

Недоступность, timeout, неподходящий ответ, redirect или отсутствие DNS
ответа сохраняют исходный SDP. Нет повторной отправки касаний, получения
чужого device lease или изменения Android data. Метрики helper outcomes и
длительности не содержат адресов и session identifiers.

Основные файлы:

- [Согласование](../../../backend/websocket/direct_probe_runtime.py).
- [Ограниченный клиент resolver](../../../backend/websocket/direct_probe_mdns.py).
- [Discovery helper для workstation](../../../pc-agent/agent/mdns_resolver.py).
- [Установка проверенного API](../../../scripts/pilot/install_reviewed_backend.py).

## Граница ближайшего маршрута

Helper должен находиться там, где доступно mDNS-имя браузера. Компонент на
этом Windows ПК помогает браузеру того же ПК и потенциально его локальной
сети. Это не возможность разрешать чужой LAN `.local` из VPS за тысячи
километров. Для такой установки потребуется workstation-side discovery
через доверенное согласование или другой подтверждённый numeric ICE путь.

После согласования media и непрерывный input идут между браузером и APK.
Helper не является локальным video relay. Центральный сервер продолжает
проверять право доступа и срок media/control grant.

RTT 0–1 мс в сети и native ACK 12–17 мс не равны полной задержке картинки.
Jitter buffer, capture, encoder, decoder и отображение измеряются отдельно.
Нельзя обещать нулевую задержку, 60 FPS при захвате 30 FPS или универсальный
P2P при CGNAT, firewall и запрете локальных маршрутов со стороны VPN.

## Проверки перед принятием установки

1. Exact source CI и packaged API image без rebuild после проверки.
2. Helper health и own-name resolution из реально установленного Docker API.
3. Новый обычный Chrome без numeric flag, без SDP interceptor и exposeFunction.
4. Прямые video counters, native DOWN/MOVE/UP ACK и ноль серверных touches.
5. Повторное подключение и management/view переключение с новым owner.
6. Те же проверки через Tuna origin, включая assets и авторизацию.
7. Неподвижный экран, sustained cadence и отсутствие coded-chain regression.
8. Helper failure: установленный peer продолжает работу; новый handshake
   сохраняет исходный SDP и пользуется существующим fallback.
9. PH030 в LAN и при физической смене сети — отдельная ещё не принятая проверка.
10. WAN/NAT/TURN и shared input — отдельные OPEN, не закрываются этим документом.

В момент записи документа установка нового API ещё не принята. Старые
JSON-срезы остаются неизменными; последующий runtime результат должен иметь
собственный срез и обновить текущий registry, не переписывая историю.
