# Исправления по полному веб-аудиту — 1 октября 2026

Этот журнал продолжает [замороженный аудит](WEB-FULL-CAPABILITY-AUDIT.md) исходников `1354d66`. Исходный документ и evidence сохраняют свою дату и ограничения; их статусы не переписываются задним числом.

## Исходная фиксация

- Аудит: 29 маршрутов, 169 REST-операций, 151 схема / 1112 свойств, 565 деклараций контролов и 41 содержимое Dialog.
- 41 замечание: 5 P1, 35 P2, 1 P3; ошибки исходников, capability gaps и acceptance risks разделены.
- Девять изолированных source-contract доказательств и 27 проверок документа; это не функциональная приёмка продукта.
- Текущий Sphere visual walkthrough остался заблокирован URL policy; исторические снимки не стали fresh evidence.
- Backend health build `8d64ca4`, исходники PR `1354d66`, ранее установленный frontend `8f615c6` различаются.

## Порядок работы

1. F03: безопасная загрузка существующего DAG, запрет записи после load error, retry и смена target.
2. F04/F05: успешный baseline настроек до записи, сохранение dirty draft при toggle/refetch.
3. F01/F02: реальная семантика показателей задания и различение 404/403/network/stale.
4. Контракты payload/outcome, полнота больших каталогов, затем модальные окна/навигация и операционная глубина.

Каждый batch получает отдельный commit с проверками конкретного operator outcome. Source regression, build, установленный runtime и live acceptance фиксируются отдельно. Публикация новых APK не нужна для исправления веб-форм.

## Реестр

