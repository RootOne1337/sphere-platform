# PC Agent, Discovery, provisioning и n8n

| ID | Приоритет | Проблема | Доказательство |
|---|---|---|---|
| INT-01 | P1 | Сканирование через PC Agent возвращает пустой успешный результат без сканирования | Два расхождения в исходниках, повторная сверка F-07 |
| INT-02 | P1 | PC Agent теряет регистрацию топологии при медленном подключении | Исполнение startup с подменой транспорта |
| INT-03 | P1 | Пакет n8n использует несовместимые маршруты и учётные данные | Контракт исходников и заголовки из опубликованного кода |
| INT-04 | P2 | Device Pool игнорирует предел и фильтр тегов, Online использует сохранённый статус | Контракт API и исполнение опубликованного кода |
| INT-05 | P2 | Execute Script превращает отмену в timeout, теряет причину ошибки и выходит за заявленный срок | Исполнение опубликованного кода |
| INT-06 | P1 | Штатная регистрация webhook не даёт производственного пути доставки событий | Контракт и поиск ссылок по backend |
| INT-07 | P2 | Генератор provisioning перезаписывает конфиги и сообщает завышенное число файлов | CLI в отдельном каталоге |
| INT-08 | P2 | Генератор provisioning успешно пишет конфиг с пустым ключом и неверным URL | CLI и контракт схемы |

## INT-01. Запрос Discovery завершается до вызова PC Agent

