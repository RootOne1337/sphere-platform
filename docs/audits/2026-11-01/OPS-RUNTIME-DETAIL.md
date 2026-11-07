# Эксплуатационные инструкции: целевая сверка команд

Дата: 1 ноября 2026. Исходники репозитория и руководства сверены выборочно;
фактическое состояние установок, credentials, Docker, Windows Scheduler, GitHub
и устройств не читалось. Команды, поставки, тестовые подключения, рестарты,
публикации и ремонт не выполнялись. Исторические receipts сохранены.

## Реестр рассмотренных документов

| Документ | Сверенный фрагмент и исходное доказательство | Результат и граница |
| --- | --- | --- |
| [LOCAL-PILOT](../../operations/LOCAL-PILOT.md) | Раздел project/адресов и пример `.local-pilot/manage.py`, профиль `docker-compose.local-pilot.yml` | Датированный состав стенда и устройств помечен историческим; `up` отделён от просмотра. Игнорируемые локальные helper и env не читались и не аттестованы. |
| [REVIEW-GATEWAY](../../operations/REVIEW-GATEWAY.md) | Проверка rendered Compose в `scripts/pilot/review_gateway_preflight.py`, описание сети и поставки | Заголовок наблюдения 12 октября теперь исторический. Validator ограничен конфигурацией, не проверяет живой ingress. `nginx -t` и runtime не запускались. |
| [REMOTE-PILOT](../../operations/REMOTE-PILOT.md) | `docker-compose.remote-pilot.yml`, описание `scripts/verify_remote_pilot.py` | Исторические provider/profile claims обозначены срезом. Probe создаёт и удаляет синтетическое устройство; это выделено перед примером. Cleanup после аварии не гарантирован. Реальные адреса не проверялись. |
| [LOCAL-BACKEND-DELIVERY](../../operations/LOCAL-BACKEND-DELIVERY.md) | CLI аргументы `scripts/pilot/local_ci.py`, `package_local_backend.py`, `install_reviewed_backend.py` | Уточнено: `--publish` отправляет pending и конечный GitHub status, включая неуспех; `--apply` устанавливает. Это не приёмка конкретного артефакта или CLI execution. |
| [BUILD-PROVENANCE](../../operations/BUILD-PROVENANCE.md) | Аргументы `local_ci`, `package_local_web`, `install_reviewed_web`, `BUILD_SHA` в Dockerfiles/Compose | Уточнены внешняя запись commit status и фактическая сборка в примере Compose, необходимость выбрать env/project. Bundle и API ревизии не запрашивались. |
| [DISCOVERY-PUBLISHER](../../operations/DISCOVERY-PUBLISHER.md) | `scripts/discovery_publisher.py` reconcile и status write; `scripts/Install-DiscoveryPublisher.ps1` | `--once` — не dry-run: возможны GitHub PUT, mirror/state write и opt-in connector recovery. Установщик сразу запускает задачу. Команды диагностики отделены от отключения, исторические имя/пути не выданы за проверку текущей установки. |
| [HOST-RESOURCES](../../operations/HOST-RESOURCES.md) | `scripts/pilot/resource_guard.py` и `scripts/pilot/atomic_json.py` | Пример guard больше не перезаписывает фиксированный файл; явно описано поведение необязательного `--output`. Это не новое измерение диска или памяти. |
| [LDPLAYER-NETWORK-RECOVERY](../../operations/LDPLAYER-NETWORK-RECOVERY.md) | Аргументы `scripts/ldplayer_network.py`, `scripts/ldplayer_watchdog.py` и `scripts/Install-LDPlayerWatchdog.ps1` | Read-only диагностика отделена от `--repair`; установка расписания отдельно обозначена как немедленный старт и последующий возможный repair. VM/процессы не инспектировались. |
| [REDIS-MEMORY](../../operations/REDIS-MEMORY.md) | Base и production Compose: 512mb maxmemory, 3072M лимит; история отдельных результатов | Срез CI и 1536 MiB pilot маркирован историческим. Значения в source не подтверждают текущий runtime. Нагрузочный probe и `docker update` не запускались. |

## Что остаётся проверить

- Полные implementations и негативные пути delivery, гарантии rollback, сетевых
  границ и происхождения образов не переаттестованы одним просмотром аргументов.
- Незакоммиченные локальные helpers/config, их секреты и реально установленное
  состояние не анализировались. Состав конкретного deployment, scheduled tasks,
  GitHub статусов и работоспособность discovery требуется проверять отдельно.
- Текстовые historical sections могут содержать другие устаревшие формулировки;
  этот проход выделил наиболее существенные обнаруженные примеры и не означает
  построчную проверку девяти руководств.
- Локальная проверка ссылок ограничена путями и не подтверждает anchors, внешние
  ссылки, корректность команд, полномочия оператора или результаты runtime.
