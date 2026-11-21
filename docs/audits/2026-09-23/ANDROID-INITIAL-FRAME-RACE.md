# AUD-161 · Android пропускал первый кадр экрана при запуске VirtualDisplay

**23 сентября 2026 · P1 operational · source fix проверен; remote runtime ещё OPEN.**

[Предшествующая маршрутная диагностика](REMOTE-INGRESS-FAILOVER.md) ·
[Fleet observability](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) ·
[Acceptance record](../../operations/PILOT-ACCEPTANCE.md)

## Влияние

Для удалённых устройств веб показывал «Подключение» и чёрный экран. Команда
запуска захвата и системный Android-индикатор могли появиться, но сами по себе они
не подтверждают передачу пикселей. Наблюдавшаяся серверная сессия приняла только
SPS/PPS и EOS, без IDR/P picture slices; декодировать такой поток невозможно.

Это дефект источника кадров на Android, найденный по живому симптому и воспроизведённый
на уровне production-класса. Он правдоподобно объясняет случай со статичным первым
экраном, но пока нельзя заявлять, что он единственная причина пропажи кадров у
удалённого Ростелеком/LDPlayer. Для этого нужна canary-установка с измерениями на
каждой границе.

## Доказательство и причина

До fix порядок в `StreamingManagerImpl.start()` был таким:

1. APK устанавливал `ImageReader.OnImageAvailableListener` и создавал
   `VirtualDisplayManager`.
2. Вызов `createDisplay()` подключал `ImageReader.surface`; Android мог сообщить о
   первом buffer ещё до возврата этого вызова.
3. `streaming = true` выставлялся только после возврата.
4. Listener сначала проверял `!streaming` и возвращался **до**
   `acquireLatestImage()`. Следовательно, первый buffer не читался и не кодировался.

На неподвижном домашнем экране новый buffer может долго не появляться. Тогда APK
сохранял живой command WebSocket, а viewer получал codec configuration без картинки.
Это согласуется с наблюдением; оно не устанавливает точное время callback на
удалённом устройстве.

Доказательства сохранены локально и не содержат чувствительных значений:

- До fix новый `StreamingCaptureLifecycleTest` синхронно вызывает listener изнутри
  mock `VirtualDisplayManager.createDisplay()`. Тест падает на утверждении, что
  capture должен быть активен к моменту первой выдачи кадра; callback не доходит до
  acquire/render. Red output: `.local-pilot/remote/aud160-capture-order-red.log`.
- После fix тот же сценарий проходит в `devDebug` и `enterpriseDebug`: полученный
  `Image` скопирован, нарисован в encoder surface и ровно один раз закрыт.
- Отдельный тест заставляет `createDisplay()` выбросить исключение и подтверждает,
  что менеджер возвращается в inactive, закрывает `ImageReader`, останавливает
  encoder и освобождает display manager.
- Существующие lifecycle cases проверяют параллельные stop/copy, callback после
  stop, устаревший callback после restart и идемпотентный stop.

## Изменение

В `StreamingManagerImpl` проверка идентичности capture session остаётся до получения
кадра, чтобы callback предыдущего запуска не трогал новые ресурсы. Активный флаг
теперь устанавливается непосредственно перед `createDisplay()`. Listener получает
ранний buffer; если сессия успела остановиться, он закрывает acquired `Image` в
`finally`, не отправляя его в encoder. Исключение создания VirtualDisplay запускает
полный `stopInternal()` и затем передаётся вызывающему коду.

Изменены:

- `android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt`
- `android/app/src/test/kotlin/com/sphereplatform/agent/streaming/StreamingCaptureLifecycleTest.kt`
- `android/version.properties` — 1.2.13 / 10213

## Проверки

На Windows локально:

```powershell
cd android
./gradlew.bat --no-daemon `
  :app:assembleDevDebug :app:assembleEnterpriseDebug `
  :app:testDevDebugUnitTest :app:testEnterpriseDebugUnitTest
```

Результат: сборки обоих debug APK успешны; **621 тест на flavor, 0 failures,
0 errors, 1 intentional skip**. Skip — существующая проверка public discovery,
которая требует непустой baked server URL, тогда как тестовые Dev и Enterprise
варианты собираются с пустым baked management URL. В каждой flavor targeted
`StreamingCaptureLifecycleTest`: 7/7 passed. Полные test reports и логи остаются в
игнорируемом `.local-pilot/remote/`, а не в Git.

Предыдущая фактическая transport-проба подтверждает, что local viewer WebSocket
открывается, но одна реальная 40-секундная сессия auto-ph-006 получила четыре
маленьких NAL (SPS/PPS/EOS), всего 122 bytes, без картинки. Ранее локальный APK
через тот же Quick Tunnel передавал IDR/P frames. Это делает Android capture/encode
границу важной для проверки до обвинения туннеля. WSS acceptance со стороны
локального dev-хоста не исключает проблем отдельного WAN/ISP маршрута.

## Release и runtime gate

