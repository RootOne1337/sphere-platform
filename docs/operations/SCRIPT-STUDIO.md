# Script Studio: граф, исходник и публикация сценария

6 октября 2026. Этап A; полный recorder/replay/debug ещё не реализован.
[Аудит и открытые критерии](../audits/2026-10-06/SCRIPT-STUDIO-FOUNDATION.md).

## Рабочий путь

1. Откройте «Сценарии → Новый сценарий» (`/scripts/builder`) и задайте название.
2. Найдите действие в каталоге 32 canonical типов. Шаг вставляется после выбранного
   линейного шага либо перед существующим завершением; condition получает две
   явные ветви на прежний target. Вставка не запускает команды.
3. Выберите шаг на графе. Справа редактируется весь JSON узла: `action`, вложенные
   параметры/селекторы, `on_success`, `on_failure`, `retry`, `timeout_ms`.
   Нажмите «Применить параметры». ID здесь неизменяем: переименование со всеми
   ссылками выполняется в JSON целого сценария. Неприменённые параметры блокируют
   save/check/run и смену выбранного шага.
4. «JSON» показывает исходник DAG 1.0. Можно вставить сценарий или импортировать
   `.json` до 512 KiB. Неверный текст остаётся для исправления; «Граф» применяет
   только валидную структуру. Предыдущий скрытый граф не подставляется при save.
5. «Проверить на сервере» возвращает SHA256, число шагов и scope. Это структура,
   маршруты/достижимость и Lua safety, **не проверка исполнения на Android**.
6. «Создать сценарий» / «Сохранить версию» используют существующий API. Обновление
   требует известный `expected_current_version_id`; конфликт 409 сохраняет ваш
   текст, не повторяет запрос автоматически. Экспортируйте изменения и откройте
   актуальную версию из каталога. Автоматического merge пока нет.
7. После сохранения откройте сценарий снова. «Запустить версию» доступен только
   неизменённой сохранённой версии с известным hash и правом `script:execute`.
   Studio открывает существующий run dialog в режиме явного выбора устройств;
   никакой автоматической массовой отправки или локального имитирования replay нет.

## Черновик и история

Undo/redo хранит до 20 документов и до 2 MiB **на каждый стек**. Изменение source
запоминается до замены; canvas selection/drag не создают semantic версии. Undo
открывает восстановленный исходник в JSON; кнопка «Граф» применяет его. Layout
не входит в wire DAG, локальные черновики его не сохраняют.
«Упорядочить» раскладывает canvas по маршрутам от entry; циклы обрабатываются
конечно, входной DAG не меняется. Положения canvas временные. Fit View показывает
весь граф в доступной области; zoom/pan не создают новую semantic версию.

Сохранение на ПК выключено по умолчанию. Checkbox включает debounce 700 ms для
одного документа на `org/user`; другой сценарий может заменить предыдущий
черновик этой identity. Максимум source 512 KiB, encoded envelope 528 KiB;
предложение восстановления действует 7 дней только для совпавшего resource.
Восстановление всегда явное и не делает API write. Полный source может содержать
приватный текст/headers/code; не включайте эту опцию на общем ПК. «Очистить
локальный черновик» удаляет только этот ключ. Ошибки storage показываются;
сохранение в backend и экспорт доступны независимо от localStorage.

Неприменённый JSON параметров узла не сохраняется как общий draft: сначала
примените его или скопируйте. Уход кнопкой каталога и закрытие вкладки при dirty
имеют предупреждение; browser beforeunload зависит от политики браузера. Ссылки
общего sidebar не имеют отдельного Studio route blocker, поэтому экспорт/draft
нужен перед навигацией. Это открытый hardening критерий, не обещание backup.

## Границы действия и права

Каталог основан на текущих `ACTION_TYPES` и шаблонах Android `DagRunner.kt`.
Он не является versioned capability schema. Обязательные runtime параметры всех
действий пока не проверены сервером; UIA2/root/permissions/selectors и версия APK
проверяются отдельным живым canary. Значения координат/селекторов — примеры,
их нужно заменить под экран. `shell`, HTTP, очистка данных, Lua и ввод способны
менять устройство; retry может повторить побочные эффекты.

Read/check требуют свежего `script:read`, write — `script:write`, run —
`script:execute`. Смена org/user/session remounts editor, отменяет load/check/save;
поздний ответ предыдущей identity не применяет документ/receipt/navigation к новой.
Истечение права чтения скрывает editor; восстановление той же identity не должно
перезагрузить уже полученный исходник поверх локальных правок.

Нет новой зависимости или внешнего CDN для source editor. Используются
существующие React Flow / React / lucide / UI primitives; оригинальная attribution
React Flow сохранена. [Лицензии frontend](../design/previews/admincn-sphere-2026-09-28/THIRD-PARTY-NOTICES.md).
# Usability redesign, 2026-10-06

The catalog now separates identity, version metadata and actions. List/card
view, density, metadata visibility and page size persist in a bounded browser
preference keyed by organization and user. Preferences contain no DAG source.
The version dialog retains guarded rollback/archive and redacted source reads.

Studio uses original rectangular nodes on React Flow and a locally served
ELK 0.12.0 worker for optional automatic layout. Its worker is terminated on
success, error, cancellation or a ten-second deadline. Node forms preserve
unknown JSON fields; advanced JSON remains available for nested arrays/maps.

Use **Устройство · запись · проверка** to select one online Android. The
workbench reuses the single-device H.264 stream and UI Automator inspector.
**Добавить элемент в сценарий** inserts a `tap_element` XPath action without
executing it. **Записать жесты** captures click/swipe/wheel submissions only,
up to 200 events in memory. Stop recording, review and explicitly insert it.
Pauses are preserved by default, capped at 60 seconds. Coordinate actions use
the APK 1280×720 / 720×1280 reference; rotation or layout changes can invalidate
their intent. Prefer XPath for persistent targets. Text and navigation keys
are not captured by this initial recorder.

**Проверить на [device]** submits one task pinned to the saved, unchanged
version. Structural validation alone does not execute Android. A network or
unconfirmed receipt blocks duplicate retry and links to the task catalog;
a definite 4xx rejection can be retried after correction. Input is locked
while a task is pending or its ownership is unconfirmed. Switching/closing
with an uninserted recording or active task asks before losing that context.

Graph highlighting uses actual last-processed progress (2-second observation)
and final node logs (success/failure); it is not a simulated active cursor.
Video, hierarchy and progress lack a common frame identity. Frame-exact replay
needs an additive Android/server protocol and remains open.

Evidence and library licenses: [redesign audit](../audits/2026-10-06/STUDIO-REDESIGN.md).

