# Переход из непрерывного управления в XPath-инспектор

8 октября 2026, Asia/Yekaterinburg. Область: один viewer PH011, APK10249;
исходный UI `bc86752`, API `28104f8`. Это регрессия владения вводом, а не
доказательство здоровья всего парка или заданной кадровой задержки.

При входе в инспектор браузер отправлял закрытие continuous owner и сразу
запрашивал `/devices/{id}/ui-hierarchy`. APK выполняет root SHELL только после
`claimDiscrete()`: ещё не освобождённый owner запрещает команду. Установленная
проверка получила `Android UI inspection unavailable: root/UI Automator command
failed`. Отдельное ручное чтение после завершённого освобождения вернуло
46 элементов launcher, 960×540, rotation0. Полный tree и его атрибуты не
публикуются. HTTP502 сам по себе не раскрывает конкретную APK exception;
кодовая гонка и наблюдение совместимы, но не доказывают причину всех ошибок UI.

## Исправление

`DeviceStream` сообщает готовность чтения только для своего текущего кадра:
нет continuous owner либо именно этот controller получил native RELEASE3.
Наличие Redis lease, завершение send, режим `retiring`, таймаут и unknown release
не являются освобождением. Активная discrete команда также удерживает gate.
`SingleDeviceStream` ждёт это подтверждение перед первым чтением, ручным
refresh и периодическим опросом. Нажатую во время ожидания точку сохраняет
только до следующего валидного ограниченного snapshot. Режим инспекции не
отправляет Android нажатий. Смена устройства, token, geometry/socket и permission
сохраняет прежние generation/abort checks. Ошибка чтения всё ещё ставит
автообновление на паузу; скрытых повторов root команд не добавлено.

## Проверки и ограничения

64 tests в pointer-control/single-device-inspection прошли; nonincremental
TypeScript проверка прошла. Новые случаи: отсутствие root RPC до release,
сохранение queued pick, RELEASE3 открывает gate, unknown release не открывает.
Проверка использует реальные отдельные consumer/controller границы, а не
только счётчик callback. Требуются exact-source hosted build/install и повторный
браузерный переход с выбором элемента; пока это source fix, не installed acceptance.

Серверная periodic authorization исправляется отдельным source `7e504d9`.
Первый fenced Home рассматривается отдельно в
[наблюдении перехода](CONTINUOUS-INPUT-HANDOFF-OBSERVATION.md).
SF26-05 и эксплуатационная квалификация остаются OPEN.

## Ограниченное ожидание и восстановление

Следующий review обнаружил скрытую кнопку recovery в режиме inspection.
Если RELEASE3 отсутствует, ожидание ограничено3000ms; UI сохраняет gate,
показывает `inspection_release_unknown` и явное восстановление свежего viewer.
Ни root read, ни касание автоматически не повторяются. Рендер возраста дерева
не продлевает deadline; известный release отменяет timer. Новый regression
сначала воспроизвёл64passed/1failed, затем65passed, TypeScript0errors.
Установленная браузерная приёмка этого follow-up ещё требуется.

## Установленная проверка `29eecb8`

8 октября около07:04UTC+5, API `2225f73`, PH01110249. Реальный браузер показал
ожидание native release перед первым root read, затем46узлов launcher960×540.
Выбор значка Sphere Agent показал bounds/XPath/все возвращённые атрибуты;
сам Android остался в launcher. Один следующий auto read завершился root SHELL
exit1, auto polling честно приостановился и предыдущий snapshot сохранился.
После двух отдельных read-only stage probes и явного возобновления несколько
auto reads успешны. Причина единичного exit1 не установлена; не считать это
безошибочным soak. Private probes использовали уникальные временные XML,
их cleanup подтверждён; XML/полные деревья не публикуются.

Обратный быстрый XPath→Control при pending read воспроизвёл другой native
rejection. Исправление и собственная приёмка разделены в
[следующем документе](INSPECTION-RETURN-TO-CONTROL.md).
