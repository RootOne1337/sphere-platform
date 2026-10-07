# Непрерывный ввод: привязка к захвату, APK и исключение конкурирующих действий

Дата: **7 октября 2026**, Asia/Yekaterinburg. Продолжение
[native canary](CONTINUOUS-TOUCH-NATIVE-CANARY.md) и
[супервизора](CONTINUOUS-TOUCH-SUPERVISOR.md); продуктовый пункт SF26-05 остаётся
**OPEN**. Документ описывает source и отдельный debug canary, а не установленное
управление на 3015.

## Поставка и граница включения

Обычная сборка не создаёт continuous controller и не регистрирует его callbacks.
`SPHERE_CONTINUOUS_INPUT_CANARY=true` включает только debug-вариант; Gradle
отказывает при попытке создать release artifact с этим флагом. Backend parser,
multiworker owner lease, доставка receipts зрителю, привязка к декодированному
видеокадру и browser pointermove ещё не реализованы. Старый backend не выдаёт
новую capability. Установленные UI af9054e / API a41c4e6 / рабочий APK сохраняются.

Готовность native helper отдельно от наличия захвата: probe возвращает
`injector_ready=false`. Только проверенный startup ACK отдельного процесса
разрешает принимать DOWN. Этот ACK означает запуск инжектора; INPUT status 1
означает принятие Android input dispatcher, а не отображение кадра в браузере.

## Захват и координаты

[CaptureInputSession](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/CaptureInputSession.kt)
содержит новую случайную epoch при каждом запуске захвата, физические и
закодированные размеры, rotation. Даже перезапуск с тем же разрешением получает
другой идентификатор. Поворот на 180 градусов также делает прежнюю сессию
недействительной, хотя ширина и высота не изменились.

[StreamingManagerImpl](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt)
возвращает snapshot только для активного захвата с совпадающими физическими
размерами и rotation. Stop сначала удаляет input session и синхронно закрывает
admission listener, затем освобождает поверхности/кодек. Listener не делает IO
и не ждёт завершения root-процесса под lifecycle lock.

Координаты проверяются на границе frame, без clamp и двойного масштабирования.
При преобразовании 1280×720 → 960×540 точка (400,200) становится (300,150).
Точка за пределами frame, неправильный epoch или frame size отклоняются.
Native helper повторно проверяет актуальную физическую геометрию перед вводом.

**Оставшаяся граница:** текущий видеопакет v1 не содержит capture epoch. Нельзя
включать продуктовый continuous режим, пока браузер не доказывает соответствие
предлагаемой сессии именно своему показанному кадру. Совпадение разрешения и
приход JSON offer не являются таким доказательством.

## Единственный владелец ввода

[DeviceInputOwnership](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DeviceInputOwnership.kt)
принадлежит одному AdbActionExecutor. Обычные root mutations и пользовательский
shell используют короткие reservations; полный DAG держит reservation от
начала до завершения, включая ожидания, Lua и паузу. Вложенные действия DAG
не освобождают reservation всего сценария.

[OwnedTouchPipeFactory](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/OwnedTouchPipeFactory.kt)
получает exclusive owner **до** подготовки нового инжектора. Если занят DAG
или primitive, root helper не запускается. Во время владения continuous
отклоняются обычные tap/swipe/key/text/shell и новый DAG; live legacy callbacks
обрабатывают `DeviceInputBusyException` и не выпускают его в application scope.

Успешный flush старой root-очереди не доказывает завершение её `input swipe`.
Поэтому перед стартом helper выполняется отдельный FIFO barrier с уникальным
marker, deadline 1000 ms и ограниченным чтением stdout/stderr. Он не запускает
root, если старого процесса нет. Отсутствующий marker, смерть процесса с pending
input или ранее неизвестный результат запрещают handoff. Команда не повторяется.

Reservation снимается только при известном teardown. При неизвестном handoff,
cleanup или cancellation остаётся fence, без автоматического reset и замены
владельца. Это намеренный отказ от новых воздействий; проверка native reset,
SIGKILL и восстановления после restart APK ещё обязательна для продукта.

Readonly capture/status не становятся произвольным shell внутри continuous
сессии. Внешние ADB/другие приложения root не участвуют в этом arbiter; такой
контроль не означает изоляцию от всех процессов Android.

## Синхронный admission и соединение

[ContinuousInputController](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousInputController.kt)
вызывается непосредственно из authenticated WebSocket callback до общего
coroutine dispatch. Он проверяет числовые типы без преобразования строк,
owner/epoch identifiers и точный набор полей. Для MOVE не создаётся coroutine
или root-процесс. Supervisor сохраняет предыдущие ограничения: четыре pending
samples, резерв для terminal, age 500 ms, local lease 1500 ms и coalescing.

