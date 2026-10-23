# Веб-запись маршрута и три нативных контакта

24 октября2026. **Состояние: реализация в коде, полный runtime-допуск открыт.**
Это продолжение0.8.1, а не новая версия motor worker; worker остаётся0.8.1.
Кандидат Android:1.2.89/10289. Установленная по прежней квитанции версия88 не
выдаётся за новую. APK89 не собрана/не установлена; новые GitHub jobs не запускались.

## Реализовано

- Из карточки и потока доступен отдельный web teaching workbench: явный connect,
  калибровка стика и действия, WASD, Shift, независимая мышь/камера, пробел,
  закреплённые Start/Stop/Escape, качество через существующий device-wide control.
- Один capture-only presence и один авторизованный WebRTC peer; original encoded
  H264 копируется до декодера и сохраняется worker в OPFS. Весь видеопоток через
  backend не копируется. Сбой не переключает ввод на другой транспорт.
- Три stable pointer IDs на одном downTime; POINTER_DOWN/POINTER_UP с правильными
  индексами Android. Снятие одного контакта сохраняет остальные. Стик получает
  один DOWN в центре, далее MOVE до отпускания клавиш. Key repeat не создаёт тапов.
- Explicit JSON opt-in `touch_open.contact_protocol=1`, затем `touch_contact_event`
  с pointer_id0..2/action0..2; handshake/status включают max_pointers3. Старый25-byte
  private pipe остаётся прежним; внутри action16+4*id+baseAction и CANCEL_ALL28.
  Старые участники не могут отправить новые действия без opt-in; полный teaching
  резервирует физический ввод от других участников. Видеопросмотр сохраняется.
- На старой APK отсутствие контактов не маскируется тремя single-pointer жестами.
  Auth/capture-bound grants, native lease1500мс, strict sequence, epoch/geometry,
  uncertainty fences и подтверждённое освобождение сохраняются.
- Browser driver: latest MOVE coalescing только внутри одного контакта;
  очередь≤8, возраст команды200мс, кадра250мс, ACK500мс, heartbeat300мс,
  close confirmation2500мс. Нет replay/rearm после blur/disconnect.
- Bounded H264/index/input journal, per-unit SHA-256, COMPLETE последним;
  viewer с временной шкалой, проверкой файлов и экспортом. Нет вечного архива
  снимков; запись только по явной кнопке оператора.

## Выполненные проверки

1. Scoped Java8 javac + Kotlin1.9.23/JUnit, JVM≤512MiB:35 тестов
   RootTouchSession/RootContactState, затем72 теста shared controller/arbiter/mailbox/
   ProcessTouchPipe — **107 passed**. Java Bridge компилирован против android-35.jar.
   Неизменённый AndroidRemoteKeyboard разрешён из прежних devDebug classes через
   friend-path; эти тесты не выполняли Android IME. Это **не полный Android Gradle CI**,
   не dex/APK/R8/signature и не физический MotionEvent на устройстве.
2. Full frontend Jest:185 suites/2648 tests passed на промежуточном дереве;
   после добавления UI tests:3 новых targeted suites/17tests passed (14 из них
   уже входят в прежний full suite). TypeScript `--noEmit --incremental false` passed.
   Окончательная source-bound локальная квитанция доставки будет отдельным addendum.
3. Worker tests проверяют отсутствие файлов до Start; IDR/header gate; исходные
   байты/90k timeline; отказ COMPLETE при pending/unknown/clock regression;
   bounded disk queue; запрет перезаписи папки. Driver tests проверяют три контакта,
   удержание/коррекцию/heartbeat, закрытие и отсутствие replay после неопределённости.
4. Визуально через CUA просмотрен **статический layout fixture реального компонента**:
   обычная узкая панель и вложенные1440/390 layouts. Wide показывает настройки
   рядом с видео, narrow — ниже; controls вне картинки. Это не авторизованный
   production UI, не реальное видео/игра, не end-to-end browser capture.

## Блокирующие условия и незакрытые проверки

Последний Android resource preflight:available8228933632bytes (~7.66GiB),
required12GiB, `ram_headroom_low`, `buildAllowed=false`. Guard не ослаблялся;
host/emulator не перезагружались, память чужих процессов не освобождалась.
Нативные focused tests обходом guard полного APK не являются: APK не собиралась.

Остаётся обязательным: локальный полный Android gate и APK89 package/sign/admit,
адресная установка PH011; полная source-bound frontend admission/install; настоящий
WebRTC encoded-transform H264 capture с реальным браузером и APK; native3-contact
hold/release; фактические FPS/frame gaps и повтор после game restart. Account
library, общий importer worker/browser,3D, route controller/arrival не реализованы.
Product9accepted/41open/50 не изменяется.

Инструкция оператора и формат:
[TEACHING-WEB](../../operations/TEACHING-WEB.md). Новый режим не меняет VPN,
игровые файлы, серверные аккаунты, настройки разрешения эмулятора или старые записи.
