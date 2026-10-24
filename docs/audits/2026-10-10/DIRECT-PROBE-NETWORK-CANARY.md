# Browser ↔ APK: локализация отказа ICE и возврат обычного пути

Дата: 10 октября 2026, UTC+5. Одна конечная попытка, только diagnostic echo.
[Машинное доказательство](DIRECT-PROBE-NETWORK-CANARY.json) ·
[Предыдущая установка](BROADCAST-INSTALLED-ACCEPTANCE.md) ·
[Текущие работы](../../operations/WORK-STATUS.md).

## Что установлено измерением

**Прямой канал не открылся.** Браузер установил полученный от APK answer и
перешёл к проверке сетевого пути. Последний сохранённый срез:

| Измерение | Результат |
| --- | --- |
| ICE / DTLS | checking / connecting |
| Кандидаты браузера / APK в browser stats | 4 / 2 |
| Проверяемые / неуспешные / успешные пары | 2 / 0 / 0 из 2 |
| ICE requestsSent / responsesReceived | 177 / 0 |
| Возраст среза при остановке | 367 ms |
| Echo samples / RTT p95 | 0 / не измерен |
| Выбранная ICE-пара | Не подтверждена |
| Причина завершения | Setup deadline 12 s |

Ноль failed pairs означает состояние счётчика на последнем срезе, а не отсутствие
отказа соединения. Ноль responsesReceived относится к этим браузерным парам;
он не доказывает, где потерян отдельный пакет. Тайм-аут 12 s не является RTT.

Read-only observer авторизованного signaling зарегистрировал offer 652 bytes,
один host/mDNS candidate, затем answer 723 bytes с двумя host candidates без mDNS.
Между публикациями **463 ms**. Оба SDP содержали только `m=application` и fingerprint.
Затем зарегистрирован close. SDP-публикация и browser getStats — разные измерения;
число кандидатов в них нельзя механически приравнивать. Raw SDP/IP/ключи не
сохраняются в публичном receipt.

Это сужает отказ до установки сетевой связи: приём answer подтверждён браузером,
успешная ICE-пара отсутствует. **Конкретная причина UNKNOWN**: native-side
receipts, разрешение mDNS, маршруты, firewall и виртуальный NAT пока не разделены
пакетным сравнением. Этот результат не объясняет отдельно прежний idle ACK timeout.

## Каким вебом выполнена проверка

Рабочие UI/API остались на `369654a0be4bded35e299062badc9bfe95101f1e`.
Полный exact-source CI этой версии принят в предыдущем receipt.

В обычном frontend artifact экспериментальная панель **выключена compile-time
флагом** `NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY`. Установка исходников панели не
включает её автоматически. Это уточняет прежнюю формулировку «диагностика доставлена»:
код входит в reviewed source, но сетевые счётчики недоступны в стандартном UI.
Предыдущий датированный receipt не переписан.

Реальный срез получен во временном Next development UI на `127.0.0.1:3017`,
через loopback relay `127.0.0.1:3016`, с этим флагом. Frontend source diff относительно
reviewed369 пуст. Это **не production canary artifact** и не установка нового веба
на публичный адрес. Оба временных процесса остановлены; отсутствие listeners на
3016/3017 проверено перед публикацией receipt. Проверочная вкладка закрыта.

Следующая доставка диагностического UI должна явно фиксировать build flag,
отдельный artifact и admission; нельзя объявлять панель активной по одному SHA.

## Android и ресурсы

Изменялся только PH011, `emulator-5554`, package
`com.sphereplatform.agent.pilot.debug`, версия 1.2.49-dev / 10249.
Canary из `9ad3481c` имеет exact Android CI 37969383314 success;
Android source diff между9ad и369 пуст. SHA APK и сертификата записаны в JSON.
App data не очищались, OTA и другие устройства не изменялись.

Два среза одного native процесса:

| UTC | VmRSS, KiB | Threads |
| --- | ---: | ---: |
| 22:00:14, во время проверки | 130540 | 40 |
| 22:00:45, после проверки и закрытия viewer | 127148 | 31 |

Срез включает legacy capture, JNI и прочую работу APK. Он не доказывает отсутствие
утечки, steady CPU или ресурсный plateau. Исходный APK до установки работал другим
процессом; его RSS не используется как сопоставимый baseline canary.

**Исходный APK восстановлен в22:00:46 UTC**; SHA-256 совпал:
`6b177bcbac3bb319597630f34f88956bc79a6e0e3261508c2fe09708b393b013`.
Native canary сейчас не установлен. Данные приложения сохранены.

## Проверенный возврат обычного пути

Тот же admitted backend369 установлен с probe disabled и пустым allowlist.
Enable и disable сохранили по45 соседних контейнеров; schema head
`20261006_script_catalog_metadata` и OTA catalog hash не изменились.
JWT не отправлялся в завершающую проверку endpoint: получен4003
`direct_probe_disabled` до аутентификации.

Оба адреса,3015 и выбранный Tuna-host: readiness200/PostgreSQL+Redis ok,
build369, PH011online. Проверочный отсутствующий script после real binary presence
вернул ожидаемый404, без durable intent или Android execution. Остальные broadcast
гарантии относятся к отдельной изолированной CI-проверке202/commit/admission.

В публичном обычном viewer после восстановления получены **9 decoded/drawn frames**,
15 packets/178108 bytes; invalid/decode/render errors0. Режим просмотра, без Android
касания/клавиш/текста. Это finite video return, не steady FPS, control или latency SLA.
Отдельный cached APK `not_streaming` не принимается за свежую capture telemetry.

## Следующий инженерный шаг

1. Добавить bounded native ICE summary и сопоставить с browser counters без raw
   IP/SDP в общих логах; отличать отсутствие запроса от отсутствия обратного ответа.
2. Выполнить контролируемое host-only/STUN сравнение с явной конфигурацией, затем
   credential-bound TURN fallback и отдельной проверкой selected pair/echo RTT.
   Не менять firewall или SDP-адреса наугад.
3. Повторить same-PC/LAN/WAN/UDP-blocked сети; не переносить отрицательный результат
   loopback диагностического браузера на все пользовательские браузеры.
4. После подтверждённого канала подключать media/control к общему владельцу,
   native receipts и recorder. Сквозные задержки измерять отдельно от ICE RTT.

WebRTC использует отдельный signaling и ICE discovery; обмен SDP сам по себе не
устанавливает достижимый канал. STUN/TURN и trickle ICE предусмотрены стандартным
стеком: [официальный WebRTC guide](https://webrtc.org/getting-started/peer-connections),
[W3C stats](https://www.w3.org/TR/webrtc-stats/).

Сетевые ограничения эмулятора нужно проверять по фактической реализации.
[Android Emulator networking](https://developer.android.com/studio/run/emulator-networking-address)
описывает его виртуальный router, alias host loopback и ограничения firewall;
это **не доказательство** модели NAT конкретного LDPlayer. Read-only адресный срез
этой машинки не совпал с описанной default10.0.2/24 сетью Android Emulator.

Product: **9 принято /41 открыто**; legacy: **7 незакрытых**. Ни один продуктовый
пункт этим отрицательным canary не закрыт. Direct media/control, причина idle ACK,
полная native resource acceptance и stable APK1.3.0 остаются OPEN.
