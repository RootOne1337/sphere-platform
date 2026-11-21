# PH025: установленное исправление повторного чёрного экрана

Дата: 8 октября 2026, Asia/Yekaterinburg. Приёмка завершена около 04:10 UTC+5.
Это продолжение двух исходных расследований: [decoder](PH025-DECODER-RECOVERY.md)
и [неподвижный экран](PH025-STATIC-RECONNECT.md). Их исходные срезы сохранены.

## Результат и установленные версии

На 3015 установлен reviewed UI `fcdc547627ea410e65d7ff79601dc71cdd25f343`.
APK `1.2.48-dev` / `10248` из `c62ded63639a4096fd091ea3f43e285f80a82734`
установлен адресно на **PH011 и PH025**. API остаётся
`a41c4e64bf569a7518d34606da0facbba32f77e6`.
Повторные подключения на неподвижный экран и подключение второго viewer
получили pictures без decode/render ошибок. Навигация Android после простоя
подтверждена ответами команд и визуально проверенными экранами.

PH010 и остальные APK парка не обновлялись. Continuous input в установленной
сборке выключен; SF26-05 и общий ledger **9 accepted / 41 open** не изменены.

## Две независимые причины

Первый путь: Chromium этого хоста отвергал AVC при принудительном
`prefer-hardware`. Один и тот же конечный набор реальных PH025 packets давал
0 pictures с этой политикой и 11 с `no-preference`, без ошибок во втором случае.
UI разрешает браузеру выбрать поддерживаемую реализацию и показывает один
allowlisted код последней ошибки. Причина недоступности аппаратного decoder
не установлена; исправление не требует предположения о неисправности GPU.

Второй путь: при статичном экране ImageReader не давал новых RAW callbacks.
Новый viewer получал SPS/PPS, но не IDR: 8 packets / 244 bytes, 0 pictures.
Исправленный encoder после sync request повторно подаёт последний успешно
принятый owned RAW I420 с новым PTS. Один pending refresh, coalescing и предел
4 refresh/s ограничивают работу. Cached SPS/PPS отправляются раньше IDR.
Stop, replacement codec и неизвестный результат queue operation исключают
использование старых input indices и повтор неопределённой native операции.

[Android MediaCodec](https://developer.android.com/reference/android/media/MediaCodec#PARAMETER_KEY_REQUEST_SYNC_FRAME)
определяет запрос sync frame «soon», но не обещает картинку без новых input.
Необходимость повторной подачи RAW для проверенного Google encoder — результат
контролируемого native эксперимента ниже, а не дополнительная гарантия Android API.

## Контролируемая native проверка

Один и тот же ограниченный `app_process` probe загружал encoder из baseline
10247 и candidate 10248 через APK classpath на `emulator-5554`.
Использовался настоящий `OMX.google.h264.encoder`, ровно один synthetic RAW,
затем два sync requests без новых producer images. Оба APK дали initial IDR.

| APK | Приняты sync requests | Новые pictures после двух requests | Errors |
| --- | --- | --- | ---: |
| Baseline 10247 | оба | 0, 0 | 0 |
| Candidate 10248 | оба | 1, 1 | 0 |

Probe не запрашивал MediaProjection, не устанавливал рабочий APK и не сохранял
pixels. Его результат отдельно проверен настоящим capture/viewer после OTA.
Текущая registry/hash идентичность `emulator-5554` соответствует PH011;
serial сам по себе не является постоянной идентичностью PH010.

## Настоящий браузер на 3015

| Условие | Drawn | IDR | Decode / render errors |
| --- | ---: | ---: | --- |
| PH011: повторный вход 1 | 6 | 4 | 0 / 0 |
| PH011: повторный вход 2 | 12 | 4 | 0 / 0 |
| PH025: повторный вход 1 | 6 | 3 | 0 / 0 |
| PH025: повторный вход 2 | 4 | 1 | 0 / 0 |
| PH025: второй одновременный viewer | 3 | 3 | 0 / 0 |

Во время подключения второго viewer наблюдались два video subscribers.
Captured counter остался 88 → 88, encoded вырос 114 → 117: IDR refresh
работает даже без нового физического изображения. Во время этих проверок
перезапуск capture для получения картинки не использовался.

После простоя «Недавние» дал command receipt 600 ms и настоящий экран
Recent apps; «Домой» дал receipt 480 ms и вернул launcher. Это время
подтверждения команды, **не измерение input → отображённый кадр**.
Визуальный результат и скалярные snapshots сохранены в ограниченном private
evidence directory; их SHA-256 записаны в [приёмочном JSON](PH025-STATIC-RECONNECT-ACCEPTANCE.json).

## Сборка, доставка и проверки

Candidate APK: 8 534 475 bytes, SHA-256
`a1ad28af34ba17a962cd7db5da7a3ce372262a2ea8115fc82278ceed2f9d461a`.
Package: `com.sphereplatform.agent.pilot.debug`; signer совпал с pilot baseline.
Planar input включён, GPU bridge и continuous input выключены.

Обновления выполнялись последовательно через два device-specific recovery
grants со сроком 600 s. Для каждого подтверждены terminal completion,
installed version 10248, новый heartbeat и автоматическое удаление grant.
App data не очищались; нормальный OTA-канал не переводился на candidate.
Windows, эмуляторы и API для этой установки не перезапускались.

13 новых регрессий: 12 native refresh cases и immediate-output ordering.
Stream leaf: 57 passed в каждой variant. Полная сборка точного candidate:
**979 passed / 3 skipped в каждой Dev и Enterprise**, 0 failures/errors.
UI source ранее прошёл 1820 frontend tests / 137 suites, fresh route types
и полный non-incremental TypeScript.

Все пять hosted runs source `c62ded6` завершились `success`:

- [Frontend](https://github.com/RootOne1337/sphere-platform/actions/runs/37698011637).
- [Backend](https://github.com/RootOne1337/sphere-platform/actions/runs/37698011792).
- [Android PR](https://github.com/RootOne1337/sphere-platform/actions/runs/37698011686).
- [Android push](https://github.com/RootOne1337/sphere-platform/actions/runs/37698004584).
- [Preview](https://github.com/RootOne1337/sphere-platform/actions/runs/37698011757).

## Практические границы

Закрыт воспроизведённый путь отсутствия первого picture при static reconnect
на двух выбранных pilots. Это конечная приёмка, не ночной soak всего парка.
Повторное encoding owned RAW не увеличивает physical capture FPS и не
доказывает свежесть кадра после нового gesture, 20–30 FPS, frame-exact управление
или поведение всех моделей codec. Continuous routes, manual/DAG exclusion,
pointer ownership/receipts и Recorder integration требуют своей live-приёмки.

Следующий приоритет — [непрерывные жесты](CONTINUOUS-INPUT-POINTER.md),
с сохранением [capture identity](../../protocols/VIDEO-CAPTURE-V2.md) и
[scoped receipts](../../protocols/CONTINUOUS-INPUT-RECEIPTS.md).
Канонический operational статус: [CURRENT-STATE](../../operations/CURRENT-STATE.md).
