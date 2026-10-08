# Обычное управление без отдельного переключателя жестов

8 октября 2026, Asia/Yekaterinburg. Automatic UX `bc86752` установлен на3015;
API `28104f8` и APK10249 на PH011 сохранены. Жест и колесо подтверждены
независимым Android View. Первый переход Home исполнился, но native control
потребовал восстановления; второй Home вернулся в READY автоматически.
[Точное наблюдение и диагностический follow-up](CONTINUOUS-INPUT-HANDOFF-OBSERVATION.md).
Это исторический checkpoint первого automatic UI. Следующий установленный
UI `29eecb8` /API `2225f73` подтвердил drag/wheel/Home→READY и XPath highlight.
Полная installed handoff qualification ещё открыта: быстрый обратный переход
во время root read воспроизвёл rejection;
[follow-up](INSPECTION-RETURN-TO-CONTROL.md) установлен как `e88c4db` и
повторён в браузере без recovery. [Финальная приёмка](CONTROL-HANDOFF-INSTALLED-ACCEPTANCE.md).

## Поведение

«Управление» автоматически запрашивает возможности APK после собственного
успешно показанного v2 кадра. Native STARTUP0 включает DOWN/MOVE/UP. Отдельная
кнопка непрерывных жестов удалена; рядом с видео показаны состояние и ACK.
«Просмотр» освобождает owner и запрещает ввод. XPath-инспектор выбирает элемент
без Android input. Legacy APK получает честное дискретное управление;
в процессе capability probe оно доступно, потому что native owner ещё не создан.
Поздний offer не меняет путь посреди уже удерживаемого legacy жеста.

«Домой/Назад/Недавние», клавиши редактирования и ввод текста сначала ждут
native RELEASE3 того же controller; только затем отправляют единственную
дискретную команду. Свежие transport/permissions проверяются снова после ожидания.
Неподтверждённый release означает «команда не отправлена», не успех SHELL.
Неподтверждённый результат уже отправленного SHELL не допускает скрытый повтор.
После подтверждённой команды управление заново согласуется автоматически.

Колесо в READY передаёт короткий180ms жест через тот же native owner, с одной
точкой касания и ограниченными координатами. Нет дополнительного legacy SWIPE,
очереди отложенных wheel событий или повторения UP в новой сессии.
Ctrl/Meta+колесо остаётся браузерным zoom. Blur/hidden/mode/capture/socket loss
закрывают owner. UNKNOWN блокирует ввод до явного «Восстановить управление»;
новый viewer должен получить свой кадр и STARTUP, старые действия не повторяются.

Cold startup имеет6000ms deadline; opening heartbeat не истекает по READY
deadline раньше STARTUP. READY input/heartbeat сохраняет500ms receipt deadline.
Хранятся не более32 scalar pending receipts и один unsent MOVE; таймеры,
listeners, release waiter и wheel terminal освобождаются при смене viewer.

## Проверки и обнаруженные регрессии

Первый полный набор:1836 tests/137 suites, TypeScript0errors. Затем review
нашёл два связанных mode bugs: persistent continuous support блокировал
XPath pick и возврат к дискретной записи после известного native release.
Оба воспроизведены отдельными assertion (44passed/2failed) до исправления;
добавлена проверка wheel recording после такого перехода. Полный набор после
исправления:1837passed/137suites, TypeScript0errors. Финальный pointer subset
с дополнительной wheel assertion:46passed. Exact-source hosted build/приёмка
пакетного HTTP и reviewed image этого source завершены; installed observation
сохранён отдельно. Более поздний набор1844/137 относится к `29eecb8`.

Также проверяются native MOVE-before-UP без двойного SWIPE, legacy compatibility,
startup delay, known release handoff, denied permission после release,
UNKNOWN HTTP completion, wheel burst, blur, смена режима и pending offer при
записи. Recorder сохраняет завершённые дискретные действия; live trajectory
recording не выдается за готовую возможность. Полная запись и SF26-05 остаются OPEN.
