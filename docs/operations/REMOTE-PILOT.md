# Удалённый пилот: исходящий туннель и реальные проверки

**12 сентября 2026 · один временный ingress проверен; постоянный резерв не готов.**

[Локальный стенд и APK](LOCAL-PILOT.md) · [План discovery](../architecture/ANDROID-BOOTSTRAP-DISCOVERY.md) ·
[Готовность](READINESS.md)

## Назначение профиля

[Remote overlay](../../docker-compose.remote-pilot.yml) добавляется после base,
full и local-pilot. Отдельный `public-gateway` проксирует только новую установку;
connector открывает исходящее соединение. Дополнительные host ports не публикуются,
открывать порт на домашнем маршрутизаторе не требуется. PostgreSQL, Redis, MinIO
console и n8n остаются в прежних пределах локального профиля.

Gateway отдаёт `/api/v1/config/agent` из отдельного routes-only JSON, включая
варианты нормализованного пути/query, и закрывает `/metrics`. Публичный документ
не должен содержать `api_key`, `enrollment_api_key` или tokens. Закрытый enrollment
config backend находится в другом каталоге. Авторизация API/устройств остаётся
включённой. Публичный gateway не заменяет production ingress/security rollout.

| Profile | Фактический результат |
| --- | --- |
| `quick` | HTTPS/WSS, enrollment, heartbeat, commands и gateway restart проверены; URL временный |
| `cloudflare` | Рецепт named connector и isolated runtime credential mount; постоянный DNS route не создан: текущие credentials не дают доступа к DNS-зоне |
| `serveo` | Рецепт autossh и отдельный secret/volume; SSH доступен, но provider требует регистрацию ключа; действующий публичный маршрут не получен |

Не включайте все profiles как якобы готовый резерв. Для текущего стенда включён
только `quick`; два постоянных profiles — подготовка для следующего этапа.

Реализация signed APK (`f61cd5a`, итоговый APK `0f1410e`) прошла миграцию через GitHub
при недоступном исходном ingress и его config mirror; затем вернулся без
переустановки. [Native evidence и границы](../audits/2026-09-05/SIGNED-DISCOVERY-NATIVE.md).
Тестовый второй connector удалён; это не работающий постоянный WAN резерв.

## Подготовка другой изолированной установки

Сначала подготовьте local-pilot schema/admin/enrollment по [основному guide](LOCAL-PILOT.md).
Для remote overlay нужны `PILOT_BROWSER_URL`, `PILOT_REMOTE_PRIMARY` и
`PILOT_REMOTE_FALLBACK`. Пока есть один путь, одинаковые primary/fallback допустимы
только как Compose-параметры; это **не два маршрута**, а в APK/config fallback
должен оставаться отсутствующим.

Создайте `.local-pilot/remote/public/agent.json` из
[публичного шаблона](../../agent-config/templates/public-discovery.json): замените
installation ID и адреса на собственные. Этот документ не является доверенным
подписанным manifest и используется только legacy APK. Новый signed APK принимает
`/bootstrap/agent.signed.json` по [отдельному контракту](../architecture/ANDROID-SIGNED-DISCOVERY.md).
Шаблон содержит неработающие example-адреса, а не готовую конфигурацию.

Для named Cloudflare profile нужен собственный `.local-pilot/remote/cloudflare/config.yml`,
его tunnel credentials JSON и заранее созданный DNS route. Config задаёт tunnel ID,
`credentials-file`, `metrics: 0.0.0.0:20241`, ingress для собственного hostname к
`http://public-gateway:8080` и завершающий `http_status:404`. Account-wide `cert.pem`
не монтируется в runtime connector. [Порядок Cloudflare](https://developers.cloudflare.com/tunnel/features/locally-managed-tunnels/create-local-tunnel/).

Для Serveo profile нужен зарегистрированный **отдельный** SSH key в
`PILOT_SSH_KEY_FILE`, собственный `PILOT_SSH_SUBDOMAIN` и доступный SSH port.
Secret копируется в собственный volume с POSIX mode 600; контейнер использует
autossh и keepalive. Существующие туннели других установок не переиспользуются.
Фактические ограничения регистрации проверяйте у [провайдера](https://serveo.net/docs/).

Quick Tunnel выдаёт URL после запуска connector. Для нового адреса необходимо
согласовать public JSON, backend public URL/CORS и выпустить новый signed version.
В signed APK management адрес менять или пересобирать APK не требуется. Автоматическая
публикация нового URL после connector restart включена через
[host publisher](DISCOVERY-PUBLISHER.md) на новом стенде; Windows logon требуется.
Для другой установки он готовится отдельно. GitHub rollout остаётся медленным; сохранённый
Quick Tunnel APK нельзя раздавать большому парку как постоянную сборку.
[Официальные ограничения](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).

## Проверка протокола и отказа

Скрипт [verify_remote_pilot.py](../../scripts/verify_remote_pilot.py) запускается
только с адресом подготовленного владельцем стенда. Он проверяет public config,
выполняет operator login, создаёт **одно синтетическое устройство**, проходит
настоящие WSS auth/heartbeat/reconnect и удаляет созданное устройство в cleanup.
Credentials читаются из локальных файлов, не передаются в аргументах командной строки.

```powershell
python scripts/verify_remote_pilot.py --base-url https://YOUR-PILOT-HOST `
  --installation-id YOUR-INSTALLATION-UUID `
  --credentials-file .local-pilot/operator-credentials.json `
  --enrollment-config .local-pilot/agent-config/environments/development.json `
  --output .local-pilot/remote/protocol-acceptance.json
```

Дополнительный `--restart-gateway-project sphere-pilot-...` явно включает fault
injection: скрипт находит единственный `public-gateway` по точным Compose labels,
перезапускает только его и проверяет повторный WSS auth. Connector не рестартует.
Это protocol probe; установка/исполнение Android APK подтверждаются отдельно.

## Подтверждённый native результат 12 сентября

На `emulator-5554` установлен пакет `com.sphereplatform.agent.pilot.debug` из
`c0c0783` (предыдущая проверка); SHA-256 установленного `base.apk` совпадает с опубликованным локальным
файлом. После gateway restart этот APK восстановил сессию за **9.03 s**, включая
время команды Docker restart: тот же PID/device ID, новая Redis WS session,
**0 повторных регистраций**, без UI/ADB reconnect. Это одно измерение, не SLA.

Backend `a22fb54` исправляет [AUD-92](../audits/2026-09-05/INTERACTIVE-COMMAND-ROUTING.md).
После подтверждённого возврата APK **12 из 12** отдельных HTTPS shell `echo` получили
ожидаемый stdout; 735–1266 ms в этом прогоне, включая весь HTTP round trip и shell.
Во время предшествующего backend restart первый запрос получил 503 до возврата
подписчика, следующие 11 прошли. Переходная недоступность сохранена в evidence;
она не заменена ложным ответом success и не скрыта автоматическим повтором команды.

Срез idle: public gateway около 34 MiB, quick connector около 25 MiB.
Это моментальная выборка контейнеров, не Android/fleet benchmark. Стриминг, DAG из
веба, VPN, physical devices и массовый reconnect ещё не приняты.
