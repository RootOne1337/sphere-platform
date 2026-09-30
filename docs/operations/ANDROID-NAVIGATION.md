# Навигация Android в одиночном видеопотоке

**Обновлено:** 1 октября 2026, Asia/Yekaterinburg.<br />
**Область:** полная карточка устройства и `/stream/{id}`; fleet tiles не получают эту панель.

[Текущее состояние](CURRENT-STATE.md) · [Video canary](VIDEO-CADENCE-CANARY.md) ·
[APK / UI inspection audit](../audits/2026-09-30/ANDROID-INSPECTION-AND-VIDEO-MODES.md) ·
[Каталог документации](../README.md) · [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Исправленная проблема

В активном `DeviceStream` не было Android navigation keys. Оператор мог открыть
Settings кликом по видеокадру, но не вернуться системной кнопкой Back. Старая
панель другого viewer отправляла плоский WS `keyevent`, который установленный
APK не обрабатывает. Новый frontend использует существующий подтверждаемый
интерактивный command contract; переустановка APK для этой панели не требуется.

| Кнопка | Android keycode | Команда |
| --- | --- | --- |
| Назад | 4 | `input keyevent 4` |
| Домой | 3 | `input keyevent 3` |
| Недавние | 187 | `input keyevent 187` |
| Меню | 82 | `input keyevent 82` |

Клавиши отправляются через authenticated `POST /api/v1/devices/{id}/shell`.
Backend проверяет организацию и `device:write`; Android выполняет команду через
свой root shell. Это **root-dependent** возможность текущего LDPlayer pilot,
не обещание работы shell input на обычном телефоне без привилегий. Команда Menu
зависит от приложения и может не менять экран. Host ADB / PC Agent не нужны.

## Состояния, границы и компоновка

- Панель находится отдельным footer под изображением, использует общие tokens,
  focus ring, обычные кнопки с keyboard activation и сетку 2/4 columns. Она не
  закрывает пиксели и не меняет native canvas resolution/object-fit.
- До первого успешно нарисованного кадра текущей WS-сессии управление выключено.
  После reconnect старое изображение не разблокирует клавиши. Ошибки управления
  и разрыв transport блокируют новые действия; transport проверяется ещё раз
  непосредственно при нажатии.
- При статичной картинке старше 10 секунд и продолжающейся связи системные
  клавиши доступны: они не используют координаты. Pointer tap/swipe по старому
  кадру по-прежнему блокируется.
- Одна pending-команда блокирует остальные клавиши синхронно, включая два
  клика в одном React batch. HTTP timeout 35 s превышает backend wait 30 s.
  Строковый `output`, включая пустую строку, подтверждает исполнение; HTTP 200
  с `error` или неполной структурой не считается успехом.
- Нет автоматического повтора при неопределённом результате. Смена устройства,
  login session или unmount отменяют HTTP wait и игнорируют старый callback.
  Abort **не отзывает** уже доставленную Android-команду. Перед новым ручным
  нажатием после unknown требуется посмотреть экран.
- Показанный command round trip измеряет ожидание API receipt, **не**
  input-to-visible latency. Подтверждение shell не доказывает, что новый кадр
  дошёл и отрисован браузером. Глобальные Esc/Backspace shortcuts не перехватываются.

## Доказательства и приёмка

1 октября source проверен полной frontend suite: **73 suites / 567 tests passed**,
`tsc --noEmit` и targeted ESLint. Регрессии покрывают четыре команды, успешный
пустой stdout, malformed/error/timeout responses, synchronous double click,
device/session/unmount abort, late response, keyboard activation, transport
loss/reconnect, first-frame/draw-failure и сохранение geometry/fleet defaults.
Production compile/deployed source stamp отмечаются отдельно в CURRENT-STATE.

Native remote control на **PH025, reported 10238**: одна private debug Activity
запущена, её foreground подтверждён read-only Android dump. Один `input keyevent 4`
получил successful empty output за **1672 ms** полного API round trip; следующий
read-only dump показал возврат launcher. Activity finite (30 s), foreign
applications/settings не менялись. Это проверка Back execution на удалённом
Android, не browser button/visual/layout acceptance и не 10–15 FPS gate. Home,
Recents и Menu проверены source regressions; native execution всех четырёх и
визуальная проверка панели остаются отдельной приёмкой.

PH010 не получил тестовый key: read-only foreground уже не подтверждал Settings,
поэтому действие пропущено. PH025 display readback всё ещё **5 Hz**, хотя оператор
сообщил изменение LDPlayer limit с 5 до 10; применение/restart не подтверждены.
Raw activity/root output и auth token сохраняются только локально; публичный
отчёт содержит allowlisted результаты, без credentials и содержимого приложений.

Browser review ранее заблокирована политикой URL CUA; обхода/нового screenshot
нет. Успешные unit tests и native root receipt не заменяют этот gate.

## Реализация

- [Панель и command lifecycle](../../frontend/src/features/stream/AndroidNavigationBar.tsx)
- [Активный video viewer](../../frontend/components/sphere/DeviceStream.tsx)
- [Карточка устройства](../../frontend/src/features/devices/DeviceInspectorDetail.tsx)
- [Интерактивный API](../../backend/api/v1/devices/router.py)
- [Android shell execution](../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/AdbActionExecutor.kt)
- [Command tests](../../frontend/__tests__/stream/android-navigation.test.tsx)
- [Stream/session tests](../../frontend/__tests__/stream/navigation-availability.test.tsx)

Новые библиотеки/заимствованный source не добавлены: общие Sphere UI-компоненты
и уже используемые Lucide icons. Native private control не становится частью
release APK или production сценария.
