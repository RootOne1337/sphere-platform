# F39 — права форм групп и локаций

Дата: 4 октября 2026, UTC+5. Продолжение
[реестра устройств](DEVICE-ACTION-PERMISSIONS.md) и
[контракта серверных capabilities](../2026-10-03/SESSION-CAPABILITIES.md).
**F39 остаётся PARTIAL**: этот этап проверяет существующие формы создания,
изменения и удаления групп/локаций, а не все действия всех страниц.

## Воспроизведённое расхождение

На архиве приложения **6635805** страницы групп не проверяли права действий.
Viewer/script_runner видели активные кнопки создания, изменения и удаления;
device_manager также мог открыть удаление. Открытая форма группы не блокировала
подтверждение после полученного отзыва права, включая отправку формы через Enter.

Страница локаций определяла права по локальному `user.role`, без проверенного
ответа `/auth/capabilities`. При локальной admin-роли pending/failed ответ или
полученные read-only permissions не блокировали операции и открытые диалоги.

**16 assertion failures / 0 passed / 0 runtime-error suites** воспроизведены
на отдельном `git archive` прежних исходников с новыми workflow tests в Node24.
Это ошибки интерфейса. Сервер уже имел соответствующие HTTP guards;
обхода серверной авторизации этим этапом не доказано.

## Серверный контракт

| Действие | HTTP | Требуемое право |
|---|---|---|
| Каталог групп и локаций / карточка локации | GET `/groups`, `/locations`, `/locations/:id` | `device:read` |
| Создание | POST `/groups`, `/locations` | `device:write` |
| Метаданные и родительская связь | PUT `/groups/:id`, `/locations/:id` | `device:write` |
| Удаление | DELETE `/groups/:id`, `/locations/:id` | `device:delete` |
| Назначение устройств через реестр | POST `/groups/:id/devices/move`, `/locations/:id/devices` | `device:write` |

Контракт сверён с [groups router](../../../backend/api/v1/groups/router.py)
и [locations router](../../../backend/api/v1/locations/router.py).
Удаление группы/локации отличается от удаления устройства и не получает право
`device:write` вместо `device:delete`. Device_manager сохраняет запись метаданных,
viewer/script_runner — чтение. Матрица ролей не дублируется в production frontend.

## Исправление

- Группы получают раздельные `device:write` и `device:delete` из существующего
  `CapabilitiesProvider`. Проверки есть у кнопок, открытия и отправки формы.
- Editor требует `canWrite`, delete dialog — `canDelete`; отсутствие положительного
  решения блокирует отправку. Удаление не запускается повторно при pending request.
- Enter проходит тот же guard, что кнопка. При полученном отзыве права черновик
  сохраняется в том же scope; отмена доступна, если запрос ещё не отправлен.
- Локации используют проверенные permissions вместо локальной иерархии ролей.
  Открытые create/edit/delete dialogs получают обновлённое решение и объяснение
  недоступности через `PermissionNotice`.
- Каталог, чтение карточки и ручное обновление остаются доступны для разрешённого
  чтения. Права не заменяют проверки свежести/владельца/родительской связи/receipt.
- Существующий session/role fence может закрыть private subtree при смене identity
  или роли. Сохранение черновика не обещается между разными identity.
- Уже отправленный HTTP запрос не отменяется задним числом. Backend проверяет
  текущую роль в БД; клиентский polling не обещает мгновенного обнаружения отзыва.

## Проверки исходников

| Проверка | Результат |
|---|---|
| Архив прежнего приложения | 16 assertion failures, 0 runtime-error suites |
| Группы / локации / regression реестра | 7 наборов / 83 passed |
| Весь frontend, Node24 | 107 наборов / 1013 passed |
| TypeScript | passed |
| Связанные HTTP tests на PostgreSQL/Redis | 89 passed, 0 failures/errors/skips |
| Изменённые Python tests | Ruff passed |

16 frontend cases проверяют read-only роли, независимое удаление, pending/failed
capabilities, отзыв права в открытых формах, Enter, сохранение черновика и
восстановление разрешённой записи. Старые workflow tests явно задают permissions
из серверного fixture; локального глобального обхода авторизации нет.
Эти page tests подменяют hook permissions и notice rendering, а не серверную
авторизацию. Реальный provider/notice проверяется отдельными существующими tests.
JSDOM не является визуальной приёмкой верстки или браузерного клавиатурного поведения.

16 новых HTTP cases проверяют настоящий SQL downgrade после выпуска admin JWT:
create/update/delete запрещены viewer/script_runner, delete — device_manager.
Owned записи сохраняются, запрещённое создание отсутствует в БД. Положительные
manager cases создают и изменяют группу/локацию через реальный API, затем получают
403 при удалении. Используется отдельная disposable audit БД и Redis;
живые Android роли и назначения не меняются.

Промежуточные ошибки test fixture (смешение mock hook с настоящим notice context,
тип union для permission arrays) не учитываются как дефекты приложения.

## Установка и границы приёмки

Source проверки не заменяют production build, проверку собранного образа и rollout.
На момент этого source-отчёта review UI остаётся **81d065a**, API **37bb436**;
APK/Tuna/OTA не обновляются для этого исправления. Установка нового UI и её
результат должны быть записаны отдельным срезом после завершения image checks.

Fresh browser acceptance остаётся **OPEN_URL_POLICY_BLOCKED**. Остальные формы,
экономичная JPEG-матрица, XPath, качество/latency видео, OTA reconciliation и
длительный stream+scripts прогон открыты. Исходные **33 source-fixed / 8 незакрытых,
включая три PARTIAL** сохраняются; frozen audit не переписывается.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[История исправлений](../2026-10-01/WEB-AUDIT-REMEDIATION.md) ·
[Readiness](../../operations/READINESS.md).