Ветка сканирования через workstation запрашивает singleton `PubSubRouter` и затем вызывает у него `send_command_wait_result`. Этот метод реализован в `PubSubPublisher`. Исключение логируется, метод возвращает пустой список и сервис продолжает формировать обычный ответ. Поле `scanned` вычисляется из размера диапазона и числа портов, даже при отсутствии отправки. У диспетчера PC Agent дополнительно отсутствует обработчик `discover_adb`, и неизвестная команда отклоняется. При работе по этому пути пустой ответ не позволяет оператору отличить отсутствие устройств от отсутствия сканирования. Сетевой скан для аудита не запускался. [Реестр F-07](../2026-11-01/FINDINGS-REGISTER.md#f-07), [вычисление scanned](../../../backend/services/discovery_service.py#L95), [путь RPC](../../../backend/services/discovery_service.py#L123), [владелец метода](../../../backend/websocket/pubsub_router.py#L234), [диспетчер](../../../pc-agent/agent/dispatcher.py#L52).

## INT-02. Одноразовая публикация топологии не привязана к соединению

Точка входа запускает отдельную задачу, которая ждёт одну секунду и один раз вызывает `report_on_connect`. `AgentWebSocketClient.send` при отключённом WS возвращается без постановки в очередь, а `TopologyReporter` затем пишет в лог «Топология отправлена». В цикле повторного подключения вызова репортера нет. Проверка запустила точку входа с подменой ADB и транспортом, который становился подключённым после первой попытки отправки. Результат — одно обращение к `send` с `connected=false`, затем успешное подключение и пустая очередь. Сервер получает данные, которые обновляет отдельное сообщение телеметрии, но оно не повторяет `workstation_register`. Возможны устаревшие hostname, agent version, serial/ADB port и истечение часового кэша топологии. Доставка по рабочему WebSocket и состояние рабочих устройств не проверялись. [Startup](../../../pc-agent/agent/main.py#L68), [send](../../../pc-agent/agent/client.py#L89), [лог](../../../pc-agent/agent/topology.py#L35), [серверный обработчик](../../../backend/api/ws/agent/router.py#L49), [probe](evidence/probe-pc-topology.py), [результат](evidence/pc-topology-probe.json).

## INT-03. Общий HTTP-клиент n8n расходится с контрактом API

В проверенном пакете `BaseNode` использует `X-API-Key` и `X-Org-ID`. Вызываемые пользовательские операции Device Pool и Execute Script используют зависимости, требующие пользовательский Bearer. Пакет не посылает заголовок `Authorization`. При штатной проверке токена такой запрос не доходит до бизнес-операции. Event Trigger дополнительно формирует `/api/v1/webhooks` без сегмента `n8n` и без обязательного поля `name`. Поэтому его зарегистрировать по этому контракту нельзя. [HTTP-клиент](../../../n8n-nodes/nodes/BaseNode.ts#L28), [user dependency](../../../backend/core/dependencies.py#L33), [Devices](../../../backend/api/v1/devices/router.py#L143), [Tasks](../../../backend/api/v1/tasks/router.py#L147), [Trigger](../../../n8n-nodes/nodes/SphereEventTrigger/SphereEventTrigger.node.ts#L99), [registry](../../../backend/api/v1/n8n/router.py#L21), [схема](../../../backend/schemas/webhook.py#L11), [наблюдённые заголовки](evidence/n8n-probe.json).

## INT-04. Device Pool формирует фильтры, которых нет в API

Отдельно от авторизации проверен контракт запроса. В режиме **Get by Tags** опубликованный `dist` отправляет `tags` и `limit`. API списка объявляет `per_page` с default 50 и не объявляет `tags`. Узел обрабатывает только первую страницу и не применяет локальный фильтр. В проверке с ответом в серверном формате узел вернул нетегированное устройство при запросе `fixture-tag`, а `total=140` и `pages=3` проигнорировал. **Get Online Only** передаёт `status=online`, который API считает legacy DB filter, хотя актуальная достижимость определяется `live_status`. После восстановления авторизации workflow может получить неполный или неверно отфильтрованный набор устройств. [Запрос узла](../../../n8n-nodes/nodes/SphereDevicePool/SphereDevicePool.node.ts#L80), [параметры и фильтры API](../../../backend/api/v1/devices/router.py#L143), [формат страницы](../../../backend/api/v1/devices/router.py#L249), [результат](evidence/n8n-probe.json).

## INT-05. Execute Script подменяет терминальный исход и теряет причину

Поллинг обрабатывает `completed` и `failed`. Backend дополнительно может вернуть `cancelled` и `timeout`, а текст причины находится в `error_message`. При `cancelled` в проверке опубликованного JavaScript с тестовым таймером узел продолжил ветку ожидания и вывел `status=timeout`. Для `failed` с явным `error_message` вывел `Unknown error`. Цикл проверяет дедлайн перед фиксированной паузой в две секунды и затем начинает GET, поэтому срок ожидания 1 секунда в проверке привёл к GET в момент 2 секунды даже при нулевой задержке HTTP. Это может направить workflow в неверную ветку обработки и скрыть первичную ошибку задачи. [Проверка срока и статусов](../../../n8n-nodes/nodes/SphereExecuteScript/SphereExecuteScript.node.ts#L122), [статусы backend](../../../backend/models/task.py#L17), [поле причины](../../../backend/schemas/task.py#L51), [probe](evidence/probe-n8n.cjs), [результат](evidence/n8n-probe.json).

## INT-06. Webhook registry и callback задачи не образуют один контракт доставки

В исходниках backend определён `N8NWebhookService.dispatch_event`. В рабочем коде потребителя этого метода не найдено. Событие `task.completed` или `task.failed` для Event Reactor и callback по `webhook_url` находятся в отдельной ветке TaskService. Callback выставляет `event_type=task.completed` и передаёт флаг `success` даже при неудаче. Подписываемый payload registry использует точные отправленные байты, а проверка n8n повторно сериализует JSON. Ключи подписи в реализации также различаются. CRUD registry может сохранять запись, но это не подтверждает доставку зарегистрированного события или прохождение проверки подписи в n8n. Проверка основана на исходниках, без создания или отправки реального webhook. [Документ контракта](../../operations/N8N-INTEGRATION.md), [registry dispatch](../../../backend/services/n8n_webhook_service.py#L100), [отправитель](../../../backend/services/n8n_webhook_service.py#L181), [приёмник](../../../n8n-nodes/nodes/SphereEventTrigger/SphereEventTrigger.node.ts#L129), [результат задачи](../../../backend/services/task_service.py#L509).

## INT-07. Provisioning сообщает число записей вместо числа файлов

В отдельном каталоге `--count 3 --instance-index 7` без workstation завершился кодом 0 и сообщил «Сгенерировано конфигов: 3». На диске остался один `sphere-agent-config-007.json`. Без workstation вычисление индекса игнорирует счётчик цикла, имя файла повторяется и открывается на перезапись. Отдельно пример в комментарии CLI с workstation и `--instance-index 42` сохранил `instance_index=0`, поскольку эта ветка использует `--start-index` с default 0. README описывает этот выбор, а CLI принимает оба сочетания без предупреждения. При подготовке фермы оператор может передать неполный комплект или конфиг с неверным индексом. [Пример CLI](../../../agent-config/scripts/generate_device_config.py#L7), [цикл и файл](../../../agent-config/scripts/generate_device_config.py#L123), [актуальный README](../../../agent-config/README.md#начальная-регистрация), [результат](evidence/agent-config-probe.json).

## INT-08. Provisioning CLI принимает недопустимый URL и пустой ключ

Генератор проверяет наличие required полей и префикс ключа только при непустом значении. В отдельном каталоге он принял `server_url=not-a-url` и пустой `enrollment_api_key`, записал файл и завершился кодом 0. Для этих полей опубликованная схема требует HTTP(S) URL и ключ с префиксом `sphr_`. Такой файл не пригоден для первичного enrollment по заявленному контракту. Обе проверки CLI выполнялись с синтетическими параметрами и без запуска Android. [Валидатор](../../../agent-config/scripts/generate_device_config.py#L55), [формат полей](../../../agent-config/schema.json#L8), [probe](evidence/probe-agent-config.py), [результат](evidence/agent-config-probe.json).

## Карта покрытия

| Контур | Проверенные точки | Ещё требуется |
|---|---|---|
| PC Agent | Startup, shutdown hooks по исходникам, повтор подключения, очередь, регистрация topology и telemetry, матрица поддерживаемых команд в dispatcher | Workstation lifecycle через живой авторизованный стенд, новое устройство, reconnect, задержки и подтверждение завершения команды |
| LDPlayer и ADB | Инвентаризация launch/quit/reboot/create/install/run и ADB devices/shell/install/push/pull/sync. Локальные тесты архитектуры и обработчиков | Операции в отдельном экземпляре LDPlayer, потеря ADB во время действия, сравнение статуса UI и фактического состояния |
| Discovery | Manifest/publisher, routing workstation RPC и результат сканирования. Автоматическая регистрация перечислена по входу | Разрешённый стенд Discovery с реальным PC Agent и изолированным тестовым устройством |
| Provisioning | JSON Schema, генерация env → single/batch, проверка наличия результата и двух ошибок валидации. Существующие тесты маршрутов генератора дали 2 passed | Доставка валидного конфига на устройство, потребление нескольких шаблонов и mode-specific настройки |
| n8n | Credentials, Device Pool (четыре режима), Execute Script (sync/async/timeout), Event Trigger и Webhook CRUD по исходникам | Загрузка пакета в поддерживаемый n8n, прогон штатного workflow, восстановление после разрыва и доставки с повтором |

Локальный прогон `test_pc_agent_arch.py`, `test_pc_agent_splits.py`, `test_pc_agent_mdns.py`, `test_pc_client_recovery.py`, `test_discovery_manifest.py`, `test_discovery_publisher.py`, `test_quick_tunnel_recovery.py` с `--noconftest -p no:cacheprovider` дал **173 passed**. Наборы используют локальные фикстуры. Прогоны выше добавляют входные ситуации, которых эти наборы не подтверждают.
