# Клиент, Script Studio и расширяемая платформа

Дата разбора: 16 октября 2026. Это план реализации и критерии приёмки, а не заявление о готовности функций. Дополняет [основной план Motor AI](MOTOR-AI-PLATFORM.md), [руководство Studio](../operations/SCRIPT-STUDIO.md) и [реестр статуса](../operations/STATUS-REGISTRY.json). Исторический backlog: 50 пунктов, 9 принятых в ограниченном объёме, 41 открытый. Новые требования ниже не закрывают исторические пункты автоматически.

## Приоритеты и факты из кода

| ID | Требование | Что обнаружено | Следующая проверяемая поставка |
|---|---|---|---|
| CS-01 / P0 | Запись не прекращается от обычного свайпа | `NativeGestureRecording` экспортирует только прямой монотонный жест до 10 с/1024 точек. `DeviceWorkbench` останавливал всю запись и для известного неподдержанного/прерванного жеста | Неподдержанный жест явно пропущен, последующая запись продолжается; UNKNOWN по-прежнему останавливает. Отдельно нужен исполнитель траекторий |
| CS-02 / P0 | Запуск из Studio сохраняет прямое видео | `taskHandoffId` выключал `LiveDirectVideo` раньше получения native RELEASE | Сохранить media peer, дождаться RELEASE, только затем отправить ровно одно задание. Нельзя заменять подтверждение таймером |
| CS-03 / P0 | Сценарий работает при других подключённых зрителях/операторах | `DagRunner.execute` требует discrete reservation; чужой shared input participant удерживает continuous reservation | Общий арбитраж Android: временная эксклюзивная аренда сценария, подтверждённое освобождение всех удержаний, видео остаётся; после завершения доступ возвращается |
| CS-04 / P1 | Проверить несохранённый граф на выбранном Android | Сейчас требуется сохранённая неизменённая `ScriptVersion` | Неизменяемый снимок черновика, серверная валидация и отдельное реальное test task. Опубликованная версия не меняется |
| CS-05 / P1 | Точные задержки записи | Сейчас ACK-time уменьшает паузу; интервалы меньше 100 мс пропадают | Отдельные local DOWN/UP и native ACK; сохранять положительные паузы с миллисекундной точностью, показать предел 60 с. Это воспроизведение расписания, не обещание hard real time |
| CS-06 / P1 | Удобная лаборатория | Кнопки записи/проверки прокручиваются вместе с длинными блоками | Закреплённая компактная панель; отдельно прокручиваемая очередь; portrait/landscape и desktop QA |
| CS-07 / P1 | XPath, пиксель, изображение вокруг цели | Есть явный выбор XPath из снимка; автоматической связанной evidence-записи нет | Версионируемый bundle привязанных кадров, точек, дерева и crop, без подстановки старого дерева под новый кадр |
| CS-08 / P1 | Лёгкая видеостена | Каждый online tile открывает полноценный `DeviceStream`; пустые 64 слота и overlay расходуют пространство | Отдельный direct preview ≤1 FPS, уменьшенное разрешение, без управления и перекрывающих картинку toolbar. Не понижать общий encoder полноэкранного зрителя |
| CS-09 / P1 | Все настройки принадлежат аккаунту | `useUIStore`, `themeStore`, `useStreamStore` используют browser persist. У `User` нет UI settings | Серверный профиль с ревизиями и синхронизацией; local storage только кэш соответствующей личности |
| CS-10 / P1 | ИИ строит сценарии и оркестрацию | Полного authoring gateway / vault для внешних model keys нет | Названные соединения, серверное хранение секретов, capability-driven prompt, proposal/diff, строгая серверная валидация |
| CS-11 / P1 | Убрать привязки к конкретным играм | В `game-accounts/servers` читается статический `backend/core/servers.json`; есть game-specific label в `/devices` | Универсальный каталог приложений/проектов/серверов; миграция существующих ссылок. Не удалять данные и историю |
| CS-12 / P1 | VPN расширяется и обновляется предсказуемо | Наличие VPN страниц/peer-модели не доказывает versioned provider compatibility | Адаптеры провайдеров, capability/version manifest, contract tests, canary/rollback и проверенный import/export конфигурации |
| CS-13 / P1 | Проекты и конфигурации без рестарта backend | Скрипты/задания уже DB-ресурсы; startup discovery Python routers не равен hot plugin loading | Версионируемые project resources, транзакционные команды и outbox/invalidation. Изменение Python кода/DDL имеет отдельный deployment lifecycle |
| CS-14 / P2 | Плагины и переиспользование между проектами | Полного жизненного цикла сторонних модулей нет | Версионированный SDK/manifest, изолированные workers, scoped capabilities, отключение/обновление с drain активных задач |
| CS-15 / P1 | Android-файлообмен | Есть проектирование; полная браузерная приёмка файлового менеджера не выполнена | Продолжить существующий контракт файлового менеджера: директории, прогресс, отмена, checksum, безопасная область путей |

