# AUD-160 · адресная смена ingress для диагностики удалённого видеопотока

**23 сентября 2026 · APK candidate 1.2.12-dev / 10212 · Fleet32: NO-GO.**

[Предыдущая live-приёмка](REMOTE-FLEET-LIVE-FOLLOWUP.md) ·
[Наблюдаемость fleet и media path](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md)

## Вывод

В исходниках найден и исправлен дефект адресного переключения маршрута. Команда
`UPDATE_CONFIG` раньше сохраняла только `server_url`, стирала резервный адрес и не
перезапускала уже установленный WebSocket. Это мешало перевести один работающий
APK на независимый вход для A/B-проверки. Исправление не является доказательством,
что именно Cloudflare отбрасывает видеокадры: реальная граница потери пока не
локализована.

Удалённый PH006 ранее трижды подключался и получал команды старта/keyframe, однако
сервер за сессии 18–42 секунды видел SPS/PPS без IDR или P-frame. Локальный
`auto-ph-000` передал через тот же Quick Tunnel IDR размером до 40,351 байта и три
P-frame. Сравнение не исключает маршрут или ISP для другой квартиры, но исключает
вывод «Quick Tunnel всегда режет все кадры больше 16 KiB».

Cloudflare сообщает о систематическом throttling Cloudflare-трафика некоторыми
провайдерами в России примерно до 16 KiB на соединение и указывает, что это
ограничение на стороне ISP, а не ошибка настройки Cloudflare. Quick Tunnel отдельно
предназначен для разработки и не имеет SLA. Это делает маршрутную гипотезу
правдоподобной, но не заменяет сравнение одного удалённого APK по двум ingress.
[Cloudflare: доступность в России](https://developers.cloudflare.com/support/troubleshooting/general-troubleshooting/service-disruption/) ·
[Cloudflare Quick Tunnels](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## Дефект и минимальное исправление

До исправления `CommandDispatcher` обрабатывал обновление так:

```kotlin
if (serverUrl != null) authStore.saveServerUrl(serverUrl)
```

`AuthTokenStore.saveServerUrl()` записывает адрес одновременно как active и primary
и удаляет `fallback_server_url`. Команда возвращала `updated=true`, но не сообщала
WebSocket-клиенту, что уже аутентифицированный сокет продолжал работать через старый
host. При этом общий `ConfigWatchdog` специально сохраняет активную сессию при
обновлении discovery, чтобы не разрывать здоровое соединение. В результате не было
безопасного адресного способа применить новый primary к одному canary-устройству.

Теперь команда читает необязательный `fallback_server_url`. При наличии обоих
адресов `saveServerRoutes(primary, fallback)` сохраняет маршрутную пару одним
операционным действием. Если порядок/состав адресов изменился, APK сначала отдаёт
обычный terminal `completed` receipt, затем через 750 ms закрывает только собственный
сокет и открывает reconnect-loop. Явная операторская смена маршрута обходит обычный
пятиисекундный reconnect debounce; автоматические повторные уведомления о сети
по-прежнему проходят debounce. Если адреса не изменились, сокет не закрывается.
После неудачи нового primary существующий reconnect-loop пробует fallback.

Изменены: `CommandDispatcher.kt`, `SphereWebSocketClient.kt`,
`CommandDeliveryTest.kt`, `WebSocketLifecycleTest.kt`, `android/version.properties`,
`CHANGELOG.md` и архитектурный реестр finding-ов.

## Воспроизведение и регрессии

Новый `CommandDeliveryTest.discoveredRouteUpdateKeepsFallbackAndReconnectsAfterAcknowledgement`
сначала запускался на исходном коде и падал: `UPDATE_CONFIG` не вызывал
`saveServerRoutes(primary, fallback)`. Это воспроизводило отсутствие резерва на
уровне production-dispatcher, а не только изолированного helper-а. После исправления
тест проверяет сохранение обоих адресов, отсутствие немедленного reconnect и порядок:
terminal command receipt предшествует принудительному reconnect.

`CommandDeliveryTest.unchangedRouteUpdateDoesNotDisconnectHealthySession` защищает
от ненужного разрыва при повторной доставке того же конфига.
`WebSocketLifecycleTest.explicitRouteSwitchCanBypassReconnectDebounce` проверяет,
что явная смена маршрута не теряется из-за недавнего обычного reconnect. Существующие
`SavedRouteFailoverTest` проверяют, что после отказа primary клиент использует
сохранённый fallback и принимает сессию только после корректного `auth_ok`.

Полная Android unit matrix и debug package-сборки прошли на исходнике версии
10212: **619 тестов `devDebug`**, **619 тестов `enterpriseDebug`**, 0 failures,
0 errors; в каждом flavor один skipped test, а не failure. Это
`ConfigRecoveryTest.public discovery of baked route retains locally provisioned
enrollment credential`: тест намеренно требует непустой `DEFAULT_SERVER_URL`, а
оба debug flavor собираются с пустым baked URL и поэтому пропускают только эту
проверку discovery. Новые regressions
вошли в оба flavor. Сборка debug APK обоих flavor завершилась успешно; свежая
пилотная подпись, release/minify сборка, OTA и remote runtime остаются отдельными
воротами. Все логи сборки и
локальные идентификаторы остаются в `.local-pilot`; в Git попадают только
агрегированные результаты.

## Что ещё не проверено

- Версия 1.2.12-dev / 10212 является исходной release-candidate версией. Подписанный
  пилотный APK, OTA-публикация и установка на PH006 пока не подтверждены.
- Backend pilot на момент среза работает из `2f8b6c2`, который не принимает новые
  Android stream snapshots из `b3375f5`. APK-кандидат 1.2.11/10211 собран из более
  раннего commit и также не содержит этих счётчиков.
- В текущем signed discovery опубликован только Quick Tunnel; два сохранённых
  одинаковых Compose URL не являются двумя ingress.
- Ни один независимый туннель сейчас не является стабильным production fallback.
  [localhost.run](https://localhost.run/docs/http-tunnels/) предоставляет бесплатные
  случайные адреса и HTTPS для тестов; стабильный custom domain/приоритетная доля
  bandwidth платные. Поэтому такой адрес годится для ограниченного A/B, но не для
  обещания enterprise uptime.
- Удалённый stream остаётся неприёмочным, пока на одном и том же удалённом APK не
  записаны обе серии: encoder/OkHttp telemetry и backend binary receipts, включая
  свежие IDR/P, а браузер не подтвердит первый decoded frame.

## Следующие gates

1. Прогнать focused regressions и полный Android unit matrix в `devDebug` и
   `enterpriseDebug`; собрать и проверить подпись, package, versionCode и SHA
   подписанного пилотного APK 1.2.12-dev.
2. Обновить только backend нового `sphere-pilot-20260911` до текущего PR head, чтобы
   получить stream telemetry. Не менять старый Compose/tunnel и не публиковать OTA
   на весь парк.
3. Проверить независимый временный ingress на HTTPS, WSS auth, API и непрерывной
   передаче binary frame. В signed config/OTA catalog ничего не менять до этих checks.
4. Перевести ровно один удалённый canary на alternate primary с Quick Tunnel в
   fallback. Сравнить на том же устройстве длительность, binary NAL types, encoder
   output, OkHttp queue accepted/rejected, WebSocket reconnects и browser decode.
5. Если кадры появляются только на alternate, зафиксировать подтверждённую причину
   маршрута и выбрать долгоживущий endpoint. Если encoder output нулевой на обоих
   входах, локализовать MediaProjection/MediaCodec/ресурсную границу; если queue
   принимает кадры, а backend их не видит, исследовать uplink/transport.

До завершения этих gates массовый тест на 20–32 эмуляторах остаётся **NO-GO**.
