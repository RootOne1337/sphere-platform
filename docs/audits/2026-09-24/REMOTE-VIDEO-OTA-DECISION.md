# AUD-163 · Удалённое видео и решение по OTA-публикации

**24 сентября 2026 · pilot `sphere-pilot-20260911` · P0 для Fleet32 · статус: причина потери удалённого изображения не локализована, массовый rollout — NO-GO. 1.2.18 установлена на одном локальном rooted canary; удалённая OTA и terminal receipt не подтверждены.**

[Текущий pilot](../../operations/LOCAL-PILOT.md) · [Readiness](../../operations/READINESS.md) ·
[Live-сравнение кадров AUD-148](../2026-09-23/REMOTE-FLEET-LIVE-FOLLOWUP.md) ·
[Первый Android-кадр AUD-161](../2026-09-23/ANDROID-INITIAL-FRAME-RACE.md) ·
[Reconnect и кандидат APK AUD-162](REMOTE-RECONNECT-INCIDENT.md) ·
[Новый A/B ingress и три remote VM AUD-164](REMOTE-INGRESS-AB.md) ·
[Отказоустойчивая OTA-архитектура](../../architecture/ANDROID-OTA-RELIABILITY.md) ·
[Fleet32 gates](../2026-09-20/FLEET32-PREFLIGHT.md)

**Дополнение 13:41–13:54 UTC:** независимый viewer ingress получил от локального
Android IDR/P, но от нового удалённого `PH008` — только SPS/PPS, как и локальный
viewer. `PH007`–`009` переподключались 19–21 раз за 15 минут, у них отсутствовал
подтверждённый heartbeat; запрос версии APK у `PH008` завершился timeout.
Подробные измерения и ограничения гипотезы Cloudflare — в [AUD-164](REMOTE-INGRESS-AB.md).
APK на удалённых устройствах не обновлялась этой проверкой.

## Решение на этот срез

**Не публиковать APK 1.2.15 в общий OTA-каталог и не менять подписанный GitHub
manifest только ради этой попытки.** Это не пропущенная загрузка в GitHub.
`sphere-agent-config` распространяет подписанные адреса управления; APK клиент
получает из каталога и artifact endpoint работающего backend. Обычный ответ
`/updates/latest` выбирает максимальный `version_code` для `android/dev`, без
настройки одной целевой машины или доли rollout. Следующая успешная периодическая
проверка могла бы предложить 1.2.15 всем совместимым dev-клиентам. С текущими
отказами обновления и неизвестными версиями удалённых APK это был бы массовый
эксперимент, а не доказательство исправления.

**Подтверждённый факт:** в трёх удалённых viewer-сессиях PH006 через backend дошли
SPS/PPS, но ни один IDR/P-кадр изображения. В контрольной локальной сессии
`auto-ph-000` через **тот же публичный Cloudflare Quick Tunnel** дошёл IDR размером
40 351 bytes и три P-кадра. Следовательно, Quick Tunnel, backend и viewer способны
передать бинарное видео в данной конфигурации. Это **не** исключает потери именно на
пути удалённого LDPlayer → его ISP/Cloudflare edge → tunnel/backend, как и дефекта
Android capture/encoder у конкретного эмулятора. Наблюдаемый значок системного
захвата доказывает запуск MediaProjection, но не формирование и доставку IDR.

**Ожидаемый следующий шаг:** один удалённый canary с проверенной установленной
версией, адресом соединения и счётчиками на каждой границе кадра. Если он
не проходит, сравнить тот же canary через независимый ingress, не меняя все
устройства. Только после успешного browser decode и reconnect переходить к
контролируемой волне и затем к Fleet32. В исходном срезе код, контейнеры, APK на
устройствах и OTA-каталог не изменялись. Последующая проверка описана ниже.

## Адресная OTA-проверка после исходного среза

