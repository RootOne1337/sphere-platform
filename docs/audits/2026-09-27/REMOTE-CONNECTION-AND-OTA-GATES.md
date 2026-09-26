# Remote WSS и OTA: срез перед расширением pilot · 27 сентября 2026

**Область:** только изолированная установка `sphere-pilot-20260911`.
Legacy Docker-проекты и удалённые Android-устройства не переустанавливались.
Сырые журналы, идентификаторы сессий и параметры доступа хранятся только в
ignored `.local-pilot/rollout/ota-ui-20260927/`.

## Решение для оператора

**Fleet32 и массовая OTA пока NO-GO.** На проверке 26 сентября около 19:05 UTC
API вернул 16 зарегистрированных записей: 12 `online`, 4 `offline`. Эти значения
являются моментальным снимком, а не длительным uptime. Десять удалённых online
устройств всё ещё сообщили `1.2.22-dev / 10222`; локальные `auto-ph-010` и
`auto-ph-011` имели 10228 и 10229 соответственно. Уже после снимка локальный
`auto-ph-011` получил canary 10230; установку и OFF/ON проверили отдельно.

| Приоритет | Дефект / ограничение | Доказательство | Текущее действие |
| --- | --- | --- | --- |
| P1 | Remote WSS закрывается, устройство колеблется между состояниями | PH022/PH025: по 20 завершённых сеансов за 20 минут на public gateway; все HTTP 101, большинство длиной ровно 40 или 60 секунд; backend close 1005. У локальных PH010/PH011 за тот же интервал не было завершившихся WSS-сеансов | Требуется контролируемый A/B ingress одного remote canary с client-side close/failure и gateway timing; Cloudflare как единственная причина **не доказан** |
| P1 | Резервный ingress неработоспособен | Primary `/readyz` → 200; подписанный fallback LocalTunnel → 502. `sphere-pilot-alt-ingress-20260926` запущен и из него origin gateway отвечает 200, но у контейнера нет healthcheck и restart policy | Не считать опубликованный fallback отказоустойчивым; восстановить управляемый второй ingress и принять health/WSS/command/frame на одном canary |
| P1 | Дистанционная OTA не доказана | `android/dev` каталог отдаёт только 10209, а 10228 лежит в `android-canary/dev`; удалённые APK остаются на 10222. PH025 после двух контролируемых адресных попыток не дал post-install receipt | Не открывать общий канал до адресной установки с PackageManager, SHA и свежим heartbeat |
| P1 | Обычная OTA-квитанция повторяется | За 20 минут backend записал 37 `ota_recovery_receipt_unrecognized` для remote PH025 и 40 для local PH010; исходник Android помечает все `OTA_UPDATE` как recovery, сервер признаёт только квитанцию существующего recovery grant | Отдельный протокольный fix после regression на normal/recovery/duplicate/foreign receipts; не ACK неизвестное сообщение вслепую |
| P2 | Веб скрывал canary-релизы | `/updates` запрашивал только `android`; backend хранит 12 релизов, включая `android-canary` 10228 | Исправлено `213402b`, regression до/после; pilot frontend развёрнут из `8fef5eb` |

У PH025 за тот же интервал backend записал 21 успешную аутентификацию и 21
`Agent heartbeat established`; у PH022 — 20 и 20. Событий `Agent heartbeat
timeout` для этих устройств в срезе нет. Следовательно, каждый новый сокет
хотя бы раз доставлял `ping`/`pong`; проблема возникает **после** установления
живой сессии. Код `1005` сообщает об отсутствии штатного close-frame, но сам
по себе не указывает, какая сторона первой оборвала TCP/WSS. Счётчики gateway
собраны по завершённым сеансам; отсутствие локальных строк за окно также не
доказывает, что локальный Android шёл в обход gateway — его длинный сокет мог
оставаться открытым и поэтому не попасть в access log.

### Что именно удалось и не удалось проверить в вебе

После замены **только** pilot frontend образа из `8fef5eb` контейнер стал healthy,
`/updates` и `/readyz` вернули 200; все остальные контейнеры и SHA файла каталога
сохранились. Авторизованный read-only API `/updates/` вернул 12 релизов, среди
них canary 10228. Frontend regression проверил default запрос без platform filter
и видимость canary; полные 39 suites / 297 tests, type-check и production build
прошли. CLI-браузер на этой Windows-сессии завершился при запуске Chrome, поэтому
фактический DOM в браузере оператора здесь **не принят**; HTTP 200 и Jest не
подменяют эту проверку.

### Почему новый APK пока не приходит автоматически

