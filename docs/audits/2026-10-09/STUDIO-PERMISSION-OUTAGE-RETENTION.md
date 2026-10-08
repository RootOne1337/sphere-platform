# Studio: сохранение работы при временном отказе проверки доступа

9 октября 2026, Asia/Yekaterinburg. **Подготовлено; установка и приёмка нового UI ещё не выполнены.**
Это уточнение SF26-05/06. Общий ledger остаётся **9 accepted / 41 open**;
восемь release gates не закрываются данным исправлением.

## Подтверждённое наблюдение

При штатной установке API be803773 в 18:39 UTC 8 октября запрос capabilities
временно не выполнился. RouteAccessBoundary размонтировал редактор. После
восстановления без F5 сохранённый граф 3 шага / 2 связи загрузился заново,
но выбранное устройство, лаборатория, карточка задания и execution marks
исчезли. [Установленный API и исходное наблюдение](../2026-10-08/CONTINUOUS-VIEWER-FAULT-ISOLATION.md).

Это отдельный дефект от пересоздания лаборатории при обновлении token,
исправленного в UI36b160f9. Отказ capabilities нельзя превращать в старые
действующие разрешения. Одновременно потеря pending/unknown результата POST
снимает защиту от повторного запуска и потому не является косметическим UX.

## Контракт сохранности

| Событие | Состояние редактора | Новые действия |
| --- | --- | --- |
| Ранее разрешённый Studio, временный network/5xx/408/429 или истечение свежести ответа | Скрытое, inert, в памяти той же страницы | Запрещены до нового проверенного ответа |
| Первый неподтверждённый доступ | Редактор не монтируется | Запрещены |
| Валидный ответ с отзывом права чтения | Приватное поддерево удаляется | Запрещены |
| Невалидная схема/ownership ответа или 4xx кроме408/429 | Приватное поддерево удаляется | Запрещены |
| Смена пользователя/org/role/sessionVersion | Старое приватное поддерево удаляется | Только по разрешениям новой сессии |
| Восстановление той же личности и разрешений | Тот же черновик, устройство, очередь и результат | Требуется новая авторизация транспорта |

Сохранение памяти не означает сохранение grants, сокета или native owner.
`can()` и `canAccessRoute()` остаются false при непроверенном ответе.
Специальная retention boundary применяется только к `/scripts/builder`.
Другие страницы продолжают использовать прежнюю строгую границу.

## Изменения исходников

- [Capabilities](../../../frontend/src/features/access/Capabilities.tsx):
  recoverable означает право сохранить память, а не выполнять команды;
  boundary привязана к session/org/user/role и pathname. Скрытая часть имеет
  `hidden`, `inert`, `aria-hidden`. Отзыв прав удаляет её до effects.
- [Builder](../../../frontend/app/(dashboard)/scripts/builder/page.tsx):
  готовый редактор сохраняет поддерево при временном отказе; pending диалог
  выхода завершается отказом. Guard не создаёт невидимый confirmation promise.
- [Workbench](../../../frontend/src/features/scripts/studio/DeviceWorkbench.tsx):
  сохраняет device, запись, task ID/version, pending POST и unknown guard;
  останавливает подготовку до POST при потере `script:execute`. Старый READY
  не позволяет создать задание после восстановления доступа.
- [Device/task hooks](../../../frontend/lib/hooks/useDevices.ts) и
  [task reads](../../../frontend/lib/hooks/useTasks.ts): optional admission
  отключает новые fleet/task/log reads при неподтверждённых разрешениях.
  Progress subscription тоже прекращается. Остальные callers не меняются.
- [SingleDeviceStream](../../../frontend/src/features/stream/SingleDeviceStream.tsx):
  при потере `stream:read` удаляет DeviceStream, закрывая старый transport и
  controller через существующий cleanup; сохраняет выбранный «Просмотр».
  Старые кадр/дерево больше не допускают root read. Native PNG panel удаляется
  при потере device-write; HTTP abort и URL cleanup не считаются Android ACK.

## Незавершённые native reads

Abort HTTP не отменяет уже отправленную Android-команду. Для hierarchy это
уже учитывалось. Для native PNG обнаружена дополнительная гонка: новая панель
при mount сообщает `idle`, хотя предыдущий capture был прерван сменой доступа
или token. Этот `idle` не должен допускать task handoff.

Теперь parent сохраняет отдельный aborted-capture fence. Поздние ответы старой
панели отбрасываются существующей generation guard. Remount, свежий видеокадр
и native handoff READY не снимают fence. Автоматического повторного screenshot
нет. После восстановления оператор явно получает новый проверенный исходный
PNG; только завершение этого запроса снимает fence для следующей попытки.
Неуспешный drain блокирует текущую попытку, не создавая task POST.

## Проверки и границы доказательств

Baseline route test: **1 failed / 32 passed** на прежней boundary. Первоначальный
прогон с тремя некорректными ожиданиями async refetch не используется как
доказательство дефекта: ожидания исправлены до принятого baseline.

Capture baseline на новом retention-коде, но без capture fence:
**2 failed / 29 passed**. Ошибки воспроизводят ложный READY после token и
permission abort. После fence stream suite: **32 passed**; дополнительный
recovery case проходит настоящий NativeScreenshotPanel и проверку ownership,
PNG signature/geometry, checksum receipt, object URL release. SHA digest
подменён детерминированной fixture: это проверка lifecycle, не реальных пикселей.

Шесть focused suites до последнего recovery case: **175 passed**. Неинкрементальный
TypeScript после последнего case прошёл. Финальный полный frontend прогон:
**1909 passed / 138 suites, 64.874 s**. CI image не подменён
локальной сборкой. Установленная на момент подготовки версия — UI36b160f9,
APIbe803773; APK/миграции/normal OTA данным source fix не меняются.

Компонентные regressions проверяют initial denial, transient503, authority4xx,
неверную ownership, session/role/grant change, несохранённый граф, скрытую
navigation guard, abort до POST, сохранение неизвестного POST, отсутствие
повторной команды, retirement stream, свежесть frame и capture recovery.
Они не заменяют runtime приёмку реального отказа API на установленном образе.

## Оставшиеся ограничения

- F5, закрытие вкладки и настоящий unmount всё ещё удаляют in-memory state.
  Durable task idempotency/reconciliation остаются OPEN.
- Queue и результат не переживают реальный logout, смену организации или отзыв
  права чтения. Это требуемая граница приватного состояния.
- Нативный retirement при outage использует прежний cleanup; при недоступном
  API release подтверждается только после восстановления/expiry. Это не новый
  distributed lease между viewer и task scheduler.
- Idle `native_receipt_timeout`, качество/latency видео и богатая запись всё
  ещё OPEN. Краткая успешная canary не доказывает непрерывную работоспособность.
- Storage incident OPEN; конечное окно сборщика завершилось, VSS/writer
  attribution недоступны. [Разбор окна](../2026-10-08/STORAGE-WINDOW-COMPLETION.md).
- Будущий прямой media transport сохранён как отдельная отложенная идея;
  технология пока не выбрана и не внедряется.
  [Границы будущего исследования](BROWSER-DIRECT-TRANSPORT-INTENT.md).

Raw credentials, owner IDs, иерархия Android, приватный текст и native pixels
не публикуются в отчётах. Установка и приёмка должны добавляться отдельным
checkpoint с source revision, CI receipt, сохранностью runtime и screenshot.
