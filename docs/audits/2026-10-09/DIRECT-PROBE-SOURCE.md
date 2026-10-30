# Прямой browser ↔ APK канал: первый диагностический source canary

Дата: 9 октября 2026. Статус: **PROTOTYPE_SOURCE / не установлен / не принят live**.

[Действующие работы](../../operations/WORK-STATUS.md) ·
[Архитектура и полная сетевая матрица](../../design/BROWSER-DIRECT-TRANSPORT.md) ·
[Последняя проверенная установка](IDLE-CONTROL-UX-INSTALLED.md).

## Запрос и границы результата

Последующий прямой запрос пользователя разрешил начать разработку browser↔APK
соединения. Более раннее «пока только исследование» перестало быть действующим
ограничением. Это отражено в machine registry и проверке документации.

Первый этап проверяет путь WebRTC и RTT между браузером и Android JNI. Он не
передаёт видео, не запускает захват, не открывает injector, не выполняет Android
команды и не переводит существующий поток или сценарии на новый транспорт.
Управление не получает новую authority от DataChannel OPEN.

Написаны реальные интеграционные точки всех трёх компонентов. Браузерные тесты
используют fake RTCPeerConnection; серверные — два runtime и общий FakeRedis с Lua.
Android протокольные тесты JVM и native-linked debug сборка не доказывают actual
JNI execution, успешную ICE pair, device RTT или отсутствие утечки native RSS.
Эти live gates ещё впереди. Текущий idle timeout остаётся открытым.

Рабочие UI d70f55c6 / API d720232e / APK PH011 1.2.49-dev в этом этапе не заменены.
Локальный debug APK является build check, не OTA artifact и не принятой установкой.
Счётчик продукта остаётся 9 принято / 41 открыто; CHAT-15 перешёл в PARTIAL.

## Карта исходников

| Компонент | Исходник | Ответственность |
|---|---|---|
| Wire | [direct_probe_protocol.py](../../../../backend/websocket/direct_probe_protocol.py) | Только одно application SDP, SHA-256 DTLS fingerprint, строгие поля и лимиты |
| Server runtime | [direct_probe_runtime.py](../../../../backend/websocket/direct_probe_runtime.py) | Redis TTL, exact owner deletion, ephemeral PubSub, связь с agent WS session |
| Browser endpoint | [direct/router.py](../../../../backend/api/ws/direct/router.py) | First-message JWT, tenant/device/RBAC, allowlist, reauthorization |
| Android ingress | [android/router.py](../../../../backend/api/ws/android/router.py) | Reply session берётся из authenticated WS handler |
| Browser peer | [directProbe.ts](../../../../frontend/src/features/stream/directProbe.ts) | Offer/answer, 20 echo samples, выбранная ICE pair и cleanup |
| Diagnostic UI | [DirectProbeDiagnostics.tsx](../../../../frontend/src/features/stream/DirectProbeDiagnostics.tsx) | Флаг, ручной start/stop, RTT отдельно от input/video |
| Android peer | [DirectProbeTransport.kt](../../../../android/app/src/directProbe/kotlin/com/sphereplatform/agent/direct/DirectProbeTransport.kt) | Один native peer, bounded mailbox, generation и monotonic TTL |
| Ordinary APK | [Stub transport](../../../../android/app/src/noDirectProbe/kotlin/com/sphereplatform/agent/direct/DirectProbeTransport.kt) | Нет WebRTC JNI/фабрики в обычном source set |
| Native contract | [DirectProbeProtocol.kt](../../../../android/app/src/main/kotlin/com/sphereplatform/agent/direct/DirectProbeProtocol.kt) | Echo nonce/sequence, строгий SDP |
| Supply chain | [verification-metadata.xml](../../../../android/gradle/verification-metadata.xml) | SHA-256 нового native AAR |

## Admission и wire contract

Endpoint: `/ws/direct-probe/{device_id}`. По умолчанию закрыт. Включение требует
`DIRECT_TRANSPORT_PROBE_ENABLED=true` и непустого JSON-массива UUID в
`DIRECT_TRANSPORT_PROBE_DEVICE_IDS`. Allowlist не заменяет JWT, tenant или RBAC.