Установлен веб `f7b6f6c1`: конечная приёмка части CS-01/02/05/06 и компоновки CS-08 на3015/Tuna зафиксирована в [отчёте](../audits/2026-10-16/STUDIO-RECORDING-HANDOFF-DELIVERY.md). Полные кривые CS-01, конфликт второго управляющего клиента CS-03 и лёгкий транспорт CS-08 остаются открыты. Все остальные строки — открытые задачи, а не скрыто реализованные функции.

## Единый транспорт и владение вводом

Браузер — самостоятельный клиент. Режимы «Поток», карточка, Studio, запись и XPath используют один транспортный контур. Сервер выдаёт авторизованный signaling/capabilities и fallback; смена UI-режима не должна уничтожать работающий media peer. Web Worker подходит для вычислений, подготовки графа, crop и очередей вне UI-потока; он не превращает вкладку в произвольный нативный сервер Windows. Это следует из [модели Web Workers](https://developer.mozilla.org/en-US/docs/Web/API/Web_Workers_API/Using_web_workers).

У каждого viewer отдельная авторизация и ICE-сессия. Нахождение рядом не доказывает достижимость UDP: NAT эмулятора, изоляция hotspot-клиентов, firewall, VPN routes и browser local-network policy требуют измерения. Direct-first означает сбор и проверку доступных host/srflx пар и их приоритет, а не ложную зелёную метку. TURN и серверный WebSocket учитываются отдельно в UI и метриках. Основа — [WebRTC connectivity](https://developer.mozilla.org/en-US/docs/Web/API/WebRTC_API/Connectivity).

Состояния видео и ввода независимы: наличие кадров не означает native READY. Текущий shared input рассчитан на десять авторизованных участников; двадцать и более пока не приняты нагрузочным тестом. Целевая матрица: localhost; два LAN-клиента; hotspot host→laptop/emulator; VPN active; WAN; четыре клиента с разными маршрутами; десять и двадцать клиентов с измерением CPU/encoder/upload.

Нужен device-level `InputCoordinator` с режимами `manual_shared`, `exclusive_pending`, `automation`, `inspection_read`, `cleanup_unknown`. Ручные зрители остаются подключёнными во всех режимах, но недоступность ввода объясняется конкретным владельцем/задачей.

Переход к автоматизации:

1. Сервер сохраняет намерение запуска и неизменяемый DAG/hash, RBAC/device/tenant binding; повтор POST не запускается автоматически.
2. Android закрывает admission новых ручных удержаний и сообщает `exclusive_pending` всем control peers, сохраняя media peers.
3. Actor завершает/CANCEL текущие pointer и key holds, дожидается native release и keyboard cleanup. Запоздалый ACK не относится к новой generation.
4. Только подтверждённая очистка позволяет атомарно взять reservation задачи. Timeout/UNKNOWN оставляет явный отказ, а не принудительный сброс защиты.
5. Пока task активен, ручной ввод возвращает `task_owns_input`; не попадает в граф и не проигрывается позже. Видео всех клиентов продолжает идти.
6. Нормальное завершение/остановка освобождает lease в `finally`; уведомляет всех текущих участников. Возвращение READY требует нового native proof, без reconnect видео.

Те же правила нужны для scheduler/API/AI/headless, а не только кнопки Studio. `invalidate()` без ожидания не является подтверждением освобождения. Вызов shell/XPath нельзя выполнять параллельно с несовместимым root input owner. Для чтения дерева нужны bounded arbitration и понятный отказ, а не порча shared touch.

## Полная запись траектории

Новый action `gesture_path` нужен отдельно от `swipe`: старый APK может проигнорировать optional поле `points` и выполнить неверный прямой жест. До поддержки новой версии/feature capability сервер обязан отказывать запуску этого action на старом APK.

Контракт: 2–1024 точек `{x,y,t_ms}`, начальный `t_ms=0`, монотонные отметки, общая длительность до 10 с на первом этапе, frame dimensions/rotation/capture epoch и canonical coordinate reference. Ограничения одинаковы во frontend, backend и APK. Coalesced MOVE разрешён только с явной измеримой погрешностью; DOWN/UP и смена направления сохраняются. Curve, out-and-back и stationary hold различаются.

Исполнитель Android отправляет один DOWN, последовательность MOVE и один UP в одном native session. Несколько независимых `input swipe` не воспроизводят такую траекторию. Отмена — CANCEL, затем подтверждённый close; неопределённое выполнение не повторяется. Планировщик использует monotonic clock и сообщает actual start/end/lateness, отдельно от клиентской задержки ACK. UI показывает неподдержанный жест и сохраняет остальные действия до появления этого исполнителя.

Время наблюдения — viewer-local monotonic DOWN/UP. ACK нужен для подтверждения выполнения, а не для изменения пользовательской паузы. Для текста/IME/клавиш отдельно нужны press/release, modifiers, composition, физические клавиши и held-key duration; текущая запись кнопок Android не означает запись всей игровой клавиатуры.

## Контекст действия и изображения

Evidence bundle хранит `device_id`, org/user, capture epoch, generation, dimensions, rotation, frame sequence/timestamps, command/request id и подтверждение. XPath snapshot связывается с конкретной генерацией экрана и временем, имеет freshness/confidence. Не следует обещать совпадение дерева и пикселей, если общего frame ID пока нет.

Локальный crop строится из реально отображённого pre-action кадра; хранит точку клика, bbox элемента, padding и преобразование координат. Полный кадр и lossless PNG/crop включаются по выбору. RAW означает явные width/height/pixel-format/stride/color-space и байты; PNG не обозначается RAW. В пакет не помещаются access tokens, root owners и transport session secrets.

Хранилище — bounded attachments по SHA-256, с лимитами размера/количества, org-level ACL, retention и очисткой недостижимых blobs. DAG ссылается на attachment IDs, не раздувается base64 на каждом MOVE. Export/import проверяет manifest/hash/mime/dimensions; отсутствующие evidence не подменяются случайной старой картинкой. Снимки могут содержать пользовательский текст: перед отправкой модели есть preview и выбор контекста.

## Проверка черновика до сохранения

`POST /scripts/validate` уже существует, но не запускает Android. Добавить endpoint для неизменяемого test snapshot: normalized DAG, action contract version, hash, selected device, срок хранения, author, idempotency key. Он создаёт test execution, не новую опубликованную версию и не скрытое изменение production script.

Тест в UI показывает «выполняется черновик hash…», реальные node outcomes и stop. При редактировании графа в ходе выполнения результат остаётся привязанным к старому снимку; подсветка нового графа отключается. Нельзя автоматически посылать команду ещё раз после сетевого timeout. Проверки RBAC, tenant, DAG и поддерживаемых APK actions — на сервере до dispatch; native release — на Android до исполнения.

## Видеостена

Цель: 0.2–1 FPS, небольшой frame, отдельный read-only preview capability и direct Android→browser. Это другой бюджет, чем интерактивные 60 FPS. Для 64 окон нельзя просто спрятать full-stream controls и продолжать принимать/декодировать 60 FPS.

Добавить APK preview producer из общего capture с единственным downscale/encode на устройство и fanout subscribers. На первом этапе достаточно lossless/качественного thumbnail формата с ограниченным размером и backpressure/latest-frame-only. В handshake согласуются max pixels/FPS/bytes, stale deadline и cancellation. На hidden/offscreen tiles подписка приостанавливается; восстановление не создаёт управляющего участника.

Нельзя менять общий encoder quality ради плитки: отдельный полноэкранный оператор может смотреть то же устройство. Нельзя выбрасывать произвольные delta H.264 packets для «1 FPS». Подпись/маршрут/возраст кадра размещаются в компактном footer; меню появляется по focus/hover/явному tap. Пустая матрица 8×8 не рисуется, если выбранных устройств четыре; оператор выбирает размер плитки/число колонок, доступно раскрытие стены на всю рабочую область.

Приёмка: 4/16/64 previews, сопоставить wire bytes, browser decode/CPU, APK encoder/memory, server media ingress и полноэкранного соседа. Фактически измерить FPS, не ограничиваться CSS. Контрольные размеры 390×844, 844×390, 1366×768 и 1920×1080; ни один toolbar не перекрывает существенную часть thumbnail.

## Синхронизация настроек аккаунта

Один versioned `user_preferences` ресурс по `(org_id,user_id)`: palette/theme mode, accent, density, font/scale, glass/motion, sidebar, inspector mode, grid columns/width/order/pinning/filter/layout, video wall и Studio layout. Browser zoom, физический fullscreen и разрешения ОС не управляются аккаунтом; приложение хранит только свой UI scale/preferred layout.

GET + PATCH с revision/ETag и optimistic concurrency. Конфликт двух клиентов разрешается по изменённым полям или показывается; нельзя безусловно перезаписывать весь профиль последним устаревшим ответом. Все enums/ranges/schema versions валидируются сервером. Быстрые изменения debounce; офлайн изменения привязаны к личности, после logout не уходят в другой аккаунт. В UI виден статус «сохранено / офлайн / конфликт».

Локальные настройки импортируются один раз с явным происхождением, затем кэш namespaced user/org. При новом аккаунте не мигрируют чужие колонки и тема. Тест: два разных браузера и телефон → те же настройки после login; revoke/logout во время PATCH; повреждённый JSON; конкурентное изменение; frontend/API rolling update.

## ИИ-конструктор

Сохранённое соединение: имя, provider, allowlisted/проверенный endpoint, model, поддержка vision/tools/schema, encrypted secret и версия ключа. Сервер никогда не возвращает полный token после сохранения; rotation/delete/test доступны отдельно. Ключ не хранится в localStorage, не помещается в system prompt, DAG, export или логи. Не давать произвольному URL доступ к внутренним адресам через backend proxy.

Prompt builder собирает актуальный machine-readable action contract (`/scripts/action-contract`), DAG/schema version, node connections, limits, available capabilities, selected device dimensions, разрешённые attachments и явно выбранный XPath. Никаких выдуманных nodes из старого статического списка. В system prompt фиксируются output schema, запрет запускать действия в фазе proposal и требование отмечать недостающие данные. UI показывает состав/размер контекста и системный prompt.

Модель возвращает proposal, затем: parse → schema/action validation → graph reachability/cycles/budgets → device capability → diff/preview. Сервер проверяет независимо. Сохранение/запуск — отдельные явные действия пользователя. Вторая фаза — scoped tools для read-only inspection; каждая операция с deadline/result provenance. Поддержка orchestration/projects строится поверх того же typed command registry, а не позволяет модели выполнять произвольный Python/shell.

Реальная модель, стоимость/latency и 50-emulator throughput не приняты: нужен отдельный GPU benchmark из Motor AI плана. Никаких неподтверждённых заявлений, что Neuro policy сама планирует поездку из A в B.

## Универсальные проекты, VPN и плагины

Игровой сервер — пользовательская конфигурация проекта, не глобальный Black Russia список в core. Перенести записи в tenant/project catalogue, сохранить IDs/foreign keys и audit history, предусмотреть export/import и disabled legacy entries. Тесты не должны зависеть от живой игры или конкретного package name.

VPN adapter имеет `provider_id`, protocol/config schema/version, detect/status/validate/plan/apply/rollback и capabilities. Конфигурации и секреты разделены. Upgrade меняет конкретный adapter/worker artifact после matrix tests; общая UI/оркестрация не переписываются. Упоминание Amnezia не доказывает совместимость всех версий: [официальная документация](https://docs.amnezia.org/documentation/amnezia-wg/) и [реализация amneziawg-go](https://github.com/amnezia-vpn/amneziawg-go) — входные источники для pin версий и fixtures. Нельзя молча смешивать разные варианты протокола.

Проект создаётся/архивируется как DB resource с изоляцией tenant/project и runtime revision. Скрипт, flow, connection и plugin config обновляются транзакционно, notification/outbox инвалидирует кэши всех API workers; активная задача продолжает immutable revision. Restart backend для этих операций не требуется. Обновление бинарного backend или несовместимое DDL не маскируется «hot reload»; используется rolling deployment и expand/contract migrations.

Plugin manifest: API version, provider/action schemas, required permissions, compatibility range, resource budgets, package digest/signature и migrations. Dynamic plugin code исполняется в отдельном ограниченном worker с versioned RPC. Установка/отключение/upgrade имеют состояния, rollback и drain, не исполняют arbitrary imports внутри API процесса. В UI — registry, capabilities, health, logs, active executions и влияние удаления. Сначала внутренний VPN adapter и application profile, затем внешний SDK.

Файловый менеджер остаётся отдельной открытой функцией. Использовать существующий проект контракта в UI-аудите; добавить path normalization, symlink/root boundaries, chunk progress, cancel, checksum/resume, quotas, conflict policy и два направления. Протокол передачи не должен удерживать control actor или блокировать видеопоток.

## Порядок поставок и доказательства

1. CS-01/02/05/06: точечный frontend fix; unit regression, полный local CI, immutable image, установка на3015/Tuna, реальные запись/свайп/handoff и скриншоты desktop/phone.
2. CS-03: Android coordinator и versioned automation events; 2/10 viewers, ручные удержания, task cancel/timeout/disconnect и отсутствие media reconnect; затем canary APK и rollout доступных устройств.
3. Полные траектории + CS-04: единый action contract и совместимость старых APK, immutable draft task API, реальные swipe-path replay/cancel.
4. CS-07/08: привязанные visual attachments и дешёвый direct preview; отдельный ресурсный бюджет и нагрузочная приёмка.
5. CS-09/10: account preferences + named AI connections/proposal workflow; cross-account/rolling/offline tests.
6. CS-11/12/13/14/15: project catalogue, provider SDK, файлообмен и runtime lifecycle с независимыми критериями.

Для каждого этапа сохраняются source revision, exact local test receipt, artifact hash, installed package/container proof, конечная матрица браузеров/устройств и известные провалы. Закрытие CS-пункта не означает автоматическое закрытие enterprise readiness, всех старых аудитов или нагрузочного SLA. CI выполняется локально, привязанные статусы публикуются на GitHub; полная миграция всех старых workflow проверяется отдельно.
