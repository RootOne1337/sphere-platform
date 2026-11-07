# F35 — XPath-инспектор выбранного Android-устройства

**Дата:** 4 октября 2026, Asia/Yekaterinburg (UTC+5).
**Историческая установка этого этапа:** API `9274e50`, UI `84750e3`, APK `1.2.44-dev / 10244`.
**Review:** [3015/devices](http://127.0.0.1:3015/devices) → карточка устройства → «Видеопоток» → «XPath-инспектор».

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Readiness](../../operations/READINESS.md) ·
[Исходный F35](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f35) ·
[Реестр исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Машинные доказательства](UI-HIERARCHY-INSPECTOR-EVIDENCE.json) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

Текущий follow-up: [native PNG, controls, system profile и новые runtime receipts](DEVICE-CONTROL-AND-NATIVE-CAPTURE.md); historical stage facts ниже сохранены.

## Результат и границы приёмки

Режим инспектора автоматически запрашивает дерево после первого кадра текущего
устройства. Клик во время загрузки сохраняется: после получения дерева выбирается
узел в этой точке. На видео показываются границы, рядом — positional XPath,
геометрия и **все атрибуты, возвращённые Android**. Доступны копирование XPath/JSON
и ограниченный по высоте список узлов с порциями по 200 записей.

Автообновление включено по умолчанию: следующий запрос через **5 секунд после
завершения предыдущего**, только в открытом видимом инспекторе. Одновременно
выполняется один запрос. Ошибка приостанавливает автообновление; оператор видит
ошибку и может повторить чтение. Действительный выбор остаётся видимым во время
обновления и проверяется по новому дереву. Выбор в инспекторе не отправляет
Android tap, swipe или navigation.

На настоящем API получены PH010 **45 узлов** и удалённый PH025 **49 узлов**,
960×540, с подтверждённым удалением временных файлов. Это подтверждает получение
дерева через APK в удалённой сети. **Собственная браузерная проверка остаётся OPEN**: собственный просмотр заблокирован `OPEN_URL_POLICY_BLOCKED`;
после установки UI оператор подтвердил рамку и информацию справа. JSDOM и API не заменяют
реальный screenshot/keyboard/mobile walkthrough.

**Оператор после установки подтвердил:** выбор на видео выделяет элемент,
справа отображается информация. Это human live acceptance двух указанных
действий. Полный визуальный аудит, все устройства и список→video отдельно
не проверены этим ответом.

Исходный ledger: **34 source-fixed / 7 незакрытых, включая 3 PARTIAL**.
F35 имеет source/API-результат, но не окончательную визуальную/production приёмку.
Это не закрытие PR19, F40/F41 или release readiness.

## Что именно воспроизведено

| Этап | Наблюдение | Исправление / предел |
|---|---|---|
| API `37bb436`, 3 октября 23:52:43 UTC | Новый endpoint: 404 на PH025 и PH010; команды Android не отправлялись | `0b35189` добавил bounded tree API и UI |
| API `0b35189`, переходное окно рестарта | Оба canary: 500; cleanup logger маскировал исходный offline отказ | Тест: 1 assertion failure / 0 runtime errors, ожидался 503. `35ef83f` использует logging `extra`, сохраняет первый отказ |
| API `35ef83f`, PH025 00:05:25 UTC | 504, RPC timeout 8 с | Отказ сохранён; ручная отдельная попытка 00:08:33 получила 200. Причина первого timeout не установлена |
| CI `35ef83f` | Backend 2485 passed / 16 skipped, но stale OpenAPI и 18 mypy errors | `176dfca` синхронизировал schema; `9274e50` исправил typing shipped XML definitions |
| Промежуточный `176dfca` | Host mypy 1.8.0 passed, image mypy 2.3.1: ещё 2 ошибки | Этот образ **не устанавливался**; final `9274e50` прошёл оба checker |
| UI `35ef83f`, сообщение пользователя | Включение режима и клик не давали ни выделения, ни информации | Вход не загружал дерево; клик до его получения молча терялся. 5 новых assertions воспроизвели пробелы |
| UI `84750e3` | Автозагрузка, pending pick, live selection, miss/error feedback | 8 integrated pointer cases passed; actual-browser result ещё OPEN |

Полные исходные отказы и отдельные успехи сохранены в evidence. Timeout/ошибка
не переименованы в успешную попытку. Строка Socket/okio в отдельном logcat PH025
не устанавливает сетевую первопричину.