Локально собранный пилотный APK 1.2.13-dev / 10213 прошёл проверку package,
versionCode, SHA-256 и пилотной подписи. SHA-256:
`8a481f07ea81202ff3ee3809cb3e9f0ea2fd25035e281f05ed1da00818cbe11d`. Он остаётся
локальным кандидатом: удалённое устройство его ещё не установило, а каталог OTA
не менялся. Пилотная подпись не является production-релизной.

### Повторная проверка живого удалённого устройства — 23 сентября 2026

В bulk live-status snapshot от 16:33 UTC PH006 имеет `online`, живую
WebSocket-сессию и heartbeat возрастом 4,3 секунды. Значит, отсутствие
изображения в этой проверке нельзя объяснить отсутствием регистрации устройства.
При этом предыдущая 40-секундная viewer-сессия через новый pilot gateway получила
HTTP 101, но только четыре маленьких transport frames общим размером 122 байта.
В них было шесть NAL units: SPS=2, PPS=2 и EOS=2; ни одного IDR/P NAL не пришло.
Браузеру нечего декодировать. Это подтверждает
отсутствие картинки до decoder/render границы и согласуется с потерей первого
неподвижного ImageReader buffer.

На интервале backend 16:20–16:29 UTC записано 10 новых авторизаций PH006, каждая
вытеснила предыдущую WS-сессию; в последующем срезе новые сессии появлялись
примерно раз в минуту. В Android logcat есть `SSLException` с `Connection reset
by peer`. В логах работающего `cloudflared` нет потери зарегистрированных tunnel
connections; найден один `context canceled` при завершении входящего запроса около
16:28 UTC, примерно за две секунды до очередной авторизации. Этой корреляции мало,
чтобы доказать, что сброс инициировал Cloudflare: остаются edge/origin, сеть
удалённого ПК, прокси-цепочка и клиентская причина.

Один безопасный интерактивный `echo`-запрос к устройству завершился HTTP 504, так
что текущий управляющий канал не позволяет подтвердить установленную версию APK
или дистанционно применить кандидата. Последний сохранённый снимок каталога OTA
показывал `dev` 1.2.9 / 10209. Кандидат 1.2.13 не добавлялся в общий каталог:
`UpdateCheckWorker` автоматически устанавливает любой более новый релиз для
совпадающих platform/flavor, поэтому такая публикация затронула бы не только PH006.

Cloudflare документирует поддержку WebSocket, но позиционирует Quick Tunnel как
средство тестирования и разработки без SLA и ограничивает его 200 одновременными
in-flight запросами; Cloudflare также рекомендует heartbeat для долгоживущих
WebSocket-соединений. См. [Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/),
[WebSockets](https://developers.cloudflare.com/network/websockets/) и
[Tunnels FAQ](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/).
Это основание не принимать Quick Tunnel как производственный SLA-механизм, но не
доказательство, что именно он блокирует кадры PH006. Предыдущий локальный тест
WSS прошёл, а решающий тест — IDR/P, принятый очередью APK, дошедший до backend и
декодированный браузером на новой APK — пока заблокирован отсутствием безопасного
таргетированного OTA: текущий release catalog не поддерживает device/cohort scope.

**Текущий статус: runtime fix ещё не принят.** Source fix и тесты прошли, но до
точечной установки, приёма первого кадра и короткого наблюдения стабильности
массовое OTA на 20–32 устройства остаётся NO-GO.

Для этого canary нужно коррелировать одну временную шкалу:

1. Android `ImageReader` callback / acquired image / frame render count.
2. MediaCodec output: SPS/PPS, IDR/P count, FPS и ошибки codec.
3. WebSocket binary queue: попытки, принято локальной очередью и отказано.
4. Backend ingress: полученные binary bytes/NAL kind по текущей session generation.
5. Viewer: доставленные binary frames и фактический browser decoded-frame timestamp.

Позитивный результат требует новых picture NAL на backend и первого свежего
decoded frame в вебе, без нового crash в Android buffer. Если encoder формирует
кадры, а queue их не принимает — исследовать APK/WebSocket backpressure. Если queue
принимает кадры, а сервер их не видит — тогда A/B независимого ingress оправдан.
Если backend получает IDR/P, но browser не декодирует — проверять framing/decoder.

До установки и runtime-проверки на одном удалённом canary, затем короткого
наблюдения стабильности, **массовое обновление 20–32 устройств не принимать**.
Cloudflare/Quick Tunnel не менялся; в signed discovery, OTA catalog и GitHub config
не публиковался новый маршрут. Старый Compose и `sphere-tunnel` не затрагивались.

## Остаточный риск

Robolectric подтверждает ordering contract, но не исполняет MediaProjection,
ImageReader native buffers или vendor MediaCodec. Поэтому тест не доказывает
runtime-fix на LDPlayer и не подтверждает работу на Android 10–15 физических
телефонах. OTA download/recovery, первое реальное изображение, длительность
стабильного стрима и WAN packet loss остаются отдельными приёмочными воротами.