В 00:59–01:02 UTC 24 сентября проверен один **логический** device ID PH006.
Проверенный APK 1.2.15/10215 (8 411 445 bytes, SHA-256
`7efc954d2895a60abce31cfbffea2f5d354bea1d1a884e588efbb2a7c43f5202`)
размещён в управляемом artifact store и опубликован только как
`android-canary/dev`. Обычный `android/dev` latest остался 1.2.9/10209; тест
`test_canary_platform_release_is_excluded_from_regular_dev_checks_and_grant_is_targeted`
прошёл вместе с 26 остальными API-тестами. Это не публикация в GitHub
`sphere-agent-config`: тот репозиторий содержит подписанные адреса, а не APK.

С текущей станции файл был скачан через публичный tunnel: HTTP 200, полный размер
и совпадающий SHA-256. После одного краткосрочного recovery grant для PH006 backend
четырежды отправил **один и тот же** `OTA_UPDATE` command ID после reconnect и
получил четыре пары `received`/`running`; один поздний `failed` классифицирован
как `timeout`. Публичный gateway записал девять HTTP 200 для этого artifact за
всё окно, включая один известный локальный probe. Access log фиксирует отправку
ответа на gateway, но не доказывает полное чтение, проверку SHA или установку на
удалённом Android. `completed`, post-install versionCode и свежий удалённый
IDR/browser decode **не получены**. Запрос собственных логов PH006 не вернулся
в пределах 15 секунд; повторять shell/logcat вслепую не стали.

В 01:02 UTC grant явно отозван (HTTP 204), после чего PH006 снова прошёл обычную
WS-авторизацию. Контейнеры pilot и общий OTA-каталог не обновлялись; старый
Compose project/tunnel не трогались. Сырые ответы, доступы и журналы сохранены
только в игнорируемой `.local-pilot/remote/ota-canary-20260924-ph006/`.

Позднее read-only API показало 7/7 карточек `online`, но у трёх, включая PH006,
`last_heartbeat=null`. Backend отмечает online при WS-авторизации, до первого
application `pong`; быстрые reconnect могут постоянно обновлять этот признак,
так и не дав 30-секундному heartbeat пройти. Поэтому online здесь означает
«недавно был авторизованный socket», а не подтверждённую работоспособность
команд или видео. Это отдельный операторский сигнал, требующий отображения
давности heartbeat и reconnect rate в UI/диагностике.

**Вывод:** публичный route и backend способны отдать файл; это сужает, но не
закрывает гипотезу о WAN/Cloudflare для бинарного видео. Повторный OTA-download
при нестабильном WS является отдельным воспроизведённым дефектом старого APK.
Сервер не может безопасно подавить все повторы для одного ID: до rebind несколько
физических клонов могут предъявлять один и тот же ID/token, и существующий
production regression намеренно проверяет доставку всем 20 копиям. Поэтому
защита должна храниться **на каждом Android-экземпляре**. В PR добавлено
журналирование `OTA_UPDATE` по command ID в APK 1.2.18/10218; red/green-тест
подтвердил отсутствие второго install на одном экземпляре и отказ от replay
после перезапуска с неизвестным исходом. Recovery-канал не присылает SQL
`result_ack`: дополнительный red/green-тест показал, что без локального terminal
ACK успешно поставленный в WS-очередь результат навсегда занимает слот outbox.
Отдельная красная regression показала и второй крайний случай: первичный
`sendJson=false`, затем успешный flush после перезапуска тоже оставлял receipt
в outbox. APK теперь сохраняет локальную delivery policy в журнале и переводит
terminal OTA receipt в индекс после успешного `sendJson`, включая reconnect
flush; при отказе queue результат остаётся pending. DAG по-прежнему ждёт
серверного `result_ack`. Обе полные Android suites прошли по 637 тестов на flavor
(ноль failures/errors, один штатный skip в каждом). Собранный
pilot candidate лежит в игнорируемом каталоге
`.local-pilot/apk/SphereAgent-pilot-candidate-1.2.18-dev-250c328.apk`: 8 413 649
bytes, SHA-256 `a2741f8ec954f79a62278d6d00ee4685573b8206bf77363f2683452a2f8ab79c`.
Package `com.sphereplatform.agent.pilot.debug`, versionCode 10218, APK Signature
Scheme v2 и совпадение signer с действующим pilot APK подтверждены; встроенный
source commit `250c328`. Промежуточные 1.2.16 и 1.2.17 не публиковались и
заменены этой версией. В момент описанной выше PH006 попытки кандидат **ещё не был
установлен** и **не был опубликован в обычный OTA-канал**. Последующий отдельный
локальный canary зафиксирован ниже; живой инцидент видео остаётся OPEN.

