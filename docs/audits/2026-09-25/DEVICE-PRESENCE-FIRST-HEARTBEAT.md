# AUD-173 · Устройство считалось Online до первого heartbeat

**Дата:** 25 сентября 2026 · **Severity:** P2 · **Статус:** source fix и regressions прошли; pilot rollout ожидает CI и canary.

[Readiness](../../operations/READINESS.md) · [Local pilot](../../operations/LOCAL-PILOT.md) · [Fleet operations](../../architecture/FLEET-OPERATIONS-AND-OBSERVABILITY.md) · [Документация](../../README.md)

## Воздействие

Backend подтверждал identity устройства через WebSocket, отправлял `auth_ok` и сразу записывал `online`. Первый application heartbeat приходил позже: ping отправляется каждые 30 секунд, а соединение закрывается после 45 секунд без pong. Между этими событиями сервер и UI могли сообщать, что устройство онлайн, хотя APK ещё не доказал, что способен отвечать на heartbeat. Оператору было труднее отличить готовый канал от зависшего подключения.

Этот дефект объясняет только преждевременный online presence. Он **не объясняет** отсутствие видеокадров у удалённых устройств и не доказывает неисправность Cloudflare или другого ingress.

## Доказательство и воспроизведение

В `backend/api/ws/android/router.py` успешная аутентификация публиковала новую сессию и записывала `DeviceLiveStatus(status="online")` до первого pong. `HeartbeatManager.handle_pong()` устанавливает `last_heartbeat` только после получения pong. Поэтому для новой сессии существовало состояние `online` с `last_heartbeat=None`.

Перед исправлением регрессия `test_new_android_session_is_connecting_until_first_heartbeat_pong` завершалась несоответствием: фактический статус был `online`, ожидаемый — `connecting`. Router-level test проходит через реальный ASGI/WebSocket handler и SQL authentication на отдельной loopback PostgreSQL, а status cache является spy/mock для проверки записанного состояния. Отдельный `test_first_pong_promotes_connecting_presence_to_online` проверяет переход через Redis-backed cache. Оба набора изолированы от pilot database. В текущей реализации новые сессии остаются `connecting`, а отдельная проверка подтверждает переход в `online` только после первого pong.

Последний read-only pilot aggregate на 25 сентября, 14:30:39 по Екатеринбургу, содержал 10 активных DB-записей: Redis имел 5 записей `online`, 1 `offline` и 4 без status key; только 3 online-записи имели heartbeat не старше 90 секунд, у двух online-записей heartbeat timestamp отсутствовал. APK version code был известен у одной записи. Aggregate не сохраняет идентификатор WebSocket-сессии для каждого результата, поэтому нельзя приписать именно эти две строки к конкретному запуску старого обработчика. Это измерение подтверждает низкую наблюдаемость состояния, а не доказывает причинность для каждой записи.

## Исправление

- Новая аутентифицированная Android-сессия получает статус `connecting`.
- Первый pong переводит её в `online` и устанавливает `last_heartbeat`; обработчик продолжает защищать presence от записи устаревшей заменённой сессии.
- Fleet summary/API возвращают отдельное число `connecting`, вместо того чтобы скрывать это состояние в `offline`.
- Dashboard, badge и список потоков показывают Connecting отдельно от Online/Offline.

Изменённые файлы: `backend/api/ws/android/router.py`, `backend/services/device_status_cache.py`, `backend/schemas/device_status.py`, `backend/api/v1/devices/router.py`, `frontend/app/(dashboard)/dashboard/page.tsx`, `frontend/app/(dashboard)/stream/page.tsx`, `frontend/components/sphere/DeviceStatusBadge.tsx`, `frontend/lib/hooks/useDevices.ts` и соответствующие тесты под `tests/` и `frontend/__tests__/devices/`.

## Проверки

- До fix: новая тестовая сессия показывала `online` без `last_heartbeat`; регрессия падала на этом условии.
- После fix: backend/device-presence integration subset — **53 passed**, 2 предупреждения; используются отдельные loopback PostgreSQL и Redis.
- Frontend: тесты Connecting badge и статуса первого кадра — **4 passed**; `npm run type-check` прошёл.
- Ruff для изменённых backend/tests файлов и `git diff --check` прошли.
- Полный GitHub CI должен повторно пройти на commit с этим исправлением; CI предшествующего head `384759c` прошёл, но не включает этот source fix.

## Остаточный риск и rollout gate

Изменение пока не развёрнуто: локальный pilot остаётся на backend/frontend image `b491a66`. Оно не проверялось на удалённых устройствах и не меняет APK. После зелёного CI нужен отдельный pilot deploy, проверка `/status/fleet` (`connecting` → `online` после pong), а затем canary, где отдельно сверяются ID устройства, свежий heartbeat, результат команды и реально декодированный кадр. Fleet32 и общая OTA остаются **NO-GO** до прохождения этих проверок.
