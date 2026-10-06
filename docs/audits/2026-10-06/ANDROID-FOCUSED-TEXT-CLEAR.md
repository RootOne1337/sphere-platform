# Android: корректная очистка сфокусированного поля

Дата: **6 октября 2026**. Область: P1 из [аудита recorder](STUDIO-COMMAND-RECORDING.md#дополнительная-находка-apk-очистка-поля).
Версия исходников APK: **1.2.46 / 10246**. Это отдельный Android этап; установленный
UI `1c26ffc7`, API `eb7a7c26` и ранее принятые receipts не переписываются.

## Доказанный дефект

`input_clear` и `type_text.clear_first:true` в DagRunner использовали keycode 277
как CTRL_A, затем DEL. В [Android KeyEvent](https://developer.android.com/reference/android/view/KeyEvent#KEYCODE_CUT)
277 означает CUT. Последовательность могла изменить clipboard и удалить только
выделение или один символ. Нет отдельного keycode «Ctrl+A»: нужен настоящий chord.
Исходники старого обработчика закреплены raw Git hash в recording evidence.

## Изменение и границы контракта

- [RootInputBridge](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootInputBridge.java)
  запускается root `app_process` из **собственного установленного APK**. Принимает
  только `clear-focused`; не получает текст, selectors, clipboard или произвольные команды.
- [RootTextClearSequence](../../../android/app/src/main/java/com/sphereplatform/agent/commands/RootTextClearSequence.java)
  нажимает Ctrl-left/A с META_CTRL_ON/META_CTRL_LEFT_ON, отпускает их, затем Delete.
  Инъекция ждёт WAIT_FOR_FINISH. При ошибке независимо пытается отпустить каждую
  клавишу; удаления повторно нет. CUT/clipboard операции отсутствуют.
- [AdbActionExecutor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt)
  ставит helper в **ту же FIFO root-сессию**, что предыдущий tap/key. Не создаёт
  конкурирующий su-процесс, который мог бы очистить поле раньше клика.
- [RootCommandAcknowledgement](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/RootCommandAcknowledgement.kt)
  принимает только уникальный marker и exit code; deadline 5 s, суммарный drain
  256 KiB, tail 128 characters. Предыдущие stdout/stderr не сохраняются и не логируются.
  Дополнительных reader threads или файлов нет. Ожидание работает на Dispatchers.IO
  под lock владения root, не на Android main loop.
- Неизвестный исход, невалидный marker, timeout, injection failure или отмена
  инвалидируют root ownership. Не выполняются CUT fallback, автоматический retry,
  ввод замены или on_failure переход. Уже доставленную команду это не отменяет;
  результат требует проверки экрана. Lifecycle root descendants остаётся отдельным gate.
- [DagRunner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt)
  использует один adapter в обоих actions. `input_clear` сообщает
  `adapter=root-key-chord, field_verified=false` в существующем string output.
  ACK input dispatch **не подтверждает**, что произвольное приложение очистило поле.
- [R8 rule](../../../android/app/proguard-rules.pro) сохраняет динамический main entrypoint.
  Новых библиотек, assets, сервисов, accessibility grants или сетевых endpoint нет.

Android 26–33 использует InputManager, 34+ — InputManagerGlobal. Это отражает
[смену AOSP manager](https://android.googlesource.com/platform/frameworks/base/+/dc79a130f72423868cae7ef70575a669d5e4bb51%5E%21/),
[официальный keyboard input path](https://android.googlesource.com/platform/prebuilts/fullsdk/sources/android-29/+/refs/heads/main/com/android/commands/input/Input.java)
и [модификаторы Android](https://developer.android.com/reference/android/view/KeyEvent#META_CTRL_LEFT_ON).
OEM hidden-API/SELinux/root поведение требует собственной runtime проверки.
Custom canvas, IME, password/editor ограничения и неверный focus могут не поддержать
shortcut; adapter не обходит их. Очистка существующего Unicode текста не означает
поддержку Unicode **ввода** через прежний `input text`.

## Проверка и доставка

**45 focused source tests**, 0 failures/errors/skips: DagRunner 33, root adapter 4,
marker 5 и editor model 3. Проверены очистка всего модельного multiline/Unicode
текста без clipboard изменений, rejected/throwing injection, независимые releases,
FIFO root-session ownership, unknown result без retry/typing/failure route, cancellation,
partial/stale/malformed marker, exited process и bounded drain.

Это source проверки, не Android instrumented proof. Сборка обеих debug flavors,
full unit suites, signer/bootstrap verification и реальное поле Android фиксируются
следующими receipts кандидата. **Установка/OTA публикация 1.2.46 ещё не выполнена.**
Текущая fleet APK 1.2.45-dev не приобретает новый handler от обновления веба.
Общий backlog **9 принято / 41 открыто** не изменён.