## Последующая локальная адресная OTA-проверка 1.2.18

На одном изолированном local pilot emulator `emulator-5554` (device `auto-ph-000`)
проверено обновление с 1.2.9/10209 на 1.2.18/10218. Проверенный APK помещён только
в local pilot artifact store и доступен как `android-canary/dev`; обычный
`android/dev` канал не менялся. Recovery grant был выдан только этому устройству и
после проверки отозван (HTTP 204). Соседний `emulator-5556` остался на
1.2.9/10209.

Успех подтверждён независимо по PackageManager `versionCode=10218`, новому PID
процесса агента, обычной последующей WebSocket-аутентификации и отсутствию нового
совпадения в crash buffer. Backend получил только `received` и `running` receipts;
terminal `completed` receipt отсутствовал. Поэтому локальная установка доказана,
а end-to-end серверное подтверждение завершения всё ещё не доказано. Удалённые
LDPlayer этой проверкой не опрашивались и не обновлялись; этот результат не
подтверждает исправление чёрного экрана или доставку за пределами локального
emulator network.

Эта проверка выявила и эксплуатационную задержку: до текущего source fix обычный
`UpdateCheckWorker` запускался только периодически раз в 6 часов. Теперь источник
дополнительно планирует сетевую one-time проверку на старте приложения и после
успешной авторизации management WS. Pending проверки объединяются WorkManager
`KEEP`; за одно время жизни сервиса `onConnected` вызывает такую проверку только
один раз, а запуск получает до 120 секунд jitter для распределения одновременного
переподключения флота. Шестичасовая периодическая задача и backoff остаются
fallback. Это пока source-level изменение с regression test; уже установленные
устройства должны получить APK с этим кодом, а расписание WorkManager всё равно
может задерживаться Android.

Отдельно исправлен ложный операторский путь во вкладке Updates: кнопка раньше
отправляла `OTA_UPDATE` на `/tasks/`, где обязательный `script_id` давал 422.
Теперь UI описывает фактическую публикацию релиза всем агентам выбранного flavor
при их плановой проверке и не выдаёт отправку несуществующей команды за успех.
Frontend regression и type-check прошли. Для настоящего адресного rollout нужен
отдельный API с устройством/когортой, версией, receipt и проверкой установки;
recovery grant не следует маскировать под обычную UI-кнопку.

## Область проверки и качество свидетельств

Проверены текущий checkout и PR #19, отдельный Docker pilot, состояние его
OTA-каталога, локальные APK, ограниченный API/логовый срез, история Serveo и
документация провайдера. Удалённая Windows-станция и её Android logcat/PackageManager
из этого workspace непосредственно не доступны. Поэтому сообщения владельца о
версии 1.2.11 на части удалённых LDPlayer и о включённом значке захвата остаются
полевыми наблюдениями, а не измеренной установленной версией или кадром.

| Уровень | Что установлено | Чего это не доказывает |
| --- | --- | --- |
| Измерено локально | Состав pilot-контейнеров, 7 зарегистрированных устройств (6 online во время проверки), 2 локальных APK 1.2.9/10209, серверный OTA max 1.2.9/10209, hash и размер кандидата 1.2.15 | Что все заявленные 20 удалённых клонов представлены уникально; какая версия стоит на каждом из них |
| Сохранённая live-приёмка AUD-148 | PH006 получал stream/keyframe команды, viewer видел SPS/PPS без picture NAL; локальный агент через тот же публичный tunnel передал IDR/P | Где именно исчез удалённый picture NAL; что браузер удалённого потока уже декодировал картинку |
| Текущий 30-минутный логовый срез | Android WS и viewer WS выполняли HTTP 101; многочисленные refresh 401/invalid-token; нет активных media-counter series в точечной выборке | Успешную авторизацию каждой WS-сессии, живой поток кадров, причинную связь всех 401 с конкретной машиной или отказ Cloudflare |
| Source/CI | Кандидат 1.2.19/10219 из `6c000ea` собран с startup/auth reconnect OTA check; package `com.sphereplatform.agent.pilot.debug`, pilot signer и signed discovery v24 подтверждены; 639 тестов/flavor прошли | Кандидат не установлен и не опубликован; это не подтверждает remote OTA, кадры или runtime на WAN |