## Серверный контракт и управление нагрузкой

**POST `/api/v1/devices/{device_id}/ui-hierarchy`**, без тела запроса.
Требуется `device:write`: это существующая привилегированная root SHELL возможность.
Право `stream:read` само по себе не разрешает её. Проверка tenant-owned устройства
выполняется до Redis lock и публикации команд.

Response: `device_id`, UUID `snapshot_id`, `requested_at`, `completed_at`,
`source=android_uiautomator_root`, native `width/height`, `rotation`,
`temporary_file_cleanup_confirmed`, `nodes`. Узел: `id`, `parent_id`, `depth`,
positional `xpath`, исходные `attributes`, безопасные hit-test `bounds` или null.
Успешный response имеет `Cache-Control: no-store`. UI не сохраняет дерево
в localStorage; значения рендерятся React как текст, не HTML.

Каждая операция отправляет пять отдельных фиксированных RPC через имеющийся APK:

1. `wm size`.
2. `uiautomator dump /data/local/tmp/sphere-ui-<32hex UUID>.xml`.
3. `cat` того же серверного UUID-owned пути.
4. Повторный `wm size`.
5. `rm -f` только этого пути в `finally`.

Пользователь не передаёт shell, XML, XPath или имя файла. Команды имеют interactive
IDs и `live_only=True`: offline задания не создаются, сервер автоматически не
повторяет отказ. Автообновление UI начинает новую операцию после успешного ответа;
ошибка его останавливает. Новый запрос получает новый UUID.

| Ограничение | Реализация |
|---|---|
| Lock | Redis NX на org/device, TTL 60 с; release только совпавшим UUID владельца |
| Конкуренция / lock failure | 429 / 503; запуск без lock запрещён |
| Deadline | Основное чтение 40 с, каждый RPC 8 с; cleanup отдельно; UI timeout 50 с |
| APK process | Существующий SHELL process budget 5 с, stdout 256 KiB; APK не изменён |
| XML | UTF-8, 128 KiB, максимум 4096 узлов, depth 64 |
| Атрибуты | Максимум 64 на узел; имя 128, значение 4096 символов |
| DTD/entity | DOCTYPE/ENTITY запрещены; частичный XML не принимается |
| Geometry | 1…16384, одинаковый `wm size` до/после; rotation 0…3, native размеры |
| Bounds | Исходный строковый атрибут сохранён; hit-test получает пересечение с экраном |
| Cleanup | Положительный флаг требует завершённого RPC receipt |
| Хранение | Raw XML/тексты узлов не публикуются в лог/public evidence; только metadata/hash |

Failed/invalid dump, root failure или malformed receipt: 502; geometry change: 409;
offline transport/Redis: 503; RPC/общий deadline: 504. Runtime outcomes описаны
здесь отдельно от объявленных OpenAPI responses. Cleanup failure сохраняет исходный
отказ; если дерево принято, ответ остаётся 200 с cleanup=false и предупреждением UI.
Durable очистка orphan files пока не реализована.

## Свежесть, геометрия и выбор

UI проверяет identity/source/UUID/timestamps, размеры, parent/depth структуру,
атрибуты и bounds. Дерево привязано к device/auth scope. Lease — **30 секунд с начала
HTTP запроса**, чтобы длительная сеть/cleanup не делали старое дерево «свежим».
Для инспекции требуется кадр текущего WebSocket; retained frame старого соединения
не открывает выбор.

Дерево и видео независимы: атомарная связь с конкретным кадром не обещается.
Перед использованием проверяется aspect ratio с допуском 1%. Новый socket/размер,
device/token/permission change инвалидируют дерево; устаревший снимок не используется
для нового выбора. Клик по устаревшему/неполученному дереву инициирует чтение
и сохраняет последнюю точку. Геометрически несовместимый ответ не получает рамку.

Hit testing выбирает самый глубокий подходящий узел, затем наименьшую область.
Native bounds масштабируются к видео через существующий contain/cover/fill mapping.
Переход в инспектор во время удержанного gesture не завершает Android tap/swipe.
При обновлении выбор проверяется по XPath/class/resource-id; если узел исчез,
UI очищает выбор и объясняет причину. Эта проверка не доказывает стабильную identity
произвольно перестраиваемого приложения.

