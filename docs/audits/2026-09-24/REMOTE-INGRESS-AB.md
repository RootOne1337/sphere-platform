# AUD-164 · Удалённый Android: где исчезает видеокадр

**24 сентября 2026, дополнено 25 сентября · P0 для удалённого видео и Fleet32 · OPEN.**

[Исходный инцидент и OTA](REMOTE-VIDEO-OTA-DECISION.md) ·
[Remote pilot](../../operations/REMOTE-PILOT.md) ·
[Подписанный discovery](../../architecture/ANDROID-SIGNED-DISCOVERY.md)

## Проверяемое утверждение

У трёх новых удалённых LDPlayer (`auto-ph-007`–`009`) веб показывает online, но
не показывает картинку. Владелец сообщает, что установил новейшую доступную ему
APK. Её фактический `versionCode` на удалённых VM **не получен**: одна адресная
read-only команда `dumpsys package` к `PH008` завершилась HTTP 504 через 30 секунд.
Повторять команду без новой информации нельзя. Установленную версию не следует
выводить из имени скачанного APK или значка захвата Android.

Гипотеза о Cloudflare **правдоподобна, но не доказана как причина отсутствия
кадров**. В истории есть `1a5a02d` (переход с Quick Tunnel на Serveo после
обрывов WebSocket) и `1246fc8` (обход Serveo interstitial). Это свидетельство
прежнего инцидента, а не трассировка текущего кадра. Cloudflare документирует
поддержку WebSocket для Tunnel и proxied WebSockets, поэтому само отсутствие
поддержки WSS не объясняет сбой. При этом TryCloudflare Quick Tunnel прямо
предназначен для тестов и разработки, не имеет SLA и ограничен 200 одновременными
in-flight запросами; для production Cloudflare рекомендует управляемый Tunnel.
Ограничение по запросам может стать отдельным пределом при большом числе долгих
соединений, но его вклад надо измерить на фактическом потоке. Локальный Android
ранее передал IDR 40 351 B через тот же публичный Quick Tunnel. Поэтому текущие
данные оставляют открытыми Android capture/encoder, WAN egress и потери в любом
промежуточном hop.

