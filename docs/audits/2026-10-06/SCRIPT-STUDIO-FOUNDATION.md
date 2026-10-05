# Script Studio: рабочее основание конструктора

6 октября 2026, Asia/Yekaterinburg. Исходники аудита `15aede54`; установленный
API `76596c39`, UI `5405d465`. **EP-014…020 OPEN**; счёт 9 принято / 41 открыто
сохраняется. По прямому запросу пользователя Studio сейчас выделен в отдельный
этап; оставшиеся ресурсные/release gates не снимаются.

[Приоритеты](ENTERPRISE-PRIORITIES.md) · [Immutable backlog](../2026-10-05/ENTERPRISE-PRODUCT-BACKLOG.json) ·
[Текущее состояние](../../operations/CURRENT-STATE.md).

## Подтверждённые разрывы

| Область | Доказательство | Следствие |
|---|---|---|
| Palette | builder показывает 6 типов; backend допускает 32 | Поддерживаемые действия нельзя нормально добавить из интерфейса |
| Source | JSON целого сценария не редактируется; imported generic action только pre | Нельзя вставить сценарий, изменить сложные параметры и увидеть граф |
| Layout | В native browser workspace 656 px, содержимое 720 px | Высота редактора учитывает viewport вместо доступной рабочей области |
| Validation | Проверка только внутри save; endpoint без сохранения отсутствует | Оператор не получает серверную проверку до публикации версии |
| Draft/history | Нет undo/redo и восстановления черновика | Ошибка JSON или уход со страницы рискуют потерять работу |
| Graph identity | Pydantic принимает повтор `id=end` | Canonical map и Android индекс неоднозначны |
| Branch types | `condition.on_true=['end']` даёт TypeError, не ValidationError | Неверный source может получить 500 вместо понятного 422 |

Встроенный browser: «Новый сценарий» → `/scripts/builder`; исходный screenshot
[before](assets/script-studio/before.jpg). Исходник: [builder](../../../frontend/app/%28dashboard%29/scripts/builder/page.tsx),
[wire export/import](../../../frontend/lib/dag/export.ts), [server DAG](../../../backend/schemas/dag.py),
[APK runner](../../../android/app/src/main/kotlin/com/sphereplatform/agent/commands/DagRunner.kt).
Repro типов выполнен напрямую через `DAGScript.model_validate`, без записи БД или
Android-команд. Это не HTTP/RLS proof. Полная серверная проверка параметров всех
actions пока отсутствует: accepted graph не равен capability/preflight/успешному run.

## Этап A: предметный результат

1. Отделить source DAG 1.0 от canvas layout. Visual/source переход атомарен;
   invalid JSON остаётся в редакторе, save/run не используют прежний скрытый граф.
2. Сделать searchable palette всех canonical actions. Для complex actions оставить
   полноценное редактирование JSON параметров; не называть read-only pre редактором.
3. Серверная проверка draft без version/task/command создания: normalized DAG,
   SHA256, число узлов и точный scope проверки. Ошибки не возвращают исходные payloads.
4. Исправить duplicate identity и неверные condition references до hash/map lookup.
5. Bounded undo/redo; явное opt-in для одного локального draft на identity, TTL/size
   и явное восстановление. Ни autosave, ни restore не публикуют сценарий.
6. Сохранить optimistic version guard. Conflict не стирает source и не делает
   автоматический retry; stale validation не подтверждает новый source.
7. Запуск только сохранённой известной версии через существующий task admission,
   с явным выбором устройств. Не выдавать local playback animation за Android execution.
8. Перекомпоновать Studio в доступную высоту, с переносом toolbar, scrollable
   panels, читаемой светлой/тёмной темой и accessible labels.

## Следующие отдельные этапы

- EP-016: versioned action/capability schema, все параметры/limits/effects/results;
  strict runtime compatibility для конкретного APK. Каталог сам по себе не proof.
- EP-017/018: live target metadata, native stream, input receipts/recording,
  selector candidates, ambiguity/fallback, ownership и координаты после смены target.
- EP-019/020: step trace с command/frame/snapshot/attempt, replay без input,
  настоящий pause/step/cancel protocol, cancel/late-result safety.
- EP-021: единое automation workspace с schedules/triggers/resources references;
  не объединять сущности через декоративные ссылки без согласованных контрактов.

## Приёмка этапа

Unit/regression: visual/source roundtrip, malformed/duplicate refs, source parse error
с сохранением текста, concurrent conflict, stale validation, identity switch,
draft byte/TTL/storage failure, bounded history и отсутствие API writes от restore.
Backend route tests должны подтвердить no database mutation и обычную auth boundary.
Затем exact-source production build/types и текущий frontend suite, schema check,
установка с сохранением прочих компонентов и визуальная проверка в native browser.
Живой canary, если запускается, только отдельный безопасный start/sleep/end сценарий;
нельзя подменять его mocked result. APK/OTA не обновляются без отдельной причины.

## Ресурсные и эксплуатационные границы

Никаких бесконечных polling/сканеров или неограниченных draft/history buffers.
Local draft содержит полный source и layout только на этом ПК; сохранение включается
оператором, ошибки storage видны. History не является backup/version history БД.
Backend schema currently checks structure/types/routes and Lua safety, не доступность
selectors на экране, root/UIA2 permissions, retry side effects или сеть устройства.
Live stream/script 20–30/500/1000 devices и backup/restore остаются независимыми gates.
