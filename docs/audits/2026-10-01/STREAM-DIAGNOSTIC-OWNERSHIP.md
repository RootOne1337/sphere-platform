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

## Установленный runtime

Compiled UI **8f615c6** установлен **17:28:52 UTC+5** на
`3015 → UI 3023 / API 18080`; предыдущий Next 3022 сохранён.
Его frontend source tree совпадает с code head **8d64ca4**:
[Frontend CI 36864314913](https://github.com/RootOne1337/sphere-platform/actions/runs/36864314913)
tests/types/build passed. API 8d64ca4 установлен отдельно в 18:04:04.
Native canary подтверждает пользу отдельного возраста: на 40 s diagnostics
содержал тот же post-encoding heartbeat, что на 25 s, хотя viewer принимал новые
pictures. Browser visual review blocked URL policy и не обходилась.
[Runtime/OTA/native evidence и ограничения](CALLBACK-LIFECYCLE-CANARY.md).
