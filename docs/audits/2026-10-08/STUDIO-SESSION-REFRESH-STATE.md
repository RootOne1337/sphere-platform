# Studio: состояние лаборатории при обновлении авторизации

8 октября 2026. **UI36b160f9 установлен; runtime refresh acceptance ещё нужна.**
Это уточнение SF26-05/06; ledger остаётся9accepted/41open.

## Наблюдение и граница доказательств

После установленной task canary5382fe4 лаборатория позднее вернулась из
«Просмотра» в «Управление», карточка завершённого задания и execution marks
исчезли. Выбранный PH011 и сохранённый граф3/2 остались. Точное событие,
пересоздавшее лабораторию в том наблюдении, не записано: нельзя утверждать,
что именно refresh вызвал этот конкретный reset.

Отдельный контролируемый resize1440→390→default688 сохранил «Просмотр».
Responsive layout использует один DeviceWorkbench; этот конечный прогон
не воспроизвёл reset из-за перехода между компоновками. Он не является soak.

## Подтверждённый дефект исходников

Baseline [DeviceWorkbench5382fe4](https://github.com/RootOne1337/sphere-platform/blob/5382fe4bbabbe46b29eea081a8e6916afe1181bd/frontend/src/features/scripts/studio/DeviceWorkbench.tsx)
увеличивает local epoch при любом изменении `accessToken` и включает epoch
в React key OwnedWorkbench. Это пересоздаёт приватные состояния лаборатории:
очередь записи, pending control request IDs, task ID/version, pending/uncertain
launch и дочерний выбранный режим стрима. В частности, неизвестный результат
POST теряет блокировку повторного запуска при штатном refresh.

[Auth store](../../../frontend/lib/store.ts) уже различает два события:

| Событие | sessionVersion | Лаборатория |
| --- | --- | --- |
| Проверенный refresh того же user/org | Сохраняется | Сохраняет результаты, очередь и guards |
| Login/logout, явная новая сессия | Изменяется | Удаляет приватное состояние и старые callbacks |

Refresh проверяет user/org, а HTTP API привязывает requests к sessionVersion.
Пересоздание всей лаборатории по одному только token не соответствует этому
контракту. Исправление использует device ID + sessionVersion как key.

## Что сохраняется и что инвалидируется

Сохраняются очередь с исходным порядком/outcome, неизвестный POST, pending
POST, task ID и его version, полученные отчёты и выбранный режим. Никакой
Android command/task автоматически не повторяется. Late HTTP control receipt
обновляет существующий slot; неизвестный результат остаётся неизвестным.

Транспорт обновляет credentials независимо: [SingleDeviceStream](../../../frontend/src/features/stream/SingleDeviceStream.tsx)
инвалидирует старые frame/tree generations и pending hierarchy request;
[DeviceStream](../../../frontend/components/sphere/DeviceStream.tsx) закрывает
старое подключение и native owner при token change. Старый frame не допускает
нового root read. Это не сохранение старых grants или owner между токенами.

Подготовка task pin-ит token перед ожиданием known release. Если token
изменился до POST, подготовка сообщает «Задание не создано» и требует явного
нового запуска. Если POST уже отправлен, guard сохраняется до его результата;
валидный ответ той же сессии принимается ровно один раз. Настоящая смена
сессии игнорирует старый ответ и очищает приватные записи.

## Проверки исходников

[Workbench regressions](../../../frontend/__tests__/scripts/studio-workbench.test.tsx):
семь новых случаев: token rotation во время preparation; pending POST;
unknown POST; completed reports; pending response после смены сессии;
late recording receipt; session boundary с прежней строкой token.
Шесть новых проверок воспроизвели baseline defect:6failed/28passed до source fix.

[Stream regressions](../../../frontend/__tests__/stream/single-device-inspection.test.tsx)
дополнены проверкой сохранения «Просмотра» и запрета root read по frame старого
token. Существующие abort/stale-tree/native-owner tests остаются обязательными.
Workbench/stream/auth-refresh/store:93passed/4suites; nonincremental TypeScript
прошёл. Полный frontend suite:1892passed/138suites,70.577s. Hosted CI и
установка приняты: все4 exact-source workflows successful. Backend3337passed,
37skipped/229subtests, frontend1892passed/138suites, Android и preview green.
Reviewed UI установлен18:08:51 UTC,45 других контейнеров/schema/OTA сохранены.
Реальный saved-v1 task b50dd03f-db64-47ad-8001-af461e852653 завершил3шага;
View/queue0/graph3/2 сохранены. Наблюдение refresh пока не выполнено.
[Installed checkpoint и API follow-up](CONTINUOUS-VIEWER-FAULT-ISOLATION.md).

## Оставшиеся ограничения

При установке API be803773 в18:39 UTC отдельно наблюдался transient capability
failure: authorization boundary размонтировал Studio, после восстановления
сохранённый graph3/2 остался, но laboratory selection/task card/marks пропали.
F5 не выполнялся. Это другой, подтверждённый P1: route outage retention должна
сохранять same-identity uncertainty и одновременно запрещать все новые действия
по недоступным permissions. [Наблюдение](CONTINUOUS-VIEWER-FAULT-ISOLATION.md).
Последующий UI46ca2096 установлен9октябряUTC+5. Конечный72s отказ API без F5
сохранил task/marks/device/View и launch options; dirty/unknown guards и PNG
abort проверены fixtures. Это outage acceptance, а не свидетельство token
refresh. [Установленный retention checkpoint](../2026-10-09/STUDIO-PERMISSION-OUTAGE-RETENTION.md).

Source fixtures доказывают различие refresh/session boundary, а не источник
ранее замеченного runtime reset. Реальный same-session refresh в установленном
браузере пока не засвидетельствован. F5/unmount всё ещё удаляет in-memory queue
и unknown launch; durable task idempotency/reconciliation остаётся OPEN.
Данный fix не распределяет lease между операторами и не объясняет idle
`native_receipt_timeout`. [Idle follow-up](STUDIO-IDLE-RECEIPT-FOLLOWUP.md).
Токены, владельцы, приватный текст и raw hierarchy не публикуются в evidence.
