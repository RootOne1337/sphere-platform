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

Version 1.2.13-dev / 10213 — только исходная кандидатная версия после source fix.
Перед canary нужно проверить подписанную APK по package, versionCode, SHA-256 и
подписи; сохранить установленный APK hash и recovery route; менять только одно
однозначно выбранное тестовое устройство.

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
