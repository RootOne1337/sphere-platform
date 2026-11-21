# Явные диагностические ICE-профили и достижимость STUN

**10 октября 2026. Статус: проверенный source и отдельные сетевые пробы.**
Прямой WebRTC-канал, его RTT, видео и касания пока не приняты. На рабочей
установке сохраняются UI639/API369, исходный APK PH011 и выключенный direct gate.
[Машинный срез](DIRECT-PROBE-STUN-PROFILES.json) ·
[Действующие работы](../../operations/WORK-STATUS.md) ·
[Архитектура](../../design/BROWSER-DIRECT-TRANSPORT.md).

## Что изменено

Браузер и Android теперь различают три **явно выбранных профиля сборки**:

| Профиль | Настройка | Назначение |
| --- | --- | --- |
| `host` | Пустая строка, значение по умолчанию | Прежний baseline, без STUN-сервера |
| `controlled-stun` | Один `stun:<RFC1918 IPv4>:<port>` | Собственный локальный узел; canonical IPv4, порт1024–65535 |
| `public-stun` | Только точная строка `stun:stun.cloudflare.com:3478` | Отдельная диагностика через опубликованный публичный сервис Cloudflare |

Списка fallback-серверов нет. Произвольные DNS-имена, публичные numeric IP,
credentials, query/path/fragment, нестандартный порт Cloudflare и non-canonical
IPv4 отвергаются. Ошибка профиля не создаёт браузерный peer или таймер; Android
валидирует значение перед native factory. В browser/native сводку попадает имя
профиля, а не адрес локального узла. Public provider назван явно.

