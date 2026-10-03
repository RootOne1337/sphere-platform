# Исправления по полному веб-аудиту — 1 октября 2026

Этот журнал продолжает [замороженный аудит](WEB-FULL-CAPABILITY-AUDIT.md) исходников `1354d66`. Исходный документ и evidence сохраняют свою дату и ограничения; их статусы не переписываются задним числом.

> [!IMPORTANT]
> **Текущий API/UI: 3 октября 2026, 18:54 UTC.** Оба установлены из **00d5ad8**:
> [рабочий веб на 3015](http://127.0.0.1:3015/devices). F39: навигация и прямые
> ссылки проверяют серверные permissions; просмотр отделён от управления Android.
> **105 suites / 982 frontend tests и 45 PostgreSQL/Redis cases — passed в собранных образах.**
> Live capabilities: 200 / no-store; без аутентификации — 401. Семь срезов подтвердили
> **14 online на APK 10244**, heartbeat <60 с и одинаковые epochs после rollout.
> Замена API сбросила прежние epochs; это не доказательство непрерывного uptime.
> **14 соседних сервисов, Tuna и OTA сохранены.**
> CI 00d5ad8: 2404 backend tests passed / 16 skipped; generated API docs gate failed.
> Документация исправлена в 729c1da; exporter check в shipped image passed.
> Повторный CI **729c1da**: Backend, Frontend, Android и Preview — success.
> **33 source-fixed / 8 OPEN; F32/F33/F39 PARTIAL.** Матричный транспорт всё ещё H.264.
> XPath, FPS profiles, остальные action permissions и visual/soak остаются OPEN.
> [Контракт и доказательства](../2026-10-03/SESSION-CAPABILITIES.md). Визуальная приёмка: OPEN_URL_POLICY_BLOCKED.

**Исторический OTA/API/UI readback,3 октября03:17:58 UTC:** UI 77fca37/API facba9a;
14 addressed installs10241 accepted, 14 online/5 offline. 12 finite samples сохранили
cohort/connection epochs, heartbeat <30 s.104 suites/946 frontend cases,364 regressions;
130 backend cases в immutable image,818 passed/1 skip на каждый Android flavor.
Backend 2381 passed/16 skipped; **5bb36ca backend/frontend/Android CI passed** после schema repair.
33 source-fixed/8 OPEN, F32/F33 PARTIAL. [Новый отчёт](../2026-10-03/OTA-RELEASE-IDENTITY.md).

**Предыдущий fleet readback10240,3 октября2026:**11 адресных installs подтверждены;
все14online на10240,5offline вне приёмки.12 finite readbacks и epoch comparison
не выявили reconnect; это не длительный soak. Code6d5f280 CI passed,
backend2351/16skipped.33source-fixed/8OPEN, F32/F33 PARTIAL.
[Rollout proof](../2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).

**Предыдущий F32 fleet срез, 3 октября2026:** UI **a2c4f02** / API **8cd5cf0**;
**33 source findings исправлены / 8 OPEN**, F32/F33 PARTIAL. **103 suites /916
frontend tests** в Node24;334 regressions.159 related backend cases также в
production image; N06 actual DI/live422/404 принято. VPN provider/Android VPN
действия не выполнялись. Finite online14→11→12;01:53UTC только3 из14 online
на1.2.40-dev. [F32 evidence](../2026-10-03/VPN-CONTROL-OUTCOMES.md) ·
[Validation](WEB-AUDIT-FIXES-VALIDATION.json).

## Исходная фиксация

**N07,3 октября:** найдено невосстановление ABR target ≤2Mbps после отказов
локальной очереди. Усиленный набор15 дал6 failures до исправления и15 passed
после; подготовлены исходники10242. APK42 ещё не опубликован/установлен на этом
этапе. Native/FPS/input latency и F36 остаются OPEN; counts33/8 не изменены.
[Расчёт, конкретные assertions и предел доказательства](../2026-10-03/STREAM-BITRATE-RECOVERY.md).

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
| [F01](WEB-FULL-CAPABILITY-AUDIT.md#f01) | P1 | Source исправлен; live OPEN | Задание: недостоверный Pass Rate |
| [F02](WEB-FULL-CAPABILITY-AUDIT.md#f02) | P1 | Source исправлен; live OPEN | Задание: ошибка API подменяется отсутствием записи |
| [F03](WEB-FULL-CAPABILITY-AUDIT.md#f03) | P1 | Source исправлен; live OPEN | Редактор: разрешена запись после провала загрузки DAG |
| [F04](WEB-FULL-CAPABILITY-AUDIT.md#f04) | P1 | Source исправлен; live OPEN | Настройки pipeline: можно сохранить неподтверждённые defaults |
| [F05](WEB-FULL-CAPABILITY-AUDIT.md#f05) | P1 | Source исправлен; live OPEN | Настройки pipeline: несохранённая форма сбрасывается |
| [F06](WEB-FULL-CAPABILITY-AUDIT.md#f06) | P2 | Source исправлен; live OPEN | Локации: очистка текста не передаётся серверу |
| [F07](WEB-FULL-CAPABILITY-AUDIT.md#f07) | P2 | Source исправлен; live OPEN | Аккаунты: законопослушность не отправляется при создании |
| [F08](WEB-FULL-CAPABILITY-AUDIT.md#f08) | P2 | Source исправлен; live OPEN | Аккаунты: debounce фактически не отменяет прошлые таймеры |
| [F09](WEB-FULL-CAPABILITY-AUDIT.md#f09) | P2 | Source исправлен; live OPEN | Аккаунты и триггеры: ошибка списка выглядит пустым каталогом |
| [F10](WEB-FULL-CAPABILITY-AUDIT.md#f10) | P2 | Source исправлен; live OPEN | OTA: поздний ответ фильтра может заменить новый |
| [F11](WEB-FULL-CAPABILITY-AUDIT.md#f11) | P2 | Source исправлен; live OPEN | OTA: ошибка соседствует с ложным empty state |
| [F12](WEB-FULL-CAPABILITY-AUDIT.md#f12) | P2 | Source исправлен; live OPEN | Сценарии: первая страница без доступа к остальным |
| [F13](WEB-FULL-CAPABILITY-AUDIT.md#f13) | P2 | Source исправлен; live OPEN | Оркестрация: три списка обрезаны до 100 записей |
| [F14](WEB-FULL-CAPABILITY-AUDIT.md#f14) | P2 | Source исправлен; live OPEN | Триггеры: поиск ограничен первыми 100 |
| [F15](WEB-FULL-CAPABILITY-AUDIT.md#f15) | P2 | Source исправлен; live OPEN | Логи: выбрать устройство можно только из первой страницы |
| [F16](WEB-FULL-CAPABILITY-AUDIT.md#f16) | P2 | Source исправлен; live OPEN | Задание: несогласованный путь к скриншотам шагов |
| [F17](WEB-FULL-CAPABILITY-AUDIT.md#f17) | P2 | Source исправлен; live OPEN | Задание: restart теряет параметры оригинала |
| [F18](WEB-FULL-CAPABILITY-AUDIT.md#f18) | P2 | Source исправлен; live OPEN | Задание: ошибки Stop/Cancel/Restart не показаны |
| [F19](WEB-FULL-CAPABILITY-AUDIT.md#f19) | P2 | Source исправлен; live OPEN | Обнаружение: текст противоречит auto-register |
| [F20](WEB-FULL-CAPABILITY-AUDIT.md#f20) | P2 | Source исправлен; live OPEN | Обнаружение: заголовок результата использует новый CIDR |
| [F21](WEB-FULL-CAPABILITY-AUDIT.md#f21) | P2 | Source исправлен; live OPEN | Мобильное меню: offscreen ссылки остаются активными |
| [F22](WEB-FULL-CAPABILITY-AUDIT.md#f22) | P2 | Source исправлен; live OPEN | Общий DialogContent: нет ограничения высоты по умолчанию |
| [F23](WEB-FULL-CAPABILITY-AUDIT.md#f23) | P2 | Source исправлен; live OPEN | Command palette: частичная навигация и нет restore focus |
| [F24](WEB-FULL-CAPABILITY-AUDIT.md#f24) | P2 | Source исправлен; live OPEN | Legacy /fleet: настоящая кнопка без действия |
| [F25](WEB-FULL-CAPABILITY-AUDIT.md#f25) | P2 | Source исправлен; live OPEN | Группы: редактирование и состав не раскрыты |
| [F26](WEB-FULL-CAPABILITY-AUDIT.md#f26) | P3 | Source исправлен; live OPEN | Локации: backend география/иерархия не доступны в форме |
| [F27](WEB-FULL-CAPABILITY-AUDIT.md#f27) | P2 | Source исправлен; live OPEN | Сценарии: архив/rollback есть в backend, нет workflow |
| [F28](WEB-FULL-CAPABILITY-AUDIT.md#f28) | P2 | Source исправлен; live OPEN | Pipeline: отсутствует полноценный detail/edit workflow |
| [F29](WEB-FULL-CAPABILITY-AUDIT.md#f29) | P2 | Source исправлен; live OPEN | Расписания: нет доступа к истории срабатываний |
| [F30](WEB-FULL-CAPABILITY-AUDIT.md#f30) | P2 | Source исправлен; live OPEN | Расписание one-shot: ISO offset подаётся в datetime-local |
| [F31](WEB-FULL-CAPABILITY-AUDIT.md#f31) | P2 | Source исправлен; live OPEN | VPN → Logs теряет контекст устройства |
| [F32](WEB-FULL-CAPABILITY-AUDIT.md#f32) | P2 | Частично; lifecycle/visual OPEN | Explicit targets/action, owned preflight, per-device receipts и no replay исправлены; kill transport unsupported, durable reconciliation/visual OPEN |
| [F33](WEB-FULL-CAPABILITY-AUDIT.md#f33) | P2 | Частично; bulk/manifest/visual OPEN | Addressed installs14/14, metadata/receipt и APK identity guards приняты по своим gates; general bulk/manifest/stable promotion и visual OPEN |
| [F34](WEB-FULL-CAPABILITY-AUDIT.md#f34) | P2 | Открыто | Матричный режим использует полноценный H.264 для каждого окна |
| [F35](WEB-FULL-CAPABILITY-AUDIT.md#f35) | P2 | Открыто | XPath-инспектор на видеокарточке ещё отсутствует |
| [F36](WEB-FULL-CAPABILITY-AUDIT.md#f36) | P2 | Открыто | Управление quality/FPS не раскрыто в single stream |
| [F37](WEB-FULL-CAPABILITY-AUDIT.md#f37) | P2 | Source исправлен; live OPEN | Аудит: фильтры и CSV действуют на текущую страницу |
| [F38](WEB-FULL-CAPABILITY-AUDIT.md#f38) | P2 | Source исправлен; live OPEN | Пользователи: форма не связывает backend validation с полями |
| [F39](WEB-FULL-CAPABILITY-AUDIT.md#f39) | P2 | Частично; all-actions/visual OPEN | Server capabilities, shell/deep links, identity retirement и device control исправлены; остальные mutation affordances OPEN |
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

- Commit реализации: `062ef47`.
- После провала первого GET нет редактируемых defaults или активных переключателей. Повтор восстанавливает реальные значения API. Ошибка фонового чтения сохраняет предыдущий снимок и черновик, но блокирует запись до успешного восстановления.
- Серверный baseline отделён от dirty-полей. Toggle и refetch не сбрасывают несохранённые правки; PATCH содержит только изменённые поля. Явные empty/null, `false` и `0` сохраняют свою семантику. Поле очищается из черновика только после подтверждения равного значения сервером.
- При обнаруженном изменении редактируемого поля на сервере Save блокируется. Оператор явно принимает серверные значения либо оставляет свои правки, после чего отдельно сохраняет. Неизменённые поля берутся из свежего снимка и не попадают в PATCH.
- Pending read/write блокирует конкурирующие действия формы. Перед mutation отменяется предыдущий GET; его поздний ответ не заменяет подтверждённый receipt. Ошибки validation показывают безопасный текст и сохраняют черновик для retry.
- `frontend/__tests__/pipeline-settings/settings-write.test.tsx`: 11/11 regressions passed, 1 октября 2026; настоящие React Query hooks/cache, API transport заменён тестовым. Проверены 401/500, retry, dirty toggle/refetch, конфликт/отмена правок, offline/stale, 422, partial/null/false/zero payload, pending write и late GET.
- Backend PATCH остаётся без revision/CAS precondition: конфликт определяется по полученным снимкам, атомарная защита между последним GET и записью не заявляется. Runtime/APK/backend этим batch не заменяются; визуальная приёмка ещё открыта.

### F01/F02/F18 — правдивые отчёты задания и результаты команд

- Commit реализации: `d53a8d7`.
- Удалён фиктивный Pass Rate и вычисление циклов по отношению счётчиков. UI показывает фактические success/failure в полученных отчётах, явно ограничивая вывод этим набором. Отсутствующие счётчики не становятся нулевыми; число исполненных шагов не подписывается как число успешных.
- 404, 401, 403 и transport failure разделены. После ошибки фонового чтения предыдущий снимок виден с временем подтверждения, команды заблокированы, доступен retry. Ответ другого task ID отвергается query hook. Смена ID изолирует локальные ошибки/receipt и отменяет старый GET.
- Ошибки Stop/Cancel/Restart отображаются, failed restart не оставляет необработанный rejected promise. Успешная остановка означает принятие запроса, а не завершение Android-работы. Ответ создания нового задания содержит ссылку на полученный ID; успешное выполнение не выдумывается.
- Ошибка журнала не выглядит пустой историей. Fallback из task.result помечен как снимок; ошибки live progress/live journal показываются отдельно.
- `frontend/__tests__/tasks/detail-outcomes.test.tsx`: 16/16 component regressions passed, 1 октября 2026; реальный React Query с mock transport. Проверены HTTP classes/retry, wrong owner, mixed/empty/terminal reports, stale command lock, три failed actions/retry, create receipt, log errors/fallback и late GET при смене task.
- F17 остаётся открытым: текущий CreateTaskRequest не принимает произвольный input_params или pinned script_version_id. Этот batch не маскирует потерю контекста добавлением несуществующих полей в запрос. Backend, APK и установленный веб не заменены; свежая визуальная приёмка открыта.

### F06 — явная очистка текстовых полей локации

- Commit реализации: `de2f9df`.
- PUT редактирования отправляет пустые строки description/address после явной очистки; `undefined` больше не исключает эти поля из JSON. Create workflow сохраняет прежнюю семантику необязательных полей.
- Контракт проверен по `backend/services/location_service.py`: сервис применяет переданные non-None значения, включая пустую строку. Backend изменять не требуется.
- `frontend/__tests__/locations/edit-clear.test.tsx`: 1/1 component regression passed, 1 октября 2026: заполненная локация → очистка/whitespace → точный PUT → подтверждённые empty labels после GET. Настоящие Query hooks, transport mock; live acceptance ещё не выполнен.

### F07/F08 и первая часть F09 — создание и поиск аккаунтов

- Commit реализации: `6ad3018`.
- Законопослушность включена в typed Create payload; 0/100 не теряются, пустое поле не превращается в placeholder 100. UI и handler блокируют нецелые и выходящие за 0–100 значения, согласованные с backend schema.
- Поиск использует общий useDebounce с cleanup таймера; быстрый ввод отправляет последнюю строку после 300 мс, новая строка возвращает pagination на первую страницу. При unmount таймер не обновляет страницу.
- Ошибка списка аккаунтов показывает явное состояние неизвестности и retry, без ложного empty state/нулевого количества записей и stale row actions. Create остаётся отдельным workflow.
- `frontend/__tests__/accounts/form-search.test.tsx`: 9/9 regressions passed, 1 октября 2026. Create использует настоящий mutation hook с mock POST; список заменён query fixture, debounce настоящий. Полная transport/визуальная проверка каталога не заявляется.

### F09 — триггеры и корректный смысл агрегатов

- Commit реализации: `d1cfbee`.
- Read failure триггеров показывает retry и unknown metrics; stale rows и empty state не выдаются за актуальный каталог. Total берётся из API envelope, локальные агрегаты помечены как относящиеся к полученной странице.
- Дополнительно подтверждена ошибка подписи: `!is_active && total_triggers > 0` не доказывает сбой выполнения. Карточка переименована в «Неактивных со срабатываниями»; выдуманный счётчик ошибок удалён.
- `frontend/__tests__/event-triggers/read-evidence.test.tsx`: 2/2 regressions passed, 1 октября 2026; failed-read без cached actions/empty/zero, server total 201 при одной полученной записи и disabled ≠ failed. Hooks списка заменены fixtures; F14 полнота pagination/поиска остаётся открыта.

## Первый набор: общая проверка и установленный review runtime

- **Source:** `d1cfbeea89a6854c722e0750653b4794b536e316`. Шесть atomic implementation commits идут после отдельной фиксации аудита `80fb365`. Новых regressions 47; frozen audit source/evidence не переписаны.
- **Tests:** полный frontend Jest, 79/79 suites, 629/629 tests, 0 failed / 0 skipped; TypeScript `--noEmit` и `git diff --check` passed. Transport mocks не объявляются реальными операциями устройств.
- **Compile:** отдельный git archive того же source, Next.js 15.5.26 production build passed с исходным `output: standalone`; стандартный config не ослаблялся. WS использует origin браузера, API — `/api/v1`. Финальная сборка содержит `NEXT_PUBLIC_BUILD_SHA=d1cfbeea89a6854c722e0750653b4794b536e316`; наличие метки проверено в собранных chunks. Существующие 44 lint warnings не скрыты; zero-warning acceptance не заявляется.
- **Installed:** в 22:19 UTC+5 старый 3015/3023 не имел listener; backend 18080 оставался доступен. Первое восстановление на 3024 выполнено в 22:25:21. Финальная сборка с SHA переключена в **22:35:03** на **3015 → standalone UI 3025 / API 18080**: Next PID 33052 / relay PID 2192. Owned loopback listeners подтверждены, Next сообщил Ready, health/build через relay соответствует backend `8d64ca4`. Заменён только проверенный relay PID 15620; предыдущий Next PID 8800 сохранён для rollback, Next 3016 и посторонние процессы не останавливались. Это local review deployment, public frontend не заменён.
- **Documents:** 371 relative target и 41 finding anchor проверены, missing 0. Числа тестов сверены с raw Jest receipt; 10 исправленных findings и 31 открытый согласованы с ledger. Frozen audit source/evidence оставлены без изменений относительно commit `80fb365`.
- **Observability:** новый Next получил прежний server-only session secret и auth API/Prometheus/Grafana upstreams; секреты в evidence не публикуются. Доступность upstream ports подтверждена, authenticated browser/Grafana workflow этим batch не принят.
- **Limits:** browser URL policy по-прежнему блокирует fresh Sphere visual walkthrough; обход не выполнялся. Public/runtime metrics не доказывают Android FPS, стабильность связи или выполнение новых задач. APK/backend/tunnel/OTA этим batch не изменялись; PR остаётся draft.
- **Next:** F10/F11 OTA ownership/empty semantics, затем F12–F15 полнота каталогов, F17 безопасный повтор с сохранением контекста и F21–F23 модальные окна/навигация. F34–F36 требуют отдельных native/browser/fleet performance gates.

## Второй набор исправлений полного веб-аудита

**Source:** `d6439d2`; первый установленный срез `d1cfbee` выше сохранён как история. Совокупно 17 source findings исправлены, 24 открыты. Новый runtime фиксируется отдельно после сборки и проверки владельца процесса.

### F10/F11 — принадлежность и достоверность OTA-каталога

- Commit `a0d833d`: React Query ключ включает platform/flavor; GET получает AbortSignal и отменяется при смене владельца. Поздний ответ старого фильтра не подменяет активный список.
- Initial/cached read failure показывает unknown и retry без empty state, ложного нуля и stale Delete. Успешный пустой ответ отдельно показывает empty. Проверяется структура envelope. Доступны ручное обновление и периодическое чтение раз в 30 секунд в активной вкладке; записи не переигрываются.
- 7 новых регрессий: на archived baseline `d1cfbee` 6 failed / 1 control passed; после исправления 7 passed плюс 2 существующих catalog-contract tests. Проверены A/B late result, failed filter, cached refresh failure/retry, malformed envelope и unmount abort. API transport mock; реальная публикация/удаление APK не выполнялись.
- F33 адресный rollout/recovery UI остаётся открытым. Регистрация release по-прежнему не означает загрузку APK, установку или подтверждение обновления устройств.

### F12 — доступ ко всему каталогу сценариев

- Commit `779ffc4`: page/per_page=50 и server query доступны из страницы; поиск задерживается на 300 ms и сбрасывает page на 1. Пока запрос меняется, прежние action rows скрыты. GET отменяется при смене page/query; поздний ответ не подменяет новый каталог.
- Показаны total и доступные страницы; при ошибке страницы нет действий от предыдущей. DAG-инспектор и ссылки редактора сохранены, page change закрывает прежний inline inspector.
- 4 новых component regressions с настоящим query hook и mock transport: 51 запись, последняя через page 2; server search последней с page reset; failed page/retry; late page result после поиска. Связанные scripts/modal/hooks: 21 passed.
- Другие script pickers и архив/rollback workflow этим изменением не объявляются завершёнными: F27 остаётся открытым.

### F14 — страницы триггеров и ясная область поиска

- Commit `b8da88f`: server page/per_page=100 сохранены вместе с total, можно перейти к 101-й записи и открыть редактирование. GET отменяется при смене page/filter. Смена активности возвращает page на 1.
- Текстовый поиск явно ограничен текущей страницей; empty copy говорит «на этой странице». Он не выдаётся за неподдерживаемый backend global search. Pagination остаётся доступна при нуле локальных совпадений.
- 3 новых real-hook/mock-transport regressions: 101 запись, открытие последней; local search и переход к следующей странице; failed page/retry без stale actions. Связанные tests/hooks: 17 passed.
- Pipeline options в форме и полнота каталогов оркестрации остаются отдельным F13, не закрываются этим результатом.

### F21 — мобильное меню как настоящий модальный workflow

- Commit `b02560c`; общий каталог навигации извлечён в `09a22e3`. Закрытое мобильное меню не монтирует ссылки. Breakpoint MatchMedia выбирает mobile modal либо обычный desktop aside.
- Использован уже установленный Radix Dialog: modal focus containment, скрытие фона от accessibility tree, Escape и возврат к фактическому opener. Desktop collapse preference не скрывает mobile labels; переход к desktop закрывает mobile state.
- 4 новых regressions плюс 3 существующих: closed links отсутствуют, Shift-Tab/Tab остаются внутри, Escape возвращает фокус, mobile labels при collapsed preference, breakpoint reconciliation. Реальный Radix в jsdom, не browser/assistive-technology acceptance.

### F22 — размеры общих диалогов

- Commit `1c4e0a8`: default content получает max-height `calc(100dvh - 2rem)`, горизонтальный отступ, overflow-y и overscroll containment; reduced motion выключает анимацию content. Явные overrides вызывающего компонента сохраняются.
- Низкий viewport больше не предполагает фиксированный доступный размер. CSS проверяется production compile; JSDOM не объявляется проверкой геометрии. Новые CSS-mirroring tests не добавлялись.
- Живая приёмка mobile keyboard, resize, длинных форм и анимаций остаётся OPEN по URL policy.

### F23 — единая навигация поиска и восстановление фокуса

- Commit `09a22e3`: sidebar и command palette используют единый `navigationCatalog.ts`, все 22 раздела доступны из поиска. Старые названия быстрых переходов и shortcuts сохранены; cmdk имеет осмысленный accessible label.
- Command palette использует Radix modal containment и возврат фокуса. Escape из appearance возвращает к поиску, следующий Escape закрывает palette. Убран minimum-height, который мог превышать маленький viewport.
- 2 новых regressions плюс существующие: все 22 destination проверены по действительному shared catalog; фон скрыт, input получает фокус, opener получает его обратно. Все 12 navigation tests passed до общего прогона.
- `d6439d2` ограничивает matchMedia fixture DOM-средой: серверный observability suite работает без window. Исправление проверочного окружения не меняет runtime/API policy.

Ожидаемый keyboard/modal контракт сверён 1 октября 2026 с [официальной документацией Radix Dialog](https://www.radix-ui.com/primitives/docs/components/dialog) и [W3C APG Modal Dialog](https://www.w3.org/WAI/ARIA/apg/patterns/dialog-modal/). Эти источники объясняют выбор primitive и критерии; они не являются доказательством визуальной приёмки Sphere.

## Историческая проверка двух первых наборов и установка, 23:14

- **Source/build:** `d6439d26640900f2a43690a0917d210812e3142c`. 12 atomic implementation commits и отдельный test-environment correction следуют за audit commit `80fb365`. Frozen main report/evidence сохранены без изменений.
- **Tests:** 82/82 suites, 649/649 tests, 0 failures / 0 skips; 67 новых regressions относительно 582-test baseline. TypeScript `--noEmit` и diff check passed. Первый полный rerun выявил отсутствие matchMedia в jsdom, затем DOM fixture в Node suite; обе причины проверочного окружения устранены, финальный полный прогон включает server suite и logout.
- **Compile:** production Next.js 15.5.26, исходный standalone config, isolated Git archive, API `/api/v1`, WS origin fallback, SHA в browser chunks. 44 существующих lint warnings остаются. Первая изолированная попытка из workspace root не прочитала Tailwind config; повтор из archived frontend прошёл. Dynamic-height/width/scroll containment правила найдены в compiled CSS — это artifact verification, не измерение browser geometry.
- **Installed, 23:14:38 UTC+5:** relay3015 → standalone3026 / API18080; owned Next PID45528 / relay PID10268, Ready 205 ms, API revision `8d64ca4`. Заменён только проверенный relay2192; Next33052 сохранён для rollback. Server-only Prometheus/Grafana/auth config сохранён; секреты не публикуются. Public frontend, APK, tunnel, OTA и удалённые устройства не изменялись.
- **CI:** предыдущий published docs head `a1d68b3` завершил 9 checks success / preview deploy skipped; это первый 629-test batch. Новый source/документация требуют собственного CI, он фиксируется отдельно. Результаты предыдущего head не подменяют проверку нового.
- **Acceptance:** 17 source fixes / 24 OPEN, все live gates остаются OPEN до проверки. URL policy браузера не обходилась. Нет нового утверждения о remote FPS/latency, APK OTA, fleet uptime или результате новых Android скриптов.
- **Дальше:** F13/F15 полный доступ к оркестрации и выбору устройств логов; F16/F17 согласованные screenshots/retry; F19/F20 discovery ownership; F24–F33 более глубокие формы/workflows; F34–F36 отдельные browser/native/fleet performance и XPath gates.

## Третий набор: источники логов и расписания, 23:50 UTC+5

### F15/F31 — точный источник журнала

- Commit `cf7ff66`. VPN Logs ведёт в `/logs?device_id=...` с encoded ID фактического peer, а не в общий аудит без device filter.
- Каталог источников читается страницами по 100. Server search с debounce 300 ms работает по name, serial, model и полному UUID — ровно возможности Device API. Можно открыть 101-е устройство; поиск/страницы не меняют уже выбранный источник.
- Прямая ссылка работает вне первой страницы и при ошибке каталога. Отдельный owned device snapshot сообщает имя; при отсутствии карточки остаётся точный ID. Выбор обновляет URL без прокрутки.
- Каждый log viewer принадлежит одному ID. Смена источника отменяет GET и создаёт новый reader; late GET/delete не заменяет другой источник. Ответ с чужим `device_id` отклоняется. Clear требует успешного read, подтверждения и блокирует повторные действия; его receipt не объявляет работу агента.
- 7 new log regressions: before 7 failed на `8582557`, after 7 passed. Дополнительный VPN link regression проверяет exact encoded ID. Связанные 38 tests passed; реальный Query cache/renderer и mock API transport. Existing log tests сохранены и расширены параметрами провайдера.
- Backend `/logs/{device_id}` возвращает ограниченный архив ранее загруженных строк, не живой Logcat. GET для search/lookup не устанавливает APK и не посылает команды устройству. Большой архив/retention/event-loop cost сервера этим frontend batch не оптимизировались.

### F30 — абсолютное время разового запуска

- Commit `16fcac3`. ISO offset нормализуется в UTC для `datetime-local`; поле и подсказка явно говорят UTC. Сохраняется тот же момент, а не wall time часового пояса браузера. Backend `timezone` применяется к CRON, `one_shot_at` — к абсолютному запуску.
- Если поле не менялось, отправляется исходное aware значение API, включая sub-millisecond precision. Новая дата/время валидируются как календарный UTC instant; минуты/секунды/fraction дают корректный ISO с `Z` без добавления лишних секунд. Malformed исходник запрещает Save до явного исправления.
- 3 before component failures на `cf7ff66`; 4 after form regressions и 13 utility cases: offsets, секунды/миллисекунды, DST dates с явно UTC трактовкой, неверный календарь, неправильные часы/precision/naive API input. Связанные 23 tests passed. Native browser datepicker/локализация — отдельный OPEN gate.
- Контракт поля сверён 1 октября с [HTML Standard: datetime-local](https://html.spec.whatwg.org/multipage/input.html#local-date-and-time-state-(type=datetime-local)) и [схемой сервера](../../../backend/schemas/schedule.py). HTML поле само не несёт time zone; внешняя документация подтверждает выбор формата, не работу Sphere вживую.

### F29 — история срабатываний

- Commit `1e1faec`. Из строки расписания открывается shared Radix dialog с `GET /schedules/{id}/executions`, page/per_page=50, total и переходом к остальным страницам.
- Показаны плановое/фактическое время UTC, raw/reported status, устройства, созданные/успешные/ошибочные задачи, IDs execution и task/pipeline batch, skip reason, finished time. Не сообщённые значения не заменены выдуманным успехом; batch IDs не превращены в ссылки на неподдерживаемые фильтры.
- Проверяется owner `schedule_id`, страница, типы времени и счётчиков. Failed first read/refresh не показывают false empty либо старый подтверждённый report. Есть изолированный retry/manual refresh и 30 s refresh открытого окна. Закрытие/смена расписания отменяет GET; новая цель начинает page 1.
- 6 new regressions, включая переход из настоящей страницы, page 2, failed read/retry, cached read failure, wrong-owner payload и late response после закрытия. Связанные 11 tests passed. API transport заменён; fire-now/POST и Android execution не выполнялись.
- Счётчики backend не являются независимым доказательством завершения работы Android. Финальное принятие выполнения сценария остаётся отдельной cross-layer задачей.

### Дополнительные подтверждённые границы Schedule API

- Commit `55b07d9`. Create не принимает пустой manual target: минимум один подтверждённый ID. Подсказка объясняет, что пустой выбор не означает весь парк.
- Create/Edit interval принимают только целые 60..86400 секунд, как [CreateScheduleRequest/UpdateScheduleRequest](../../../backend/schemas/schedule.py); HTML min/max/step и `canSubmit` согласованы.
- 5 before failures на `1e1faec` → 5 passed: отсутствие цели, явные device_ids, обе inclusive границы, дробь/59/86401 и снятие единственной цели. Этот дополнительный guard не переписывает frozen F01–F41 и не закрывает другие недостатки orchestration forms.

## Проверка и установка третьего набора, 1 октября

- Source/compiled stamp `55b07d91004b895481c6fd515d332e5af68375be`; full frontend **87 suites / 685 tests**, 0 failures/skips. **36 новых regressions** в третьем наборе, **103 всего** относительно 582-test baseline. TypeScript noEmit и diff check passed.
- Original production Next.js 15.5.26 standalone config, isolated Git archive, same-origin API и WS fallback; compiled SHA проверен. 44 существующих lint warnings остаются; build gates не отключались.
- Installed **1 октября 2026, 23:50:20 UTC+5**, loopback 3015 → UI3027 / API18080. Owned Next PID42560, relay PID18164; Ready231ms. Relay10268 проверен по PID/start/command/listener и заменён; старый Next45528 сохранён для rollback. Backend revision `8d64ca4` остался прежним.
- Секреты не печатались и не публиковались. Public UI, APK, туннели, OTA и команды Android этим набором не изменены. Это ревью веба, не fleet rollout.
- Предыдущий published head `8582557`: 9 GitHub checks success, preview deploy skipped, включая frontend/backend/Android/Alembic. Новый published head требует собственного CI. Старые зелёные checks не подменяют этот результат.
- 21 source fix / 20 OPEN по frozen audit; browser visual acceptance OPEN по URL policy. Нового свидетельства о stream FPS/latency, OTA или uptime парка нет.
- Следующие приоритеты: F13 orchestration catalog paging; F16/F17 screenshots/restart context; F19/F20 discovery ownership; F24–F28 формы/редакторы; F32/F33 command outcomes/OTA recovery; F34–F36 streams/XPath; F37 export/filter scope; F38–F41 validation/access/acceptance.

## Ручная приёмка установленного веба

Эти шаги ещё не приняты агентом; автоматизация браузера для Sphere заблокирована URL policy. Для текущей установки используйте `5fcf18a`; исторические source/runtime результаты ниже не являются новой визуальной приёмкой.

1. Открыть [Системные логи](http://127.0.0.1:3015/logs), проверить source SHA в шапке. Поиск устройства, переход к следующей странице и выбор меняют источник только по явному выбору; открыть скопированную ссылку в новой вкладке и сопоставить тот же device ID.
2. На VPN peer нажать Logs и сопоставить ID в URL с ID peer. История пользователя /audit и архив агента /logs — разные данные.
3. В [Оркестрации](http://127.0.0.1:3015/orchestration) → Schedules открыть «История срабатываний», посмотреть detail row и страницы. Это GET: не нажимать fire-now для проверки верстки.
4. Открыть one-shot edit и сравнить исходное время API с UTC полем; Cancel завершает проверку без записи. Проверить keyboard/scroll/focus длинного dialog и небольшого viewport.
5. Создать черновик расписания: без target Save отключён; интервалы 59/дробь/86401 не отправляются. Cancel закрывает черновик; реальный запуск/сохранение проверяются отдельным согласованным canary.

Операторские destructive actions, API permissions, responsive geometry, browser focus и реальные execution results остаются отдельными live gates. Source tests/build не отмечают эти пункты завершёнными.

## Дополнение истории расписаний и актуальная установка, 2 октября

- Проверка полного `ScheduleExecutionStatus` выявила ещё `partial` и `failed`. Commit `c3bf0e5` добавляет явные подписи «Частичный результат» / «Задачи завершились с ошибками» и warning/destructive severity; raw unknown status сохраняется для будущего API.
- Два дополнительных regression cases сопоставляют terminal status с фактическими succeeded/failed counters; они не называют их успехом. Финальный полный прогон: **87 suites / 687 tests**, 0 failed/skipped; **105 новых regressions** относительно 582, включая 38 в продолжении логов/расписаний. Types/diff check passed.
- Production standalone compiled из Git `c3bf0e5c3105dcd80becfb86c743a363d0b2d23c`, первоначальный Next15.5.26 config; 44 lint warnings. Browser chunks содержат source stamp; dynamic dialog CSS проверен. Fresh browser acceptance остаётся OPEN по URL policy.
- Installed **2 октября 2026, 00:03:15 UTC+5**, 3015 → UI3028/API18080. Next PID47416, relay PID23052; прежний owned relay18164 заменён после проверки PID/start/command/listener, Next42560 сохранён. API8d64ca4, server-only auth/observability config и внешние tunnel/OTA не заменялись.
- Source fix count остаётся 21/41; F29 дополнен, остальные 20 OPEN. Ранее установленный `55b07d9` и его 685-test результат выше остаются историческими фактами.
- Frontend CI published `19cd53b` success ([run36910704364](https://github.com/RootOne1337/sphere-platform/actions/runs/36910704364)); это промежуточный 685-test head. Итоговый head после дополнительного source/docs commit требует собственного CI; его результат фиксируется отдельно.


## F13 — страницы оркестрации и четвёртый набор, 2 октября

- [Полный отчёт с контрактами, тестами и ограничениями](../2026-10-02/ORCHESTRATION-CATALOG-PAGING.md). Commit `186ce02` сохраняет envelope трёх каталогов, независимые страницы и поддерживаемые серверные фильтры; счётчики не выдают размер страницы за общий итог.
- Create/Edit расписания имеют собственный paginated pipeline picker. Выбранный ID вне страницы/поиска сохраняется. Неизвестное имя запуска отображается реальным pipeline ID; прежний поиск по известному имени сохранён (`7f30d9d`).
- 8 before failures на `868f523`; финальные 13 catalog и 5 picker regressions. Дополнительное расширение существующего case поймало потерю name search на `d43626c` и подтвердило её устранение. 9 orchestration suites / 60 tests passed; полный frontend **89 suites / 705 tests**, 0 failures/skips. **18 новых cases / 123 относительно baseline582**.
- Lint follow-up `d43626c` убрал два новых предупреждения. Original production Next15.5.26 standalone build `7f30d9d5282804d7b477bff665cfea256dd31aeb`, types и SHA stamp passed; 44 прежних lint warnings остаются. Windows trace-copy warnings как в предыдущей сборке; локальный runtime использует workspace dependencies, переносимый Windows package этим не принят.
- Installed **2 октября 2026, 00:36:17 UTC+5**, `3015 → UI3029/API18080`. Next7416, relay48892. Предыдущий relay23052 проверен по PID/start/command/listener и заменён; Next47416 сохранён. API8d64ca4 и server-only конфигурация прежние. Чтение health/build через новый relay и ownership listeners подтверждены; public UI/APK/OTA/tunnels не менялись.
- **22 source findings исправлено, 19 OPEN**; browser visual acceptance OPEN по прежнему URL policy. Текстовый поиск ограничен текущей страницей, что явно подписано. Глобальный свободный поиск, snapshot export, backend-wide аналитика не реализованы этим frontend batch. Полнота script pickers остаётся F27.
- Published `868f523`: 9 checks success, preview deploy skipped. Новый source/docs head требует собственного CI. Это отдельный результат от live API permissions/controls и выполнения Android сценариев.
- Следующий приоритет: F16/F17 screenshot/restart context; F19/F20 discovery ownership; F24–F28 workflows; F32/F33 outcomes/OTA; F34–F36 video/XPath; F37–F41 export/access/acceptance. Остальные замечания не объявлены устранёнными.


## Batch: F16/F17 — 2 октября 2026, 01:30 UTC+5

- `4f141d8`: серверный повтор pinned версии, глубокая копия входов/таймаута, проверки владения/контекста и конфликтов; real PostgreSQL concurrency.
- `7df0fc4`: manifest и private screenshot content вместо stub/raw keys; bounded JPEG/PNG reads и ошибки storage; dedicated credentials configuration.
- `5fcf18a`: UI использует оба API; lazy authorized Blob, React error/retry/cleanup, task receipts и version semantics.
- Проверки: 14 before failures на чистом 9b1f0e1; 92 backend units, 13 PostgreSQL, 1 real MinIO; 91 frontend suites / 718 tests; types/build passed, 44 прежних warnings.
- CI `5fcf18a`: 2165 backend tests passed / 16 skipped, coverage78%; job остановился на stale generated API docs. OpenAPI и endpoint catalog обновлены штатным exporter, local `--check` passed. Следующий published head требует собственного CI; failed run сохранён как доказательство пропуска. Отдельный commit `3fe5eac` усиливает проверку глобального mutation retry без изменения application code.
- API установлен 01:27:36, UI3015/3030 — 01:28:45 UTC+5; API/UI SHA совпадают. На 01:30:49 — catalog19, reported online14/offline5; это моментальный срез. Public frontend/APK/OTA/tunnels не заменены.
- Follow-up N01: Android screenshot action сохраняет локальный файл без загрузки; pilot storage read пока выключен. [Полный контракт, ограничения и приёмка](../2026-10-02/TASK-ARTIFACTS-AND-RERUN.md).
- Далее: N01 Android artifacts; F19/F20 discovery; F24–F28 формы/workflows; F32/F33 command/OTA outcomes; F34–F36 video/XPath; F37–F41 export/access/live acceptance. PR19 не закрыт.

## Runtime и Android follow-up — 2 октября 04:51 UTC+5

Native review процессы исчезли после ранее записанной установки; причина не установлена. Review [3015](http://127.0.0.1:3015/) восстановлен в Docker: UI0f4530c / API5fcf18a, оба healthy, login/API/Prometheus/Grafana/events WS и restart passed. Все 14 прежних контейнеров сохранены. На remote PH025/10240 два variable-only задания completed/success; rerun исполнил pinned v1 после изменения latest v2. N01 upload, browser visual, массовые сценарии и video latency остаются открытыми. [Подробности и receipts](../2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md).

## F19/F20 — 2 октября 05:08 UTC+5

Commit `d4364e5`: submitted scan context сохраняется вместе с validated response; registration copy/payload согласованы. Дополнительно исправлен N02: required workstation UUID, typed port_range/timeout и registered_id/already_registered вместо несуществующих fields. Android APK не зависит от PC Agent; ADB-режим обозначен отдельно. Before d5d3d14: 10 failed / 1 control passed / 0 runtime errors; after11 passed, full92 suites/729 tests и types/Docker build passed. Review3015 установлен; login/API/observability/events WS и compiled stamp подтверждены. Совокупно26 исправлено /15 исходных OPEN, новые N01 и N03 OPEN. N03 — backend legacy RPC failure выглядит empty scan; живой scan не запускался. [Контракт, доказательства и ограничения](../2026-10-02/DISCOVERY-REQUEST-OWNERSHIP.md).

## F24/F25 — 2 октября 05:48 UTC+5

Commit `eb4598b` добавляет metadata editor, confirmed deletion/membership cache invalidation, URL-scoped device registry и legacy fleet redirect. Beforea7829df: 23 failed/9 controls/0 runtime errors; after32 targeted passed; full94 suites/753 tests, types/production Docker build passed. Live API подтвердил own-group create/update/GET persistence/409/filter/204 cleanup, исходные группы и memberships сохранены. Review3015 установлен; все44 прежних containers (14running) без изменений. N04 parent null clear воспроизведён и OPEN; parent editing read-only. 28/41 исправлено, 13 исходных и N01/N03/N04 OPEN. [Полный отчёт и receipts](../2026-10-02/GROUP-WORKFLOWS.md). Browser visual не принят.

## N04/N05 —2 октября 06:42 UTC+5

`dce2c99`/`a9240a7`: explicit null clearing, valid ancestry и nonwaiting PostgreSQL write fence, parent editor с сохранением draft/owner и подтверждением результата. Before:4 HTTP/6 PostgreSQL/8 frontend failures; controls и runtime errors отделены. После:34 group cases,10 hierarchy DB cases,8 новых frontend regressions; full95 suites/761 tests. Finite own-empty-group canary подтвердил clear/omission/reassignment, descendant400 без partial write, parent delete с сохранением child/leaf и исходных device memberships.

Runtime logs выявили N05: rollback удалял ORM tenant attrs и audit failed requests терялся. `933164e` сохраняет immutable authenticated UUID snapshot.4 PostgreSQL/ASGI failures воспроизведены; после24 combined DB cases passed и в actual final image. Live audit readback подтвердил3 refused PUT 400/404/409 с правильным actor/status. Старый локальный dependency export отличался; production-image OpenAPI check matched. Первое live audit чтение использовало неподдерживаемый route; исправленный readback принят без повторения writes.

Review3015 UIa9240a7/API933164e установлен; login/API/Prometheus/Grafana/events WS passed,43 остальных containers preserved.28/41 source fixes,13 исходных OPEN; дополнительные N01/N03 OPEN, N04/N05 source+finite API fixed. Outbox durability и browser visual OPEN. Published 1767bec полностью прошёл CI, новая публикация имеет собственные checks. [Полный отчёт и allowlisted evidence](../2026-10-02/GROUP-HIERARCHY-AND-AUDIT.md).

## F38 —2 октября16:18 UTC+5

Commit `e2362eb`: native user creation form, safe field-level errors/focus, captured role/deactivation dialogs, actual grant matrix, exact identity/receipt checks, active-tab abortable session-scoped catalog. Before4898577:16 assertion failures/0 runtime errors; after16 workflows+5 hook cases,23 user HTTP,49 RBAC pairs. Full96 suites/777 tests/types/lint/production Docker build passed;44 прежних warnings. UI3015 установлен16:09, API933164e сохранён. Login/API/Prometheus/Grafana/events WS/compiled SHA passed; negative user API422/404/400 и неизменность прав подтверждены.44 остальных containers,14running сохранены.29/41 source findings fixed,12 original OPEN. Browser visual и successful live user mutation OPEN; F39 общей оболочки не закрыт. Published4898577 полностью прошёл CI; новый head проверяется отдельно. [Контракт и allowlisted evidence](../2026-10-02/USER-ACCESS.md).


## Двенадцатый batch — глобальное расследование аудита, 2 октября17:12 UTC+5

Коммиты `39baa13`/`67b6bef`: shared backend conditions для списка/CSV; validated action/status/actor/resource/aware time/AND search; UI draft отделён от applied filters; CSV5000 cap, one projection SELECT, scalar allowlist, formula protection и проверяемые headers. Before5d27624:11 UI assertions failed/0 runtime-error suites; initial PostgreSQL18 failed/6 controls. After29 новых UI/validation cases,36 focused,98 suites/806 full;61 PostgreSQL cases прошли также внутри production image. Types/mypy223 files/production Ruff0.15.2 и обе immutable Docker builds passed;44 старых frontend warnings. OpenAPI172 operations/135 paths соответствует actual image. Local old Ruff0.3.0 различался; final production check accepted.

UI3015/audit установлен17:11, API39baa13 —17:09. Реальный журнал5386: event со второй страницы найден combined filters и совпал с CSV; cap5000 уникальных rows с truncation подтверждён. Login/API/Prometheus/Grafana/events WS/compiled SHA passed;19 devices,14online/5offline — finite recovery slice.43 прочих containers (13running), APK/OTA/tunnels/public UI preserved.30/41 source findings fixed,11 original OPEN; браузер и безлимитный архив/large-volume performance/outbox не приняты. Source frontend CI67b6bef passed; backend/Android выполнялись на срезе, docs head отдельный. [Контракт и allowlisted receipts](../2026-10-02/AUDIT-INVESTIGATION.md).


## F33 — адресная доставка и remote canary, часть1

Коммиты `8267b94` (backend) и `d61ab49` (UI). Grant теперь будит уже подключённый Android socket; worker повторно проверяет tenant/signed grant/command/session/deadline. Перечитывание и same-ID dispatch не продлевают разрешение; conditional revoke не удаляет заменённую команду.

310 backend regressions,5 actual PostgreSQL/RLS/Redis cases на host и внутри production image,99 suites/825 frontend tests passed. Remote PH013 адресно обновился10230→10240: live send13:11:37 UTC, completed receipt13:11:59 UTC и последующий свежий heartbeat. Один grant600s, normal channel не продвигался. F33 остаётся частичным; fully-fixed count30 не увеличен. [Отчёт и ограничения](../2026-10-02/OTA-ADDRESSED-DELIVERY.md) · [Операторский workflow](../../operations/OTA-ADDRESSED-UPDATES.md).

## F27 — 2 октября 2026,23:45 UTC+5

Архивный server scope, immutable version viewer/redacted diff и conditional archive/rollback/Run установлены. 14 before PostgreSQL failures и11 UI failures воспроизведены. После25 actual DB/production-image tests и846 frontend tests passed. Свой pilot сценарий v1→v2→новая v3→архив принят; stale mutations/admissions409; исходные версии сохранены. Public UI/APK/OTA/Tuna не менялись.31 findings исправлено/10 OPEN. [Операторский контракт](../../operations/SCRIPT-VERSIONS.md) · [Report](../2026-10-02/SCRIPT-VERSION-WORKFLOW.md) · [Receipts](../2026-10-02/SCRIPT-VERSION-WORKFLOW-EVIDENCE.json). Browser visual OPEN_URL_POLICY_BLOCKED.


## F28: определение pipeline и исправленная активация —3 октября

- Baseline d6be09a:22 failed/8 passed на реальном PostgreSQL; toggle без active422
  подтверждён installed API. Update принимал пустые/101 steps, stale/null edit,
  runtime timeout под active run; полного owned detail/edit в UI не было.
- cc28e9b: expected_updated_at, NOWAIT definition/admission fence, update graph
  validation и atomic rejection runtime edit при nonterminal run. Metadata и
  deactivation сохраняют существующие jobs; steps snapshot не переписывается.
- d829b47 + legacy compatibility5b20955: detail/editor/confirmation/receipt, role/session ownership, dirty
  conflict и unknown outcome без replay; actual active query исправляет кнопку.
- 21 UI cases/full867 passed/types/build;120 related PostgreSQL,35 production-image,
 16 toggle/service unit; pinned Ruff0.15.2/mypy224 passed.
- Install/API proof21:14–21:16UTC: review3015 UI/API revision matched;
  own pipeline4ff5f7e3-f9f0-428e-97f6-cce53550df05 v2/inactive,0 runs.
- Initial12online/7offline, затем6 samples14online/5offline в150s;13 running
  соседних containers IDs/images/starttimes preserved. No new long-soak/FPS claim.
- Input_schema semantic validation/global chain retries/runtime settings snapshot
  migration, visual/keyboard/mobile/production/fleet gates OPEN.
- Далее: F32/F33 command/OTA outcomes и F34–F36 video/XPath;
  остальные замечания не объявлены устранёнными. [Контракт/receipts](../2026-10-03/PIPELINE-DEFINITION-WORKFLOW.md).


## F26: география и иерархия локаций — 3 октября

- API `db6be05`: nullable clear, owned GET с датами и прямыми counters, tenant
  transaction fence, cycle/ancestry validation до mutation, optional CAS PUT/DELETE.
- UI `8e0aeb5`: parent/root/coordinate поля, paths/ID/dates, role/session scope,
  dirty/stale preservation, receipt validation и dialog последствия удаления.
- Baseline PostgreSQL 15 failed / 11 passed из 26; final 30 passed, related
  location/group 40 passed; 30 также в immutable image без backend source mount.
- Старый UI page + новые helper controls: 11 failed / 7 passed; final 26 новых
  UI cases и весь frontend 102 suites / 893 tests passed. Types/build/lint passed;
  44 существующих lint warnings (в body UI commit осталось историческое 45).
- Live API: две собственные локации; valid zero/boundaries, cycle400/invalid422,
  null clear, stale PUT/DELETE409 и parent DELETE204/child retained подтверждены.
  Созданные объекты удалены, metadata существующих локаций не изменена.
- Review 3015 установлен; login/API/compiled stamp/Prometheus/Grafana/events WS
  passed. Шесть finite samples: 14 online / 5 offline; 13 persistent neighbors
  неизменны. Собственный ephemeral image-test probe учтён отдельно.
- [Контракт](../../operations/LOCATION-HIERARCHY.md) ·
  [Подробное доказательство](../2026-10-03/LOCATION-HIERARCHY.md) ·
  [Receipts](../2026-10-03/LOCATION-HIERARCHY-EVIDENCE.json).
- OPEN: F32, F33 PARTIAL, F34–F36, F39–F41, N01/N03 и durable audit outbox.
  Source/API fix не закрывает visual/keyboard/mobile, production rollout и
  combined stream+scripts load. Frozen audit не изменён.

## F32 — VPN targets/outcomes; N06 dependency ordering

API3461bf6→8cd5cf0 и UIa2c4f02 установлены на3015/vpn. Legacy enabled:false
больше не превращается в enable; empty rotate не global. Entire owned preflight
выполняется до provider/sender; результаты отдельно configured/rejected/unknown
и submitted/not_sent/unsupported/unknown. Android execution не выдумывается.
Pending/scope/duplicate guards и retained receipts проверены21 новыми UI cases.

Backend baseline17:15 failures/2controls; final21 focused/159related и159 в
immutable image passed. Live empty422/duplicate422/missing404 подтверждены после
N06: первоначальный cipher dependency возвращал503 раньше body validation.
Node24 first suite913passed/2failed из-за build env fixture; test-only3ac818f
исправил fixture, добавил mismatch check. Итог103suites/916passed, types/build/lint
passed с44 прежними warnings. Production frontend междуa2c4f02/3ac818f не менялся.

13 neighbors сохранены; no mutating Android/VPN commands. Отдельно выполнены2
read-only REQUEST_LOGS наPH028/PH011:1.2.32-dev. Online finite14→11→12; latest
catalog01:53UTC14online/5offline и3latest/11old. F32/F33 не закрыты; next priority
channel/artifact/delivery/receipt/heartbeat и continued reconnect evidence.
[Полный отчёт](../2026-10-03/VPN-CONTROL-OUTCOMES.md) ·
[Контракт](../../operations/VPN-CONTROL-OUTCOMES.md).

## F33 — совместимость и controlled addressed wave,3 октября

Live channel/android-dev остаётся10209, canary-dev10240; текущий Worker поэтому
не предлагает10240 старым версиям.11oldonline не имели active10240 grants.
Exact installed SHA/package/signer проверены; PH02810232→10240, затем10 targets
последовательно.11completed receipts/post-install heartbeats, grant auto-clear;
14online теперь10240.12 finite samples и unchanged connected_since до/после,
но длительная стабильность/normal promotion/general manifest/bulk UX OPEN.
[Квитанции, исходные каналы и ограничения](../2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).

## F33 — публикация, APK identity и 14 установок10241,3 октября

73bfa9a: malformed metadata/duplicate 409 под FileLock и conflicting latest 503.
77fca37: validated publication modal, reset consent, exact201, retained unknown и
GET-only reconciliation. facba9a: package/version/minSdk/current signer guard,
bounded rejection codes, worker не retry immutable incompatible APK.
5bb36ca: generatedOpenAPI обновлён после CI failure; 175 operations/137 paths.

130 backend cases на PostgreSQL/в immutable API image;104 suites/946 frontend
tests,364 cases выше582 baseline;818 passed/1 skip на каждый Android flavor.
Full GitHub backend 2381 passed/16 skipped до отдельного staleOpenAPI отказа.
На live API пять invalid/duplicate POST отказали без изменения каталога.
Canary10241 опубликован managed, normal/dev10209 не продвинут; PH028 и 13 targets
подтверждены по exact terminal receipts/post-install heartbeat. 12 конечных
readbacks:14online10241, unchanged epochs, heartbeat <30 s.13 соседних сервисов
сохранены. Старый10240 installer выполнил эту волну; новый10241 native guard
ещё требует следующего live upgrade. F33 остаётся PARTIAL, fixed-count33 не увеличен.
[Отчёт](../2026-10-03/OTA-RELEASE-IDENTITY.md) ·
[Контракт](../../operations/OTA-PUBLICATION-AND-APK-CHECKS.md).

## N07/N08 — ABR recovery и native OTA canary,3 октября

ABR b39676e:6 воспроизведённых failures→15passed;10242 full build821passed/1skip
на flavor, GitHub source checks passed. Managed canary10242 опубликован,
но PH02810241→10242 отказал `ota_signer_unavailable`:0 установок, rollout остановлен.
Сертификат/installed exact hash проверены. Native guard10241 пока не принят.

N08 candidate10243: modern current signer authoritative; missing SigningInfo
может использовать legacy лишь для bounded v2-only candidate/installed archives.
Rotation/unknown/malformed остаются fail-closed.10 targeted cases:6pass/4fail
до изменения→10pass после. Full build/native next-upgrade ещё OPEN.
[ABR report](../2026-10-03/STREAM-BITRATE-RECOVERY.md) ·
[Signer report/evidence](../2026-10-03/OTA-SIGNER-COMPATIBILITY.md).
33 source-fixed/8OPEN, F33 PARTIAL/F36 OPEN сохранены.

## N08 native result и14online10244,3 октября

PH028 штатный43→44:exact completed receipt/new heartbeat/grant auto-clear;
последующий installed hash совпал.13 других целей со старым guard41 получили
scoped root recovery, exact hash и новый heartbeat каждое. Всего14online10244;
12finite samples сохранили cohort/epochs и heartbeat<60s.16контейнеров сохранены.

Две остановки preflight до installer:PH014 original stderr unavailable/readonly
reconciled;PH019 confirmed login429, helper исправлен на одну operator session,
лимиты сохранены. Installerunknown не повторялся. Native fallback branch
не доказан пустым boundedlogtail; новая политика/flags приняты по install receipt.
Full832/flavor:831pass/1skip;sourcead34 CIbackend/frontend/Androidsuccess.
Normal/dev10209,stable/manifest/bulk/visual/soak/F36OPEN;33fixed/8OPEN сохранены.
[Полный отчёт](../2026-10-03/OTA-SIGNER-COMPATIBILITY.md).

## N09 — восстановление H.264 и измеренная доставка, 3 октября

До N09 на API facba9a / APK 10244: PH025 — 597 кадров за 20  с (29,85 кадра/с),
PH010 — 598 (29,90). По одному самозавершающемуся тесту движения на устройство.
Это доставка по WebSocket, не browser rendered FPS или задержка ввода.

Воспроизведены семь assertion failures старой очереди; ещё один case проверяет
новый recovery callback. После потери кадра зависимая цепочка отбрасывается до
нового IDR. Deadline проверяется при выдаче; mixed SEI/VCL учитывается целиком.
Запросы recovery выполняются отдельно от Redis reader, объединены по устройству
и ограничены одной task и интервалом 1  с. Прошли 230 WS и 41 PostgreSQL/Redis case,
Ruff/mypy; все 271 прошли в immutable image. Backend **37415e3 установлен**.
Повторный тест: PH025/PH010 по 599 кадров за 20  с (29,95). Семь срезов сохранили
14 online на 10244 и новые даты соединений; UI/Tuna/15 соседних сервисов сохранены.
Два отката по raw mount comparison разобраны; итоговые mounts эквивалентны.
Browser/input/F36 OPEN; исходные 33 исправленных / 8 OPEN сохранены.
[Отчёт](../2026-10-03/STREAM-REFERENCE-RECOVERY.md).

### F39 — серверные права и просмотр без управления

Implementation00d5ad8 и schema repair729c1da; установленный UI/API00d5ad8.
[Контракт, before/after, shipped-image проверки и live readback](../2026-10-03/SESSION-CAPABILITIES.md).
Только этот slice принят по API/JSDOM gates; full role-action UX и visual OPEN.
