# AUD-145 / F32-34 · версия привязки идентичности клонов

**23 сентября 2026 · P0 / High до пилота 32 устройств · исходники и source-pinned APK проверены; удалённая приёмка открыта.**

[Fleet32 readiness](FLEET32-PREFLIGHT.md) · [Предыдущие clone/WAN доказательства](CLONE-IDENTITY.md) · [Android keyframe startup](ANDROID-KEYFRAME-STARTUP.md) · [Первый кадр в web](STREAM-FIRST-FRAME.md)

## Наблюдение и доказательство

Владелец сообщил о 20 удалённых LDPlayer-клонах Android 9 x64 и двух локальных
инстансах. В предыдущем pilot-срезе сервер показывал только три записи; журналы
общей удалённой карточки подтверждали повторные подключения и вытеснения старого
WebSocket новым. Это объясняет, почему клоны не видны как 20 независимых устройств.
Последний доступный API-снимок датирован 22 сентября и сам по себе не позволяет
утверждать, что каждый из 20 клиентов дошёл до backend: часть могла вообще не
зарегистрироваться.

До этого изменения Android выбирал постоянный MAC виртуального интерфейса, а при
его отсутствии — Android ID. Оба значения могут копироваться образом эмулятора;
стабильный serial виртуальной машины не участвовал в привязке. Если у клона совпадают
выбранный источник и скопированные preferences, backend получает одну binding и
идемпотентно возвращает одну карточку. Число online-клиентов поэтому не равно числу
устройств в UI.

Проверка без установки или изменения состояния запускала `/system/bin/getprop`
под UID установленного debug-пакета через `run-as`: на двух локальных Android 9
эмуляторах serial был доступен приложению и различался (2/2). Это подтверждает
rootless-доступность свойства на этой паре, но **не доказывает**, что 20 удалённых
LDPlayer-клонов имеют уникальные serial. Их значения не собирались и не публикуются.

Последний сохранённый crash-buffer baseline двух доступных устройств датирован
22 сентября 22:29 UTC: Android 9, APK 1.2.9-dev / 10209, по нулю marker-ов падения.
Он относится только к двум локальным экземплярам и не подтверждает состояние 20
удалённых клонов или получение ими видеокадров.

Отсутствие stream-кадра — связанный симптом, но отдельная граница отказа. Ранее
сохранённый viewer-срез содержал SPS/PPS и ноль IDR; исправления повторного запроса
keyframe в browser и удержания раннего запроса до готовности Android encoder уже
описаны в [AUD-140](STREAM-FIRST-FRAME.md) и [AUD-142](ANDROID-KEYFRAME-STARTUP.md).
Эти source-fixes не доказывают, что текущий удалённый APK выдал IDR, backend его
переслал и браузер декодировал изображение.

## Исправление

- Android отправляет `instance_binding_version=2`. Для x86/x86_64 эмулятора
  binding строится только из нормализованного `ro.boot.serialno` или запасного
  `ro.serialno`, прочитанного обычным `getprop`. MAC и скопированный Android ID
  не используются как резервная identity. Если VM serial отсутствует, регистрация
  явно откладывается с ошибкой; приложение не создаёт ложную общую карточку.
- Идентичность не вызывает `su`, не просит root-разрешение и не зависит от сети.
  При обновлении старой сохранённой MAC-based метки binding переводится на VM serial.
  Для физического устройства остаётся Android ID; неизвестное или неполное значение
  не принимается.
- Сырые свойства устройства не отправляются: backend получает только SHA-256
  binding и номер версии. Android сохраняет номер подтверждённой сервером версии
  вместе с credentials атомарно и не принимает новые credentials без ACK версии.
- Backend под блокировкой строки организации однократно переводит старую карточку
  с v1 на v2. Следующие разные v2 binding получают отдельные детерминированные
  карточки; повтор регистрации остаётся идемпотентным. Запоздавшая v1-регистрация
  после миграции получает HTTP 409, чтобы не слить устройства обратно.
- Backend должен быть обновлён **до** установки APK-кандидата. Старый backend не
  подтвердит v2; APK корректно откажется сохранять неполный ответ и может временно
  не открыть обычный командный WS. Поэтому текущий APK не следует вручную ставить
  на удалённый инстанс до backend-first canary.

