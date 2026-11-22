# Непрерывное касание: Android-инжектор и независимая приёмка

Срез **7 октября 2026, после18:47 Asia/Yekaterinburg**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Связано с **SF26-05 / EP-017,020**, [исходным исследованием](../2026-10-06/CONTINUOUS-INPUT-INTEGRATION.md)
и [продолжением Studio](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md).

**Статус: native foundation / standalone canary. Новый режим ещё не включён в вебе.**
На3015 остаются UI **af9054e** и API **a41c4e6**. Основной APK на тестовом
`emulator-5554` остался **1.2.47-dev /10247**. Java-инжектор проверен отдельно
через `app_process`; это не доставка нового APK и не browser→server latency test.
SF26-05 и общий ledger **9 accepted /41 open** остаются открытыми.

**Следующий source этап:** [APK mailbox/supervisor/private pipe](CONTINUOUS-TOUCH-SUPERVISOR.md)
реализован отдельно; runtime-интеграция ещё открыта. Native source1dccd05 прошёл
exact CI37632496375/37632506124 (Android),37632506201 (frontend) и37632506071
(backend). Это smoke/source validation, не установка continuous capability.

## Доказательство поведения до отпускания

Приёмник — отдельное одноразовое Android-приложение с обычным `View.OnTouchListener`.
Он считает реальные `MotionEvent`, независимо от подтверждений инжектора.
До UP приёмник зарегистрировал **DOWN=1, MOVE=5, UP=0, CANCEL=0**.
После UP — **DOWN=1, MOVE=5, UP=1, CANCEL=0**.
Это непосредственное доказательство MOVE во время удержания, а не нескольких
завершённых `input swipe` и не имитации движения в браузере.

[Точные snapshots, подтверждения и SHA-256](CONTINUOUS-TOUCH-NATIVE-EVIDENCE.json).
Время ACK означает результат InputDispatcher; оно не доказывает отрисовку
кадра или завершение обработки Android-приложением.

| Настоящий canary | Результат |
| --- | --- |
| DOWN→пять MOVE→проверка до UP→UP | Пять MOVE приняты самим View до UP |
| Закрытие stdin владельца при удержании | View получил один CANCEL, UP не синтезирован |
| Молчание владельца | Локальный watchdog отменил touch; время записано в evidence |
| Повтор sequence | Отказ и CANCEL; повторный MOVE в View не поступил |
| Неподвижное удержание с десятью heartbeat | Удержание дольше lease; MOVE/UP не синтезированы |
| Частичный пакет без завершения | Reader не помешал watchdog отменить touch |
| Неправильный protocol magic | Процесс завершился с отказом; View получил CANCEL |
| Изменение display960×540→950×530 при удержании | Geometry check отказал; CANCEL подтверждён; размер восстановлен |

Диагностический receiver после проверок удалён, helper JAR удалён после сверки
SHA-256, исходный launcher возвращён на передний план, `wm size reset`
подтверждён. Ни рабочий Android-агент, ни игры/данные других приложений не
переустанавливались. SQL, OTA, backend и frontend этими canaries не заменялись.

## Реализация

- [RootTouchSession](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTouchSession.java):
  один палец, монотонный downTime, строгая последовательность и gesture ID,
  bounds, lease1500ms, local geometry checks, fail-closed unknown outcome.
- [RootTouchBridge](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTouchBridge.java):
  отдельный привилегированный `app_process`, обычный Android `MotionEvent`
  с `TOOL_TYPE_FINGER`/`SOURCE_TOUCHSCREEN`, default display0, закрытые stdio pipes.
  Есть только reader и один watchdog с периодом100ms; нет сети, файлового лога,
  сохранения кадров или root-запроса при обычном запуске APK.
- [RootTouchWire](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTouchWire.java):
  фиксированные поля, bounded hex framing, строгие ACK, без произвольных строк,
  shell-команд или размеров массива из входа.
- [Builder probe](../../../scripts/pilot/build_touch_probe.py): компилирует
  малый helper/опциональный receiver в новый путь; ничего не ставит на Android.
- [Canary receiver](../../../scripts/pilot/android/TouchCanaryActivity.java):
  один перезаписываемый файл менее1KiB; без скриншотов и растущего журнала.
- [Регрессии](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/RootTouchSessionTest.kt):
  независимая модель injection failure после возможной доставки и отмены;
  отсутствие replay, bounds, gesture/sequence fencing, framing и timestamps.

Для Android API34+ выбирается `InputManagerGlobal`, раньше — `InputManager`,
как в существующем RootInputBridge. Реальная приёмка выполнена только на
доступном Android9/LDPlayer; поддержка API34+, других OEM и non-root устройств
этим не подтверждена. Reflection failure не превращается в успешный input.

### Почему не установлен целый scrcpy server

В предыдущем исследовании scrcpy5.0 был первым кандидатом, а не принятой
зависимостью. Для этой ограниченной single-finger операции расширен уже
существующий подход Sphere: встроенные Android input API в приватном root
helper. Upstream-код и binary не копировались, второй video encoder не появился.
Это уменьшает текущую поверхность интеграции, но не отменяет обязанности
проверять скрытый Android API на каждой реально поддерживаемой платформе.
Scrcpy остаётся отдельным кандидатом для более широкой совместимости.

