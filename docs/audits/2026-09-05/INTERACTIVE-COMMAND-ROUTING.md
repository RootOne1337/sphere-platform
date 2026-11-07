# AUD-92 · High · Подключённое устройство ошибочно объявлялось offline

**12 сентября 2026 · runtime defect · backend API / Redis / Android command path.**

[Отчёт](AUDIT-REPORT.md) · [Стенд](../../operations/LOCAL-PILOT.md)

## Влияние и root cause

При четырёх Gunicorn workers WebSocket принадлежит одному процессу. HTTP `shell`,
`logcat` и `reboot` проверяли локальный `ConnectionManager` процесса, получившего
HTTP-запрос. Другой worker возвращал `400 Device is offline` для подключённого APK.
При попадании в правильный процесс результат мог потеряться: подписка Redis
создавалась уже после отправки команды. Reboot дополнительно выдавал
`reboot_initiated` после timeout без подтверждения устройства.

## Доказательство до исправления

Через HTTPS нового pilot отправлены три безвредные shell-команды вида
`echo SPHERE_REMOTE_ACCEPTANCE_n` на установленный APK. Первая вернула HTTP 400
`Device is offline`, следующие две — HTTP 200 с ожидаемым stdout. Это реальный
четырёхпроцессный backend, а не только mock локального connection manager.

Новая regression использует изолированные PostgreSQL и Redis, настоящий ASGI API,
две `ConnectionManager` и `PubSubRouter`. Только remote manager владеет socket
double; он немедленно публикует результат в настоящий Redis. До fix все три
варианта shell/logcat/reboot получили **400 вместо 200**.

## Исправление

API проверяет принадлежность устройства через SQL, затем использует общий
`PubSubPublisher`. Подписка на результат подтверждается Redis **до публикации**
команды. Команда достигает worker, владеющего WebSocket. Интерактивные действия
отправляются только через live transport; при отсутствии подписчика возвращается
503 без скрытой постановки в offline queue.

Shell/logcat ждут terminal result с прежним форматом ответа. Reboot может вернуть
initiated после received/running ACK, но timeout теперь возвращает **504 с явно
неизвестным исходом**, без автоматического повторения действия. Поведение обычных
пользователей publisher с offline queue сохранено через default parameters.

## Файлы и сохранённые regression tests

- [devices/router.py](../../../backend/api/v1/devices/router.py): общая доставка
  трёх интерактивных API с SQL-проверкой доступа.
- [pubsub_router.py](../../../backend/websocket/pubsub_router.py): subscribe ACK,
  live-only option и ожидание progress по явному запросу.
- [test_interactive_command_routing.py](../../../tests/production/test_interactive_command_routing.py):
  12 сценариев — три cross-worker/immediate-result, три offline без deferred effect,
  три foreign-device denial до publish, reboot timeout/ACK и отсутствие transport.

После fix эти 12 и три существующие deadline regression прошли: **15 passed,
1 существующее предупреждение, 6.40 s**. Объединённый прогон `tests/` без отдельного
opt-in `tests/load`: **1526 passed / 368.66 s**, 4 предупреждения, без измерения coverage.
На четырёхпроцессном backend image `a22fb54` после подтверждённого возврата native
APK прошли **12/12** HTTPS `echo` с правильным stdout (735–1266 ms). Первый запрос
во время предшествующего backend restart получил 503, следующие 11 прошли; этот
переход сохранён отдельно. Успех после возврата связи не маскирует outage.

Targeted Ruff и generated API check проходят. Общие локальные Ruff/mypy остаются
нечистыми: 1 E721 и 13 type errors. Архив исходников `c0c0783` в том же окружении
воспроизводит те же количества и файлы; новые routing-файлы ошибок не добавили.
Это не заявление о прохождении этих gates в CI.

## Residual risk

Redis PubSub не является durable delivery. Разрыв после публикации может оставить
исход действия неизвестным; отсутствие результата не доказывает, что shell или
reboot не исполнился. API не повторяет их автоматически. Это интерактивный путь,
не долговременное DAG-задание. Native acceptance использует только `echo`;
настоящее выключение/перезагрузка пользовательского эмулятора не выполнялись.
Регрессии reboot/logcat используют управляемый ответ устройства через настоящий
Redis. Производительность большого парка и отказ Redis после publish остаются
отдельными испытаниями.
