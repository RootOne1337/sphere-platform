# Script Studio: запись подтверждённого ввода Android

Дата: 2026-10-06. Область: часть EP-018. PR: [#19](https://github.com/RootOne1337/sphere-platform/pull/19).

## Исходная проблема и область изменения

Установленная metadata-only сборка `eb7a7c26` записывала только click/swipe
WebSocket. AndroidNavigationBar отправлял текст и keyevent через `/devices/{id}/shell`
и проверял результат APK, но этот отдельный путь не попадал в запись Studio.
Сценарий после ручной проверки мог потерять Back/Home/Enter и введённый текст.
Подтверждение APK и отправка WebSocket имеют разные контракты.

Изменение добавляет наблюдение HTTP-команды в момент отправки и её отдельный
результат. Backend endpoint, APK transport, root требования, существующие
ограничения текста, selector insert и task launch не заменяются.
Новые библиотеки и лицензии не добавлены. Это разработка Sphere поверх
существующих React Flow/ELK и компонентов, с прежним учётом авторства.

## Исходники

- [Общий контракт наблюдений и текстового канала](../../../frontend/src/features/stream/controlObservation.ts).
- [AndroidNavigationBar](../../../frontend/src/features/stream/AndroidNavigationBar.tsx).
- [Передача наблюдений через DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx).
- [SingleDeviceStream](../../../frontend/src/features/stream/SingleDeviceStream.tsx).
- [Запись и перевод в DAG](../../../frontend/src/features/scripts/studio/recording.ts).
- [Лаборатория, guards и список действий](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx).
- [Инструкция оператора](../../operations/SCRIPT-STUDIO.md#запись-действий).

## Семантика и границы

| Событие | Статус | Условие переноса |
| --- | --- | --- |
| click/swipe/wheel | transport-submitted | WS send завершился; Android выполнение не подтверждено |
| key/text отправлен | android-pending | Перенос заблокирован |
| валидный SHELL output, включая пустой | android-confirmed | key_event/type_text с исходными параметрами |
| ошибка, timeout, malformed reply, abort | android-unknown | Проверка экрана и явное удаление; без автоматического повтора |

Таймстамп берётся при отправке. Поздний ответ меняет исходную строку по
request ID, device ID, исходному времени, dimensions и command. Он не добавляет
действие после Stop/Clear или в новую auth session. Повторный submitted/result
не удваивает запись. Команды не сохраняют произвольный shell-текст: известные
keycodes переводятся в `key_event`, ввод — в `type_text` с `clear_first:false`.

Геометрия копируется с первого успешно нарисованного кадра текущего socket.
Поворот экрана во время HTTP ожидания не переписывает метаданные старой команды.
Смена устройства/session/unmount прерывает локальное ожидание, не отменяет
уже доставленную команду. Наблюдатель не может превратить успех APK в ложную
ошибку или изменить переданную команду.

Ожидание HTTP результата вычитается из следующей паузы: DAG исполнение уже
ожидает key/text. Это приближение операторских пауз, а не синхронизация с frame ID.
Неизвестные результаты блокируют весь перенос, а не исчезают из графа молча.
Лимит 200 распространяется на все действия; при превышении запись прекращается
с ошибкой, существующие строки сохраняются. Управление Android не отменяется.

Текст не выводится в строках receipts/timeline и не копируется в clipboard.
До вставки он находится только в памяти страницы; после вставки входит в DAG
и подчиняется обычному явному сохранению/экспорту/опциональному local draft.
Содержимое Android clipboard не записывается. Его keycodes остаются зависимыми
от текущего выделения и буфера; это не переносимый снимок окружения.

## Проверки и доставка

На этапе подготовки: 197 тестов в 9 suites прошли; TypeScript прошёл.
Это включает существующие stream/inspector проверки и новые tests lifecycle,
foreign/late replies, bounds, pause conversion, interrupted wait, скрытие текста,
close/run/transfer guards, auth session isolation. В существующем тесте
single-device-inspection были React `act` warnings; это не native browser logs.
Полный frontend набор после изменения: **1546 passed / 128 suites**, без
failed/pending; финальный TypeScript прошёл. После изменения только текста
подсказки отдельно проверяются builder-load/builder-contract. Ошибка вызова
несуществующего `studio-builder.test.tsx` была ошибкой пути проверки, не
провалом runtime теста; используется фактически существующий набор.
Окончательные source test/build/native receipts добавляются после проверки
конкретной сборки. До их добавления этот документ не доказывает runtime доставку.

## Дополнительная находка APK: очистка поля

В [DagRunner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt)
ветки `input_clear` и `type_text.clear_first:true` используют keycode 277 с
комментарием CTRL_A. По [официальному Android KeyEvent](https://developer.android.com/reference/android/view/KeyEvent#KEYCODE_CUT)
277 — CUT, а не SELECT_ALL. Такая последовательность может удалить только
выделение/символ, затронуть буфер и не очистить поле полностью. Это отдельный
подтверждённый кодовый дефект; исправление требует корректного input adapter и
Android runtime проверки. Новый recorder не вызывает эти ветки неявно:
записанный ввод сохраняет `clear_first:false`, CUT записывается именно как CUT.

## Оставшиеся ворота

EP-018 остаётся частично открытым: automatic selector candidates, snapshot
provenance, переносимый Unicode/IME/Accessibility input и state prerequisites.
EP-019/020 frame-correlated trace, replay и agent debug step/pause не закрыты.
Backend/API наличие действий не гарантирует поддержку каждого установленного APK.
Общая приёмка 20–30 устройств, FPS/input latency/soak и storage writer attribution
не подменяются этими source тестами.
