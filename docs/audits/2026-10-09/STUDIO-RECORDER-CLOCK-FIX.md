# Studio: смешение часов в очереди XPath и Android input

Дата: 9 октября 2026, Asia/Yekaterinburg. Исходный срез: `5effec7d`.

## Подтверждённый дефект

`StreamInput.at` использует монотонное `performance.now()`: это время отправки
команды, не календарное время и не время получения позднего ответа APK.
Клик/свайп в `DeviceStream` и submitted/completed receipts AndroidNavigationBar
соблюдают этот контракт. `DeviceWorkbench.onInsertSelector` передавал `Date.now()`.

Одна очередь поэтому содержала два несовместимых начала отсчёта. Последовательность
клик → XPath → клик при настоящем epoch времени останавливала запись с ошибкой
порядка времени, хотя действия пользователя были последовательными. Перевод
системных часов мог также исказить паузы. Ранее компонентный тест подменял Date.now
значением 2000 и проверял только клик → XPath; следующий ввод не проверялся.

## Регрессия до исправления

Новый компонентный тест вызывает настоящие callbacks DeviceWorkbench в порядке
клик(1000) → XPath(2000) → клик(3000) → Back submitted(3500), Stop, ACK(3800).
Android transport и hooks заменены fixtures; реальное устройство не управляется.

Два значения wall clock проверяют независимость от календарного времени:

| Date.now | Результат исходного кода |
| --- | --- |
| 1791500000000 | Запись остановлена до Stop: следующего клика нет в очереди |
| 1000 | Ошибочные паузы: первая пропала, вторая стала 2000 вместо 1000 мс |

Оба новых случая упали на исходном коде. Изменён существующий selector тест:
он теперь подменяет монотонные часы, соответствующие transport contract.

## Изменение и проверка

Selector insertion теперь использует `performance.now()`. Защиты порядка,
device binding, размера очереди, pending/unknown и позднего ACK сохранены.
XPath остаётся явно выбранным будущим шагом, без утверждения, что APK его выполнил.

После исправления оба случая сохраняют четыре исходных действия, три паузы
1000/1000/500 мс и APK receipt в исходной строке. DAG передаётся только явной
кнопкой после Stop; fixture не вызывает POST /tasks и не меняет версию.

| Проверка текущих исходников | Результат |
| --- | --- |
| Workbench + selector + command recording | 76 passed / 3 suites |
| Полный frontend Jest | 1938 passed / 139 suites, 80.288 с |
| TypeScript, без incremental cache | Exit 0 |

Полный набор сохранил существующие предупреждения Radix о Description в
Users dialogs и предупреждение Node о localstorage-file. Они не являются
доказательством доступности всех модальных окон; учитываются в EP-048 отдельно.

## Границы доставки

На момент проверки браузер на3015 всё ещё показывает UI **ec3f2267**, API
**be803773**. Этот документ подтверждает source correction и регрессии;
установка нового reviewed artifact и mixed-input browser acceptance ещё не
проводились. APK/API не менялись. 9/41 продуктового ledger не изменяется:
EP-018 включает существенно более широкую запись и остаётся OPEN.

[Workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx) ·
[Regression](../../../frontend/__tests__/scripts/studio-workbench.test.tsx) ·
[Clock contract](../../../frontend/src/features/stream/controlObservation.ts) ·
[Следующие требования](../2026-10-08/STUDIO-RECORDER-NEXT-P1.md).