JWT находится только в первом signaling сообщении `{token}`; не в URL, SDP,
DataChannel payload или TURN configuration. Применяется текущая проверка access
token/revocation/active user/org и `stream:read`; DB session не удерживается.
Права и текущий agent session перепроверяются не реже пяти секунд после admission.

Browser offer: `{type: direct_probe_offer, sdp}`. Client не назначает org, user,
worker, agent generation или probe session. Server генерирует nonce 128 бит,
связывает org/device/user/viewer worker/current agent session в Redis с TTL 30 s.
Единственный lease на device защищён SET NX; удаления сравнивают полное значение.

Agent offer: `{type: direct_probe_offer, session_id, sdp, ttl_ms}`. Он доставляется
только в текущий authenticated Android socket. Никакой offline queue, reconnect
replay или автоматической попытки пересогласования нет.

Agent answer: `{type: direct_probe_answer, session_id, sdp}`. Принимается только
от соответствующего device/current agent session и возвращается точно в viewer
worker. Повторный answer, expired lease и старая agent generation отвергаются.

Channel label: `sphere-probe-v1`; ordered/reliable. Payload: `SP1 <nonce> <sequence>`.
APK возвращает тот же payload; никаких JSON Android-команд эта grammar не содержит.
Sequence строго 1..64, browser отправляет максимум 20. Пакеты не journaled.

Nonce связывает echo с согласованным peer; DTLS fingerprint передаётся по
авторизованному signaling. Это не финальная renewable media/control grant schema.

## Лимиты и закрытие

| Ресурс | Лимит / поведение |
|---|---|
| Browser | Один peer, один канал, один pending echo, 20 samples |
| Setup | Browser 12 s; server first auth / offer по 10 s |
| Lifetime | Browser 30 s; server Redis lease 30 s; APK remaining TTL ≤30 s |
| Echo | Раз в секунду; pending на следующем tick завершает probe без retry |
| APK echo | Не чаще 100 ms; максимум 80 bytes, последовательность ≤64 |
| SDP | UTF-8 ≤32768 bytes, одно application media, ≤64 candidates |
| Signaling envelope | ≤36864 UTF-8 bytes после JSON encoding |
| Viewer runtime | Восемь active/reserved admissions на worker; reservation до первого await |
| Agent runtime | Восемь transient pending records на worker, expiration before next admission |
| Native callbacks | Mailbox 32, один actor; idle actor не имеет polling timer |
| WS SDP send | Generation fenced; existing 1 MiB queue budget сохранён |
| Redis/WS operation | До 2 s; listener failure retires, без resubscribe/replay |

При manual stop, unmount, изменении device/token или скрытии страницы browser
закрывает timers/channel/peer/signaling. Invalid echo, backpressure, setup deadline,
disconnect или signaling loss завершают probe; недоставленный echo не повторяется.

APK закрывает peer/channel/factory при TTL, current WS generation mismatch,
close exact nonce, overflow/invalid message или service-scope cancellation.
Factory threads не сохраняются после probe. Коллизии/late callback и native
dispose при callback overflow требуют реального JNI stress test до admission.

Если explicit close не проходит через Redis/WS, native monotonic TTL ограничивает
срок peer. Lease не продлевается. Старое закрытие не удаляет нового owner.

## Dependency admission: что проверено

Кандидат: `io.getstream:stream-video-webrtc-android:146.7.0`, non-repackaged,
Java namespace `org.webrtc`. Maven Central metadata на проверенном срезе объявлял
этот release для данного artifact. Более новый publisher release
145.19.0-repackaged — другая координата/namespace; номера не сравниваются как
одна линейка. README sample 137.0.1 не использован как указатель latest.

