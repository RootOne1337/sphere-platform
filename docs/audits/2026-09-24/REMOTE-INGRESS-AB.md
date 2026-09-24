# AUD-164 · Удалённый Android: где исчезает видеокадр

**24 сентября 2026, 13:41–13:54 UTC · P0 для удалённого видео и Fleet32 · OPEN.**

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

Гипотеза о Cloudflare **сильная, но пока не доказанная**. В истории есть
`1a5a02d` (переход с Cloudflare Quick Tunnel на Serveo после обрывов WebSocket)
и `1246fc8` (обход Serveo interstitial). Это свидетельство прежнего инцидента,
а не трассировка текущего кадра. [Cloudflare документирует](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/)
примерно 16 KiB на соединение у части российских ISP. Такой предел совместим с
прохождением маленьких SPS/PPS и потерей большого IDR, но один локальный Android
ранее передал IDR 40 351 B через этот же публичный Quick Tunnel. Путь из двух
квартир может идти через разные сетевые узлы; ни один из этих фактов не снимает
гипотезу о сбое encoder/отправки на удалённом Android.

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

`RootOne1337/sphere-agent-config` — **не APK-хранилище**. Его `main` содержит
историческую конфигурацию марта; draft PR #1 содержит подписанный manifest v24
с одним текущим Cloudflare management URL и без fallback. Менять этот документ
на короткоживущий тестовый URL сразу для всего парка нельзя. Код APK 1.2.18
есть в PR #19, локальный файл собран, но не опубликован как общая OTA-версия.
Два локальных эмулятора фактически имеют 1.2.9/10209; `android/dev` catalog
также заканчивается 1.2.9. Поэтому отсутствие 1.2.18 на них сейчас ожидаемо,
но адресный rollout и post-install receipt всё ещё отсутствуют.

## Риски, исправление и gate

| Severity | Defect / root cause status | Minimal next action | Regression / acceptance |
| --- | --- | --- | --- |
| P0 | Удалённый picture NAL не достигает viewer; точка потери между Android encoder/WS и backend не установлена | На **одном** удалённом canary сверить PackageManager version, encoder IDR bytes, WS enqueue, backend binary ingress; затем переключить только его Android egress на проверенный независимый маршрут с прежним Cloudflare fallback | IDR/P и движущееся изображение после первичного connect и reconnect; одинаковый тест на двух маршрутах |
| P0 | Три новых remote WS постоянно пересоздаются; online присваивается раньше подтверждённого heartbeat | Разделить socket-auth, heartbeat-confirmed и stream-health в API/UI; найти причину разрыва на canary | Без pong и при 20 reconnect/15 min UI не объявляет машину здоровой; команда возвращает явную ошибку |
| P1 | Один временный Quick Tunnel в signed config; независимого рабочего постоянного ingress нет | Поднять зарегистрированный/владельческий постоянный HTTPS/WSS endpoint, проверить `/health`, auth, binary frames, rollback, затем подписать новую версию manifest | Тот же canary продолжает задачи и стрим при выключении primary; возврат без переустановки APK |
| P1 | 1.2.18 не в общем OTA; нынешний каталог без cohort/device gate | Создать адресную публикацию/доставку с одним command ID, receipt и проверкой установленного versionCode; начать с локального canary | Никакой remote APK не получает canary до решения оператора; локальный post-install reconnect и сохранение ID подтверждены |

Сейчас массовое переключение provider или `android/dev` latest — **NO-GO**.
Нужно не просто HTTP 101 или значок MediaProjection, а IDR/P в backend и
движущиеся кадры viewer на удалённом canary; затем 3 → 20 → 32 уникальных
устройства с проверкой длительности соединения и автообновления.