Сырые журналы, устройства, ключи и подписанный manifest в отчёт не копируются.
Состояние online — моментальный снимок API, а не доказательство непрерывной связи.

## Точный путь данных и точки отказа

```text
Android MediaProjection / ImageReader
  → MediaCodec: SPS/PPS + IDR/P
  → StreamingManagerImpl.sendBinary / очередь OkHttp
  → удалённый uplink / публичный ingress
  → backend Android WebSocket
  → Redis video Pub/Sub
  → backend viewer WebSocket
  → browser H.264 decoder / canvas
```

Management WebSocket и media payload делят связность, но успешный control ping или
HTTP 101 не удостоверяет очередной binary video frame. SPS/PPS — конфигурация
кодека, а не изображение. Первый декодируемый экран требует IDR. Показатель
`PUBSUB NUMSUB=1` на видео-канале означает подписавшийся backend worker, не один
живой browser viewer и не принятие видеокадра. Нулевая серия media-метрик в
моментальной выборке означает отсутствие измерения на тот момент, не нулевой
трафик на всех интервалах.

### Сохранённое сквозное сравнение

| Источник и сессия | Viewer binary payload | Практический вывод |
| --- | --- | --- |
| PH006, 42.06 s | 2 SPS + 2 PPS; 0 IDR/P | Нечего декодировать как картинку |
| PH006, 20 s | SPS + PPS; 0 IDR/P; первый config через 8.172 s | Повтор отсутствия image NAL, не только задержка первого кадра |
| PH006, 18.02 s | SPS + PPS; 0 IDR/P | Третье независимое воспроизведение |
| `auto-ph-000`, 12.78 s, через публичный Quick Tunnel | SPS=1, PPS=1, IDR=1, P=3; 42 789 bytes суммарно; самый большой IDR 40 351 bytes | Публичная цепочка в принципе передаёт payload больше 16 KiB |

Источник: [AUD-148](../2026-09-23/REMOTE-FLEET-LIVE-FOLLOWUP.md). Это измерение
серверного viewer WebSocket, не браузерного декодера. Локальный и удалённый
Android проходят разный исходящий WAN/edge путь, поэтому результат первого не
оправдывает категорическое «Cloudflare исправен для всех».

### Свежий ограниченный runtime-срез

На 24 сентября pilot backend image `ff87b56dbbd7`, frontend `48c9480` и
`cloudflared:2026.9.1` были healthy. APK и tunnel в эту проверку не обновлялись.
В 30-минутном окне backend записал 15 подключений viewer, 8 disconnect,
480 `invalid_token`, 235 `auth passed` и 235 `stream resumed`. Публичный gateway
записал 8 закрытых `/ws/stream/` запросов со статусом 101. Число «подключений»
из разных логов нельзя механически вычитать: access log появляется при закрытии,
а лог приложения — в другой точке жизненного цикла. За 24 часа gateway записал
66 OTA check: 44 HTTP 401 и 22 HTTP 200. Без общего correlation ID это не
44 доказанных отказа обновления конкретно PH006, но это реальное препятствие
безоговорочному утверждению «обнова сама точно прилетит всем».

В той же точечной выборке Prometheus FPS, encoder frames/bytes и WS queue
accepted/rejected не имели активных series; Redis video channels PH006 и локального
агента имели по одному подписчику. Старые установленные APK могли предшествовать
новой телеметрии. Новый viewer для дополнительного probe в этом срезе не
создавался: до canary установленной версии повторный `start_stream` мог прерывать
активный захват из-за исправленного только в candidate дефекта AUD-162.