| ID | Приоритет | Статус после аудита | Предмет |
|---|---|---|---|
| [F01](WEB-FULL-CAPABILITY-AUDIT.md#f01) | P1 | Открыто | Задание: недостоверный Pass Rate |
| [F02](WEB-FULL-CAPABILITY-AUDIT.md#f02) | P1 | Открыто | Задание: ошибка API подменяется отсутствием записи |
| [F03](WEB-FULL-CAPABILITY-AUDIT.md#f03) | P1 | Source исправлен; live OPEN | Редактор: разрешена запись после провала загрузки DAG |
| [F04](WEB-FULL-CAPABILITY-AUDIT.md#f04) | P1 | Source исправлен; live OPEN | Настройки pipeline: можно сохранить неподтверждённые defaults |
| [F05](WEB-FULL-CAPABILITY-AUDIT.md#f05) | P1 | Source исправлен; live OPEN | Настройки pipeline: несохранённая форма сбрасывается |
| [F06](WEB-FULL-CAPABILITY-AUDIT.md#f06) | P2 | Открыто | Локации: очистка текста не передаётся серверу |
| [F07](WEB-FULL-CAPABILITY-AUDIT.md#f07) | P2 | Открыто | Аккаунты: законопослушность не отправляется при создании |
| [F08](WEB-FULL-CAPABILITY-AUDIT.md#f08) | P2 | Открыто | Аккаунты: debounce фактически не отменяет прошлые таймеры |
| [F09](WEB-FULL-CAPABILITY-AUDIT.md#f09) | P2 | Открыто | Аккаунты и триггеры: ошибка списка выглядит пустым каталогом |
| [F10](WEB-FULL-CAPABILITY-AUDIT.md#f10) | P2 | Открыто | OTA: поздний ответ фильтра может заменить новый |
| [F11](WEB-FULL-CAPABILITY-AUDIT.md#f11) | P2 | Открыто | OTA: ошибка соседствует с ложным empty state |
| [F12](WEB-FULL-CAPABILITY-AUDIT.md#f12) | P2 | Открыто | Сценарии: первая страница без доступа к остальным |
| [F13](WEB-FULL-CAPABILITY-AUDIT.md#f13) | P2 | Открыто | Оркестрация: три списка обрезаны до 100 записей |
| [F14](WEB-FULL-CAPABILITY-AUDIT.md#f14) | P2 | Открыто | Триггеры: поиск ограничен первыми 100 |
| [F15](WEB-FULL-CAPABILITY-AUDIT.md#f15) | P2 | Открыто | Логи: выбрать устройство можно только из первой страницы |
| [F16](WEB-FULL-CAPABILITY-AUDIT.md#f16) | P2 | Открыто | Задание: несогласованный путь к скриншотам шагов |
| [F17](WEB-FULL-CAPABILITY-AUDIT.md#f17) | P2 | Открыто | Задание: restart теряет параметры оригинала |
| [F18](WEB-FULL-CAPABILITY-AUDIT.md#f18) | P2 | Открыто | Задание: ошибки Stop/Cancel/Restart не показаны |
| [F19](WEB-FULL-CAPABILITY-AUDIT.md#f19) | P2 | Открыто | Обнаружение: текст противоречит auto-register |
| [F20](WEB-FULL-CAPABILITY-AUDIT.md#f20) | P2 | Открыто | Обнаружение: заголовок результата использует новый CIDR |
| [F21](WEB-FULL-CAPABILITY-AUDIT.md#f21) | P2 | Открыто | Мобильное меню: offscreen ссылки остаются активными |
| [F22](WEB-FULL-CAPABILITY-AUDIT.md#f22) | P2 | Открыто | Общий DialogContent: нет ограничения высоты по умолчанию |
| [F23](WEB-FULL-CAPABILITY-AUDIT.md#f23) | P2 | Открыто | Command palette: частичная навигация и нет restore focus |
| [F24](WEB-FULL-CAPABILITY-AUDIT.md#f24) | P2 | Открыто | Legacy /fleet: настоящая кнопка без действия |
| [F25](WEB-FULL-CAPABILITY-AUDIT.md#f25) | P2 | Открыто | Группы: редактирование и состав не раскрыты |
| [F26](WEB-FULL-CAPABILITY-AUDIT.md#f26) | P3 | Открыто | Локации: backend география/иерархия не доступны в форме |
| [F27](WEB-FULL-CAPABILITY-AUDIT.md#f27) | P2 | Открыто | Сценарии: архив/rollback есть в backend, нет workflow |
| [F28](WEB-FULL-CAPABILITY-AUDIT.md#f28) | P2 | Открыто | Pipeline: отсутствует полноценный detail/edit workflow |
| [F29](WEB-FULL-CAPABILITY-AUDIT.md#f29) | P2 | Открыто | Расписания: нет доступа к истории срабатываний |
| [F30](WEB-FULL-CAPABILITY-AUDIT.md#f30) | P2 | Открыто | Расписание one-shot: ISO offset подаётся в datetime-local |
| [F31](WEB-FULL-CAPABILITY-AUDIT.md#f31) | P2 | Открыто | VPN → Logs теряет контекст устройства |
| [F32](WEB-FULL-CAPABILITY-AUDIT.md#f32) | P2 | Открыто | VPN: mutate без отображения ошибок/результатов |
| [F33](WEB-FULL-CAPABILITY-AUDIT.md#f33) | P2 | Открыто | OTA: recovery и адресный rollout не доступны оператору |
| [F34](WEB-FULL-CAPABILITY-AUDIT.md#f34) | P2 | Открыто | Матричный режим использует полноценный H.264 для каждого окна |
| [F35](WEB-FULL-CAPABILITY-AUDIT.md#f35) | P2 | Открыто | XPath-инспектор на видеокарточке ещё отсутствует |
| [F36](WEB-FULL-CAPABILITY-AUDIT.md#f36) | P2 | Открыто | Управление quality/FPS не раскрыто в single stream |
| [F37](WEB-FULL-CAPABILITY-AUDIT.md#f37) | P2 | Открыто | Аудит: фильтры и CSV действуют на текущую страницу |
| [F38](WEB-FULL-CAPABILITY-AUDIT.md#f38) | P2 | Открыто | Пользователи: форма не связывает backend validation с полями |
| [F39](WEB-FULL-CAPABILITY-AUDIT.md#f39) | P2 | Открыто | Role-aware оболочка не закрывает UX отказов доступа |
| [F40](WEB-FULL-CAPABILITY-AUDIT.md#f40) | P2 | Открыто | Низкая полнота текущего визуального acceptance |
| [F41](WEB-FULL-CAPABILITY-AUDIT.md#f41) | P2 | Открыто | Зелёный CI не покрывает перечисленные operator outcomes |

## Доказательства следующего этапа

Начальная фиксация аудита: commit `80fb365`, до любых изменений приложения. Дальнейшие результаты перечислены ниже; «source исправлен» не означает installed/live acceptance.

### F03 — безопасная загрузка DAG

- Commit реализации: `9593321`.
- Существующий сценарий доступен для редактирования только после успешного чтения именно его ID и корректного графа. Ошибка API, отсутствующий DAG, неверный entry и ответ другого ресурса оставляют отдельный error/retry экран без Save.
- Смена ID создаёт отдельного владельца graph/error/save состояния; предыдущий GET отменяется, поздний ответ игнорируется. Завершение старого Save не перенаправляет новый редактор. New-script workflow сохранён.
- `frontend/__tests__/scripts/builder-load.test.tsx`: 8/8 component regressions passed, 1 октября 2026. Проверены failed-read→retry→original PUT, malformed/wrong target, late response, target failure, создание нового графа и поздний save. ReactFlow/Monaco заменены тестовыми renderers; real Canvas/браузер не принят.
- Изменений APK/backend/runtime не требуется и этим batch не выполнялось. Conditional/version-safe concurrent PUT остаётся отдельной задачей; новый UI не объявляет атомарную защиту от чужого одновременного редактирования.

### F04/F05 — подтверждённые настройки и сохранение намерения оператора

- После провала первого GET нет редактируемых defaults или активных переключателей. Повтор восстанавливает реальные значения API. Ошибка фонового чтения сохраняет предыдущий снимок и черновик, но блокирует запись до успешного восстановления.
- Серверный baseline отделён от dirty-полей. Toggle и refetch не сбрасывают несохранённые правки; PATCH содержит только изменённые поля. Явные empty/null, `false` и `0` сохраняют свою семантику. Поле очищается из черновика только после подтверждения равного значения сервером.
- При обнаруженном изменении редактируемого поля на сервере Save блокируется. Оператор явно принимает серверные значения либо оставляет свои правки, после чего отдельно сохраняет. Неизменённые поля берутся из свежего снимка и не попадают в PATCH.
- Pending read/write блокирует конкурирующие действия формы. Перед mutation отменяется предыдущий GET; его поздний ответ не заменяет подтверждённый receipt. Ошибки validation показывают безопасный текст и сохраняют черновик для retry.
- `frontend/__tests__/pipeline-settings/settings-write.test.tsx`: 11/11 regressions passed, 1 октября 2026; настоящие React Query hooks/cache, API transport заменён тестовым. Проверены 401/500, retry, dirty toggle/refetch, конфликт/отмена правок, offline/stale, 422, partial/null/false/zero payload, pending write и late GET.
- Backend PATCH остаётся без revision/CAS precondition: конфликт определяется по полученным снимкам, атомарная защита между последним GET и записью не заявляется. Runtime/APK/backend этим batch не заменяются; визуальная приёмка ещё открыта.
