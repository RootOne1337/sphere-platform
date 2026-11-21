# Studio: доступные панели и сохранность рекордера

9 октября 2026, Asia/Yekaterinburg. Ниже сохранён исходный source checkpoint.
**Конечный UI ec3f2267 установлен и проверен на3015 в21:43–21:51UTC8октября.**
Frontend CI1936/139suites; actual390×844/844×390/1440×900, четыре APK keys и
browser/global Back2132.5→2132.5 подтверждены отдельно. Поздние CSS iterations
и границы: [installed acceptance](STUDIO-RESPONSIVE-INSTALLED-ACCEPTANCE.md).
[Canonical installed state](../../operations/CURRENT-STATE.md).

## Доказанные причины

В предыдущем редакторе action library отсутствовала в device workspace.
Baseline regression нового случая упал при открытой лаборатории. Компоновка
в узком окне складывала несколько длинных рабочих областей вертикально;
оператор не видел одновременно переключение, схему и библиотеку.

Скрытие через HTML `hidden` не было достаточным: Tailwind `display:flex/grid`
перекрывал его в реальном браузере. Явный `display:none` теперь применяется к
неактивным панелям и вспомогательным desktop/mobile controls. Desktop device
mode имел graph basis40% плюс flex grow: при1280px лаборатория сжималась до
212px. Этот basis удалён, оставшееся пространство делится между рабочими
областями без исходного перекоса.

## Новая компоновка

- Workspace занимает остаток динамического viewport после общей шапки;
  основной документ не образует длинную внешнюю прокрутку Studio.
- При ширине меньше1280px доступны «Схема», «Действия», «Параметры»,
  «Устройство». Выбрана одна основная рабочая область.
- Кнопки проверки/сохранения остаются в шапке с доступными именами.
  Импорт/экспорт/упорядочивание/направление/запуск доступны через «Ещё».
- На широком экране action library доступна и рядом с лабораторией.
  Оператор может скрыть её явно.
- Выбор узла или связи в компактном графе открывает соответствующие параметры.
  CTA выбора устройства тоже переключает нужную панель.
- Добавление из скрытого графа рассчитывает точку по сохранённому viewport;
  после добавления показана схема. Вставка/отдельный узел остаются явными.
- Search, параметры, выбранное устройство, queue/task/unknown outcome
  сохраняются в mounted областях, без создания второй копии workbench.
- Именованные скроллы библиотеки, инспектора и лаборатории имеют независимые
  границы и не прокручивают внешнюю страницу через scroll chaining.

## Неактивная лаборатория

Переключение на другую компактную панель прекращает recording и native reads/
stream/control. Очередь не выбрасывается. Уже отправленный key/text ACK
обновляет исходную строку даже после скрытия. Новый поздний callback не
добавляет ввод или XPath в скрытую очередь.

Native preparation перед task POST завершается отказом при скрытии, а поздний
ready receipt не отправляет задание при возврате. Уже отправленный POST не
объявляется отменённым; pending/unknown task state сохраняется. Показ панели
не возобновляет запись, не переносит очередь и не запускает задание автоматически.
Возобновление stream требует нового кадра; View/Control/XPath choice сохраняется.

## Recorder: ответ на дополнительный запрос

Назад4, Домой3, Недавние187 и Меню82 проходят существующий observer Android
navigation bar. Добавлены четыре проверки полной цепочки: click→submitted→
запрет экспорта pending→Stop→поздний APK confirmed→ровно один key_event в DAG.
Ошибка/timeout не превращаются в success и не запускают автоматический повтор.
Меню может не иметь видимого результата в конкретном Android-приложении.

Однако **recording сейчас дискретный**: pointer up создаёт click или endpoint
swipe; native MOVE path не записывается. Normal control поддерживает live input
отдельно от recording. XPath добавляется явно из inspector как planned future
action; обычный tap не получает автоматически atomic XPath/PNG/crop/pixel bundle.
Обещать запись непрерывной траектории и синхронные пиксели нельзя.
Этот запрос остаётся существующим SF26-05/06, rich recorder OPEN.
[Versioned evidence plan](../2026-10-08/STUDIO-RECORDER-NEXT-P1.md).

## Проверки и пределы приёмки

Финальный локальный frontend:1936tests/139suites,69.491s. Focused navigation+
builder64passed, builder54; предыдущий focused stream/workbench/navigation145.
Nonincremental TypeScript passed. CI и установка этого source ещё pending.

Source preview был визуально наблюдён при фактических390×844 и1280×720,
позже648×884. Проверены добавление свободного узла из мобильной библиотеки,
открытие параметров и Undo без публикации, desktop library+laboratory.
Viewport capability после reconnect не дала подтверждённого844×390: landscape
не считать живой приёмкой, только source breakpoint support.
Preview WebSocket показывает recovery из-за dev proxy; это не доказательство
состояния канала установленного3015. Новые Android команды в preview не отправлялись.

Не закрыты: реальная landscape/keyboard acceptance, same-session live refresh,
idle native receipt timeout, rich observation manifest/trajectory replay,
distributed controller lease, durable idempotency после F5, storage attribution.
Audit ledger остаётся9accepted/41open; частные UX проверки не закрывают весь пункт.

## Связанные контракты

[Builder](../../../frontend/app/(dashboard)/scripts/builder/page.tsx),
[workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx),
[stream](../../../frontend/src/features/stream/SingleDeviceStream.tsx),
[navigation](ROUTE-SCROLL-RESTORATION.md),
[outage retention](STUDIO-PERMISSION-OUTAGE-RETENTION.md),
[idle P1](../2026-10-08/STUDIO-IDLE-RECEIPT-FOLLOWUP.md).