Затронуты: `InstanceBindingReader`, `InstanceRegistrationGuard`,
`DeviceRegistrationClient`, `AuthTokenStore`, схема и сервис регистрации,
регрессионные тесты Android/backend, OpenAPI и `android/version.properties`.
Версия кандидата — **1.2.11-dev / 10211**, пакет
`com.sphereplatform.agent.pilot.debug`. Предыдущий APK 1.2.11-dev был собран до
ужесточения правила идентичности и считается устаревшим. Новый strict-serial артефакт
находится в приватном `.local-pilot/apk/SphereAgent-pilot-candidate-1.2.11-dev-strict-serial.apk`,
SHA-256 `401F08C191DE9B74D36AC1698C13952D694B565E9FE048E9AF64B06A628C4F53`.
Package ID, versionCode и локальная подпись проверены, сертификат совпал с pilot
baseline. Артефакт не устанавливался и не публиковался в OTA-каталог; совместимость
с подписью на удалённой станции и новый backend там ещё не проверены.

## Проверки

- `InstanceIdentityTest`: **13/13** passed в dev и enterprise. Полный Android
  `testDevDebugUnitTest`: **610 tests, 0 failures/errors/skips**;
  `testEnterpriseDebugUnitTest`: **610 tests, 0 failures/errors, 1 existing skip**.
- Backend registration regressions: **21 passed**; Ruff прошёл.
  На PR head `114c48f` Android и frontend CI прошли, но backend job остановился
  на stale `docs/openapi.json`, до backend/integration tests. Документация API
  пересобрана и повторно проверена на закреплённых CI-версиях FastAPI 0.136.3,
  Pydantic 2.9.2 и Starlette 1.3.1.
- Добавлен PostgreSQL integration regression: **32 конкурентных клона**, отдельные
  повторные регистрации и отказ устаревшему v1. Полная Alembic-схема была применена
  к отдельным временным PostgreSQL 15 и Redis 7.2, привязанным только к loopback;
  integration test прошёл **1/1**. После проверки остановлены и удалены только два
  созданных для неё контейнера. Результат был получен до завершения PR CI, см. итог
  проверок текущего head ниже.
- Source-pinned candidate собран из полного PR head
  `6788c90704319b5cf17ea0d92c7803220ba1c9a0`; `GIT_SHA` проверен внутри DEX. Файл:
  `.local-pilot/apk/SphereAgent-pilot-candidate-1.2.11-dev-6788c90.apk`, SHA-256
  `18935e44b43b2f731176677a2acf8d306821792eee0477901a4f2606a76e73b7`. Package ID,
  versionName=`1.2.11-dev`, versionCode=`10211` и v2 signer проверены; сертификат
  совпадает с локальным pilot baseline. Dev и enterprise suites: **610 тестов на flavor**,
  0 failures/errors и по одному существующему skip теста baked-route.
- Новый PR CI на head `6788c90` прошёл backend Tests (включая real-service/Redis
  persistence), APK build, frontend, Alembic, security, lint, RLS и production-image
  bootstrap. Deploy job пропущен. Кандидат не установлен, не опубликован в OTA и не
  менял pilot; от проверки подписи локального baseline нельзя выводить совместимость
  с APK на удалённой станции.

Ранние результаты на `114c48f` и `633bf34` выше оставлены только как история; они не
заменяют приёмку текущего head. Для этой проверки фактический runtime Android и
backend/stream на удалённой станции всё ещё отсутствуют.

## Критерии удалённой приёмки

1. Backend с поддержкой v2 развёрнут и healthy; проверить миграцию старой карточки
   на одной удалённой VM и безопасно зафиксировать только версию ACK, число записей
   и факт успешной регистрации.
2. Подтвердить уникальную регистрацию одного удалённого клона, после чего запускать
   следующую VM. Для всех 20 должны появиться отдельные стабильные device ID;
   reconnect не должен создавать новые строки или вытеснять соседний ID.
3. Для одного канареечного устройства сопоставить request keyframe, готовность
   encoder, факт реального IDR, получение кадра backend и первый декодированный кадр
   в browser. Android-иконка захвата или открытый WS сами по себе приёмкой не являются.
4. После canary пройти ступени 5 → 20 → 32 с проверкой reconnect, восстановления
   backend/сети, stream latency, crash buffers и нагрузки Redis. Сейчас Fleet32
   остаётся **NO-GO**.

## Master image и Android-only identity

