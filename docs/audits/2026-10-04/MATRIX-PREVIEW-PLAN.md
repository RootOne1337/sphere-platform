# F34 — экономичный обзор парка и отдельный видеопоток

Дата: 4 октября 2026, UTC+5. Проверены исходники `37bb436`.
Статус: **проект реализации; F34 OPEN**. Транспорт preview ещё не установлен.
Документ продолжает [журнал исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md#n10--отзыв-прав-открытого-websocket-4-октября)
и фиксирует следующий этап после исправления доступа к открытым потокам.

## Проверенные факты

| Участок | Что работает сейчас | Чего нет |
|---|---|---|
| Матрица `/stream` | Каждая открытая плитка монтирует общий `DeviceStream` | Отдельного экономичного transport/profile |
| Browser viewer | `/ws/stream/:id` регистрируется в `VideoStreamBridge` | Различения thumbnail и selected video |
| Bridge | `register_viewer` отправляет `start_stream` с quality/bitrate; binary delivery использует H.264 queue | JPEG fan-out и preview leases |
| Android capture | `StreamingManagerImpl.start` создаёт H.264 encoder; в pilot используется ImageReader/planar path | Preview-only capture без H.264 encoder |
| Команда SCREENSHOT | Возвращает путь файла внутри Android | Доставки его байтов браузеру в этой операции |
| Права | F39 отделяет просмотр от управления; N10 перепроверяет права открытого viewer | Preview endpoint с явно запрещённым вводом |

Исходники:

- [Матрица потоков](../../../frontend/app/%28dashboard%29/stream/page.tsx).
- [Активный DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx).
- [Viewer endpoint](../../../backend/api/ws/stream/router.py).
- [Bridge](../../../backend/websocket/stream_bridge.py).
- [Android capture](../../../android/app/src/main/kotlin/com/sphereplatform/agent/streaming/StreamingManagerImpl.kt).
- [Android dispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt).

Наличие других legacy DeviceStream файлов не означает, что матрица пользуется
другим transport. Отбрасывание кадров в браузере после получения H.264 не снижает
Android encoding и ingress traffic. Подмена матрицы текущей SCREENSHOT-командой
тоже не обеспечивает preview: сейчас её результат — локальный Android path.

## Ограничения Android, проверенные по первичным источникам

MediaProjection захватывает экран в Surface; ImageReader является одним из
поддерживаемых consumers. Для Android 14+ нельзя повторно потреблять один grant
для второй `createVirtualDisplay`; режимы должны учитывать lifecycle одного
захвата, callback stop/resize и foreground service. [Android MediaProjection](https://developer.android.com/media/grow/media-projection).

ImageReader требует своевременно закрывать Images; acquireLatestImage позволяет
получать последний буфер, освобождая устаревшие. Для такого поведения нужен запас
как минимум в два доступных Images. Null означает отсутствие нового изображения,
а не сам по себе разрыв сети. [Android ImageReader](https://developer.android.com/reference/android/media/ImageReader).

Следующий контракт — инженерное предложение для Sphere, а не требование Android
и не измеренный результат production. Имеющийся root bootstrap не объявляется
универсальным обходом согласия MediaProjection на обычном телефоне.

## Целевое поведение

1. Матрица получает небольшие независимые JPEG-кадры. Выбор одной машинки
   открывает существующий H.264 видеопоток с управлением и реальной геометрией.
2. Preview и видео одного устройства используют согласованного владельца capture.
   Закрытие плитки не останавливает видео другого зрителя.
3. Для preview-only H.264 encoder не работает. При совместном просмотре JPEG
   получается из ограниченного raw capture path; server не декодирует H.264.
4. Совместимость объявляется capability агента. Старый APK получает понятный
   unsupported outcome; скрытого перехода всех плиток на дорогой H.264 нет.
5. Последний кадр, его возраст, heartbeat и capture status отображаются отдельно.
   Отсутствие новых кадров не выдаётся за доказательство неподвижного экрана.
6. Ни preview, ни его diagnostics не разрешают touch/key/text. Для управления
   нужен отдельный selected-device stream с stream:control.

## Начальные бюджеты для canary

Все значения ниже предварительные; их корректируют по фактическим CPU, памяти,
байтам и latency на слабом эмуляторе 2 ядра / 2 ГБ.

| Параметр | Начальное предложение | Проверка |
|---|---|---|
| Частота | 1 JPEG/с; режим 0,5 кадра/с для плотной матрицы | Actual published/delivered/rendered отдельно |
| Геометрия | Длинная сторона ≤512 px с сохранением aspect ratio | Landscape/portrait/rotation без искажения |
| JPEG | Quality 65 как старт canary | Читаемость элементов и измеренный размер |
| Верхняя граница кадра | 256 KiB, жёсткая валидация до fan-out | Oversize отклоняется; не становится target bitrate |
| Очередь | Один последний кадр на device/consumer | Нет накопления и replay старой картинки |
| Пилот | 1 устройство → 4 → 14 → отдельный допуск 32/64 | Шаг не проходит только по unit tests |
| Активность UI | Только явно запущенные видимые плитки | Скрытая вкладка/страница освобождает leases |

Нужен отдельный aggregate byte/FPS admission для организации. 64 × 256 KiB/с —
слишком большой worst case для обычного канала; верхняя граница кадра не является
допустимым постоянным расходом. Оператор должен видеть отказ admission и actual
effective profile. Значения для тысяч устройств не обещаются без нагрузочных gates.

## Контракт между слоями

### Агент

- Объявить protocol version и поддержку preview в heartbeat/capabilities.
- Ввести bounded preview demand с capture epoch и сроком lease. Прежний
  start_stream остаётся совместимым; неизвестные поля не меняют поведение старого APK.
- Отдельно считать video и preview demand; reconnect переустанавливает актуальное
  aggregate demand, а истёкшие leases не оживают из offline queue.
- Preview-only не запускает MediaCodec. Resize/rotation сохраняют capture ownership;
  второй VirtualDisplay на использованном MediaProjection не создаётся.
- Throttle применяется до CPU copy/resize/JPEG. Нужны bounded pending work и
  освобождение Image/Bitmap/buffer при drop, stop, timeout и новой capture epoch.
- Compression не задерживает control/heartbeat. Неуспешная отправка кадра не
  переводится в durable command receipt и не повторяет старый JPEG.
- Отдельные счётчики: captured, encoded JPEG, throttle/drop, queue accepted/rejected,
  bytes, epoch, source geometry, effective interval и последняя причина остановки.

GPU и planar paths требуют явного решения по совместному capture. Нельзя объявить
готовность только по CPU path pilot, если другой flavor может выбрать GPU.
Рефакторинг capture lifecycle принимается до массовой OTA новой версии.

### Сервер

- Отдельный `/ws/preview/:device_id`, first-message authentication без JWT в URL.
- Проверять stream:read, активную identity и tenant/device ownership. Применить
  тот же отзыв просмотра, что в [N10](VIEWER-AUTHORIZATION.md).
- Viewer не принимает input/control payloads; recovery не создаёт arbitrary commands.
- Новый versioned binary envelope отличает JPEG от H.264: тип, размеры, capture epoch,
  sequence, bounded length. Точные поля и endian фиксируются до первого APK canary.
- Проверять envelope/размеры/длину до Redis publish. Не доверять произвольному
  Android device_id из пакета: ownership определяется аутентифицированным socket.
- Preview Pub/Sub отделён от H.264 reference queues. JPEG независимы; latest-only
  coalescing не требует IDR recovery. Для slow viewer предусмотрены send deadline
  и отдельный drop counter.
- Aggregate demand должен работать между несколькими HTTP workers; local dict
  не считается общей истиной. Leases очищаются при worker death и Redis outage.
- Fan-out не пишет изображения в БД/MinIO. Экспорт снимка — отдельная явная операция
  с permission/retention, без случайного накопления кадров.

### Веб

- Отдельный preview component без H264Decoder и без pointer input.
- Object URL/ImageBitmap/decoder resources освобождаются при новом кадре, смене
  устройства, identity, stop и unmount. Старый callback не рисует на новой плитке.
- Frame metadata сохраняет source и preview geometry, epoch и последовательность.
  Последний кадр не становится fresh после heartbeat или transport ping.
- Visibility/selection ограничивают subscriptions. Возврат страницы не запускает
  ранее закрытые плитки и не переводит неизвестный outcome в успешный start.
- В карточке выбранного устройства остаются H.264, Android navigation, диагностика
  доставки/декодирования и отдельный будущий XPath inspector.
- Интерфейс использует общие AdminCN-derived tokens, нормальную ширину toolbar,
  адаптивные плитки и reduced motion; browser geometry/keyboard gates обязательны.

## Порядок реализации и доказательства

| Этап | Изменение | Обязательный gate |
|---|---|---|
| 1 | Envelope и demand/capture state machine | Before/after, malformed/oversize, epoch, concurrent video+preview |
| 2 | Native preview-only + dual demand | SDK 28 pilot и Android 14+ lifecycle; отсутствие H.264 encode в preview-only |
| 3 | Multiworker preview transport | Real Redis/SQL ownership; slow viewer, worker replacement, lease expiry |
| 4 | Matrix UI и переход к карточке | Types/tests/build + real browser network/decode/geometry |
| 5 | Managed APK canary | Exact package/version/signer/SHA, one remote OTA receipt и fresh heartbeat |
| 6 | Live 1/4/14 preview + selected video | Bytes/FPS/CPU/RAM, input-to-visible для выбранного устройства |
| 7 | Допуск 32/64 и более | Длительный soak/reconnect/fault, отсутствие неконтролируемой памяти/traffic |

Нельзя считать F34 закрытым по появлению `<img>` при сохранённом ingress H.264.
При неудачном canary откатывается только его demand/profile; working selected-video
и действующий managed OTA остаются доступными. Полный rollout разрешается после
runtime и native gates, с документированным fallback для старой версии агента.

F35 XPath и F36 quality/FPS развиваются на том же capture geometry contract, но не
подменяют этот этап. AI screenshot delivery, VPN/Amnezia и универсальные project
configs сейчас не реализуются.
