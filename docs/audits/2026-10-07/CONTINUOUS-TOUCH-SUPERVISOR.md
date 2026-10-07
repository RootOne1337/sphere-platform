# Непрерывное управление: ограниченная очередь и владение Android-инжектором

Продолжение **7 октября 2026, Asia/Yekaterinburg**; [native canary](CONTINUOUS-TOUCH-NATIVE-CANARY.md)
и [SF26-05](../2026-10-06/STUDIO-INTERACTION-FOLLOWUP.md). Эта часть реализована
в source, но **не подключена к CommandDispatcher/браузеру и не установлена как
новый APK**. На 3015 остаётся UI af9054e / API a41c4e6. Ledger 9/41 сохраняется.

## Владение и жизненный цикл

[ContinuousTouchSupervisor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousTouchSupervisor.kt)
имеет ровно один текущий owner и один последовательный worker. Входящее движение
не создаёт coroutine или root-процесс. Construction ленивый; только явный
`open(binding)` может запустить один helper. Binding содержит owner, capture
epoch и физическую геометрию, с ограничением идентификаторов/размеров.
Это интерфейс для **будущей server-issued lease**, а не самостоятельная auth
проверка: вызов из недоверенного browser payload запрещён до её интеграции.

Активный owner нельзя незаметно заменить ни другой сессией, ни duplicate open.
Нужен явный close с завершением старого pipe. Invalidating owner немедленно
закрывает admission и удаляет pending events; уже отправленный input может
завершиться и получить свой receipt. Он не повторяется.

На каждой итерации проверяются capture ownership predicate и device-monotonic
lease. Новая геометрия/эпоха, disconnect или service stop должны вызывать
`invalidate()` до асинхронного `close()`. Эти callbacks пока не зарегистрированы
в действующем диспетчере; эта инструкция не выдаёт их за выполненную поставку.

Если pipe termination/cancellation неизвестны, `needsReset=true` запрещает
следующий open. Автоматического сброса флага и повторной инжекции нет. До
продуктового включения нужен отдельно проверенный native reset, включая
SIGKILL/столкновение с DAG и restart самого APK. Простое создание нового
supervisor не является доказанным release предыдущего touch.

## Ограниченная очередь

[ContinuousTouchMailbox](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/ContinuousTouchMailbox.kt)
содержит максимум **четыре** ожидающих события. Для обычных событий доступны
три места; четвёртое зарезервировано для UP/CANCEL.

| Случай | Поведение |
| --- | --- |
| Последовательные MOVE одного gesture | Pending MOVE заменяется последней точкой; DOWN и terminal остаются |
| Движение по разные стороны UP/CANCEL/нового DOWN | Не объединяется через barrier |
| Последовательные heartbeat | Заменяются последним; MOVE не синтезируется |
| Чужой owner | Отказ; настоящий owner не отменяется и его lease не обновляется |
| Та же owner, неверная capture epoch/sequence/gesture/bounds | Admission закрывается, pending очищается, pipe освобождается |
| Переполнение очереди | Owner retired; не отбрасывается UP с продолжением held state |
| Pending sample старше 500 ms | Не исполняется задним числом; owner retired |
| Receipt gap >= 1500 ms | Lease истёк, поздний heartbeat не оживляет session |

Device receipt time читается под тем же lock, что admission; browser clock
не переносится в MotionEvent. Свежий heartbeat не обновляет возраст старого
DOWN/MOVE, заблокированного в очереди. Coalescing означает, что не каждая
присланная точка была injected: recorder обязан сохранять это различие.

Модельный stress: 10 000 MOVE при удержанном worker дают **DOWN → последний
MOVE → UP**, без накопления 10 000 объектов. Это проверка очереди, не доказанный
парковый load/soak и не измерение FPS.

## Приватный root pipe

[RootTouchPipeFactory](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/RootTouchPipeFactory.kt)
использует installed APK на CLASSPATH и отдельный `su -c exec app_process`.
APK path проверен/quoted; command содержит только фиксированную entry point
и заранее проверенную геометрию. Ни owner token, ни координаты не попадают
в shell-команду. Stdout дискретного AdbActionExecutor не переиспользуется.

Входной packet — bounded hex protocol из native stage. ACK читается строго,
включая sequence, magic, status, canonical length/LF-or-CRLF. Положительный
ACK должен соответствовать действию: 1 — input, 2 — heartbeat, 3 — CANCEL. Неверный,
пропавший, усечённый, переполненный ACK или write failure не вызывает replay.

Startup ACK deadline — 5 s; input ACK — 500 ms. Stderr не сохраняется, его lifetime
budget — 4096 bytes. Teardown закрывает stdin, ожидает normal owned-process exit
не более 2 s, ограниченно дренирует streams, затем завершает процесс при отказе.
Force kill — **не** cancellation confirmation; helper descendant/SIGKILL
acceptance остаётся открытой. Возможные stall внутри OS write/Binder не имеют
доказанного hard wall-clock deadline; нельзя обещать 500 ms для всей платформы.

`open()` возвращает только admission начатой lifecycle операции. Ready должен
подтверждаться отдельным STARTUP receipt. INPUT receipt содержит sequence
конкретной попытки. RELEASE receipt сообщает cleanup отдельно, поэтому
успешный teardown не переписывает unknown outcome нажатия.

## Проверки и границы

[Mailbox tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/ContinuousTouchMailboxTest.kt),
[supervisor tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/ContinuousTouchSupervisorTest.kt),
[pipe tests](../../../android/app/src/test/kotlin/com/sphereplatform/agent/commands/ProcessTouchPipeTest.kt)
проверяют поведение независимыми fake receiver/pipe и process outcomes.
Полный локальный прогон обеих Android debug variants завершён успешно:
**925 passed / 3 skipped в каждой, 77 suites**. Новая часть содержит
**33 самостоятельных случая**: 12 mailbox, 12 supervisor и 9 process pipe.
Прежние 23 native state/wire случая также прошли в каждом варианте.
Это 56 разных touch-тестов, выполняемых дважды, а не 112 разных сценариев.
[Точные результаты и SHA-256 исходников](CONTINUOUS-TOUCH-SUPERVISOR-EVIDENCE.json).

Реальная native приёмка MotionEvent относится к предыдущему source 1dccd05;
Kotlin supervisor на реальном Android пока не принят. Release/R8 smoke CI
предыдущего 1dccd05 успешен; следующий source требует собственного CI.

Обязательные следующие соединения: capture epoch/physical mapping, current
WS generation, synchronous bounded dispatcher admission, DAG exclusion,
server multiworker lease/auth renewal, scoped ACK delivery, browser pointermove
и loss cleanup, recorder trajectory/uncertainty. Старые APK и установленный
веб продолжают работать в discrete режиме; новая capability не рекламируется.