Ссылки на первичную документацию Cloudflare: [поддержка WebSocket в Tunnel](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/),
[ограничения Quick Tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/)
и [proxied WebSockets](https://developers.cloudflare.com/network/websockets/).

## Runtime-доказательства

В новом Compose project `sphere-pilot-20260911` основной Cloudflare connector
оставался включённым; backend, APK и подписанный manifest не менялись. Отдельный
временный SSH ingress localhost.run был подключён к **тому же** `public-gateway`.
Через его HTTPS ответ `/api/v1/health/readyz` был 200. Протокольная проверка
создала одно синтетическое устройство, получила авторизованный WSS `auth_ok`,
обменялась heartbeat/pong, повторно подключилась с теми же credentials и удалила
probe device. Это проверка протокола, не Android APK.

Следующий 20-секундный контроль открыл три viewer WebSocket одновременно.
Android-агенты при этом **оставались на прежнем Cloudflare ingress**:

| Источник → viewer ingress | Binary | H.264 NAL | Максимальный пакет | Итог |
| --- | ---: | --- | ---: | --- |
| Удалённый `PH008` → локальный gateway | 4 | SPS=2, PPS=2; IDR/P=0 | 37 B | Нет изображения |
| Тот же `PH008` → независимый localhost.run | 2 | SPS=1, PPS=1; IDR/P=0 | 37 B | Нет изображения |
| Локальный `PH000` → localhost.run | 13 | SPS=2, PPS=2, IDR=1, P=8 | 23 173 B | Изображение прошло |

Это отделяет браузерный/viewer ingress от участка **удалённый Android → его WAN
→ Cloudflare → backend**. Альтернативный viewer не заменял Android egress:
поэтому таблица **не является** A/B Cloudflare против другого провайдера для
самого удалённого агента. Backend получил SPS/PPS от `PH008`; где исчез IDR,
по-прежнему неизвестно.

Срез backend logs за 15 минут, завершившийся в 13:53:51 UTC, показывает:

| Устройство | WS connect | Receive-loop error | Eviction старой сессии | Disconnect |
| --- | ---: | ---: | ---: | ---: |
| Локальный `PH000` | 0 | 0 | 0 | 0 |
| Локальный `PH001` | 1 | 1 | 0 | 1 |
| Удалённый `PH007` | 20 | 20 | 12 | 8 |
| Удалённый `PH008` | 21 | 20 | 12 | 8 |
| Удалённый `PH009` | 19 | 19 | 11 | 8 |

Ошибка `Cannot call "receive" once a disconnect message has been received`
наблюдалась после закрытия сокета. Частый reconnect делает статус online
обманчивым: у всех трёх новых карточек в точечной API-выборке
`last_heartbeat=null`. Для `PH008` команда версии не дала ответа за 30 секунд.
Это доказывает нестабильность их двустороннего канала, но само по себе не
показывает, закрывает ли сокет ISP, Cloudflare или Android.

Приватные воспроизводимые результаты: `.local-pilot/remote/serveo-ab/viewer-ab.json`,
`connection-summary.json`, `localhost-run-protocol.json`, `ssh-probes.json`;
личные токены и полные
логи в Git не включены. A/B-скрипт там же. Не подменять 20-секундную проверку
продолжительным soak-тестом.

## Проверка второго провайдера и GitHub

Serveo на SSH-порту 443 предъявил ED25519 fingerprint
`SHA256:GnmVK+70U6GqbupoV+gg7LnHHUsW1IjrK0cLqvDJxIk`, совпадающий с
[его документацией](https://serveo.net/docs/). Но подключение без ключа,
с новым отдельным ключом на портах 22/443, с другим SSH username и даже с
существующим **отдельным ключом нового pilot** завершилось
`Permission denied (publickey,keyboard-interactive)`. Действующий Serveo route
для **нового** pilot не поднят. Ключи/контейнеры прежнего `sphere-tunnel` не
использовались. Подставить старый Serveo hostname нельзя: он не доказывает
маршрутизацию к новому backend.

Временный localhost.run дал успешный HTTPS/WSS, но бесплатные домены
[меняются и ограничены по скорости](https://localhost.run/docs/forever-free/).
Он пригоден для сравнения одного canary, не для долговременной связи 20–32
устройств. После A/B временный localhost.run container остановлен; основной
Cloudflare connector остался работать. Cloudflare сам обозначает
[Quick Tunnel как test/development без SLA](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
Простая смена бесплатного сервиса без проверенного второго маршрута и rollback
не равна устранению P0.

### Повторная проверка временного маршрута, 24 сентября

Отдельный LocalTunnel процесс был направлен на тот же локальный
`public-gateway`. Его HTTPS health-check и WSS upgrade прошли до backend. Через
этот viewer ingress один короткий просмотр `PH008` получил **2 валидных Sphere
wire-пакета, 61 байт всего: SPS=1, PPS=1, IDR/P=0**. Кадра для декодирования не
было. Это подтверждает доступность альтернативного viewer ingress, но само по
себе не меняет egress удалённого Android.

Для попытки проверить egress была отправлена одна `UPDATE_CONFIG` только на
логическую запись `PH008`: LocalTunnel как primary и прежний Cloudflare URL как
fallback. Backend вернул `504` через 18 секунд, без терминального receipt; факт
применения конфигурации неизвестен. Отдельный read-only запрос логов к `PH007`
также завершился `504` через 15 секунд. Перепосылать команду без receipt не
стали. После завершения временного LocalTunnel его URL стал отвечать `503`, а
локальных соединений к gateway не осталось. Основной Cloudflare connector не
менялся; его контейнер healthy, текущий signed public endpoint вернул HTTPS
`200`, а WSS прошёл upgrade и закрыл тестовую сессию ожидаемым кодом авторизации
`4001`.

**Вывод:** Android-egress A/B не состоялся. Viewer через LocalTunnel тоже увидел
только SPS/PPS, но это не доказывает ни вину Cloudflare, ни успешный перевод
агента на новый маршрут. Ключевой эксплуатационный блокер для такой проверки —
удалённые команды и их receipts сейчас не подтверждаются. Глобальный manifest,
APK и backend при тесте не менялись. Подробный текущий статус — в
[readiness](../../operations/READINESS.md).

`RootOne1337/sphere-agent-config` — **не APK-хранилище**. На 25 сентября draft
PR #1 содержит подписанный manifest v24 с одним Cloudflare management URL и без
резервного ingress; оба его GitHub CI прогона прошли. Изменять конфигурацию всего
парка на короткоживущий тестовый URL нельзя.

### Перепроверка release readiness, 25 сентября 2026

Read-only ADB snapshot на этом рабочем ПК: `emulator-5554` — 1.2.20-dev/10220,
`emulator-5556` — 1.2.19-dev/10219. Других ADB-устройств этот компьютер не видит;
удалённые APK версии этим не подтверждены. Сохранённый локальный candidate
1.2.21-dev/10221 (`69a275b052477f8b0ce445149369ecba3b566c42f3d2a0fae0b6f5641deb98f8`)
собран из `182d40b`, но после него менялись Android OTA recovery, startup/reconnect
и streaming diagnostics. Поэтому candidate **не соответствует текущему Android
source** и не должен называться последней сборкой. Текущий
`android/version.properties` всё ещё задаёт 10221; для нового содержимого нужен
новый монотонный versionCode, иначе агент с уже установленным 10221 его не примет.

GitHub Android CI для `c8a1146` собрал debug APK и прошёл unit tests; это не release
APK и не доказательство совместимости подписи с установленными приложениями.
`.github/workflows/release.yml` создаёт release notes по Git tag, но не собирает и
не прикрепляет Android APK. В inventory repo/staging Actions secrets, локальных
`SPHERE_KEYSTORE_*` переменных и keystore-файлов в `android/`/`.local-pilot/`
подписывающий материал не обнаружен. Нельзя безопасно заменить его новым ключом:
установленные Android-пакеты могут отказаться от обновления из-за несовпадающей
подписи. Поэтому свежего подписанного OTA-кандидата и подтверждённой массовой
публикации сейчас нет; APK rollout остаётся **NO-GO** до восстановления исходного
release key, конфигурации enrollment/discovery, новой сборки с повышенным
versionCode, проверки signature/digest и адресного post-install canary.

## Подтверждённый backend queue-дефект — AUD-167

В локальной red/green-регрессии подтверждено, что backend раньше распознавал
только 4-байтовый Annex-B prefix. Трёхбайтовый IDR становился `UNKNOWN` и мог
выпасть из очереди после задержки; теперь Sphere header, оба вида prefix и флаг
keyframe обрабатываются корректно. 83 профильных backend stream-теста проходят.

Это объясняет, как WAN backpressure мог обрезать поток, но сохранённый remote
capture не содержит сырого IDR и его prefix. Очередь с исправлением сейчас
развёрнута в здоровом backend image `b2562ca04f5f`; работающий контейнер прошёл
read-only классификацию синтетического 3-byte IDR как critical. Причина
конкретного удалённого сеанса всё ещё не локализована, а Cloudflare остаётся
гипотезой. Подробная первопричина, воспроизведение и residual risk описаны в
[AUD-167](H264-ANNEXB-QUEUE-CLASSIFICATION.md).

## Риски, исправление и gate

| Severity | Defect / root cause status | Minimal next action | Regression / acceptance |
| --- | --- | --- | --- |
| P0 | Удалённый picture NAL не достигает viewer; точка потери между Android encoder/WS и backend не установлена | Сначала получить подтверждённый command receipt и установленную версию APK для одного стабильного уникального remote ID; затем переключить только его Android egress на проверенный независимый маршрут с прежним Cloudflare fallback | IDR/P и движущееся изображение после первичного connect и reconnect; одинаковый тест на двух маршрутах |
| P0 | Три новых remote WS постоянно пересоздаются; online присваивается раньше подтверждённого heartbeat | Разделить socket-auth, heartbeat-confirmed и stream-health в API/UI; найти причину разрыва на canary | Без pong и при 20 reconnect/15 min UI не объявляет машину здоровой; команда возвращает явную ошибку |
| P1 | Один временный Quick Tunnel в signed config; независимого рабочего постоянного ingress нет | Поднять зарегистрированный/владельческий постоянный HTTPS/WSS endpoint, проверить `/health`, auth, binary frames, rollback, затем подписать новую версию manifest | Тот же canary продолжает задачи и стрим при выключении primary; возврат без переустановки APK |
| P1 | 1.2.18 не в общем OTA; нынешний каталог без cohort/device gate | Создать адресную публикацию/доставку с одним command ID, receipt и проверкой установленного versionCode; начать с локального canary | Никакой remote APK не получает canary до решения оператора; локальный post-install reconnect и сохранение ID подтверждены |

Сейчас массовое переключение provider или `android/dev` latest — **NO-GO**.
Нужно не просто HTTP 101 или значок MediaProjection, а IDR/P в backend и
движущиеся кадры viewer на удалённом canary; затем 3 → 20 → 32 уникальных
устройства с проверкой длительности соединения и автообновления.