Это диагностический выбор, не production provisioning или выбор провайдера для
пользователей. STUN помогает получить адрес; ответ STUN не доказывает выбранную
ICE-пару, открытый DataChannel или действие Android.
[Модель WebRTC](https://webrtc.org/getting-started/peer-connections),
[RFC8489](https://www.rfc-editor.org/rfc/rfc8489.html).

Браузерные границы теперь различимы: сбор адресов8s, согласование8s, открытие
канала12s после допустимого ответа APK. Общий срок30s не продлевается. Поэтому
медленный сбор адресов больше не называется неудачной проверкой прямого пути.
До20 echo остаются верхней границей; медленное согласование может оставить меньше
времени. Stop, deadline и поздние callbacks закрывают peer/канал/WS и таймеры.
Никакие команды Android или кадры через эту проверку не передаются.

## Конечные сетевые пробы на PH011

| Проба | Наблюдение | Допустимый вывод |
| --- | --- | --- |
| Toybox `nc -u` | `Unknown option u`, несмотря на exit0 | Ошибка инструмента; это не результат UDP-пути |
| DatagramSocket → стандартный emulator host alias | Один пакет, receive timeout2s, Windows listener не получил запрос | Этот конкретный путь не подтверждён; стандартный alias Android Emulator нельзя автоматически применять к LDPlayer |
| DatagramSocket → проверенный физический private IPv4 ПК | Один пакет, receive timeout2s, listener не получил запрос | Локальный путь не подтверждён; причина потери не установлена |
| DatagramSocket → фактический Android policy gateway | Процесс завершился137; logcat того же PID показывает `PortUnreachableException`, `ECONNREFUSED` | Получен ICMP Port Unreachable; необработанное исключение диагностического app_process, не падение Sphere APK |
| Windows и Android → опубликованный STUN Cloudflare | По одному20-byte request; ответы32bytes, matching transaction/cookie/header; Android также проверил XOR-MAPPED attribute | Исходящий UDP roundtrip к одному публичному узлу доступен в этом срезе |

Последняя проба заняла конечное окно01:04:10–01:04:12UTC. Android выполнил её с
ADB shell UID, а не UID APK. DNS разрешён на Windows; оба клиента использовали
один numeric ответ. Это не проверка DNS внутри libwebrtc и не тест native
ICE gathering. Windows helper проверил header/cookie/transaction; Android
дополнительно разобрал bounded attributes. FINGERPRINT отсутствовал (`null`),
не был объявлен подтверждённым. Mapped IP/port не сохранялись в публичный receipt.

Публичный endpoint проверен по первичному источнику:
[Cloudflare connection patterns](https://developers.cloudflare.com/realtime/sfu/get-started/connection-patterns/).
Документация сервиса описывает STUN отдельно от TURN:
[Cloudflare FAQ](https://developers.cloudflare.com/realtime/turn/faq/).
Отправлены только STUN binding headers; ни auth tokens, ни видео, ни текст,
ни сценарии или идентификаторы устройств не отправлялись провайдеру.

Локальные listeners были ограничены одним endpoint, восьмью секундами и восемью
пакетами, затем закрыты. Firewall/VPN/routes/OTA/APK/рабочие контейнеры не менялись.
Малые DEX утилит оставлены как измерительные артефакты; никаких recursive delete.
Полученные ответы не объясняют прежние native remote0/pairs0 и не исключают
NAT/mDNS/VPN/firewall причину локального отказа.

## Конфигурация и границы включения

Диагностическая Android сборка требует `SPHERE_DIRECT_TRANSPORT_CANARY=true`;
`SPHERE_DIRECT_PROBE_STUN_URL` выбирает профиль. Непустой URL без canary gate
останавливает Gradle configuration. Любой direct canary по-прежнему запрещён
для release-shaped tasks. Обычный APK использует noDirectProbe source set;
проверка отсутствия WebRTC JNI/dex references в ordinary APK остаётся в CI.

Браузер требует `NEXT_PUBLIC_DIRECT_TRANSPORT_CANARY=true` и соответствующий
`NEXT_PUBLIC_DIRECT_PROBE_STUN_URL`. Непустой URL с выключенным gate останавливает
Next configuration. Этот URL является публичной частью диагностического bundle,
не местом для credentials. Нельзя брать endpoint из query params, SDP или viewer
сообщения. Auth, server allowlist и30s lease сохраняются.

Профили browser/APK пока **не согласуются в wire protocol**: coordinator обязан
сверить оба exact build settings перед пилотом. Source позволяет локальный и
public диагностические профили; credentials и TURN relay в него не добавлены.
Production потребует отдельный versioned/tenant-scoped ICE contract, выдачу
краткоживущих TURN credentials, отказ/revocation, quota и сетевую матрицу.

## Проверки и следующий gate

В source receipt отдельно зафиксированы полный frontend прогон, targeted
browser/build tests, Android profile tests и реальные Gradle denial checks.
Предыдущий полный local-STUN Android прогон993/86/3skips относится к промежуточной
версии до добавления public profile; его нельзя назвать полной приёмкой финального
public APK. Final source проходит отдельные public/default targeted проверки;
CI проверяет ordinary signed smoke, host/local/public debug profiles.

Следующий пилот: exact-source CI и signed build admission → один PH011,
явно одинаковый public STUN-профиль в browser/APK → native candidate counters,
browser selected pair и echo RTT → гарантированный возврат original APK,
probeoff/allowlist[] и закрытие временного UI. Успешный shell STUN не заменяет
этот gate. В случае отсутствия channel сохранить отрицательный результат,
проверить направление ICE checks и перейти к контролируемому TURN-профилю.
Media/control и APK1.3 остаются отдельными gates; backlog counts не меняются.

Исходники:
[Browser ICE validation](../../../frontend/src/features/stream/directProbeIce.ts),
[Finite browser probe](../../../frontend/src/features/stream/directProbe.ts),
[Panel](../../../frontend/src/features/stream/DirectProbeDiagnostics.tsx),
[Android profile](../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeIceProfile.kt),
[Native transport](../../../android/app/src/directProbe/kotlin/com/sphereplatform/agent/direct/DirectProbeTransport.kt),
[Gradle gates](../../../android/app/build.gradle.kts),
[CI matrix](../../../.github/workflows/ci-android.yml).
