# AUD-147 · Удалённые клоны: три новые offline-карточки и отсутствие видео

**23 сентября 2026, 16:12 Asia/Yekaterinburg · P0 / High · Fleet32: NO-GO.**
Это read-only аудит изменений 22–23 сентября и работающего pilot. Backend, APK,
конфигурация, контейнеры и данные во время этой проверки не изменялись. «Зелёный CI»
ниже означает проверку исходников, а не успешный удалённый запуск.

> **Актуальность:** это исходный read-only snapshot на 16:12. Он был superseded
> backend-first rollout и повторной stream-приёмкой позже в тот же день. Новые
> доказательства и фактическое состояние pilot записаны в
> [AUD-148 follow-up](REMOTE-FLEET-LIVE-FOLLOWUP.md); таблицы ниже сохраняют только
> историческое состояние на момент заголовка.

[Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md) ·
[Эксплуатационная готовность](../../operations/READINESS.md) ·
[Предыдущий разбор клонов](../2026-09-20/CLONE-IDENTITY.md) ·
[Первый кадр](../2026-09-20/STREAM-FIRST-FRAME.md)

## Решение и границы доказательств

**К массовому тесту 20–32 удалённых эмуляторов стенд пока не готов.** Три новые
карточки доказывают, что часть регистраций начала разделяться, но не доказывают
подключение этих APK: все три offline. Старая общая удалённая карточка продолжает
получать конкурирующие соединения. Видеопоток из неё не принят. Для двадцати
удалённых LDPlayer нет подтверждённых двадцати устойчивых online-ID и первого
декодированного кадра. Предел пропускной способности 32 потоков не измерен.

Точный установленный APK каждого удалённого клона, его serial, локальные Android
исключения и результат сохранения registration response сейчас неизвестны. Поэтому
нельзя объявлять причиной новых offline-карточек конкретный Android exception или
утверждать, что новый APK уже работает на удалённой станции. Отдельно описанный
ниже конфликт версий — **проверяемый по исходникам возможный механизм**, а не
установленный факт об этих трёх устройствах.

## Что реально изменилось за 22–23 сентября

