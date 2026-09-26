# AUD-146 / F32-35 — Host remote-pilot мог перенаправлять WSS

**23 сентября 2026 · P1 для named-hostname ingress · source fix внесён; remote rollout не проверен.**

[Remote pilot guide](../../operations/REMOTE-PILOT.md) · [Fleet32 readiness](FLEET32-PREFLIGHT.md)

## Влияние и причина

`public-gateway` принимал WSS/HTTPS с внешним Host и проксировал запрос к
`nginx:80`, сохраняя этот Host. Когда он совпадает с `SERVER_HOSTNAME`, Nginx
выбирает production HTTP vhost, который возвращает `301 https://$host$request_uri`.
Браузерный `/ws/stream/{device_id}` не получает ожидаемый WSS upgrade. Команда
`start_stream` при этом может уже дойти до Android, поэтому уведомление захвата не
доказывает, что viewer WebSocket подключился или получил картинку.

Это воспроизводимо для named-hostname remote-pilot конфигурации. Для временного
Quick Tunnel с Host, отличным от `SERVER_HOSTNAME`, этот конкретный redirect не
срабатывает; мы не установили, что именно этот маршрут использует текущая удалённая
станция владельца.

## Доказательство до исправления

Изолированный Docker regression направлял gateway Host `primary.example.test` на
Nginx upstream с тем же поведением HTTP vhost, что в репозитории. До изменения
`remote-pilot.conf` запрос к `/api/v1/updates/latest` ушёл на HTTPS redirect, после
чего изолированная сеть не могла разрешить внешний hostname (`wget: bad address`).
Тест завершился **1 failed**, подтвердив зависимость от Host и порта upstream.
Тестовая сеть была Docker `--internal`; старые stacks не затрагивались.

Основание в исходниках: `infrastructure/nginx/nginx.conf` содержит production
HTTP vhost для `${SERVER_HOSTNAME}` с редиректом и отдельный default HTTP vhost с
`/ws/` proxy; `infrastructure/nginx/remote-pilot.conf` сохраняет внешний Host.

## Исправление

Основной Nginx теперь также слушает порт `8081` только во внутреннем Docker vhost,
который обслуживает обычные `/api/` и `/ws/` маршруты. `public-gateway` проксирует
на `nginx:8081`, так что внешний Host сохраняется, но больше не выбирает HTTP
redirect vhost. Compose не публикует порт 8081 на хосте.

Затронуты: `infrastructure/nginx/nginx.conf`,
`infrastructure/nginx/remote-pilot.conf`,
`tests/deployment/test_remote_gateway_host.py`, этот отчёт и remote-pilot guide.

## Проверка и остаточный риск

Docker regression проверяет три Host-варианта, корректное сохранение Host и
`X-Forwarded-Host`, передачу `Upgrade: websocket` / `Connection: upgrade`, а также
что ни один из четырёх штатных Compose-профилей не публикует порт 8081. До
конфигурационной правки тест падал на redirect; после правки изолированный
`tests/deployment/test_remote_gateway_host.py` прошёл **1/1**.

Исходники PR не изменяют живой Nginx. Необходимо применить этот конфиг в remote
pilot и проверить browser WSS handshake с его фактическим hostname. Эта правка не
исправляет дубликат serial клона и не подтверждает появление IDR/декодированного
кадра; после WebSocket upgrade всё ещё нужна проверка цепочки encoder → backend →
browser decoder.
