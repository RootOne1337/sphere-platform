# Управление одиночным потоком при статичном экране

**Дата:** 1 октября 2026, Asia/Yekaterinburg.
**Область:** карточка устройства и отдельный `/stream/{id}`; остальные viewer defaults сохраняются.

[Текущее состояние](CURRENT-STATE.md) · [Навигация Android](ANDROID-NAVIGATION.md) ·
[Video canary](VIDEO-CADENCE-CANARY.md)

## Counterexample и исправление

Оператор подтвердил улучшение живого видео PH010 / APK 1.2.39, затем показал
баннер «Нет новых видеокадров более 10 секунд» и невозможность нажать на экран.
`DeviceStream` связывал pointer input с `connection === 'live'`. ImageReader
может не присылать новое изображение неподвижного экрана; возраст кадра сам
по себе не доказывает disconnect или неправильные координаты.

Single-device views включают `enableStaticInput`. После первого успешного draw
текущего открытого socket новый tap/swipe допустим и в состоянии `stale`.
Баннер сообщает возраст и управление по последнему кадру. Это не доказательство
исправности Android, отсутствия network/encoder stall или свежести содержимого.
Автоматический keyframe recovery продолжает работать с bounded backoff.

## Границы

- Старое изображение другого socket не даёт разрешения на ввод после reconnect.
  Новая сессия должна нарисовать свой кадр; одних ping недостаточно.
- Socket OPEN и принадлежность кадра проверяются ещё раз при down/up, включая
  закрытие до React rerender. Error, transport timeout и decoder recovery
  блокируют новые действия. Unknown actions автоматически не повторяются.
- Held gesture отменяется при expiry/rotation/reconnect; после expiry можно
  начать отдельный жест. Coordinate mapping сохраняет native frame dimensions,
  object-fit/letterboxing и boundary clamp.
- APK `mapStreamPoints` дополнительно проверяет текущие display dimensions и
  rotation относительно активного capture; несовместимый input не исполняется.
- «Сохранить свежий кадр PNG» остаётся выключенным для stale image. Доступность
  pointer input не делает старое изображение свежим.
- Fleet tiles не включают новый opt-in. Частоту fleet snapshots этот фикс не меняет.

## Проверки

Source regressions: новый tap/swipe на static image; отмена прежнего held gesture;
close/error/denied/timeout; новый socket без нового draw; silent socket closure
до release; first-frame gate даже с ping; отдельный fresh PNG gate.
Сохраняются прежние rotation/pointer ownership, decoder/reconnect и navigation tests.
Полная frontend suite: **73 suites / 576 tests passed**, type-check и targeted
ESLint в существующем legacy config profile прошли. Compiled runtime записывается
в CURRENT-STATE отдельно; green source tests ещё не означают установленный UI.

CUA browser review ранее заблокирована политикой URL. Обход не выполнялся;
source tests и listener/build readback не являются browser visual acceptance.
Операторский скриншот — доказательство дефекта старого UI, не нового исправления.

Исходник: [DeviceStream](../../frontend/components/sphere/DeviceStream.tsx),
[pointer regressions](../../frontend/__tests__/stream/pointer-control.test.tsx),
[first-frame/PNG regressions](../../frontend/__tests__/stream/diagnostics.test.tsx).
Новые зависимости/сторонний source не добавлены.