Android-поведение проверено по первичным источникам:
[MotionEvent](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/view/MotionEvent.java)
и [InputManager](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/main/core/java/android/hardware/input/InputManager.java).
Здесь mode1 — `WAIT_FOR_RESULT`: разрешение dispatch, без ожидания завершения
обработки приложением. Mode2 в прежнем text-clear path сохранён.

## Ошибка совместимости, выявленная расширенным canary

Исходный бинарный вариант прошёл короткий MOVE-тест, но сломался в более
длинном heartbeat-тесте. Канал `su` на этом эмуляторе превратил byte LF в CRLF,
в частности на sequence10. Следующий ACK оказался сдвинут. Успех короткого
теста не был объявлен полной приёмкой.

Теперь25-byte payload передаётся как ровно50 lower-case hex characters +LF;
17-byte ACK —34 characters +LF. Допускается только один дополнительный CR
непосредственно перед LF. Цифра, length, magic и status проверяются строго;
никто не вырезает случайные CR из бинарных данных и не ищет magic в мусоре.
Пакеты с байтами10/13, truncation, плохими символами и лишним содержимым
проверяются отдельно. Исправленный источник повторно прошёл семь input
canaries и отдельный geometry canary.

Одновременно исключено ложное нарушение monotonic clock при соревновании
reader/watchdog: uptime читается после взятия того же session lock, под которым
изменяется состояние. Timestamp браузера в Android-событие не передаётся.

## Локальный контракт v1

Big-endian payload внутри фиксированной hex-строки:

| Поле input | Размер / правило |
| --- | --- |
| magic | uint32 `0x53544931` /STI1 |
| sequence | positive int32, строго больше предыдущего; gaps для coalesced MOVE допустимы |
| gesture | int64, возрастает для каждого нового DOWN |
| action | uint8:0DOWN,1UP,2MOVE,3CANCEL,4heartbeat |
| x,y | int32, physical pixels, каждый внутри проверенной геометрии |

Heartbeat содержит gesture текущего удержания или0 в idle. CANCEL сохраняет
точку последнего фактически отправленного input. Новый DOWN не заменяет
удерживаемый палец. Неизвестный результат инвалидирует helper: автоматического
повтора DOWN/MOVE/UP нет. Положительный CANCEL очищает local held state.

ACK содержит magic`0x53544131`, sequence/int32, status/uint8, device uptime/int64.
Status:0ready,1dispatcher-accepted,2heartbeat-accepted,3cancelled,4expired,
5rejected,6unknown. Watchdog сообщает sequence0; packet ACK — sequence пакета.
`ready` означает инициализацию adapter/geometry; это не health assertion для
произвольного приложения и не receipt от backend.

Lease1500ms и tick100ms — параметры локального watchdog. Измеренный timeout
относится к здоровому InputDispatcher в конкретном canary. Зависший Binder,
kernel, SIGKILL самого helper и авария всей ОС не имеют этим этапом доказанного
hard deadline или подтверждённого release. Супервизор должен сохранять unknown
и выполнить проверенный reset до разрешения следующего управления.

## Проверки финального источника

`testDevDebugUnitTest` и `testEnterpriseDebugUnitTest`: **по895 tests,892 passed,
3 skipped,0 failures/errors,74 suites**. Новая suite содержит **23** выполненные
регрессии в каждом варианте; это не46 различных test cases. Полный локальный
прогон завершён после framing fix, за3m47s. Builder прошёл Ruff/mypy и собрал
7310-byte helper; exact SHA-256 и resource preflight сохранены в evidence.
Release/R8 smoke build и проверки других вариантов относятся к отдельному CI,
не выдаются за локальные runtime canaries или установленную capability.

Финальный canary выполнялся с:

```text
./gradlew :app:testDevDebugUnitTest :app:testEnterpriseDebugUnitTest
python scripts/pilot/build_touch_probe.py --sdk <SDK> --java-home <JDK> --output <fresh-helper.jar>
```

Builder сам не ставит APK/JAR на устройство. Диагностический receiver собирается
отдельно флагом`--receiver` и требует отдельной debug-подписи; он не является
агентом Sphere и не должен распространяться на парк. Совместимость root stdio
обязательно проверяется на выбранной платформе, включая sequences10/13;
короткий однократный tap этого не доказывает.

## Что ещё требуется для включения в карточке устройства

1. APK supervisor с одним owner и bounded/coalesced MOVE queue; без coroutine
   на каждое движение. UP/CANCEL должны иметь гарантированное место и порядок.
2. Связать lifetime helper с агентом, capture epoch, geometry, socket generation,
   disconnect/service stop и приоритетом DAG. Проверить crash/reset отдельно.
3. Server-issued lease с tenant/user/session fencing между workers; актуальные
   права и результат APK, без SQL roundtrip на каждый mousemove.
4. Capability/version/geometry negotiation и маршрутизация ACK. Старый APK
   остаётся в discrete mode; root flag не включает capability автоматически.
5. Browser DOWN/MOVE/UP/CANCEL, bounded rate/backpressure, blur/visibility/
   lostpointercapture cleanup и отсутствие replay после reconnect.
6. Recorder сохраняет trajectory/timing и uncertainty либо явно блокирует
   запись неподдерживаемого continuous input; кривую нельзя тихо заменить swipe.
7. Installed end-to-end canary на local/remote: MOVE до UP в самом Android,
   loss/rotation/owner competition, реальные capture FPS, отдельные
   submit→dispatch и submit→correlated-frame distributions.

Ни один из этих семи пунктов не объявлен выполненным данным standalone этапом.
