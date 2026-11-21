# Проверка конкретного PNG: исходные пиксели PH011

Дата: **6 октября 2026**, UTC. Установлены UI `1c26ffc7`, API `eb7a7c26`;
PH011 — Agent **1.2.47-dev / 10247**, SDK28. Новые UI исправления ниже ещё
не установлены. [Факты и контрольные суммы](NATIVE-PNG-PIXEL-EVIDENCE.json).

## Файл, указанный пользователем

Проверен именно `sphere-414ce0e9-4b93-4f96-b9ca-ee675f53835e-dc4f98b956364287bb5157d9bee5450f.png`
из локальной Downloads, а не прежний снимок PH010 или кадр видеопотока.
Device ID совпал с карточкой **auto-ph-011** и ранее проверенным ADB mapping
на `emulator-5554`. Live UI сообщает версию 10247. Read-only `wm size` дал
**960×540**, `wm density` — **160**. Настройки Android не менялись.

| Проверка | Результат |
| --- | --- |
| Файл | 236 486 B; 960×540; RGBA, 8 bits на канал |
| PNG структура | IHDR, sBIT, 29 IDAT, IEND; все CRC верны; хвоста нет |
| pHYs / eXIf | Оба отсутствуют; DPI в файле не задан |
| SHA-256 файла | `1dd467f72b8838020922687ddf4f09a8f7e3b5b4226893cb44af37b55dd388d7` |
| SHA-256 декодированных RGBA | `4b54e5abfc8927f7e9fa6c25a4c58d1c58585f062c201771d581d4c8eec6792b` |
| Backend correlation | Тот же device/snapshot ID, native endpoint, HTTP200, 10/10 RPC |
| Capture completion | 16:50:12.366814 UTC; 6714 ms; cleanup подтверждён |

В этой версии endpoint вызывает отдельный `screencap -p`, читает файл блоками
и проверяет SHA Android. Browser проверяет тот же SHA перед созданием Blob;
скачиваемые bytes не проходят canvas/video encoder.
[Service](../../../backend/services/native_screenshot.py) ·
[Endpoint](../../../backend/api/v1/devices/router.py) ·
[Browser verifier](../../../frontend/src/features/devices/NativeScreenshotPanel.tsx).

Запись server trace подтверждает путь именно этого запроса. Исторические
response headers пользовательского скачивания не сохранены; повторное
утверждение о сравнении их SHA было бы необоснованным. Локальный hash файла
измерен независимо; следующая проверка сравнивает реальные декодированные pixels.

## Независимое сравнение с несжатым Android RAW

В **16:58:01 UTC** выполнены два последовательных read-only захвата того же
неподвижного launcher: `adb exec-out screencap -p` и `adb exec-out screencap`.
Получены новый PNG **236 267 B** и RAW **2 073 616 B**: 16-byte header и
**2 073 600 B** RGBA pixels. Геометрия/format проверены, header не входит
в сравнение. RAW не сохранён на диск; PNG и small receipt остаются private pilot
evidence. Ни stream decoder, ни PNG пересохранение не использовались.

Декодированный PNG и RAW совпали по **всем 518 400 pixels**, включая alpha.
SHA обоих pixel buffers —
`6365e2c23fb19b323a99b4d645a1a23d879e2851b6b87a15ca5023be74e9c0cb`.
Это прямое измерение отсутствия pixel loss при native PNG encoding на PH011.

Затем сравнили файл пользователя и новый native PNG: **518 274 pixels совпали**,
**126 отличаются** только внутри строки состояния, bbox `[42,5,931,19)`.
Вся область ниже status bar, `[0,24,960,540)`, **495 360 pixels**, совпала
побайтово с новым native RGBA. Часы/индикаторы между двумя захватами менялись;
несовпадение целых файлов ожидаемо и не является transport corruption.

Для этого файла деградация screenshot pixels **не подтверждена**. Проверка не
доказывает состояние всех файлов, других устройств или приложения с protected
surface. Она также не восстанавливает потерянные детали исходного рисунка,
который сам Android отображает в 960×540.

## Почему 96 DPI и малый вес не означают потерю качества

В PNG физическая плотность задаётся optional `pHYs`; без него физический размер
пикселя не определён. Этот конкретный файл не содержит значения ни 96, ни160.
Windows viewer сообщил96; это не записанная настройка APK.
[W3C PNG, physical pixel dimensions](https://www.w3.org/TR/png-3/#11pHYs).

PNG использует сжатие **без потерь**: 236 KB на диске могут представлять
2 MB RGBA в памяти без изменения pixels. В отличие от H.264/JPEG, меньший вес
такого файла сам по себе не означает ухудшение изображения.
[W3C PNG specification](https://www.w3.org/TR/png-3/).
Android `wm density` управляет интерфейсом и не требует записи того же значения
в физические metadata PNG. Добавление160 DPI не повысило бы детализацию и
изменило бы исходный SHA; native bytes сохранены без такой подмены.

## UI изменения и проверки

В source candidate:

- В карточке одного устройства убрана дополнительная команда сохранения кадра
  видео. **Исходный снимок** использует прежний отдельный Android endpoint.
- Optional diagnostic export DeviceStream называется **Кадр видео (PNG) · не
  оригинал**; tooltip предупреждает о невосстановимых потерях H.264.
- Native preview имеет **Вписать в панель / 100% · 1:1**. Native режим задаёт
  исходные width/height без ограничения шириной панели; контейнер прокручивается.
  Один pixel файла занимает один CSS pixel; browser zoom/DPR остаются отдельными.
- Переключение масштаба не вызывает API/canvas/новый Blob и не меняет download.
  При смене target/auth/freshness прежний image и Blob очищаются по прежнему lifecycle.

**49 tests / 3 suites passed**: native-screenshot, stream diagnostics,
single-device-inspection. Два новых cases проверяют неизменность download и
сброс просмотра при смене цели; существующие проверяют целостность, permission,
late responses, abort и temporary cleanup. **TypeScript passed**, 1 GiB heap.
До дополнения preview соседние Studio/stream/DAG suites дали **220 / 10**.

Новые кнопки не проверены визуально в установленной сборке: build/deploy удержан
из-за C: **Warning / Full Repair Needed** (последний read-only замер: free39.08GiB).
[Host incident и postboot acceptance](HOST-FILESYSTEM-INCIDENT.md).
После ремонта нужны dark/light, narrow viewport, scrolling и неизменный downloaded
SHA. Общая приёмка rich recorder / task artifact delivery остаётся открытой.