Уточнение от 24 сентября: требуемый сценарий — запускать и настраивать APK в master,
затем клонировать этот готовый образ без повторной ручной установки. Такой master
допустим. Критично не само наличие сохранённых credentials, а то, чтобы каждый clone
прошёл rebind по собственной стабильной identity до любого использования этих
credentials. В этой ветке закрыты найденные пробелы для WebSocket, OTA, загрузки логов
и первичного enrollment-запроса; регрессии блокируют использование старого token при
недоступном rebind и не отправляют master bearer на регистрацию. Для обычной работы
не нужен отдельный Windows/Linux сервис: APK использует исходящее подключение.

Текущая реализация v2 использует VM serial на эмуляторах. На двух доступных локальных
LDPlayer 9 Android 9 instances serial различался, при этом Android ID совпадал. Это
подтверждение 2/2 локальных VM, а не доказательство поведения клона. Если клон
получает тот же serial и скопированные binding/credentials, APK v2 не сможет отличить
его от master. Массовое использование до проверки serial/binding для 3 disposable
canary остаётся **NO-GO**.

APK и backend остаются одинаковыми для телефонов и эмуляторов. Поддержка конкретной
Android image зависит от доступной APK стабильной per-instance identity: локальная
пара LDPlayer имеет разные serial, но удалённые клоны ещё не проверены. Если сам
эмулятор копирует один и тот же serial и всё app state, никакой только-серверный
алгоритм или GitHub endpoint не может узнать, что это разные VM. Оператору нужно
показать `identity_conflict`, а не скрыто свести их в одну карточку. Отдельный host
adapter остаётся необязательной интеграцией для специальных сред, а не требованием
обычного подключения.

Официальная справка LDPlayer описывает copy/modify/launch/runapp/getprop и другие CLI
команды, но не гарантирует уникальность serial клона или переносимость permission
state. Схема Android-only identity, ограничения server-side discovery,
MediaProjection и acceptance gates описаны в
[Golden image и portable clone provisioning](../../architecture/ANDROID-EMULATOR-GOLDEN-IMAGE.md).

Разрешения надо принимать по категориям. Root и package permissions проверяются
после clone; PROJECT_MEDIA AppOp не является MediaProjection session token. Приложение
всё ещё вызывает createScreenCaptureIntent(), а официальная Android документация
требует согласие для сессии и запрещает повторно применять token. LDPlayer Android 9
clone должен пройти runtime тест; Android 14+ отдельно следует своей более строгой
модели.

OTA остаётся отдельной стадией: после rebind каждый clone опрашивает catalog по
platform/flavor/version_code. Текущий пилотный каталог и выпуск должны быть сверены
до canary; публикация APK не выводится из сборки артефакта. Старые клоны и общую
карточку сохранять до инвентаризации и доказанного миграционного плана.

### Follow-up finding: enrollment inherited the master's bearer

**Severity: P2.** The shared OkHttp network interceptor automatically added the
saved device bearer to every request sent to the configured management origin.
`DeviceRegistrationClient` correctly authenticates clone registration with
`X-API-Key`, but before this follow-up the same POST also carried the master's
copied `Authorization: Bearer …` header. The backend registration route currently
authenticates with the enrollment key, so this did not by itself prove a duplicate
device record; it did violate the credential boundary and could expose the copied
device token to reverse-proxy, tracing, or request-capture layers.

- **Root cause:** automatic origin-wide bearer injection did not exclude the
  enrollment endpoint.
- **Reproduction:** `ServerCredentialScopeTest.cloneEnrollmentDoesNotReceiveCopiedDeviceBearer`
  failed before the fix because the interceptor attached the saved token to
  `POST /api/v1/devices/register`.
- **Fix:** `AppModule` strips `Authorization` on the registration POST. The request
  continues to carry only its explicit, organization-scoped enrollment key. Normal
  authenticated management requests still receive the bearer.
- **Regression:** the same test now passes and existing scope tests still verify
  bearer injection for `/api/v1/devices/me` and removal on a different origin.
- **Affected files:** `android/app/src/main/kotlin/com/sphereplatform/agent/di/AppModule.kt`,
  `android/app/src/test/kotlin/com/sphereplatform/agent/network/ServerCredentialScopeTest.kt`.
- **Residual risk:** this source-level test does not inspect the remote proxy's
  logging policy. Remote clone identity, endpoint behavior and stream acceptance
  remain open; the enrollment key itself must remain protected by the existing
  config/discovery controls.
