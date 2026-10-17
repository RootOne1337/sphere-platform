# Android ICE counters: ограниченная диагностика native peer

Дата: 10 октября 2026, UTC+5. Source/test этап после
[конечного отказа ICE](DIRECT-PROBE-NETWORK-CANARY.md).
[Действующие работы](../../operations/WORK-STATUS.md) ·
[Transport design](../../design/BROWSER-DIRECT-TRANSPORT.md).

## Причина изменения

Последний browser срез показал177 ICE requestsSent и0 responsesReceived после
установки Android answer. Этого недостаточно, чтобы определить, получал ли APK
проверки браузера и отправлял ли ответы. Предположения о mDNS, виртуальном NAT,
маршруте и firewall остаются гипотезами. Новая диагностика добавляет другую
сторону измерения; она не меняет ICE servers и не исправляет сетевой путь сама.

## Что добавлено

[Native transport](../../../../android/app/src/directProbe/kotlin/com/sphereplatform/agent/direct/DirectProbeTransport.kt)
после отправки answer запрашивает `PeerConnection.getStats` из уже используемого
SDK `io.getstream:stream-video-webrtc-android:146.7.0`. Сигнатуры pinned AAR проверены
через `javap`; новая зависимость не добавляется.

[Pure reducer и бюджет](../../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeNetwork.kt)
возвращают только фиксированный JSON:

| Поля | Смысл |
| --- | --- |
| localCandidates / remoteCandidates | Число candidate stats rows |
| pairs / checkingPairs / failedPairs / succeededPairs | Число пар по наблюдаемому состоянию |
| requestsSent / requestsReceived | Суммы ICE checks в двух направлениях |
| responsesSent / responsesReceived | Суммы ICE responses в двух направлениях |
| dtlsState | Согласованное известное состояние transport rows |
| sampleAgeMs | Возраст среза к моменту обработки Android actor |

Один запрос одновременно, интервал не меньше1000ms, максимум32запроса за peer.
Ожидающий callback блокирует следующий запрос; тайм-аут не создаёт параллельную
очередь. Session TTL, generation fence, mailbox32 и retirement существующего
транспорта сохраняются. Закрытие retires stats budget; поздний callback не
публикует результат retired peer и не включает ввод.

Native report больше256rows не агрегируется. Отсутствующие, отрицательные,
нецелые и переполненные counters — `null`, а не ноль. Сумма частично отсутствующих
показателей тоже `null`. Ноль сохраняется только при полученном корректном нуле.
Несогласованные или неизвестные DTLS states также `null`. Успешная ICE-пара,
selected pair и рабочий DataChannel не выводятся из общего количества кандидатов.

Адреса, порты, RTCStats IDs, SDP, сертификаты, fingerprint и credentials не
попадают в JSON. Native report целиком никогда не сериализуется. Агрегат
пишется только в локальный Android logcat, tag `SphereDirectProbe`, событие
`native_ice_summary`. Нового WS endpoint, upload log или UI relay здесь нет.
Обычный `noDirectProbe` source set не запрашивает и не пишет эти измерения.

## Проверка исходников

[Пять новых JVM regressions](../../../../android/app/src/test/kotlin/com/sphereplatform/agent/direct/DirectProbeNetworkTest.kt)
проверяют все четыре counter directions и отсутствие закрытых полей, частичные
данные/overflow, oversized report/ambiguous DTLS, one-in-flight/rate limit и
конечный budget/late callback retirement. Они проверяют reducer и бюджет;
реальное выполнение JNI callback в emulator в этом source этапе не измерено.

- Canary DevDebug: **989 tests,0failures,0errors,3skipped,85suites**;
  `compileDevDebugKotlin` и полный `testDevDebugUnitTest` прошли за4m2s.
- Обычный EnterpriseDebug без экспериментального source set: **989 tests,0failures,
  0errors,3skipped,85suites**; compile и полный unit run прошли за4m5s.
- Первый запуск без `ANDROID_HOME` завершился до компиляции: SDK location not found.
  После задания существующих SDK/JBR paths повтор прошёл; зависимости не загружались.

Команды выполнялись offline, `--no-daemon --max-workers=2`, JVM heap1536MiB.
Private test logs/XML находятся в `.local-pilot/direct-probe-20261010/` и
`android/app/build/test-results/`; сырые Android network stats не коммитятся.

## Граница результата и следующий gate

Это **не установленное обновление APK**, не stable1.3.0 и не доказательство
работающего direct media/control. UI/API остаются369; исходный APK PH011
восстановлен, server probeoff/allowlist[], временный diagnostic UI остановлен.
Product counts9accepted/41open и legacy7 не изменены.

Следующая конечная canary должна связать browser и native counters одного окна,
проверить callback cleanup и повторный return обычного viewer. Перед установкой
нужны exact-source hosted Android CI, signed artifact admission и исходный APK
для возврата. Затем — контролируемое сравнение ICE configuration и сети;
live RTT, resource plateau, STUN/TURN credentials, native provenance/SBOM и
отдельное согласование media/control остаются открытыми.