Пустая точка получает явный miss feedback. В списке можно выбрать узел с null bounds:
его атрибуты доступны, отсутствие видимой рамки объясняется. Long tree/attributes
ограничены scroll областями; sidebar располагается рядом с видео на широком экране
и ниже на узком. Проверки CSS/zoom/4K/keyboard/mobile остаются визуальным gate.

Скрытая вкладка останавливает будущие периодические чтения; уже отправленный RPC
не обещается отменённым на Android. Возврат на видимую страницу запрашивает дерево.
Период обновления включает время Android/RPC плюс 5 с: это не 5-Hz или мгновенный
push-инспектор и не частота видеопотока.

## Какой Android engine реально используется

Работает **системный `uiautomator dump` через root APK**. Новый APK, обязательный
PC Agent, Windows helper и host ADB не добавлены. Это не встроенный полный Appium
UIAutomator2 server и не AndroidX instrumentation внутри текущего APK.

Не-root путь этим этапом не реализован/не принят. Нельзя обещать все game pixels:
Canvas/OpenGL может раскрывать только поверхность без внутренних accessibility узлов.
Все возвращённые атрибуты видны; несуществующие в Android дереве данные не выдумываются.

Следующий Android adapter gate перед отдельной реализацией:

1. Согласовать единый capability contract: root dump, instrumentation/UA2,
   accessibility и unsupported должны явно сообщать доступность и ограничения.
2. Для UA2 изучить lifecycle server/test APK и instrumentation, подписи, совместимость
   SDK/Android 14+, версии и минимальные зависимости. Host ADB не должен стать
   обязательным runtime условием пользовательского сценария.
3. Проверить через текущий authenticated APK transport ownership, deadlines,
   cleanup/cancel, process restart, одновременный video/input и CPU/RAM бюджета.
4. Принять Native UI, WebView, Compose, dialogs/IME, rotation, multiwindow и Canvas
   как отдельные случаи. Измерить actual tree freshness и input-to-visible latency.
5. Версионировать helper/adapter и OTA contract, затем canary одного удалённого
   устройства перед расширением парка. UI/API tests не подменяют эти native gates.

Это план открытого расширения, не внедрённый dependency. Исходники Appium не копировались;
его Apache-2.0 должен быть сохранён при будущей интеграции.

## Исходники, образы и CI

| Проверка | Фактический результат |
|---|---|
| UI `84750e3`, Node 24 source | 110 suites / 1043 passed, 0 failures/runtime-error suites |
| UI exact builder image | Те же 110 / 1043; приложение из git archive, application source не mounted |
| Stream subset | 152 passed; 8 новых integrated SingleDeviceStream + DeviceStream pointer cases |
| Before user-flow | 5 assertion failures, 0 passed / 0 runtime-error suites |
| TypeScript / production build | Passed; standalone runner собран и установлен |
| API `9274e50` source/image | 108 passed / 0 failures/errors/skips; parser и real isolated PostgreSQL/Redis HTTP/RPC |
| Shipped mypy 2.3.1 / host 1.8.0 | Оба passed, 228 backend files; промежуточные различия сохранены |
| Ruff / schema | Passed в exact image; network none, non-root; 177 HTTP operations / 139 paths |

Pointer workflow использует настоящий handler chain обоих React компонентов,
но подменяет API, WebSocket и H.264 renderer. Покрыты mode entry, ожидание первого
кадра, pending pick, refresh selection, error pause, no overlap, visibility и
miss/list selection. Это не browser decoder/render/native визуальный тест.

API cases: owner/viewer rejection до публикации, concurrent lock, fixed commands,
cleanup failure без маскировки результата, entity/deep/oversized/partial/bad UTF-8 XML,
rotation/empty bounds, timeout/root failure, geometry mismatch и malformed receipt.
Исходный pytest harness требовал коротких ID: огромный Unicode parameter ID превышал
Windows environment limit. Non-root cache path требовал `/tmp` для mypy и `--no-cache`
для Ruff. Эти tooling отказы отдельно от продуктовых 500/504.

CI каждого SHA и время чтения находятся в evidence. API `9274e50`: все 4 workflow
success. UI `84750e3`: все 4 workflow success на записанном срезе. Последующий docs HEAD
имеет свои проверки; pending не называется success. Docs commit не меняет уже установленный application source.

## Настоящие Android canary и установка