## Версии в исходном срезе до адресной OTA-проверки

| Поверхность | Исходное состояние 24 сентября до canary | Значение для инцидента |
| --- | --- | --- |
| Pilot backend | Образ `sphere-pilot-20260911-backend:ff87b56dbbd7` healthy; commit включает поддержку телеметрии AUD-151 и Redis recovery | Не путать с HEAD PR: backend-часть `4c057c5` о корректном disconnect log ещё не применена |
| Pilot frontend | Образ `sphere-pilot-20260911-frontend:48c9480` healthy; включает повторный keyframe request до первого кадра | UI retry сам не создаст IDR, если Android/сеть его не передаёт |
| Pilot tunnel | Cloudflare Quick Tunnel 2026.9.1; действующий подписанный manifest указывает один публичный management route | Независимого live fallback сейчас нет; смена manifest без второго проверенного endpoint ничего не чинит |
| Локальные LDPlayer | Два package `com.sphereplatform.agent.pilot.debug`, `1.2.9-dev` / 10209 | Рабочий локальный контроль, но версия устарела относительно source candidate |
| Удалённые LDPlayer | Пользователь ранее называл 1.2.11/10211 на части; remote PackageManager, APK hash и route не измерены | Нельзя объявлять их обновлёнными или одинаковыми |
| Backend OTA catalog | 8 записей; максимальный `android/dev` — `1.2.9-dev` / 10209 | Самостоятельная проверка не предложит 1.2.15 |
| Локальный pilot candidate | `1.2.15-dev` / 10215, 8 411 445 bytes, SHA-256 `7efc954d2895a60abce31cfbffea2f5d354bea1d1a884e588efbb2a7c43f5202`; pilot debug signer совпадает с локальным baseline | Собран и протестирован, но не установлен remote, не OTA-опубликован и не production release-signed |
| GitHub `sphere-agent-config` | Draft PR #1: подписанная версия маршрута 24, срок 21 октября 2026, один Quick Tunnel URL; GitHub Releases отсутствуют | Репозиторий конфигурации — bootstrap/discovery, а не место APK OTA |

Каталог OTA читается из `SPHERE_UPDATES_PATH`; `GET /updates/latest` выбирает
максимальный release по platform/flavor и возвращает URL managed artifact на **том
же сервере управления**. APK проверяет HTTPS и совпадение host `download_url`
с host сохранённого server URL. Поэтому простая загрузка APK как GitHub Release
и ссылка на неё из каталога нарушили бы проверку клиента. Рабочая публикация
требует согласованного backend artifact и catalog entry, а не только GitHub commit.
`UpdateCheckWorker` сохраняет периодическую проверку раз в 6 часов через WorkManager
как резерв и retry-путь. Candidate 1.2.19 дополнительно запускает сетевую проверку
при старте приложения и после первой авторизованной WS-связи в service lifetime;
это не обещание мгновенной установки, особенно при 401, Android defer или потере всех
маршрутов. [Дизайн и точные ограничения](../../architecture/ANDROID-OTA-RELIABILITY.md).

Кодовые опоры: `backend/api/v1/updates/router.py`,
`android/app/src/main/kotlin/com/sphereplatform/agent/workers/UpdateCheckWorker.kt`,
`android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt`.
Наличие специального recovery-пути в backend не превращает обычный latest catalog
в целевой staged rollout. До изменения release policy публикация нового максимума
для `android/dev` является общей.

## Проверка гипотезы Cloudflare и исторического Serveo

Коммит `1a5a02d` ранее сменил Cloudflare Quick Tunnel на Serveo SSH tunnel;
`1246fc8` исправлял interstitial Serveo. Это подтверждает, что сходный класс
проблем уже встречался, но старые коммиты и тексты `docs/deployment.md` /
`docs/architecture.md` не являются трассировкой текущей сессии. Нынешний pilot
снова использует Quick Tunnel. Текущая Serveo-конфигурация требует отдельной
регистрации ключа; готового второго публичного пути в pilot нет. Старые
`sphere-platform` и `sphere-tunnel` не затрагивались.