| Компонент | Изменение и проверка | Состояние работающего pilot |
| --- | --- | --- |
| Backend и PostgreSQL | `ed3d544` разделил регистрации копий по v1 instance binding; `e4fdb71` добавил ограниченное OTA recovery; `c5ca5e5`/`3be0e29` уточнили причины отказов. Последующий `39cefcb` добавил подтверждаемую binding v2 и миграцию; isolated PostgreSQL regression проверил 32 конкурентные регистрации и повтор. | Backend image **`3be0e29`** healthy: v1 и recovery установлены, **v2 ещё нет**. Тест 32 HTTP-регистраций не проверяет 32 настоящих APK/WS. |
| Android | `a53f165` проверяет instance перед командным WS; `2cb4a9d` повторяет один оборванный OTA transfer через HTTP/1.1; `a66e460` удерживает ранний запрос IDR; `39cefcb`/`21814e9` требуют уникальный VM serial и ACK v2. Source-pinned debug APK **1.2.11-dev / 10211** из `6788c90` собран: SHA-256 `18935e44b43b2f731176677a2acf8d306821792eee0477901a4f2606a76e73b7`, подпись проверена; 610 JVM-тестов на каждый flavor, один существующий skip на каждый. | Последний опубликованный OTA и локальный `LATEST` — **1.2.9-dev / 10209** (`a53f165`). Кандидат 1.2.11 не опубликован и не установлен нами; версии удалённых копий не подтверждены. |
| Web UI и видео | `717c5a1` повторяет запрос первого IDR; `a66e460` добавил Android-side backstop; `e635de8` исправил корень standalone-сборки. Frontend tests и CI прошли. | Frontend image **`9924eb1`** healthy, но без нового browser retry и standalone fix. Отдельный реальный первый кадр с удалённого устройства не подтверждён. |
| Nginx/remote ingress | `6788c90` исправил выбор redirect vhost для named-hostname WebSocket; isolated upgrade regression прошёл. | Живой gateway не пересоздавался после fix. Не доказано, что именно этот vhost участвует в текущем Quick Tunnel-сеансе. |
| Redis/Compose | `bee9bc0` поднял source limit до 2 GiB после OOM при 1.5 GiB; три isolated AOF/BGSAVE прогона прошли, худший `memory.peak` достиг самого лимита 2 GiB. | Живой pilot остаётся на прежнем лимите 1.5 GiB; 32 stream/slow-client нагрузка не принята. |
| GitHub | Draft [PR #19](https://github.com/RootOne1337/sphere-platform/pull/19): последний code head `6788c90` прошёл APK, backend, frontend, RLS, security, Alembic и image checks; затем следуют только документальные коммиты. | `deploy` **skipped**; PR остаётся draft/unmerged. CI не устанавливает APK и не заменяет pilot. |

Это инвентаризация изменений указанного периода. PC agent, VPN, PostgreSQL failover,
оркестрация задач и другие пункты общего [реестра Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md)
в данном инциденте не прогонялись повторно; их прежние открытые критерии сохраняются.

## Независимый срез живого стенда

Серверные логи агрегированы за **15:40–16:10 23 сентября, Asia/Yekaterinburg**
(10:40–11:10 UTC). PostgreSQL и Redis перечитаны в 16:12. Это счётчики событий,
а не число уникальных физических эмуляторов.

| Проверка | Результат | Что означает |
| --- | --- | --- |
| PostgreSQL `devices` | **6** активных строк: 3 прежних online, **3 созданных в 15:53 offline**. У новых три различных `instance_binding` и три fingerprint; все три уже имеют признак re-enrollment. | Разделение началось, но по сравнению с заявленными 22 эмуляторами отдельные рабочие подключения не получены. Новые записи не имеют подтверждённой версии binding v2 на старом backend. |
| Redis presence | Отслеживаются **3 online** статуса и ни одного live-статуса для новых трёх. | Новые карточки не стали online в наблюдаемой серверной выборке. Их свежий `devices.updated_at` может отражать повторную регистрацию и **не доказывает heartbeat APK**. |
| Backend Android WS | **24** `auth passed`/`Agent connected`, **22** `Evicting old connection` и **565** `invalid_token`, все для **одной старой удалённой карточки**. Все 565 отказов классифицированы как `Token expired`. Для новых трёх ID нет ни одного `auth passed` в этом интервале. | Старый shared ID продолжает переиспользоваться/вытесняться; регистрация новой строки сама по себе не создаёт командную сессию. История до начала интервала и состояние самого Android недоступны из этих логов. |
| Public gateway | **99** `POST /devices/register` → 201; **558** `POST /devices/refresh` → 401, 3 → 200; **590** `/ws/android` → HTTP 101. | HTTP 101 подтверждает WebSocket upgrade, **не успешную auth**. Ответ 201 не подтверждает, что Android проверил ACK и сохранил токены. Запросы не содержат безопасной сквозной метки экземпляра, поэтому 99 попыток нельзя без Android-логов распределить по всем 20 VM. |
| Просмотр удалённой карточки | В 16:04:16 сервер зарегистрировал viewer и передал `start_stream` и `viewer_connected` общему удалённому ID. Viewer закрылся через ~3 секунды с code 1005. За этот сеанс backend не зарегистрировал ни одного `Binary frame from agent`; последующий `stop_stream` доставлен. Более ранняя независимая 18-секундная выборка содержала девять SPS и девять PPS, **ноль IDR**. | Последний трёхсекундный сеанс слишком короток для вывода о длительном отказе кодера, но кадр в нём не дошёл до backend. Старый длинный срез доказывает отсутствие декодируемого IDR тогда. Наличие Android-значка захвата и доставленной команды не равно изображению в браузере. |

Сырые серверные журналы, device ID, сетевые адреса, токены и private diagnostic
artifacts остаются в `.local-pilot`; в Git добавлены только агрегаты.

## Открытые дефекты и гипотезы, от важного к менее важному

### P0 · F32-28: общая командная identity всё ещё вытесняет клонов

**Первопричина старого поведения:** полный клон переносит сохранённые credentials,
fingerprint и device ID. Текущая опубликованная v1 binding допускает MAC/Android ID,
которые могут копироваться вместе с VM. `ConnectionManager` закрывает прежнюю сессию
при новом WS с тем же ID. Сегодня это подтверждено 22 вытеснениями за 30 минут;
ранее за 15 минут их было 463. **Затронуты:** Android `CloneDetector`,
`InstanceBindingReader`, `InstanceRegistrationGuard`, `AuthTokenStore`; backend
`device_registration_service.py`, `connection_manager.py`; UI fleet status.

**Состояние fix:** v2 serial binding и backend migration покрыты тестами, но не
установлены. Новые три v1-карточки не закрывают требование 20 независимых online-ID.
**Остаточный риск:** копии с одинаковым VM serial останутся неразличимы; удалённые
serial и отсутствие новых вытеснений после rollout нужно измерить на месте.

### P0 · F32-36: регистрация новых трёх ID не завершается командным соединением

**Доказательство:** 3 новые разные записи в 15:53 и повторные регистрации; все
остались offline, без Redis presence и без `auth passed` для их ID до 16:10.
**Точная Android-side причина неизвестна:** сервер не видит, какая APK установлена
на каждой VM, дошёл ли registration response полностью и почему клиент не сохранил
или не применил credentials. Это отдельный критерий приёмки после создания строки.

**Сильная, но пока условная гипотеза совместимости:** source APK 1.2.11 требует
`instance_binding_version=2` в ответе до `saveRegistration()`. Живой backend
`3be0e29` не имеет этого поля и может успешно создать строку, но не подтвердить
версию. При установке такого APK до backend v2 клиент отвергнет ответ и не откроет
командный WS; повторная регистрация может обновлять серверные refresh credentials.
Локальный код обеих версий доказывает этот механизм; **нет доказательства, что именно
1.2.11 стоит на трёх удалённых VM**. Другой возможный исход — отказ сети/процесса
после регистрации. Нужны installed version и короткий redacted Android log каждого
кандидата. **Затронуты:** Android `DeviceRegistrationClient`, `AuthTokenStore`,
`SphereWebSocketClient`; backend registration response/refresh; gateway.
**Регрессия/остаточный риск:** 32-way PostgreSQL тест проверяет серверную
идемпотентность, но не совместимость APK со старым backend и не путь register →
persist → WS auth → Redis presence на реальной удалённой VM.

### P0 · F32-29/F32-31: удалённый стрим не выдаёт подтверждённый первый кадр

**Доказательство:** `start_stream`/`viewer_connected` дошли до общего ID, но в
последнем viewer-сеансе backend не получил binary frame; прежняя 18-секундная
выборка получила SPS/PPS без IDR. **Корень потери именно в этом WAN-сеансе не
установлен.** Подтверждённые отдельные source-дефекты — однократный запрос IDR
в старом UI и ранняя потеря команды до готовности Android encoder. Их исправления
есть в PR, но не в работающих frontend/APK. **Затронуты:**
`frontend/components/sphere/DeviceStream.tsx`, Android `StreamingManagerImpl` и
`H264Encoder`, backend `stream_bridge.py`, gateway. **Регрессии:** frontend
reconnect и Android keyframe coordinator прошли; реальный remote IDR, бинарный WS,
Redis forwarding и browser decode — **OPEN**. Отдельно нужно сверить viewer duration:
сеанс 3 секунды не заменяет длительную видео-приёмку.

### P0 · F32-33: опубликованный канал ещё не доставляет исправление на удалённый парк

**Доказательство:** прежний OTA remote receipt вернул `HTTP/2 PROTOCOL_ERROR`/TLS
failure при незавершённой загрузке, хотя ingress отвечал 200. В текущем каталоге
верхняя версия остаётся 1.2.9, а проверенный 1.2.11 — лишь локальный кандидат.
**Fix:** ограниченный retry HTTP/1.1 и проверка SHA-256 есть в исходниках 1.2.11;
реальный remote download/install не принят. **Затронуты:** Android
`OtaUpdateService`, backend `device_ota_recovery.py`, update catalog, внешний маршрут.
**Регрессия:** локальные OTA recovery tests прошли; TLS/provider failure и
совместимость подписи на удалённых APK остаются открыты. Не считать ответ 200 или
создание файла доказательством установленной версии.

### P1 · F32-35 и F32-32: ingress и ресурсы не прошли целевую приёмку

Для named-hostname remote profile source Nginx раньше мог направить WSS upgrade
в redirect vhost; `6788c90` добавил внутренний listener и isolated regression.
Живой gateway не обновлён, а текущий реальный маршрут не сопоставлен с этой веткой;
**не приписываем ей нынешний чёрный экран без handshake evidence**. Затронуты
`infrastructure/nginx/nginx.conf`, `infrastructure/nginx/remote-pilot.conf` и
`tests/deployment/test_remote_gateway_host.py`; реальный named-host upgrade остаётся
открытым. Redis source 2 GiB (`docker-compose.yml`,
`docker-compose.production.yml`, `tests/deployment/test_redis_memory_budget.py`)
выдержал три конкретных persistence прогона, но один достиг ровно лимита, pilot
ещё на 1.5 GiB. 32 stream, slow viewer и одновременные задачи не измерены.

### P1 · диагностика версии и тракта кадра недостаточна для удалённой приёмки

Текущие `DeviceLiveStatus` и записи `devices.meta` не дают проверенного installed
APK version/build для каждой удалённой VM. Сервер видит регистрацию, WS и отдельные
NAL, но не сопоставляет по одному безопасному correlation ID всю цепочку
`registration ACK → сохранение credentials → WS auth → encoder IDR → APK send →
backend receive → browser decode`. Поэтому причину трёх offline-карточек и место
потери нынешнего кадра нельзя доказать только серверными логами. Нужно сохранить
связанные, ограниченные по объёму события с приватными ID/токенами вне публичных
логов; это критерий будущей реализации, **в этом аудите код не менялся**.

### P1 · F32-37: открытый viewer может ждать кадр бесконечно при живых ping

Это **новый дефект именно source frontend**, не доказанная причина отсутствия кадров
в старом запущенном frontend. В
[`DeviceStream.tsx`](../../../frontend/components/sphere/DeviceStream.tsx#L118-L146)
watchdog закрывает сокет только после 30 секунд *без любого серверного сообщения*.
Обработчик `onmessage` обновляет `lastReceived` и обнуляет счётчик reconnect до
разбора типа сообщения. Серверный
[`_viewer_ping_loop`](../../../backend/api/ws/stream/router.py#L174-L188) посылает
`ping` каждые 10 секунд. Поэтому при исправном control WS, но нуле видеокадров,
watchdog не срабатывает, статус остаётся «Ожидание видеокадра…», запрос IDR
продолжается каждые 20 секунд без конечного результата или диагностического
сообщения. Это следует из конкретной пары таймеров 10 < 30 секунд; повторное
подключение при таком условии не начинается.

**Покрытие:** 33 целевых frontend теста повторно прошли 23 сентября; имеющийся
[`reconnect.test.tsx`](../../../frontend/__tests__/stream/reconnect.test.tsx#L94-L98)
проверяет обрыв *без ping*, а тест
[`без первого кадра`](../../../frontend/__tests__/stream/reconnect.test.tsx#L53-L69)
вызывает callback кадра перед проверкой через 40 секунд. Комбинация «ping есть,
кадра нет часами» не покрыта. **Требуемый fix и регрессия:** отдельный deadline
до первого *декодированного* кадра, явное состояние деградации и ограниченный
recovery; тест с непрерывными ping без binary/decoder output. Нельзя сбрасывать
video-deadline по control ping. Даже после этого отдельная приёмка причины
нулевого IDR на удалённом Android обязательна.

## Ревью качества кода 22–23 сентября

Проверены изменённые Android, backend, frontend, Nginx и Compose файлы в диапазоне
`ed3d544^..6788c90`, соответствующие регрессии и текущие CI checks. Это ревью
реального поведения кода и границ теста; отсутствие замечания не является
доказательством готовности каждого компонента к 32 устройствам.

| Изменение | Что подтверждено кодом/тестом | Что пока не подтверждено |
| --- | --- | --- |
| Clone identity v2 и PostgreSQL | [`InstanceBindingReader`](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/InstanceBindingReader.kt#L47-L78) отвергает отсутствие VM serial на x86; [`DeviceRegistrationClient`](../../../android/app/src/main/kotlin/com/sphereplatform/agent/provisioning/DeviceRegistrationClient.kt#L146-L163) требует ACK версии до атомарного сохранения. [`32-way regression`](../../../tests/production/test_clone_registration_migration.py#L40-L66) проверяет уникальность ID, повтор и отклонение устаревшего v1. Это хороший fail-closed контракт и тест серверной конкуренции. | Тест подставляет **32 заведомо различных serial-хеша**; равенство/доступность serial на 20 реальных LDPlayer не измерены. Android test с mock response и backend test новой версии не составляют end-to-end матрицу «новый APK + старый backend». Код действительно откажется сохранять ответ старого backend *после* создания/обновления серверной строки; поэтому backend-first rollout — обязательный, пока не выполненный gate. Для non-x86 источником остаётся Android ID, его устойчивость к битовому клонированию этим тестом не доказана. |
| OTA/recovery | [`OtaUpdateService`](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ota/OtaUpdateService.kt#L102-L168) ограничивает повтор одним HTTP/1.1 запросом, перезаписывает partial APK, проверяет checksum перед install и закрывает вызов при отмене. Тесты моделируют обрыв body, повтор, отмену и cleanup. Recovery grant связан с org/device/digest/сроком, обычный WS/задачи не разрешает. | Mocked body/изолированный HTTP не воспроизводят реальный TLS/HTTP2 маршрут провайдера и не доказывают доставку/установку 1.2.11 на удалённые VM. Старый серверный OTA каталог остаётся 1.2.9. |
| Первый кадр и браузер | Отложенный Android запрос не теряется до готовности encoder; браузер повторяет запрос IDR с ограниченной частотой; 33 целевых теста frontend decoder/reconnect прошли повторно. Декодер требует SPS/PPS и IDR, поэтому старые девять SPS/PPS без IDR не могут дать изображение. | Нативный `MediaCodec` и end-to-end путь APK → gateway → backend → браузер на удалённом LDPlayer не приняты. Регрессии не моделируют ping-only без кадра (F32-37). Даже I-frame interval 1 секунда в конфигурации не доказывает фактическую выдачу encoder под этой VM. |
| Nginx ingress | Regression запускает отдельный edge Nginx с реальным `remote-pilot.conf`, проверяет Host/Upgrade и отсутствие redirect в **модельном upstream**. Исправление слушателя присутствует в настоящем `nginx.conf`. | [`test_remote_gateway_host.py`](../../../tests/deployment/test_remote_gateway_host.py#L29-L80) пишет **синтетический** upstream config с ответом `200`, а не запускает настоящий `nginx.conf` и полный WebSocket handshake. Тест доказывает конфигурационную идею, но не реальный named-host/TLS/tunnel путь текущего pilot; причина нынешнего чёрного экрана по нему не установлена. |
| Redis/Compose | Повышение cgroup ceiling до 2 GiB прошло три изолированных AOF/BGSAVE/restart прогона после OOM на 1.5 GiB; сохранность ключей проверена. | Один из трёх `memory.peak` равен **ровно 2 GiB**, так что запас на 32 streams не доказан. Pilot по-прежнему на 1.5 GiB, нагрузочный профиль и отказоустойчивость не приняты. |

Тесты подтверждают несколько локальных исправлений; **интеграционное качество для
удалённого парка остаётся неудовлетворительным**, потому что актуальные source
версии не совпадают с работающим стендом и не пройдены регистрация → online →
первый кадр → reconnect → OTA на реальных клонах. Это вывод по наблюдению, а не
оценка стиля или числа коммитов. Отдельные PC agent, task orchestration, VPN и
PostgreSQL failover за эти два дня не менялись; их прежние критерии остаются в
[реестре Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md).

## Проверка гипотезы Cloudflare Quick Tunnel / F32-20

**Вердикт:** непригодность нынешнего Quick Tunnel как гарантированного постоянного
канала для Fleet32 подтверждена условиями провайдера; **причина конкретного
отсутствующего IDR пока не установлена**. 23 сентября в новом pilot действительно
работает контейнер `cloudflare-quick` (healthy), не Serveo. Старые
[`architecture.md`](../../architecture.md) и [`deployment.md`](../../deployment.md)
всё ещё описывают Serveo как действующий путь; для текущего стенда их сведения
устарели. Точный WAN URL и приватные логи здесь не публикуются.

Данные проекта уже позволяют сузить место отказа. За прежние 18 секунд сервер
получил по Android WebSocket **9 SPS и 9 PPS, но 0 IDR**; значит, через удалённый
вход прошли хотя бы маленькие бинарные NAL. Отсутствие IDR зафиксировано *до*
Redis и браузерного WebSocket. Один только браузерный декодер или обратный
туннель к viewer не объясняет этот конкретный серверный счётчик. Остаются
MediaCodec, локальный [`sendBinary` с потолком очереди 1 MiB](../../../android/app/src/main/kotlin/com/sphereplatform/agent/ws/SphereWebSocketClient.kt#L384-L390),
WAN/провайдер и входящий tunnel. При переполнении очереди APK явно может
отвергнуть IDR, но remote `sendBinary`/encoder receipts пока не собраны. В другом
сеансе HTTP 200 предшествовал неполному OTA body с HTTP/2 reset/TLS error: это
независимый признак нестабильности передачи **крупного** тела по тому же публичному
маршруту, но не доказательство идентичной причины для WebSocket.

История репозитория поддерживает проверку маршрута, но не заменяет свежую
диагностику: [мартовский commit `b6354db`](https://github.com/RootOne1337/sphere-platform/commit/b6354db4a6ecd1cdbc0262d978d1bb5de63c60d1)
фиксировал idle-разрывы Cloudflare через 5–50 секунд;
[`03c736e`](https://github.com/RootOne1337/sphere-platform/commit/03c736ede7fd274b9c26f3097a312d7b429e8256)
добавил viewer ping каждые 10 секунд и кеширование параметров; проект тогда
временно перешёл на Serveo. Новый трёхсекундный viewer-сеанс слишком короток,
чтобы приписать его закрытие прежнему idle timeout. Пришедшие SPS/PPS не
подтверждают достаточную пропускную способность для IDR.

Проверка документации провайдера 23 сентября:

| Источник | Подтверждённый факт | Вывод для Sphere |
| --- | --- | --- |
| [Cloudflare WebSockets](https://developers.cloudflare.com/network/websockets/) и [Tunnel FAQ](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/) | WebSocket через Tunnel поддерживается; idle-соединения закрываются, heartbeat рекомендован. | Тип `wss://` сам по себе не запрещён. Имеющийся 10-секундный ping решает только idle-сценарий, не потерю больших кадров или тела APK. |
| [Quick Tunnel limits](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/) | TryCloudflare предназначен для тестов, без SLA/uptime, 200 одновременных in-flight requests, затем HTTP 429; SSE не поддерживается. | 20 APK плюс единичный viewer **не достигают** этого лимита сами по себе; нельзя объявлять 429 причиной нынешнего одного чёрного экрана. Для 32 viewer и APK это минимум ~64 долгоживущих WS плюс API, а гарантии задержки/скорости нет. |
| [Cloudflare о доступе из России](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/) | Cloudflare сообщает о систематическом throttling у российских ISP, ориентировочно до **16 КБ на соединение** для затронутого трафика. | Оба наблюдаемых адреса владельца находятся у Ростелекома в России; это сильная гипотеза для обрыва APK и отсутствия более крупных NAL. Документ **не доказывает**, что ограничение действует именно на этот WebSocket и именно сейчас. |
| [Tunnel FAQ: video traffic](https://developers.cloudflare.com/cloudflare-one/faq/cloudflare-tunnels-faq/#large-file-and-streaming-traffic-through-tunnel) | Для public-hostname маршрута на Free/Pro/Business Cloudflare указывает требование отдельного платного сервиса для видео/крупных файлов; у private-network routes условие иное. | Бесплатный публичный Quick Tunnel нельзя закладывать как долгосрочную основу 20–32 видеопотоков. Нужно выбрать допустимый постоянный маршрут и отдельно измерить его; смена провайдера без приёмки сама по себе кодек не исправит. |

В [пользовательском сообщении в issue cloudflared #1282](https://github.com/cloudflare/cloudflared/issues/1282)
описаны долгоживущие WS, которые разрывались только через Tunnel. Это частный
отчёт, не воспроизведение Sphere. Другие сообщения о потере `Upgrade` до origin
тоже нельзя переносить на сеанс, где backend уже получил SPS/PPS.

**Разделяющий эксперимент, ещё не выполнен:** на *одной* удалённой VM с
подтверждённой версией APK держать viewer ≥60 секунд; сопоставить timestamp и
счётчик `encoder IDR produced` → `sendBinary accepted/rejected` и размер/queue →
backend `Binary frame` NAL/size → Redis publish/drop → browser decode. Повторить
на независимом допустимом маршруте при тех же bitrate/устройстве, записать
WS close code, cloudflared errors, 429, задержку и байты. Если IDR не произведён
или rejected локально — это APK/codec/backpressure; accepted в APK, но отсутствует
на backend — WAN/tunnel/ingress; получен backend, но не browser — Redis/viewer
egress/decoder. Только такое сравнение докажет или отвергнет гипотезу туннеля.
Пока не запускать массовый 32-viewer тест и не менять работающий ingress вслепую.

## Условия снятия NO-GO

1. Сверить installed package/version/signature и VM serial **одной** удалённой VM,
   плюс её redacted Android-журнал регистрации; не распространять неподтверждённый
   APK на остальные клоны. Обновить backend с v2 **до** APK v2, затем подтвердить
   полный путь registration ACK → сохранение → WS auth → Redis online и отсутствие
   нового ID при reconnect.
2. Отдельно на этой же VM измерить `viewer_connected`, готовность encoder, факт
   IDR, APK binary send, backend receive и первый browser decode. Повторить после
   закрытия/открытия viewer и сетевого reconnect без ручного вмешательства.
3. Только после canary пройти 5 → 20 → 32 экземпляра: число уникальных online-ID,
   отсутствие eviction/refresh churn, команды, видео, нагрузка PostgreSQL/Redis,
   временный обрыв WAN/backend и возврат, PID/crash buffers, сохранённые receipts.
   Частичный успех и здоровые контейнеры не являются прохождением этих gates.

Публикация APK, замена backend/frontend, запуск пробных запросов с изменением
состояния и повторная регистрация устройств в рамках этого аудита **не выполнялись**.