[Publisher и build workflow](https://github.com/GetStream/stream-video-android-webrtc),
[Maven artifact](https://central.sonatype.com/artifact/io.getstream/stream-video-webrtc-android),
[Официальный DataChannel API](https://webrtc.org/getting-started/data-channels).

AAR скачан из Maven Central; размер 49,890,907 bytes. SHA-256:
`8650f62de6bf8ae930ce72a70e999f1ce2a1dfb87dddca2bbe0cb3317dc6fd28`.
POM 1221 bytes, SHA-256:
`cfe1664acdf5f4cb1e757417f784c442f9294a4db625a4389ea68949402f18a4`.

| ABI | Native `.so` bytes |
|---|---:|
| armeabi-v7a | 6,955,720 |
| arm64-v8a | 12,465,592 |
| x86 | 12,941,200 |
| x86_64 | 16,480,336 |

Inspected `classes.jar` подтверждает PeerConnection/DataChannel/SdpObserver API.
Gradle verification фиксирует AAR checksum. Старые dependencies сохраняют прежнюю
trust policy; это не полная verification metadata всей dependency graph.
Build требует `SPHERE_DIRECT_TRANSPORT_CANARY=true`; тогда выбирается отдельный
source set/dependency. Release-shaped задачи с этим флагом запрещены.
Обычные builds выбирают stub; production signer/key/catalog не менялись.

Publisher source repo/build recipe изучены; точная Chromium/libwebrtc revision,
воспроизводимость binary, полный third-party notices/SBOM и native advisories
не установлены. GitHub release lookup для 146.7.0 вернул 404, тогда как Maven
artifact существует. Поэтому checksum admission не объявлен production provenance.

## Выполненные source проверки

1. Backend direct protocol + runtime/route tests, existing continuous runtime,
   stream bridge и keyframe viewer: 76 passed. FakeRedis Lua проверяет SET NX, atomic
   exact TTL/compare/delete, два worker,
   cross-tenant rejection, reconnect, expiry, late close, admission race,
   allowlist/default-off, unauthorized route и listener failure cleanup.
2. Frontend full suite: 1956 tests / 140 suites; type-check passed. Новые шесть
   тестов проверяют auth-only signaling, echo, timeout/no retry, wrong nonce,
   late callback, 20-sample cleanup, selected pair и исключение IP из отчёта.
3. Android isolated debug canary: native-linked `assembleDevDebug` и два
   `DirectProbeProtocolTest` проходят после final callback lifecycle changes.
   Обычный stub debug APK также собран; WebRTC JNI exclusion проверен по ZIP entries.
   Fresh ordinary APK: 8,535,835 bytes; JNI и `Lorg/webrtc/` DEX symbols отсутствуют.
   Canary APK: 57,736,648 bytes, четыре JNI ABI. При local incremental переключении
   canary→ordinary ZIP сохранил около 49 MB неиспользуемых байтов; повторная упаковка
   нового generated APK убрала их. CI canary теперь начинается с clean. Это build
   artifact эффект, не атрибуция постоянного расхода SSD или Docker runtime.
4. Ruff/mypy проверяют новые Python boundaries; full hosted CI является отдельным
   доказательством exact commit, не результатом этих локальных запусков.
5. Machine registry/docs checker различает PROTOTYPE_SOURCE и installed media;
   source evidence не может поднять статус в production accepted.

## Оставшиеся gates и следующий шаг

1. Source-pinned normal/canary builds и exact CI; не устанавливать случайный
   disposable CI-signature APK поверх рабочей установки.
2. Изолированный pilot APK на одной согласованной машинке; проверить ABI/JNI,
   фактическую выбранную ICE pair и 20 echo samples; screenshot + raw receipt.
3. Повторить 100 connect/close/expiry/reconnect циклов; RSS/native threads/handles,
   malformed/extra channels, overflow disposal и callbacks после retirement.
4. Этот этап использует host ICE без внешнего STUN/TURN. Same-PC эмулятор за NAT
   может не пройти. Неудача не означает недопустимость WebRTC; потребуется
   последующий admission разрешённых STUN/TURN и сетевой матрицы.
5. Peer OPEN / low echo RTT не принимаются как native input или frame latency.
   Следующий adapter должен использовать реальные native receipts и ownership,
   единый capture owner и один encoder, channel backpressure/geometry fences.
6. Сохранить browser/session revocation и task/API handoff. Контроль в direct
   transport не должен обходить supervisor или зависеть от одного server worker.
7. До release: полная provenance/SBOM/notices/advisories, auth/abuse/revocation,
   media/control network matrix, resource gates, compatibility и rollback.

Данные этого canary не доказывают устранение исходных задержек или обрывов.
Существующая блокировка неизвестного касания и отсутствие replay сохранены.
