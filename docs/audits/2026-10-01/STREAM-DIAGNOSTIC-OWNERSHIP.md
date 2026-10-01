# Веб: владение диагностическим отчётом и его свежесть

Дата: **1 октября 2026**, Asia/Yekaterinburg.
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Static input contract](../../operations/STATIC-STREAM-INPUT.md) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19).

## Подтверждённые ошибки

В `DeviceStream` прежний APK report оставался видимым после выбора другого
устройства до следующего HTTP response. Poll не зависел от смены auth session.
Медленный запрос допускал дополнительные параллельные polls каждые 15 секунд.
Отображаемый возраст APK snapshot не увеличивался между HTTP responses.

Три новых regression tests падают на прежнем коде: смена устройства при pending
request, незавершённый запрос длительностью 45 s и возраст snapshot между polls.

## Контракт исправления

- Ответ привязан к выбранным `deviceId` и auth token в памяти компонента; данные
  предыдущего выбора скрываются уже при render нового выбора. Токен не выводится
  в интерфейс, логи или метрики.
- Один poll в полёте. Cleanup отменяет HTTP через AbortSignal. Если транспорт
  всё же вернул запоздалый ответ, неактивный effect не обновляет state.
- Возраст из API дополняется прошедшим временем браузерных monotonic clock,
  с обновлением раз в секунду только при открытой диагностике. Неизвестная
  исходная свежесть остаётся неизвестной.
- Poll failure виден оператору; следующий успешный poll убирает сообщение ошибки.
  Диагностический GET не запускает screenshot, stream или другие Android actions.

## Проверка

Targeted stream diagnostics: **14 passed**, включая auth replacement, поздний
response, recovery после poll failure и существующие first-frame/PNG/input gates.
Полный frontend: **73 suites / 582 tests passed**; TypeScript и lint изменённых
файлов прошли. Build и установленный runtime учитываются отдельно в
[CURRENT-STATE](../../operations/CURRENT-STATE.md).

Это подтверждение React/transport-контракта. Оно не является визуальным browser QA,
измерением draw FPS или input-to-visible latency удалённого эмулятора.
