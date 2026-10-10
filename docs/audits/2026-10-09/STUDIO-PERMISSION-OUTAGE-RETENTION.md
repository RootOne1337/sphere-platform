# Studio: сохранение работы при временном отказе проверки доступа

9 октября 2026, Asia/Yekaterinburg. **UI46ca2096 установлен на3015; конечная приёмка отказа API выполнена.**
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

## Portalled модальные окна

Финальная проверка обнаружила дополнительную границу: Radix portal окна запуска
находится вне скрытого контейнера Studio. Одного `hidden/inert` у редактора для
него недостаточно. Первое исправление7a3820f4 поэтому ещё не устанавливалось.

RunScriptModal получает explicit `suspended` от Builder. Временный отказ закрывает
portalled UI и новые group/fleet reads, сохраняя selection/options, pending POST
и unknown guard в том же компоненте. Handler дополнительно проверяет текущее
admission перед отправкой. Успешный version/target-checked receipt, пришедший
во время outage, сохраняет ссылку на созданное задание/пакет, блокирует повтор
и не перенаправляет скрытую страницу. После восстановления переход явный.
Неизвестный POST остаётся неизвестным; автоматического повтора нет. Leave portal
скрывается уже в render, а pending navigation intent завершается отказом.

Modal baseline: **3 failed / 11 passed**. Новый green набор с Builder/group-hook:
**72 passed / 3 suites**. Подтверждены обычное скрытие портала, сохранность
приоритета, task/batch success during outage, unknown POST и передача suspended
родителем. Полный final прогон после portal fix указан в следующем checkpoint.

Local checkpoint: **1915 passed / 138 suites, 75.347 s**; nonincremental
TypeScript прошёл. После дополнительного render fence leave portal отдельно
повторён Builder: **50 passed**. Exact-source CI и установка приняты ниже.

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
не публикуются в отчётах. Исторические source checkpoints выше сохраняют
состояние на момент подготовки; финальная установленная версия описана ниже.

## Установленная приёмка, 8 октября20:13–20:23 UTC / 9 октябряUTC+5

Source **46ca2096fef48486be821b3239eeef16f231bbc5** установлен из проверенного
frontend CI37836971092, job113516363445, attempt1. Завершённый job независимо
подтвердил config digest **sha256:7ce74bf9feb70ec193c8791650a12c60a5084ffdc6411e6ec1e6b94baeaadb03**.
Архив120866245bytes;26pages/73assets. Загруженный Docker image ID
**sha256:0a13d13e0647848e47673b9e8fa5d9a1790ac6e5fa275a43d376c0edcc30f03a**;
UI запущен20:13:59.432214133Z. Установка заменила только UI;45 других
контейнеров, APIbe803773, schema и normal OTA сохранены. APK отдельно прочитан
через ADB: **1.2.49-dev /10249**; установка APK или продвижение OTA не выполнялись.

Все четыре exact-source workflows завершились успешно: frontend37836971092,
backend37836971186, Android37836971084, preview37836971113. Frontend CI:
**1915passed/138suites**; backend **3346passed/37skipped/229subtests**.
Types/build/image admission, packaged bootstrap, SQL restart, RLS, lint,
security и single Alembic head checks прошли. Raw job logs остаются private;
публичный receipt содержит только источник, номера, результаты и checksum.

На PH011 в режиме **«Просмотр»** один сохранённый version1 сценарий выполнил
3шага, включая sleep2000ms. Task380fa1ef завершён; graph3nodes/2edges,
три отчёта и три зелёные execution marks видны. Окно верхнего запуска открыто
с PH011 и priority8; второй запуск не отправлялся. Далее ровно один API container
штатно остановлен на72s при отсутствии active/queued tasks и восстановлен
`finally` в том же ID/image. Stop20:16:01.984884Z; start20:17:14.601003Z;
проверки восстановления завершены20:17:33.997470Z.45 других контейнеров,
schema и OTA остались прежними; контейнеры не пересоздавались.

При отказе AX показал **«Не удалось проверить права»**: editor/task/launch portal
исчезли из accessibility tree. F5 во время отказа и восстановления не выполнялся.
После автоматической проверки прав окно вернуло PH011/priority8. Оно закрыто
через «Отмена». Лаборатория сохранила PH011/«Просмотр», task ID, три отчёта,
execution marks, пустую очередь и тот же graph/version. Независимое SQL read
в20:23:12Z нашло **ровно одно** задание этого сценария с20:14:14Z; дополнительный
POST в этом конечном окне не обнаружен. Это не durable idempotency после F5.

Desktop1440×900 просмотрен визуально. Mobile390×844: document clientWidth и
scrollWidth равны390; обычный688 viewport после reset тоже без горизонтального
переполнения. Browser console read вернул0 записей из запроса последних40;
это ограниченный срез, а не полный console/soak audit.

**Граница доказательства:** отказ сохранён в AX-наблюдении, но screenshot самого
notice не получен. Ранний screenshot уже пришёлся на восстановление и оставлен
private. Публичные screenshot ниже показывают состояние до/после отказа; они не
выдаются за изображение outage. Реальный canary был View-only: новых Android
input/tree/PNG команд не отправляли. Dirty queue, pending/unknown POST во время
отказа, abort PNG и late success проверены компонентными fixtures отдельно,
а не этой установленной canary. Живой same-session token refresh не наблюдался.

[Машиночитаемая приёмка](STUDIO-PERMISSION-OUTAGE-INSTALLED-ACCEPTANCE.json) ·
[Окно до отказа](assets/permission-outage/modal-before.jpg) ·
[Окно после восстановления](assets/permission-outage/modal-restored.jpg) ·
[Desktop и три отчёта](assets/permission-outage/desktop-restored.jpg) ·
[Mobile390](assets/permission-outage/mobile-restored.jpg) ·
[Обычный viewport](assets/permission-outage/default-restored.jpg).

Пять evidence JPEG занимают суммарно375645bytes, ниже бюджета2MiB.
Они не содержат native Android pixels. Новое ночное наблюдение, широкая очистка
Docker, storage attribution, idle timeout и расширение recorder данным
checkpoint не выполнены и не закрыты. Ledger остаётся9accepted/41open.