| API / устройство / UTC 4 октября | Response | Узлы / geometry | Время | Cleanup |
|---|---|---|---|---|
| `35ef83f`, PH025, 00:05:25 | 504 | Не принято | 8,063 с | Нет утверждения об успехе |
| `35ef83f`, PH010, 00:05:33 | 200 | 45 / 960×540 / rotation 0 | 3,344 с | Confirmed |
| `35ef83f`, PH025, ручная попытка 00:08:33 | 200 | 49 / 960×540 / rotation 0 | 2,734 с | Confirmed |
| `9274e50`, PH025, 00:29:07 | 200 | 49 / 960×540 / rotation 0 | 2,563 с | Confirmed |
| `9274e50`, PH010, 00:29:10 | 200 | 45 / 960×540 / rotation 0 | 2,937 с | Confirmed |

Оба дерева содержат 18 видов атрибутов: `NAF`, `bounds`, `checkable`, `checked`,
`class`, `clickable`, `content-desc`, `enabled`, `focusable`, `focused`, `index`,
`long-clickable`, `package`, `password`, `resource-id`, `scrollable`, `selected`, `text`.
Raw values/XML в public evidence не опубликованы.

- API `9274e50` установлен **00:27:57 UTC / 05:27:57 UTC+5**,
  image `sha256:59749263367b7e142f12d3b26e31803e95f499dffea6ed3dccc239bfa39a6978`.
- UI `84750e3` установлен **00:50:32 UTC / 05:50:32 UTC+5**,
  runner `sha256:752a7f8cba2cef61d4813de1dfcd2e3b127b121f30c41d59f7109f96bc42cfd2`.
- Каждый шаг сохранил 15 соседних контейнеров; суммарно обновлены только API/UI.
  Tuna/OTA catalog сохранены, APK/input/reboot/VPN/OTA не менялись.
  API restart изменил прежние connection epochs: seamless connectivity не принята.

### Отдельные окна парка — без смешивания успеха и отказа

| Окно UTC | Результат |
|---|---|
| 00:08:33–00:09:34, API `35ef83f` | 7 срезов, те же 14 online10244; новые post-restart epochs стабильны |
| 00:29:21–00:30:21, API `9274e50` | **FAILED:** 14→13; PH015 выпал после 00:29:41. Причина неизвестна; стабильная когорта не принята |
| 00:45:01, до нового UI | PH015 восстановился: 14 online. Один snapshot не доказывает непрерывный uptime |
| 00:54:18–00:55:18, после UI `84750e3` | **PASSED:** 7 срезов сохраняли все 14, даты соединений до UI rollout и heartbeat <60 с; API/Tuna/OTA/15 соседей сохранены |

API build/readiness, capabilities200/no-store/owned identity, anonymous401 и
Prometheus backend up=1 проверены отдельно. Пять offline устройств вне приёмки.
Минутные окна не являются hours-long soak, нагрузочным тестом или uptime SLA.

## Оставшиеся gates

F35 source/API gap исправлен; оператор подтвердил выбор/атрибуты в живом UI.
Расширенная browser selection/layout/keyboard/mobile acceptance OPEN.
F32/F33/F39 остаются PARTIAL; F34 JPEG Matrix, F36 quality/FPS/input latency,
F40 walkthrough и F41 20–30-device stream+scripts/fault/soak/clone/Android14+ OPEN.
N01 screenshot delivery, N03/outbox и повторные remote disconnects не объявлены
решёнными. Full embedded UA2, nonroot adapter, atomic frame/tree и game-pixel
detection этим этапом не реализованы. PR19 остаётся draft/unmerged.

## Первичные источники

- [Android UI Automator legacy](https://developer.android.com/training/testing/other-components/ui-automator-legacy) — доступные UI/accessibility элементы и ограничения модели.
- [Android UI Automator 2.4 API](https://developer.android.com/training/testing/other-components/ui-automator) — отдельный instrumentation подход; источник не означает внедрение этой библиотеки в наш APK.
- [UiDevice API](https://developer.android.com/reference/androidx/test/uiautomator/UiDevice) — hierarchy API, независимое от пикселей видео.
- [Appium UIAutomator2 server, исходники и Apache-2.0](https://github.com/appium/appium-uiautomator2-server) — server/test APK и instrumentation lifecycle; dependency в этом этапе не добавлен.
- [Python XML](https://docs.python.org/3/library/xml.html) — untrusted XML; наши byte/depth/entity limits проверены отдельно.

Источники обосновывают архитектуру и ограничения. Успех нашего удалённого дерева
доказан указанными native RPC canary, а не ссылкой на чужую документацию.
