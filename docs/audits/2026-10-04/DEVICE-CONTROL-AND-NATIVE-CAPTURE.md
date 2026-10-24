# Выбранное Android-устройство: управление, исходный PNG и системный профиль

> **Отчёт сохраняет утреннюю установку9716348 и исходные успехи/отказы.**
> Вечерний API/UIc1a6e79 после PC reboot, trace native capture, новый remote504
> и recovery200, размеры диска/RAM и исправление build-cache описаны отдельно:
> [host/RPC follow-up](HOST-RESOURCE-PRESSURE-AND-RPC-DIAGNOSTICS.md). Старые PNG hashes/timings не переписаны.

**Дата:** 4 октября 2026, Asia/Yekaterinburg (UTC+5).
**Исторические API и review UI этого отчёта:** `9716348018e60647dc749774acb00422d0f2cd08`.
**APK:** существующий `1.2.44-dev / 10244`; новый APK в этом этапе не выпускался.
**Review:** [3015/devices](http://127.0.0.1:3015/devices) → выбранное устройство.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Readiness](../../operations/READINESS.md) ·
[XPath и исторические отказы](UI-HIERARCHY-INSPECTOR.md) ·
[Машинные доказательства](DEVICE-CONTROL-AND-NATIVE-CAPTURE-EVIDENCE.json) ·
[Реестр исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[PR19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Что изменилось и чем подтверждено

| Возможность | Реализация и проверка | Предел принятого результата |
|---|---|---|
| Выбор XPath | Видео → точка → native Android tree → подсветка и все возвращённые атрибуты | Пользователь подтвердил рамку и правую панель; полного UIAutomator2-server нет |
| Дерево → видео | Ограниченный список узлов, выбор и проверка геометрии/срока снимка | Интеграционные pointer-тесты; отдельная human-приёмка списка не записана |
| Колесо | Короткий native-coordinate swipe; только одиночный просмотр | Есть проверки guards/частоты/геометрии; live человеческий результат пока не записан |
| Редактирование | Backspace/Delete/Enter/Tab, Android copy/cut/paste, ограниченный ASCII input | Клавиши используют APK SHELL и receipt; Unicode/emoji адаптер не реализован |
| Исходный снимок | Root `screencap -p` → точный PNG → Android/server/browser SHA-256 | Два настоящих Android-файла получены и полностью декодированы; текущий browser download отдельно не подтверждён |
| Системный профиль | Семь фиксированных manual read-команд, bounded allowlist-парсеры | Реальные ответы PH025/PH010 приняты теми же TS-парсерами; layout не объявлен визуально принятым |
| APK/сервер/сеть | Только Android APK + существующий сервер и Tuna | Нет обязательного PC Agent, host ADB или установленного на станции контроллера |

## Разбор пользовательского снимка и DPI

Пользователь сообщил: разрешение совпало, но свойства файла показывают 96 DPI,
а эмулятор настроен на 160 DPI. Проверен файл в Downloads с префиксом
`Sphere-frame-…png`: этот префикс создаёт только сохранение canvas видеопотока.
Следовательно, в данном случае скачан декодированный H.264-кадр. PNG-контейнер
не восстанавливает детали, уже потерянные при видеокодировании.

Проверены структура и полное декодирование этого файла и двух native PNG:

| Источник | Пиксели | Размер файла | PNG pHYs / DPI |
|---|---:|---:|---|
| Скачанный видеокадр | 960 × 540 | 259400 байт | Не записаны |
| Native PH010, первый успешный API trial | 960 × 540 | 231150 байт | Не записаны |
| Native PH025, первый успешный API trial | 960 × 540 | 220881 байт | Не записаны |

В этих PNG нет физического размера пикселя. Windows-показание 96 DPI не является
значением, извлечённым из pHYs этих файлов; интерпретация программой просмотра
не доказывает уменьшение или потерю пикселей. Android density задаёт масштаб
UI/dp, а PNG pHYs — физический размер/соотношение пикселей. Это разные данные.
Размер сжатого файла зависит от содержимого и PNG-кодирования, а не только от
разрешения. PNG использует сжатие без потерь.

Исходный файл не перекодируется ради установки метки 160 DPI. Для pixel matching
важны native ширина/высота и значения пикселей. При необходимости печатные
метаданные можно менять в отдельном производном файле, сохранив оригинал.

[PNG: lossless и pHYs](https://www.w3.org/TR/png-3/#11pHYs) ·
[Android: density и dp](https://developer.android.com/training/multiscreen/screendensities) ·
[AOSP screencap](https://android.googlesource.com/platform/frameworks/base/+/master/cmds/screencap/screencap.cpp).
AOSP master объясняет механизм; корректность установленного Android 9 здесь
подтверждается actual RPC/file trials, а не совпадением с master source.

## Где получить нужный файл

1. Карточка → «Видеопоток» → раскрыть **«Исходный PNG для пиксельных эталонов»**.
2. Нажать **«Получить снимок»**. Чтение не запускается при открытии страницы.
3. Дождаться геометрии, размера файла и **«SHA-256 совпал: Android → сервер → браузер»**.
4. Нажать **«Скачать исходный PNG»**. Имя: `sphere-<device-id>-<snapshot-id>.png`.

Тот же компонент доступен из обзора карточки через «Снимок экрана».
Кнопка поверх видео называется **«Сохранить кадр видео (PNG)»**, имеет подсказку
об H.264 и создаёт `Sphere-frame-…png`. Это отдельная операция.
Ни сохранение видеокадра, ни новый разовый native capture не являются DAG
artifact-upload pipeline; прежний N01 остаётся открытым.

## Контракт исходного PNG

**POST `/api/v1/devices/{device_id}/screenshot/native`**, тело не задаёт команды.
Проверяется `device:write` и принадлежность устройства организации до lock/RPC.
Привилегия root-команд не следует из одного `stream:read`.

Один Redis lock на organization/device: NX, 120 секунд, UUID owner, compare-delete.
Конкурентный запрос получает 429; освобождение не удаляет чужой lock.
Все временные пути принадлежат snapshot UUID. Нельзя передать свой shell/path.

Последовательность фиксированных APK SHELL RPC:

1. `wm size` — подтверждённая геометрия до чтения.
2. `screencap -p <UUID-owned PNG>` — отдельный native capture.
3. `wc -c <PNG>` — полный размер до передачи.
4. `sha256sum <PNG>` — SHA-256 файла на самом Android.
5. Для каждого блока: `dd` в собственный `.part`, затем `base64` этого блока.
6. Повторный `wm size` — отказ, если Android geometry изменилась.
7. В `finally`: фиксированный `rm -f <PNG> <part>`, отдельное подтверждение cleanup.

Ограничения: PNG до 5 MiB; блок 128 KiB, encoded output до 180 KiB, ниже APK stdout
cap 256 KiB. Геометрия до 4096 × 4096; bounded RGB/RGBA 8-bit PNG; максимум
4096 chunks. Проверяются signature, IHDR, chunks/CRC, IDAT/IEND, полный размер и
отсутствие trailing data. Для повёрнутого дисплея допустимо переставленное native
соотношение сторон; bitmap не ресайзится. Чтение ограничено 80 s; каждый live-only
RPC имеет timeout 8 s, cleanup отдельный. HTTP client ждёт до 100 s.

Android digest должен содержать ровно допустимый hash и текущий UUID-owned path.
Его несовпадение с собранными байтами — ошибка, без частичного PNG. Значение
`X-Screenshot-Android-SHA256` выдаётся только после этой сверки. Браузер проверяет
собственный Web Crypto SHA-256 против обоих headers до создания downloadable Blob.
Файл не проходит через canvas, видео decoder, JPEG или browser PNG encoder.
Это проверка неизменности доверенного Android-файла; не подпись независимого
источника и не защита от скомпрометированного root/сервера.

Ответ `image/png`, `no-store`, `nosniff`, attachment и headers: device ID,
snapshot ID, SHA256/Android-SHA256, native width/height, requested/completed UTC,
cleanup-confirmed. Старый GET screenshot stub сохранён и не используется панелью.

| Отказ | Поведение |
|---|---|
| Другая организация / нет права | 404 / 403, команды не публикуются |
| Конкурентная съёмка | 429, чужой owner не изменяется |
| Неполный файл, неверный hash/PNG/receipt | 502; частичный downloadable файл отсутствует |
| Канал/lock недоступен | 503; offline replay нет |
| Истёк RPC или общий deadline | 504; автоматического повторения нет |
| Не подтверждён cleanup после корректного файла | PNG сохраняется, cleanup=false показан отдельно |

Обрыв может оставить временный файл на Android; cleanup остаётся best effort.
Не реализован blanket sweep чужих временных файлов. Это ограничение нужно
учитывать при fault/retention-приёмке. На смене устройства, токена или потере
reachability frontend aborts request, discards поздний ответ и освобождает Blob URL.

## Реальная приёмка PNG и сохранённый отказ

API установлен **05:01:30 UTC / 10:01:30 UTC+5**, UI **05:04:21 UTC / 10:04:21 UTC+5**.
Каждый rollout менял только один образ; проверены readiness/revision, mounts и
15 остальных контейнеров. APK, Tuna и bytes OTA catalog не менялись.

Первый запрос PH025, **05:01:51–05:02:07 UTC**, вернул **504 за 16.072 s**.
PH010 в том же trial вернул PNG за 4.319 s. Failed trial сохранён.
В API журнале **05:02:08.813–05:02:08.837 UTC** — семь disconnects с code1005,
включая PH025. Позднее отдельный `wm size` на PH025 завершился HTTP200 за 0.335 s.
Tuna process в этом интервале не выдал warning/error, но отсутствие такого лога
не исключает сетевой сбой. Эти данные не определяют причину таймаута и не
доказывают, что семь disconnects вызваны PNG/SHA256 или самим Tuna.

После восстановления выполнены **новые ручные diagnostic captures**, с новыми
UUID; исходная неуспешная операция не была автоматически повторена/поставлена в очередь.

| Устройство | Сеть | Native PNG | Байты | Время | Android/file SHA256 | Cleanup |
|---|---|---|---:|---:|---|---|
| PH025 | Удалённая | 960 × 540 | 218676 | 3.130 s | Совпали | Да |
| PH010 | Локальная | 960 × 540 | 231280 | 2.947 s | Совпали | Да |

Успешный trial **05:05:01–05:05:07 UTC**. Pillow verify и full pixel decode прошли
на обоих реальных файлах; hashes/snapshot IDs содержатся в evidence. Native
pixel/byte proof принят; текущее нажатие download в браузере не объявлено выполненным.
Исходные экраны/сырые logs/profiles остаются private ignored artifacts.

## Системный профиль — без скрытого polling

Обзор карточки → «Идентификация и доступ» → **«Системный профиль Android»**.
Сбор стартует только вручную; устройство/право/fresh heartbeat проверяются перед
каждым запросом. Семь отдельных команд: `getprop`, `/proc/cpuinfo`, `/proc/meminfo`,
`wm size`, `wm density`, `ip -o addr show`, `/proc/uptime`. Первый отказ прекращает
сбор, сохраняет отдельно отмеченную partial информацию; общий UI deadline 60 s.
Смена auth/device scope или потеря freshness прерывает запрос/отбрасывает поздние данные.

Парсер bounded: 128 KiB characters, 1024 lines, 4096 characters/line, 512 rows.
`getprop` выводится по allowlist product/build/version/fingerprint/hardware/serial;
произвольные vendor/config свойства не показываются. К каждому разделу прилагаются
UTC timestamp и elapsed time; unsupported/error output не выдаётся за telemetry.

Реальный trial **01:51:18–01:51:22 UTC** на API5e80137: 14 настоящих ответов,
по 7 PH025/PH010. Те же source TS-парсеры приняты на реальных private fixtures:
30 cases — 16 unit/flow и 14 actual-response parser cases.
PH025: 35 property, 50 CPU, 44 memory, 1 size, 1 density, 4 network, 2 uptime rows
(137 всего). PH010: 35/54/43/1/1/12/2 (148 всего). Это количество строк, а не
137/148 независимых гарантий или физическое железо Windows-хоста.

Interface IP не доказывает public/VPN egress; guest serial/fingerprint не являются
clone-safe identity. Здесь нет внешнего IP probe, host inventory или background
root polling на весь парк. Для отсутствующих значений сохраняется unknown.

## Управление, logs и shell: что действительно доступно

Колесо ограничено четырьмя swipes в секунду, 180 ms каждый, native координаты;
игнорирует letterbox, Ctrl/Meta zoom, held drag, readonly/inspection/no-current-frame,
закрытый WS и buffer выше 64 KiB. Статичный свежий кадр не запрещает ввод.
WebSocket submit не является выполнением действия или измерением input-to-photon.

Навигация включает Home/Back/Recents/Menu. В «Клавиатура и текст»: keyevents
67/112/66/61 и Android clipboard 278/277/279; request receipt показывается
отдельно. Clipboard Android не синхронизирован автоматически с браузером.
ASCII field ограничен 1024 символами, отказывает control/non-ASCII, `%s` и shell
metacharacters. Это совместимый путь установленного SHELL, а не обещание любого текста.
Проверен реальный APK injection pattern; ранний небезопасный quoted-text mock
исправлен отдельным `6dc5e7e`. KDoc старого TYPE_TEXT ошибочно обещал ClipboardManager;
комментарии приведены к фактическому `input text`, бинарник APK не менялся.

Live logs приходят из APK/backend, а не декоративных event fixtures. Слова
crash/recents в приложении не являются доказательством system crash/ANR trace.
Terminal — ограниченные HTTP command/receipt calls, не постоянная PTY.
Сложные multi-line shell/операторы ограничиваются установленным APK validator;
произвольный script runtime не становится доступным из-за названия кнопки.
Автономные flight/DAG задания проверяются своим execution/outcome pipeline.

В **01:10 UTC audit** зафиксированы 12 настоящих read-only ответов PH025/PH010:
shell, navigation key numbers без исполнения, tail20 SphereLog и UI tree.
Root reads занимали 0.28–0.50 s, tree 3.080/3.268 s. Тaps, swipes, typed text,
reboot, VPN и OTA этим audit не отправлялись. Human wheel/edit результат остаётся OPEN.

## UI Automator, UIAutomator2 и другие готовые инструменты

| Решение | Что даёт | Почему не объявлено установленным |
|---|---|---|
| Root Android UI Automator | Native XML, bounds/attributes, positional XPath | Используется сейчас; game Canvas может раскрыть только поверхность |
| Appium UIAutomator2 server | Persistent instrumentation, дополнительные accessibility actions/extras, настройки idle | Нужны встроенный APK/test lifecycle и capability adapter; внешний ADB controller не добавлен |
| OpenATX uiautomator2 | Native UI automation + controller APIs | Python/device-agent stack не встроен в Android-only architecture |
| AccessibilityService/NodeInfo | Events/actions, text selection, windows, collection/range/extra data, ACTION_SET_TEXT | Нужны разрешение пользователя, version guards, bounded lifecycle/resource budget |

Все возвращённые текущим dump атрибуты показываются; это не вся теоретически
доступная Android-информация. Дерево/video — независимые снимки. Уменьшение
idle timeout может ускорить ответы, но не гарантирует актуальность UI.
Persistent adapter следует принимать отдельным APK canary с CPU/RAM/event limits,
Unicode/text proof, nonroot coverage и без polling тяжёлого dump для всех устройств.

Исследованы primary repositories/documentation; сторонний код в этом этапе не
копировался/не vendored. Сохранены авторство и лицензии:

- [Appium driver](https://github.com/appium/appium-uiautomator2-driver/blob/master/README.md) и
  [server](https://github.com/appium/appium-uiautomator2-server):
  [Apache-2.0, JS Foundation и contributors](https://github.com/appium/appium-uiautomator2-server/blob/master/LICENSE).
- [OpenATX uiautomator2](https://github.com/openatx/uiautomator2):
  [MIT, Copyright 2017 openatx](https://github.com/openatx/uiautomator2/blob/master/LICENSE).
- [Android AccessibilityNodeInfo](https://developer.android.com/reference/android/view/accessibility/AccessibilityNodeInfo):
  version-dependent framework capabilities; источник для будущего local adapter.

## Проверки, runtime и следующие gates

Source `9716348`: 49 focused frontend cases + TypeScript; 140 isolated API cases.
Собранные git-archive образы: **113 suites / 1117 frontend cases**, types/build;
**140 API tests** на отдельной audit PostgreSQL/Redis; Ruff, mypy229files и runtime
OpenAPI check прошли. Generated contract: **178 operations / 140 paths**.
Все четыре GitHub workflows source9716348 completed/success; links в evidence.
API/UI используют immutable labeled images, application source не bind-mounted.

После UI rollout, **05:05:51.672–05:06:52.233 UTC**, семь конечных
cohort/heartbeat/epoch срезов сохранили 14online10244, epochs и heartbeat<60s.
Точный результат и scope — в evidence; это не continuous monitoring, soak или SLA.
API restart намеренно создаёт новые epochs; сравнение относится к последующему
UI-only rollout, не обещает неизменности через restart. Семь предыдущих disconnects
и PH025504 сохранены. Пять offline устройств в приёмку не включены.

34 source-fixed / 7 незакрытых: F32/F33/F39 PARTIAL, F34/F36/F40/F41 OPEN.
Новый PNG не закрывает N01 durable screenshot upload, Matrix/H.264 preview,
browser motion/bitrate/input latency, native UA2/nonroot, полную визуальную проверку,
20–30-device stream+scripts/fault и soak. Stage-ready не означает production-ready.
Полный browser visual gate остаётся OPEN_URL_POLICY_BLOCKED; другой порт/браузер
для обхода ограничения не использовался. Старые failed CI/schema/runtime факты сохранены.

Следующий порядок: принять native download/keyboard/wheel в текущем UI;
изолировать transient disconnect с phase-aware RPC evidence; затем persistent
Android inspector/text adapter; потом measured single-stream latency/quality;
после этого — ступенчатый stream+scripts/fault/load test, по [Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md).
