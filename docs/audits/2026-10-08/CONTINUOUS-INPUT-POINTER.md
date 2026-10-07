# Непрерывные жесты: браузерный контроллер и реальная Kotlin-проверка

Дата: **8 октября 2026, Asia/Yekaterinburg**. Предыдущий серверный source:
**0a8cd9422c70c71284fa672be2a24f5de06b59cc**. Рабочая ветка PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).

**Статус: источник браузерного контроллера проверен; Kotlin → native View
проверен отдельно на Android. Непрерывное управление на3015 ещё не установлено.**
SF26-05 остаётся OPEN, общий ledger **9 accepted /41 open** не изменён.
Установленные UI **af9054e** / API **a41c4e6** и рабочий APK **1.2.47-dev /10247**
сохранены. Документ не заменяет [каноническое текущее состояние](../../operations/CURRENT-STATE.md).

## Требуемое поведение и реализованная часть

При зажатии мыши Android должен получить DOWN, затем MOVE по мере движения,
включая смену направления, затем UP при отпускании. Траектория не должна
превращаться в один завершённый `input swipe` после pointerup. Потеря фокуса,
прав, capture/socket или неизвестный результат должны отменять владельца,
без автоматического повторения движения после восстановления связи.

[continuousPointer.ts](../../../frontend/src/features/stream/continuousPointer.ts)
реализует эту последовательность и отдельный native DOM adapter для canvas.
Сейчас модуль **не импортирован установленным DeviceStream и не подключён
к публичному viewer route**. Тестирование модуля не является включением функции.

Перед `open()` вызывающий код обязан подтвердить scoped server capability и
совпадение с успешно показанным v2 кадром текущего socket. Один объект владеет
одним конкретным socket: внешняя замена socket требует уничтожения объекта.
Размер сам по себе не подтверждает capture identity. Кадр v1/неотрисованный
v2 пакет не разрешает этот режим. Браузер не выбирает owner/user/org/worker.

`touch_open` передаёт только epoch/width/height по
[серверному контракту](../../protocols/CONTINUOUS-INPUT-SERVER.md).
После acquire будущий scoped route должен выдать `touch_session`:

```json
{
  "type": "touch_session",
  "session_id": "server_issued_viewer_session",
  "owner": "server_issued_owner_nonce",
  "capture_epoch": "71532996-5c56-4a17-b931-67f66d54abde",
  "frame_width": 960,
  "frame_height": 540
}
```

Этот ответ связывает identity, **не разрешает DOWN**. Только совпадающий
`continuous_input_status` с injector STARTUP0 разрешает действия. Сервер
должен проверить authenticated APK socket и Redis binding до пересылки receipt.
Клиентская проверка receipt сама по себе не заменяет server RBAC и tenant checks.

## Границы очереди и подтверждений

| Ограничение | Поведение |
| --- | --- |
| MOVE scheduler | Один interval16ms на canvas, без task/timer на каждое движение |
| Неотправленный MOVE | Одна последняя точка, без растущего списка траектории |
| Возраст MOVE | Более100ms — точка удаляется, не проигрывается позже |
| Scheduling gap | Более500ms или обратный clock — fence даже до позднего tick |
| Heartbeat | Через250ms тишины; held gesture ID или0 в idle |
| Receipt deadline | 500ms; successful socket send не считается native ACK |
| Scalar receipt records | Максимум32; превышение отменяет owner |
| Socket buffer | Более1024B — fence; cancel не добавляется в уже перегруженный socket |
| Счётчики | Положительные31-bit sequence/gesture без wrap |
| Pointer | Один primary pointer; вторичный не меняет текущий жест |
| Capture | Canonical non-nil UUID и фактические размеры1…16384 |

UP/CANCEL отправляются сразу, заменяя одну ещё не отправленную MOVE-точку.
Новый DOWN ждёт **точный terminal receipt**. Sparse MOVE receipts могут
отражать coalescing: удаление старых scalar deadlines не означает, что все
предложенные MOVE были применены. Поздний точный terminal ACK остаётся допустимым
после более позднего heartbeat ACK, но не вызывает повторную отправку.

Native input CANCEL имеет status3; это отдельно от status1 для DOWN/MOVE/UP,
status2 для heartbeat и stage=`release`/status3 для освобождения всего owner.
Это соответствие проверено и в JS, и в настоящем Kotlin-канале. Foreign
owner/session/epoch receipts не завершают и не отменяют действующего владельца.
Unknown RELEASE6 не разрешает повторное подключение текущего контроллера.

DOM adapter обрабатывает pointerdown/move/up/cancel/lostpointercapture,
потерянную mouse button, blur, visibility и текущую control authority. Он
использует переданный существующий fit/letterbox mapper, не меняет разрешение
Android и не интерпретирует CSS-координаты как native pixels. Ошибка
setPointerCapture после DOWN отправляет одну отмену owner. Dispose снимает
все слушатели, interval и retained state. Retired owner останавливает interval
даже до unmount. Нет recorder/history/file/PNG persistence.

## Реальный Kotlin → native → независимый Android View

После восстановления доступности ADB выбран один idle локальный экземпляр
**PH010 /emulator-5554**, physical **960×540**, rotation0, density160,
Android display60Hz. Свежий read-only SQL срез не обнаружил queued/assigned/
running/paused tasks для этого устройства. Эмулятор не перезапускался;
display geometry не менялась.

