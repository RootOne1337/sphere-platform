# Непрерывные жесты: подключение веба, сервера и APK

Дата: 8 октября 2026, Asia/Yekaterinburg. Source checkpoint до установки;
установленная приёмка будет записана отдельно. SF26-05 пока OPEN.

В выделенном viewer добавлен переключатель «Непрерывные жесты». После
проверенного native offer, успешно показанного v2 кадра и injector STARTUP0
canvas передаёт DOWN/MOVE/UP по мере движения мыши. Legacy click/swipe и
колесо одновременно не отправляются. Native RELEASE3 возвращает доступность
Android navigation. Потеря фокуса, capture, socket или ACK закрывает owner.
Неизвестный release не разрешает автоматически вернуться к legacy input.

Сервер связывает реальные authenticated viewer/Android routes с проверенными
lease/delivery/receipt компонентами. Один serial transient subscriber на worker
использует собственный Redis pool8, Retry0, timeout250ms. Pattern agent channel
не заменяет origin: локальный ConnectionManager snapshot, Redis presence session,
tenant, exact viewer nonce, capture и срока проверяются перед передачей.
Offer хранится только в ограниченной RAM registry64, не в offline queue.
Pub/Sub outage отключает новые жесты; video transport остаётся независимым.

Control permissions и known running/assigned task проверяются до open и каждые
750ms во время owner. Auth renewal не удерживает умерший viewer lease. Native
shared ownership независимо закрывает race с DAG и дискретными командами.
Startup/shutdown снимают subscribers, callbacks, задачи и pool. Все команды
непрерывного пути transient: нет replay или автоматического повторения UNKNOWN.

APK10249 собирается как debug canary с CONTINUOUS_INPUT_CANARY=true. Default
и release flag остаётся false. Готовится адресная установка только PH011;
normal OTA channel и остальные APK не меняются. Legacy API migration heads,
database и артефакты должны быть сохранены reviewed installer.

В Script Studio запись по-прежнему использует завершённые дискретные действия:
continuous toggle там заблокирован с объяснением. Это исключает ложное сохранение
частичного live gesture как успешно исполненного reusable swipe. Correlated
trajectory/native-pixel/XPath recording остаётся следующей отдельной работой.

Проверки до установки: two-worker probe/open/READY/MOVE-before-UP/known release,
глобальная замена APK session, wrong tenant/epoch/dimensions/expiry/extra fields,
second viewer exclusion и cleanup. Canvas regressions проверяют отсутствие
двойного swipe, known release, blur, старый APK и границу recording.

Не заявляются zero latency, frame-exact синхронизация, 20–30 physical FPS,
overnight/fleet soak или recovery после Redis replacement. ACK в UI показывает
receipt roundtrip, не input-to-picture latency. Unknown transport требует новой
видеосессии/восстановления сервера; история input после reconnect не проигрывается.

Контракты: [server](../../protocols/CONTINUOUS-INPUT-SERVER.md),
[receipt](../../protocols/CONTINUOUS-INPUT-RECEIPTS.md),
[pointer](CONTINUOUS-INPUT-POINTER.md), [capture](../../protocols/VIDEO-CAPTURE-V2.md).
