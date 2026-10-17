# Диагностика вне обрезаемого видеоблока

9 октября 2026. Source-проверка; новая компоновка ещё не установлена на момент
этого receipt. [Fingerprints и проверки](STREAM-DIAGNOSTICS-LAYOUT.json).

## Подтверждённый дефект

В установленном UI0b321d49 блок «Диагностика» находился внутри absolute overlay
видеоповерхности с overflow-hidden. При обычном desktop1280×720 лаборатория уже
панели: начало строк и нижние показатели обрезались. Это реальное наблюдение
браузера, не вывод из unit tests. Исходный снимок сохранён в локальном evidence.

## Изменение

Панель стала отдельным sibling после видео и Android navigation. Ширина ограничена
родителем, высота — min(60dvh,32rem); доступна собственная прокрутка с клавиатуры.
Есть sticky heading и явная кнопка «Закрыть диагностику». Цвета используют текущую
тему; сетка метрик имеет minmax(0,1fr) и перенос текста. Панель больше не live-region:
обновление счётчиков не требует непрерывных screen-reader объявлений.

Закрытие отменяет pending запрос и прекращает polling. Никаких Android input,
новых журналов, persistence, deadlines или reconnect budgets не добавлено.
Отдельная панель не переносит фокус и не закрывает лабораторию/запись/граф.

## Проверка исходника

- 151 tests/3 focused suites проходят; включая cancel pending poll при явном
  закрытии и отсутствие Android input/новых HTTP-запросов после закрытия.
- Полный frontend:1948 tests/139 suites,79.076s, всё прошло.
- Nonincremental TypeScript: exit0.

Exact-source CI/image и visual desktop/mobile acceptance относятся к следующему
installed receipt. Исторический source receipt диагностики не переписан.

## Idle failure теперь подтверждён с измерениями

На предыдущем установленном UI0b321d49/APIbe803773 PH01110249 находился в режиме
Control без касаний и записи. Между baseline13:02:43UTC и наблюдением13:13:05UTC
управление остановилось после разрешённого единственного idle recovery.
Точный момент самого failure не записан: это время наблюдения уже сохранённого
снимка. В момент fencing: №1340 отправлен/№1338 подтверждён,2 pending; oldest
№1339 HEARTBEAT512ms; browser tick gap15ms; последний actual ACK RTT248ms,
ACK age521ms; last send256ms; палец не удерживался, terminal не ожидался;
WebSocket OPEN,0B send buffer. Decode/render errors0/0, запись0/200, графv1/3узла/
2связи, Undo0. После сохранения доказательства выбран View. Save/Run не выполнялись.

Эти данные не поддерживают гипотезу browser scheduling gap или заполненного
browser send buffer в данном событии. Они не определяют участок задержки между
сервером, Redis, APK transport, native очередью и обратной доставкой. Увеличение
deadline не применялось. EP-020/029 и SF26-05 остаются OPEN;9accepted/41open.
Для исправления нужна корреляция server/APK/native receipts с этим browser snapshot.
