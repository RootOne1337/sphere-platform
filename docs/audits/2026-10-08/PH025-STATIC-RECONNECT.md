# PH025: ключевой кадр при повторном входе на неподвижный экран

## Область и статус

Это второй независимый путь чёрного экрана, обнаруженный после исправления
выбора WebCodecs decoder. Положительный первый запуск не закрывает повторный
вход. Установка APK и окончательная live-приёмка фиксируются отдельным срезом;
до него результат source/tests не считается установленным исправлением.

## Установленный веб и воспроизведение

На 3015 установлен reviewed runtime исходников `fcdc547627ea410e65d7ff79601dc71cdd25f343`.
Все четыре hosted CI этого source прошли. Frontend: 1820 tests /137 suites;
backend: 3302 passed,37 skipped,229 subtests. Проверенный installer заменил
только UI; 45 остальных container identities/image/start/status и SHA-256
OTA-каталога сохранились. API остаётся `a41c4e64bf569a7518d34606da0facbba32f77e6`.

PH025 (`b410464a-5f26-4803-a756-7840cc17b128`, APK 10245) при первом входе
дал 11 drawn frames без decode/render ошибок. После «Недавние» счётчик дошёл
до32, после «Домой» до49. Receipts 574/494ms подтверждают ответ Android-команды,
а не время input→picture. Это не доказательство стабильных 20–30 FPS:
во время движения отчёт APK показывал около5 FPS физического захвата.

При следующем быстром disconnect/reconnect на статичном launcher:

- Capture оставался активным; Android total encoded/captured52 не изменился.
- Новый viewer получил8 packets /244 bytes:4 SPS и4 PPS.
- IDR,delta,decode submitted,output,drawn: **0**.
- Decode/render errors:0/0; через10s появился first-frame timeout.

Значит исправление browser decoder успешно, но в этом случае отсутствует
сам picture packet. Пользователь независимо подтвердил повторный чёрный экран.
Для временного восстановления адресно перезапущен только захват PH025;
браузер затем показал70 drawn /0 decode errors. Это третий scoped capture
restart этого расследования; он не считается постоянным исправлением.
OS,Docker backend,эмуляторы и Android application data не перезапускались/не очищались.

## Причина в native encoder

Planar capture передаёт новые RAW изображения через ImageReader. Неподвижный
экран не обязан создавать новые callbacks. `MediaCodec.setParameters` с
REQUEST_SYNC_FRAME просит IDR для следующего native input, но сам RAW input
не создаёт. Повтор cached SPS/PPS не заменяет picture.

Реальный ограниченный `app_process` probe загрузил encoder из установленного
APK10247 на `emulator-5554` и использовал настоящий `OMX.google.h264.encoder`.
Ровно один synthetic RAW дал один initial IDR. Два последующих sync requests
были приняты, но оба дали **0 новых pictures**, без ошибок codec. Screen capture
permissions не запрашивались; рабочий APK не устанавливался/не менялся, image
bytes не сохранялись. В текущем реестре APK10247 с этим hash подтверждён у
auto-ph-011; serial не используется как постоянная идентичность PH010.

## Изменение

`H264Encoder` после sync request подаёт в MediaCodec последний успешно
принятый RAW I420. Буфер I420 уже принадлежит converter: дополнительный
полноэкранный cache, PNG, screenshot request и compressed-frame replay не нужны.
При нехватке native input остаётся только один pending refresh; callback
продолжает его при освобождении буфера. Requests coalesce; предел4 refresh/s.
До первого успешно принятого RAW нельзя подать неинициализированный cache.
PTS строго растут, даже если новый producer PTS меньше refresh PTS.

Stop удаляет pixel ownership,pending request и timestamps до освобождения
кодека. Старый callback не получает индексы replacement session. Неизвестный
результат native queue operation блокирует повтор: native failure сообщается
один раз, дальнейшие raw/refresh submissions до восстановления отвергаются.
Ошибки deferred callback не выходят из codec Looper.

`StreamingManagerImpl` сначала ставит cached SPS/PPS в transport queue,
затем запрашивает IDR. Немедленный encoder output не должен обогнать параметры
fresh decoder. Test имитирует именно синхронный output внутри sync request.

## Проверки и ограничения

12 новых native cases покрывают first frame,одинаковые пиксели,busy admission,
quota,PTS,невалидный buffer,retired callbacks,замену codec,отказ parameters и
неопределённый исход source/cached queue. Полный default unit run до последней
ordering регрессии: **978 passed /3 skipped,83 suites в каждой из Dev и Enterprise**.
Ordering regression и окончательный candidate проходят отдельную проверку.
Latest stream leaf с ordering case:57 passed в каждой из двух variants.
[Машиночитаемый срез](PH025-STATIC-RECONNECT-EVIDENCE.json).

Probe source: [PlanarViewerRefreshProbe.java](../../../scripts/pilot/android/PlanarViewerRefreshProbe.java).
Сборка: `build_codec_probe.py --probe PlanarViewerRefreshProbe` с явными SDK,
Java home и новым output path. Только synthetic RAW/числовые counters;
используется APK в CLASSPATH, не установка. Сравнение candidate с baseline
обязательно до canary; успешное admission не считается picture output.

Повторная native encoding исходных pixels не является новым физическим
capture. Capture FPS/counters этим фиксом не увеличиваются. Эти refresh кадры
не доказывают continuous input→fresh capture, frame-exact latency или качество
любой другой модели codec. Continuous routes/ownership/receipts/Recorder и
общая SF26-05 остаются открытыми; автоматическое массовое обновление отключено.

См. также [предыдущий decoder fix](PH025-DECODER-RECOVERY.md),
[текущее состояние](../../operations/CURRENT-STATE.md) и
[контракт capture identity](../../protocols/VIDEO-CAPTURE-V2.md).