| Сообщение debug protocol | Поля кроме type | Значение |
| --- | --- | --- |
| `continuous_input_probe` | session_id | Предложение текущего захвата без native readiness |
| `continuous_input_open` | owner, session_id, capture_epoch, frame_width, frame_height | Новый owner; запуск одного helper после handoff |
| `continuous_input_event` | owner, capture_epoch, sequence, gesture, action, x, y | Action 0 DOWN, 1 UP, 2 MOVE, 3 CANCEL, 4 HEARTBEAT |
| `continuous_input_close` | owner | Отмена только соответствующего владельца |

Owner должен выпускаться сервером после проверки user/tenant/RBAC и lease.
Передача этих полей напрямую от браузера не разрешена данным контрактом.
Эта APK-часть доверяет authenticated server socket; самостоятельной серверной
авторизации, SQL/Redis owner registry или публичного endpoint она не добавляет.

READY проверяется после асинхронного старта: disconnect/stop во время открытия
не позволяет объявить устаревшую готовность или начать DOWN. До READY можно
обновлять lease heartbeat, но DOWN не откладывается в очередь для поздней инжекции.
Чужой owner не отменяет, не переоткрывает и не продлевает настоящий owner.

Generation проверяется перед каждой доставкой и отправкой ответа. Peer closing,
локальный reconnect и disconnect прекращают admission до позднего callback
onClosed/onFailure. Малые transient receipts имеют максимум 2048 UTF-8 bytes
и проверяют общую очередь OkHttp 1 MiB; они не сохраняются в durable journal.
Отказ outbound ACK вызывает local retirement без replay. Unknown input и RELEASE
сообщаются раздельно; отсутствие receipt не считается успешным действием.

## Проверки

[Controller tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/ContinuousInputControllerTest.kt)
проверяют движение до terminal, physical mapping, dormant default, wrong owner,
плохие поля, ту же размерность с новой epoch, смену соединения, старт с потерей
владения, отсутствие readiness, outbound loss и expiry.
[Ownership tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/DeviceInputOwnershipTest.kt)
проверяют nested DAG reservations, конкуренцию во время handoff и unknown cleanup.
[Handoff tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/AdbContinuousHandoffTest.kt)
исполняют настоящий AdbActionExecutor с fake OS process/owned FIFO marker.
Capture session и authenticated WS generation/byte budgets покрыты отдельно.

Во время первого полного прогона обнаружен startup regression: выключенная
ветка обращалась к новому capture listener. Исправление создаёт controller и
регистрирует listener только при включённом debug flag. Итоговая проверка
должна включать существующие legacy live tap/swipe tests, а не только новую ветку.

Итоговый полный локальный прогон прошёл: **958 passed / 3 skipped, 81 suites
в каждом** из `devDebug` и `enterpriseDebug`; 961 test cases на вариант,
failures/errors = 0. В этой поставке 33 новых самостоятельных случая: controller
12, ownership 8, handoff 5, capture 4, WebSocket 3, CRLF acknowledgement 1.
С предыдущими этапами это 89 различных новых случаев, выполняемых в двух
вариантах, а не 178 различных сценариев. Собран обычный devDebug APK с
выключенным canary; он не установлен. Попытка `assembleDevRelease` с флагом
canary завершилась ожидаемым отказом Gradle до создания release artifact.
[Результаты, хеши и граница приёмки](CONTINUOUS-INPUT-APK-EVIDENCE.json).

Предыдущий supervisor source `3cb9fe9ecc79f7f190c5808ea964d2578f44d64d`
прошёл Android push/PR, frontend, backend и preview CI. Это не CI текущего
изменения; его exact-source runs фиксируются отдельным последующим срезом.

## Standalone Android probe

[ContinuousInputCanary](../../../android/app/src/debug/kotlin/com/sphereplatform/agent/commands/ContinuousInputCanary.kt)
входит только в debug source set. Это отдельный root app_process entry, без
manifest component, HTTP endpoint или изменения рабочего APK. Артефакт можно
разместить во временном `/data/local/tmp/` и проверить controller → ownership →
Kotlin process pipe → native MotionEvent на независимом View receiver.
Он не запускает MediaProjection и не доказывает полный путь веб → сервер → APK.
STDIN ограничен 128 сообщениями по 2048 bytes; diagnostics не записывают файлы.

На текущем срезе оба локальных LDPlayer существуют, но ADB devices пуст и
serial emulator-5554 не доступен через platform-tools и bundled LDPlayer adb.
Параметры эмуляторов/ADB не изменялись. Новый Kotlin pipeline на Android
**ещё не принят**; прежние восемь native helper canaries не подменяют эту проверку.

Следующие обязательные шаги: реальная приёмка Kotlin pipe; безопасный reset;
server-issued multiworker lease и scoped receipts; epoch показанного видеокадра;
browser pointermove, pointer loss/blur/visibility cleanup; recorder trajectory,
Android navigation и uncertain/coalesced outcomes; latency и bounded load soak.