Временный receiver `com.sphereplatform.audit.touchinput` установлен отдельно
и принимает настоящие MotionEvent в обычном View. Его
[source](../../../scripts/pilot/android/TouchCanaryActivity.java) хранит один
перезаписываемый файл менее1KiB. Flagged debug APK загружен только как временный
classpath в `/data/local/tmp`, **рабочий Sphere Agent не переустановлен**.

Entry point [ContinuousInputCanary](../../../android/app/src/debug/kotlin/com/sphereplatform/agent/commands/ContinuousInputCanary.kt)
вызывает реальные ContinuousInputController, AdbActionExecutor, общий
InputOwnership, OwnedTouchPipeFactory, RootTouchPipeFactory и Java-инжектор.
Отдельный driver использует fake CaptureInputSession/generation вместо
MediaProjection и WebSocketClient. Его `canary_epoch_1234/5678` не является
canonical UUID серверного wire protocol. Эта проверка **не доказывает** работу
capture v2, Application/Service lifecycle, CommandDispatcher WS connection,
HTTP permissions, multiworker delivery или нового браузерного модуля на Android.

| Десять настоящих случаев | Проверенный результат |
| --- | --- |
| DOWN → пять MOVE туда-сюда → UP | View до UP: DOWN1/MOVE5/UP0/CANCEL0; затем UP1 |
| Discrete key во время continuous ownership | Общий arbiter отклонил key; BACK не исполнялся |
| EOF stdin при удержании | View получил CANCEL1, UP0 |
| Тишина без heartbeat | CANCEL через1501ms после injector DOWN ACK |
| Same-size capture restart и старый MOVE | CANCEL1; новый STARTUP0; старый MOVE не поступил |
| Потеря connection generation | CANCEL1; старый generation не требует доставленного release receipt |
| Foreign owner MOVE | Действующий owner не отменён; последующий собственный MOVE принят |
| Duplicate sequence | Admission rejection5 и CANCEL; MOVE/UP0 |
| Explicit CANCEL3 → следующий gesture | Input receipt3; CANCEL1; следующий DOWN и UP приняты |
| Семь heartbeat2 при неподвижном удержании | Finger держался1816ms, без синтетических MOVE/UP/CANCEL |
| Burst32 MOVE → UP | Bounded coalescing: View MOVE1/UP1/CANCEL0; terminal receipt1 сохранён |

Первый и discrete exclusion выполнены в одном случае; поэтому в таблице11
строк, но **10 различных сценариев**. Пять независимых View snapshots до UP
подтвердили x **340 →180 →400 →220 →340**. Координаты View local отличаются
от physical y на смещение окна; это не изменение capture aspect ratio.

Для семи DOWN/MOVE/UP command→injector receipt private ADB roundtrip был
**5.08…50.15ms**. Это малый локальный diagnostic sample, без network relay,
browser rendering и latency distribution. Он не является p95, гарантией
production задержки или обещанием «кадр в кадр» с нулевым лагом.

Receiver удалён, temporary classpath удалён, launcher восстановлен; версия
рабочего APK до/после **1.2.47-dev /10247**. Не выполнялись main APK install,
массовое обновление, OTA, restart Docker/эмулятора, SQL mutations или изменение
UI/API. История8-case проверки сохранена отдельно. Первый private preflight
выявил fixture mistake: отсутствующий `pm path` возвращает exit1. Это исправлено
до receiver install, не было ошибкой Android-инжектора.

[Sanitized evidence, hashes и exact source CI](CONTINUOUS-INPUT-POINTER-EVIDENCE.json).
Private runner/stdout/snapshots сохранены в ignored `.local-pilot`, не в Docker
context. Приёмка на Android9/LDPlayer не заявляет совместимость иных OEM/API.

## Проверки source и следующая обязательная поставка

[64 browser cases](../../../frontend/__tests__/stream/continuous-pointer.test.ts)
проверяют движение до UP, reverse path, coalescing, loss и bounds, receipt
uncertainty, native statuses, late terminal, duplicate readiness, scheduler
gap, DOM lifecycle и cleanup. Это Jest/jsdom с mock transport и synthetic
pointer events, **не реальный browser→Android end-to-end**.

Fresh route typegen и полный TypeScript без incremental cache прошли. Полная
frontend regression suite: **1817passed /137suites**, итог записан в evidence.
Предыдущий exact server source0a8cd9 принят всеми четырьмя hosted CI runs:
Android, frontend, backend и preview. Backend **3268passed/37skipped/229subtests**,
frontend **1753tests/136suites** плюс types/build. Эти CI не включают новый
browser source этого этапа; его новый exact-source CI проверяется отдельно.

Далее требуется:

1. Подключить bounded transient agent/receipt subscriptions и startup/shutdown
   к dedicated no-replay Redis pool, с точными scope и socket identity.
2. Связать probe offer/current rendered capture с viewer acquire; подключить
   `touch_session`, STARTUP/input/release replies. Проверить fresh authorization
   cadence/revocation и серверную конкуренцию manual/DAG/discrete.
3. Подключить canvas adapter к DeviceStream и Recorder без двойной legacy
   swipe отправки. Navigation/key/text должны дождаться известного release,
   а uncertainty recording не превращаться в успешный reusable gesture.
4. Выполнить один reviewed debug canary APK/сервер/веб deploy и настоящий
   local/remote browser→server→APK→render acceptance, затем ресурсный soak.
5. Проверить known reset после unknown helper cleanup, SIGKILL/Binder stall,
   восстановление после worker/Redis replacement и документированный rollback.

До этих проверок нельзя включать новый режим массово или закрывать SF26-05.