По официальной документации Cloudflare проксируемые WebSocket поддерживаются;
соединения могут закрываться по idle/edge restart. Quick Tunnel предназначен для
разработки/теста, без SLA, с лимитом 200 одновременных in-flight requests.
Cloudflare также описывает нарушения доступности через некоторые российские ISP,
включая снижение пропускной способности примерно до 16 KiB на соединение. Это
делает гипотезу пользователя об удалённом маршруте обоснованной для проверки,
но не устанавливает её как root cause: локальный контроль передал IDR 40 351 bytes
через тот же сервис, а удалённый кадр мог не появиться ещё в Android encoder.

Источники: [Cloudflare WebSockets](https://developers.cloudflare.com/network/websockets/) ·
[Cloudflare Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) ·
[Cloudflare service disruption в России](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/).

## Приоритетный реестр дефектов и рисков

| ID / severity | Root cause или проверяемая гипотеза | Evidence / reproduction | Затронуто и минимальное действие | Regression / residual risk |
| --- | --- | --- | --- | --- |
| RV-1 / P0, OPEN | У удалённого PH006 отсутствует picture NAL на viewer. Граница Android encoder → socket → ingress пока неизвестна. | Три viewer-сессии SPS/PPS без IDR/P; local public-tunnel control с IDR/P. | Android capture/encoder/OkHttp, WAN, backend `websocket/stream_bridge.py` / `video_transport.py`; сначала один инструментированный canary, не массовая смена tunnel. | Гейт: IDR/P и живое движение на browser canvas, повтор после reconnect. Root cause и устойчивость остальных 20 не доказаны. |
| RV-2 / P1, source-fixed, rollout OPEN | Ранний ImageReader callback отбрасывался до завершения `createVirtualDisplay`; неподвижный первый экран мог остаться без буфера. | Детерминированная red/green regression AUD-161; симптом совместим с RV-1, но связь с PH006 не подтверждена. | Android `StreamingManagerImpl`; fix входит в candidate 1.2.18 и установлен на одном local emulator-5554. | Удалённый canary должен получить первый IDR на статичном и движущемся экране; без этого нельзя назвать fix причиной восстановления. |
| RV-3 / P1, source-fixed, rollout OPEN | Refresh 401 повторно использовал отвергнутые credentials; reconnect мог зациклиться. Дублирующий `start_stream` ронял уже активную projection. | AUD-162 red/green тесты; live 401/invalid-token и source duplicate-start regression; 1.2.18 подтверждён на одном локальном устройстве. | Android `AuthTokenStore`, `ScreenCaptureService`, `CommandDispatcher`; candidate 1.2.18. | На удалённом canary сверить installed version, refresh/re-enrollment, PID/crash buffer, отсутствие повторной projection и новый IDR после reconnect. Remote APK ещё не измерены. |
| RV-4 / P1, PARTIALLY SOURCE-FIXED | Нет device/cohort gate в обычной публикации; `android/dev` latest застрял на 1.2.9 и часть check отвечает 401. До текущего diff OTA-проверка планировалась только раз в 6 часов. | `get_latest` фильтрует platform/flavor, выбирает max; 44/66 check за сутки = 401; локальный targeted 1.2.18 подтвердил, что отдельный grant доставляет APK только выбранному устройству. | Добавлена immediate one-time check на app start и authenticated reconnect с `KEEP`, network constraint и jitter; далее нужны backend cohort rollout и terminal receipt. Не публиковать global latest как canary. | Regression на schedule dedup/network constraint; тест staged policy, auth recovery, SHA/signature и post-install receipt остаётся открытым. Часть 401 может не относиться к нужному устройству. Каталожная lost-update race F32-14 остаётся отдельно. |
| RV-5 / P1, OPEN | Один Quick Tunnel route без независимого public fallback, плюс ограничения test-сервиса. | Signed config v24 с одним route; старый Serveo commit; официальные ограничения Cloudflare. | Discovery manifest, ingress, `docs/operations/REMOTE-PILOT.md`; сравнить второй owned endpoint лишь после проверки его доступности. | A/B на одном устройстве с одновременным frame-level evidence; смена провайдера сама по себе не считается fix. |
| RV-6 / P1, OPEN | Неполная live-наблюдаемость: старые APK не сообщают все encoder/queue counters; нет сквозного receipt на каждый frame stage. | В моментальной metrics выборке media series пусты; 101/Redis subscriber не говорят о кадре. | Android counters AUD-151, backend metrics, viewer browser; сохранять redacted session IDs и bounded counters. | Один canary должен сопоставить frame generation, local enqueue, backend receipt, Redis publish, viewer send, browser decode; без каждого звена причина останется вероятностной. |
| RV-7 / P1, OPEN | 7 backend-карточек не равны 22 физическим инстансам; clone binding на всех remote VM не принят. | Моментальный API: 7 records, 6 online; пользователь ожидает 20 remote + 2 local. | Android identity/binding и backend registration; отдельная приёмка 3/20/32 клонов по AUD-145. | Проверить независимые ID, одновременный online, OTA и stream на каждом; не удалять/пересоздавать старые VM вслепую. |
| RV-8 / P1, source-fixed, rollout OPEN | Старый Android `CommandDispatcher` не журналировал `OTA_UPDATE` по command ID; reconnect повторно запускал download/install. Recovery-канал не шлёт SQL `result_ack`, что оставляло terminal receipt в outbox и после reconnect flush. | Адресный grant PH006: четыре `received`/`running` одного ID, девять artifact HTTP 200 за окно, один `timeout`; red/green Android regression для duplicate install и освобождения outbox после queue failure/restart. | APK 1.2.18 ведёт локальный durable receipt и локально закрывает поставленный в WS-очередь terminal result, включая flush; серверная блокировка по общему ID отвергнута, потому что она лишит обновления остальные клоны. | 637 тестов/flavor; 1.2.18 подтверждён только на одном local emulator, версия удалённых APK неизвестна. После restart «unknown» требует проверки версии перед новым grant. Успех `sendJson` означает локальную очередь, не подтверждение получения сервером. |
| RV-9 / P2, source-fixed, deployment OPEN | Updates UI отправлял `OTA_UPDATE` в `/tasks/`, где обязателен `script_id`; кнопка не могла выполнить обещанный push. | Контракт API + red/green frontend regression: старый UI предлагал device button и ложный статус, запрос давал 422. | Убрана кнопка и показана действительная catalog-wide семантика плановой проверки. | 32/32 frontend suites, 267 tests, type-check; запущенный frontend image ещё прежний. Настоящий targeted rollout API остаётся будущей работой. |
| RV-10 / P1, OPEN | Online присваивается при WS auth до первого heartbeat; частый reconnect сохраняет online без подтверждённого pong. | После отзыва grant API показывал 7/7 online, у трёх `last_heartbeat=null`, включая PH006; исходник `android_agent_ws` публикует online при auth. | Backend presence и frontend fleet health: отделить недавно открытый socket от heartbeat-confirmed/stream-healthy и показывать reconnect age. | Не считать online приёмкой удалённого канала; нужен тест при reconnect <30 s, пропущенном pong и разрыве сети. |
| RV-11 / P1, OPEN | OTA metadata и APK artifact используют один backend host; нет независимого разрешённого mirror set. Потеря management tunnel/host блокирует и проверку каталога, и APK download. | `OtaUpdateService.validateDownloadUrl` требует совпадения host с сохранённым server URL; локальный test tunnel передал APK, но альтернативный artifact origin не проверен. | Следовать [OTA reliability architecture](../../architecture/ANDROID-OTA-RELIABILITY.md): подписанные immutable metadata, точный allowlist origins, scoped download authorization и один отдельно работающий mirror. | Fault injection для каждого ingress/mirror; доказать byte-identical SHA и успешный install при недоступности primary. В полном сетевом partition обновление недоступно. |

RV-2/RV-3 — доказанные **исходные** дефекты и покрытые source-фиксы; одна локальная
установка подтверждена, но remote rollout и устранение текущего runtime-инцидента
не доказаны. RV-1 — реальный наблюдаемый отказ с
пока неизвестной точкой потери. RV-5 — эксплуатационный риск и гипотеза, а не
объявленный виновник. F32-14, F32-20, F32-28–29, F32-33–34, F32-37 остаются
в [общем Fleet32 реестре](../2026-09-20/FLEET32-PREFLIGHT.md).

## Минимальная приёмка одного удалённого canary

1. Выбрать **один** удалённый LDPlayer с устойчивой сетью. Зафиксировать его
   PackageManager `versionCode`/signer, уникальный device ID, route generation,
   timestamps и прежний PID/crash buffer. Не предполагать 1.2.11 только по имени
   файла, скачанного на рабочую станцию.
2. Проверить отдельно `GET /updates/latest` с действующим устройством без
   публикации нового release. Если 401, классифицировать refresh/re-enrollment и
   добиться подтверждённого ответа именно этого canary. Не повторять слепо
   изменяющие запросы.
3. Обновить только canary проверенным pilot-compatible APK 1.2.19/10219 по
   контролируемому каналу после фиксации старой версии и rollback-возможности.
   Глобальный `android/dev` latest не переключать. Убедиться в установленной
   версии, сохранении ID и новом авторизованном WS.
4. Открыть один stream и коррелировать единую сессию на четырёх границах:
   encoder output IDR/P; Android OkHttp queue accepted/rejected; backend binary
   receipt/Redis; viewer binary receive и browser decoded/moving frames.
   Отдельно воспроизвести неподвижный первый экран, движение и reconnect.
5. Если encoder выдаёт IDR и очередь принимает bytes, а backend их не получает,
   сделать A/B **того же canary** через проверенный независимый ingress с
   одинаковыми размером/частотой кадра. Если encoder не выдаёт IDR — исследовать
   Android MediaProjection/ImageReader/MediaCodec и локальный logcat. Если backend
   получает IDR, а viewer/browser нет — исследовать bridge, Redis и decoder.
6. После 30–60 минут без crash, auth loop и чёрного экрана повторить на малой
   согласованной волне. Fleet32 — только после 32 уникальных IDs, runtime receipts,
   recovery-сценариев и устойчивой browser-просматриваемой картинки.

Приёмка **не пройдена** по HTTP 101, Android значку захвата, SPS/PPS, online badge,
успешной сборке или локальным двум устройствам. Нужны удалённые IDR/P и
декодированные движущиеся кадры с сохранением соединения после сбоя сети.

## Проверки этой ревизии и оставшийся риск

- Read-only: состояние девяти новых pilot-контейнеров, локальная версия двух APK,
  каталог backend, GitHub config branch/Releases, ограниченные API/gateway/backend
  метрики и история коммитов. Старый Compose project/tunnel не менялись.
- Local OTA 1.2.18 was confirmed on emulator-5554 by PackageManager, process restart,
  normal WS auth and unchanged crash buffer; grant revoked. Backend terminal receipt
  is still missing, emulator-5556 stays 1.2.9, and remote versions are unknown.
- Текущая правка prompt OTA scheduling проверена полной dev и enterprise suite:
  по 639 тестов, ноль failures/errors, один штатный skip на flavor. Candidate 1.2.19
  собран, но не опубликован и не установлен. Проверки предыдущего PR head
  не заменяют CI для новой ревизии; сборка и unit tests не являются удалённой
  приёмкой.
- Не проверялись установленная версия и crash buffer remote APK, свежий
  browser decode после candidate, независимый WAN route и 20–32 уникальных клонов.
  Пока эти факты отсутствуют, заявлять «обновление уже придёт само» или
  «Cloudflare — единственная причина» нельзя.

**Операционное правило:** сохранить этот audit как контрольную точку. До следующего
canary не пересобирать/перезапускать pilot или tunnel только ради гипотезы и не
обновлять общий OTA-каталог. После canary внести в этот документ точные receipt,
версии и итог PASS/FAIL вместо предположений.