`UpdateCheckWorker` проверяет каталог при старте/восстановленном management
соединении с jitter до 120 секунд и периодически каждые шесть часов при сети.
Его запрос — `platform=android&flavor=dev`. На pilot этот канал всё ещё указывает
на **10209**, поэтому версия 10222 правомерно получает `update_available=false`.
Canary 10228 доступен через отдельный platform и не выбирается штатным worker.
Регистрация релиза в каталоге не загружает APK в GitHub или на Android.

Второй репозиторий `sphere-agent-config` содержит **конфигурацию обнаружения
маршрутов, а не APK**. Pilot APK использует подписанный документ v25 из ветки
`codex/pilot-bootstrap-20260911`; локальный и публичный signed manifest совпали.
`main` второго репозитория всё ещё содержит исторический Serveo v2 и не является
источником текущей pilot-сборки. Подписанный адрес fallback может устареть:
наличие корректной подписи не означает health доступного туннеля.

### Fix: проверка OTA-каталога через сохранённые маршруты

**Root cause.** Worker использовал только `getServerUrl()`. Если сохранённый
активный fallback возвращал 502 или TCP reset, он выдавал `Result.retry()` без
попытки обращения к доверенному primary, хотя `AuthTokenStore` уже хранил оба
маршрута, а скачивание APK в 10229 уже разрешало оба HTTPS origin.

**Reproduction → fix → regression.** Тест с активным fallback (502) и рабочим
primary сначала падал: было одно обращение и `retry`. В `0e259bc` worker
перебирает уникальные сохранённые management routes, не меняя владение активным
WebSocket-маршрутом. На 502 или IOException он пробует следующий маршрут;
401/403/429 прекращают перебор и возвращают WorkManager retry, чтобы не
рассылать отклонённый токен/лимит по другим адресам. Тесты проверяют 502,
connection reset, 401 и запуск OTA ровно один раз после удачного каталога.
Обе полные flavor suites прошли **683 теста каждая**, 0 failures/errors,
1 штатный skip; `lintDevDebug`, `assembleDevDebug` и `assembleEnterpriseDebug`
прошли. Следует отдельно проверить refresh истёкшего токена при смене маршрута:
этот fix не утверждает, что весь auth failover закрыт.

**Canary runtime.** Source-pinned pilot debug APK `1.2.30-dev / 10230` из
`0e259bc` имеет SHA-256
`525108a0e07962e8b76bb1aab33efa97f757682bda3f0f9d8fa21caeb2462498`,
тот же signer/package и signed discovery v25; адреса управления не зашиты.
Только `emulator-5554` установлен этим APK; установленный `base.apk` совпал по
SHA. После полного LDPlayer quit/launch без открытия Sphere Activity появились
новый Android boot ID, persisted boot job, PID `2224`, foreground service и
server heartbeat `online`/10230 в `19:22:26Z`, без нового crash Sphere.
Это доказывает автономный запуск на одном локальном Android 9, **не на удалённых
клонах и не на Android 14+**. Кандидат 10230 не опубликован в OTA-каталоге или
GitHub Releases и не установлен на remote.

## Следующий доказательный шаг

1. Поднять и постоянно проверять независимый второй ingress, не меняя старый
   Docker; провести на одном удалённом Android сравнительные WSS-сеансы с
   замером Android `onFailure`/close, gateway duration, backend heartbeat и
   command receipt. Внешний Quick Tunnel или LocalTunnel без health недостаточен.
2. Исправить normal OTA-result ACK по долговременному протоколу: сохранить
   идентичность выданной операции, проверить tenant/device/command/status,
   записать bounded receipt, только затем ACK. Исторические 10222-квитанции
   требуют отдельной миграционной стратегии; неизвестный recovery grant не
   следует подтверждать без проверки.
3. На одном remote canary подтвердить delivery/download/SHA/PackageInstaller,
   установленный versionCode и heartbeat после перезапуска APK. Только после
   этого открыть общий `android/dev` канал по ступеням 1→4→8→16→32 с rollback.
4. Проверить moving frames независимо: encoder на Android, исходящий счётчик,
   ingress/backend, первый IDR/P, декодирование в браузере и поведение после
   40/60-секундного reconnect. `online` не является доказательством видео.

[Приёмка boot и прежней OTA](../2026-09-26/ANDROID-COLD-BOOT-AND-OTA-CANARY.md) ·
[Подробный remote control path](../2026-09-26/REMOTE-CONTROL-PATH-DIAGNOSIS.md) ·
[План Fleet32](../2026-09-20/FLEET32-PREFLIGHT.md)
