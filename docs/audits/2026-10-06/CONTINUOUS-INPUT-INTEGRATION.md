# Непрерывное управление Android: проверенный upstream и границы интеграции

Дата исследования: **6 октября 2026, UTC**. PR [#19](https://github.com/RootOne1337/sphere-platform/pull/19).
Связано с **SF26-05 / EP-017,020** в [follow-up](STUDIO-INTERACTION-FOLLOWUP.md).
Статус: **source audit / design**, не поставленная continuous capability.
Установленные UI1c26ffc7/APIeb7a7c26/APK не менялись; команды Android не отправлялись.

## Почему жест сейчас выполняется только после отпускания

| Уровень | Наблюдение в source | Следствие |
| --- | --- | --- |
| [DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx) | pointerdown сохраняет начальную точку; pointerup отправляет click/swipe; pointermove handler отсутствует | До отпускания сеть не получает движения |
| [Viewer WS](../../../backend/api/ws/stream/router.py) | Поддерживаются click/swipe/keyevent/text; swipe содержит две точки и duration | Нельзя сохранить удерживаемый touch или кривую траекторию |
| [CommandDispatcher](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/CommandDispatcher.kt) | touch_swipe запускает mapStreamPoints и swipeRaw | Каждый запрос — законченный жест |
| [AdbActionExecutor](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt) | Постоянный su pipe, но отдельная команда `input swipe` для каждого жеста | Persistent shell не превращает свайп в DOWN/MOVE/UP |

Это достаточное доказательство протокольного ограничения. Язык Python сам по
себе его не создаёт; реальное влияние очередей/сети/CPU требует отдельного замера.
Current swipe duration вычисляется из расстояния150–600ms; это не запись
реального времени удержания. Старый альтернативный decoder component тоже
отправляет только завершённый жест, но выбранные device/workbench routes
используют Sphere DeviceStream из первой строки.

Дополнительные риски для нового протокола: viewer session ID передаётся в
touch_tap/touch_swipe, но APK handlers не проверяют его как owner/epoch;
они используют текущую active capture geometry. Это source observation,
**не доказанный live stale-input incident**. Непрерывный режим нельзя включать,
наследуя такую неопределённость владения.

## Готовое решение: scrcpy, pinned v5.0

Официальный [release v5.0](https://github.com/Genymobile/scrcpy/releases/tag/v5.0)
опубликован **5 октября2026,10:30:35Z**, проверено GitHub API.
Annotated tag object `1de04a1f3d7716f86625601d51f73328dda864bd` указывает на commit
**`19871982cefb9de4c981c2314dfda2ac81564b48`**.
Авторство: **Genymobile / scrcpy contributors**; [Apache-2.0 LICENSE](https://github.com/Genymobile/scrcpy/blob/19871982cefb9de4c981c2314dfda2ac81564b48/LICENSE).
Это исследованный upstream, **не новая включённая зависимость**. Исходники,
assets или server binary в Sphere не копировались; при будущей поставке нужны
полная лицензия, NOTICE при его наличии, provenance и перечень изменений.

Проверены исходники именно этого commit:

- [Controller](https://github.com/Genymobile/scrcpy/blob/19871982cefb9de4c981c2314dfda2ac81564b48/server/src/main/java/com/genymobile/scrcpy/control/Controller.java):
  injectTouch, собственный downTime, pointer state, MotionEvent и Device.injectEvent.
  Touch и мышь имеют разные Android source/buttons semantics.
- [ControlMessageReader](https://github.com/Genymobile/scrcpy/blob/19871982cefb9de4c981c2314dfda2ac81564b48/server/src/main/java/com/genymobile/scrcpy/control/ControlMessageReader.java):
  отдельный binary control format, action,64-bit pointerId, position со screen
  dimensions, pressure, actionButton/buttons. Не JSON Sphere WS.
- [Options](https://github.com/Genymobile/scrcpy/blob/19871982cefb9de4c981c2314dfda2ac81564b48/server/src/main/java/com/genymobile/scrcpy/Options.java):
  независимые video/audio/control flags; exact client/server version check.
  Это позволяет исследовать control-only sidecar без второго video encoder.
- [Architecture](https://github.com/Genymobile/scrcpy/blob/19871982cefb9de4c981c2314dfda2ac81564b48/doc/develop.md):
  privileged app_process server, отдельный control socket, hidden Android injection.
  **Важно:** примеры/описание protocol в этом файле всё ещё именуют4.0.
  Для adapter5.0 необходимы pinned source и upstream serialization tests;
  команды и wire layout нельзя копировать из устаревшего примера вслепую.

README v5.0 указывает минимум Android API21. Это upstream requirement;
совместимость конкретного LDPlayer Android9/root/OEM ещё не принята.
Чужие заявления о latency/FPS не являются измерениями Sphere.

## Выбранное направление, ещё не реализация

Исследовать **versioned control-only sidecar adapter** внутри Android agent:
Sphere сохраняет текущие H.264, auth, task DAG и telemetry paths. Привилегированный
helper принимает инжекцию через локальный канал; браузер не получает su/ADB
и не говорит напрямую на нестабильном scrcpy binary protocol.

| Вариант | Оценка |
| --- | --- |
| Отдельный pinned scrcpy server и Sphere adapter | Первый кандидат: upstream содержит Android compatibility work; нужны lifecycle, packet parity и локальная защита канала |
| Копировать Controller/reflection в APK | Больше собственных Android/OEM рисков и обязанностей сопровождения; обычный app UID не приобретает INJECT_EVENTS |
| Серия HTTP/WS input swipe на каждый mousemove | Не соответствует held-touch: каждое движение начинает отдельный жест; очереди увеличивают задержку |
| UIAutomator/Accessibility finished gesture API | Полезны для script-level automation, но не эквивалент произвольному low-latency held input без отдельной реализации |

Для control-only режима source Controller допускает physical display без
video display mapping. Sphere adapter должен передавать **physical coordinates**
после собственной проверенной capture→display трансформации. Crop/scale/rotation
не должны обрабатываться дважды. Same-size rotation/session replacement требует
новой geometry epoch, даже если width/height совпали.

## Обязательный контракт Sphere, предлагается v1

Это требования к будущим совместным source changes, не существующий endpoint.

1. Capability сообщает protocolVersion, injectorVersion/hash, ready/failure,
   supported display, pointer limit и geometry epoch. Наличие root не равно
   successful injection. Неизвестная/старая APK остаётся в discrete режиме.
2. Server-issued owner lease на device; atomically fenced к user/tenant/session.
   Один controller в первой версии. Сценарий и ручное управление не борются
   за touch; takeover требует явного stop/release, не скрытого захвата.
3. Сообщение содержит action DOWN/MOVE/UP/CANCEL, pointer/gesture ID, sequence,
   lease epoch и capture geometry epoch. Типы конечны/строги, bounds проверены.
   DOWN с новым gesture не может заменять удерживаемый touch незаметно.
4. Android downTime/eventTime берутся из monotonic uptime устройства. Browser
   wall clock не используется для Android MotionEvent; clock domains различаются.
5. MOVE коалесцируется до последней точки в bounded queue. DOWN/UP/CANCEL не
   теряются и не переставляются. Предел rate/queue согласуется capability;
   бесконечные coroutines/shell commands для каждого движения запрещены.
6. Pointercancel/lost capture, blur, hidden tab, rotation, owner expiry,
   socket close и sidecar failure освобождают held state. Terminal cleanup
   должен работать локально на Android даже при полной потере сервера.
7. В pinned Controller pointer release учитывается через ACTION_UP. Наличие
   ACTION_CANCEL на wire **не доказывает очистку всех внутренних pointer slots**.
   Adapter обязан проверить release/reset на sidecar, а не просто отправить
   один CANCEL и объявить безопасность. При неизвестном результате управление
   блокируется до подтверждённого reset; старый DOWN не replay после reconnect.
8. ACK различает adapter accepted / injected / rejected / unknown. Transport
   send и inject ACK не выдаются за изменение изображения. Неизвестный ввод
   автоматически не повторяется; recorder сохраняет uncertainty.
9. Исходный PNG, XPath dump и capture frame имеют независимые временные метки.
   Special recorder не обещает один и тот же момент без correlation protocol.
   Кривая trajectory не превращается в точный straight swipe без предупреждения.

## Минимальная приёмка перед включением

| Проверка | Что должно быть доказано |
| --- | --- |
| Pure protocol tests | Strict types, stale epochs, duplicate/reordered events, sequence/owner isolation |
| Adapter parity | Binary packets против pinned upstream serialization fixtures; exact5.0 version rejection |
| Privileged local canary | DOWN действительно удерживается; MOVE изменяет Android до UP; no phantom taps |
| Loss during held touch | Client/server/sidecar crash, socket reset, timeout/lease loss освобождают touch |
| Geometry | Landscape/portrait, crop/scale, same-size epoch change, outside-video letterbox |
| Weak remote canary | Android5/10Hz не подменяется дублированием кадров; trace сохраняет реальные FPS |
| Resource/lifecycle | Один bounded helper/channel на active controller, cleanup, process/RAM/queue limits |
| Latency | Submit→inject и submit→correlated rendered frame отдельно, local/remote p50/p95 + sample count |

C: **Warning /Full Repair Needed** не позволяет сейчас выполнять новый APK/Next
build и установку. Hosted source tests можно выполнять отдельно; никакое
положительное unit/CI подтверждение не заменяет эти runtime canaries.
Общий ledger **9 accepted /41 open** не изменён. VPN/AI/group input этим этапом
не подключаются; сначала single-owner input и его отказные случаи.
