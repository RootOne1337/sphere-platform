# Видеопоток и reconnect между backend workers

**13 сентября 2026 · AUD-111 · High operational · baseline и regression сохранены.**

[Аудит](AUDIT-REPORT.md) · [Память очередей](VIDEO-QUEUE-BOUNDS.md) · [Viewer RLS](STREAM-VIEWER-RLS.md)

## Дефекты и доказательства

Android и viewer WebSocket могли попасть в разные Gunicorn workers. Bridge
хранил кадры, viewer и команды только в памяти одного процесса; существовавший
Redis video channel фактически не имел producer/subscriber. `start_stream`
через REST уже исправлен в AUD-108, но это не обеспечивало просмотр.

Кроме того, `unregister_viewer(device_id)` не проверял session ID: старый handler
в `finally` удалял нового viewer. Другой worker мог остановить захват при закрытии
своего viewer, хотя просмотр продолжался в соседнем процессе. При reconnect
Android проверялось только локальное наличие viewer.

Шесть исходных regression cases: **4 failed / 2 passed**. Failures: cross-worker
binary delivery, agent resume, global viewer stop и cleanup старой сессии.
На pilot backend `1310016` оба APK отвечают на shell, но два независимых viewer
connections дают **0 binary frames за 15 секунд каждое**. После baseline REST
stop отправлен обоим. Это конкретная выборка, не оценка вероятности сбоя.

## Исправление

- Отдельный binary Redis Pub/Sub transport с **одной subscription connection
  на worker**. Подписывается только на каналы открытых просмотров; ACK подписки
  предшествует start. Даже local viewer получает кадр одним путём, без дублирования.
- Agent read loop складывает кадры в bounded queue; Redis publication и запись
  браузеру выполняются отдельными задачами. Зависший consumer/Redis не удерживает
  обработку сообщений Android. Queue bounds описаны в AUD-109.
- Session ID передаётся в cleanup; устаревшая сессия не удаляет replacement.
  Viewer controls идут через существующий live command publisher с прежними
  RBAC-проверками и явным сообщением об отсутствии транспорта.
- При закрытии просмотр отписывается. После debounce 2 s Lua атомарно проверяет
  отсутствие video subscribers и публикует stop. Новый subscriber отправляет start
  после ACK; нет разрыва между проверкой отсутствия viewer и stop publication.
- Agent reconnect ищет viewers в Redis. Восстановление video subscription после
  обрыва заново запрашивает capture и codec config/IDR. Продолжающаяся публикация
  кадров без subscribers также останавливает захват после 2 s: это покрывает
  исчезновение viewer worker без его `finally`.
- Idle publisher queues освобождаются после 10 s; на shutdown закрываются
  subscriptions и фоновые задачи. Видео не сохраняется в Redis/offline queue.

Affected: `backend/websocket/{stream_bridge,video_transport,startup}.py`,
`backend/api/ws/{stream,android}/router.py`.

## Проверки

`tests/production/test_stream_video_routing.py` использует настоящие Redis sockets,
отдельные managers/bridges и реальный viewer handler; doubles стоят на границе
Android/browser WebSocket. Проверяются exact binary bytes с не-UTF-8 payload,
отсутствие duplicate/cross-device delivery, replacement, два viewer workers,
agent reconnect, реальный разрыв собственного Redis pool, vanished subscriber,
медленный browser, медленный video publisher, independent commands и RBAC.

**211 passed**: streaming regressions, viewer restricted PostgreSQL, REST controls,
agent authorization и полный `tests/test_ws`. Один существующий deprecation warning.
[Машиночитаемые результаты](evidence/stream-video-routing-summary.json).

```sh
SPHERE_RUN_INTEGRATION=1 python -m pytest tests/production/test_stream_video_routing.py tests/production/test_stream_viewer_tenant_runtime.py tests/production/test_stream_control_routing.py tests/production/test_agent_authorization.py tests/test_ws -q
```

Ранний contention test имел 1 s timeout сразу после запуска command router,
который сам ждёт до 1 s первой подписки. Fixture теперь подтверждает настоящую
warm-up delivery до измерения contention; поздний вызов не выдаётся за дефект fix.

## Границы текущей приёмки

Backend **f8c66b9** установлен, все его required CI checks pass. Новый pilot,
OTA catalog и APK hash сохранены. Первый post-deploy artifact GET по прежнему
HTTP connection завершился timeout и вызвал rollback только нового backend.
Повторная установка с fresh-connection read-only проверкой прошла; during-rollback
WebSocket 502 не засчитан как after-fix.

Шесть native connections после исправления получают SPS/PPS/IDR; первый binary
frame за **1.328–1.703 s**. В настоящем браузере декодированы оба экрана. Однако
**стабильная приёмка отклонена**: APK 1.2.4 падает в native ImageReader copy на
обоих Android. Владелец подтвердил crash dialogs. Проверка 45 frames/15 s не прошла;
редкие кадры нельзя объяснять только неподвижным экраном, поскольку crash доказан.
Эта первоначальная неуспешная проверка сохранена как baseline.
Далее [AUD-112](ANDROID-CAPTURE-LIFECYCLE.md) установил APK **343c6e8 / 1.2.5**
через OTA на оба Android: 10 native capture lifecycle trials прошли с неизменными
PID и без новых crash records. [AUD-113](STREAM-IDLE-RECOVERY.md) устраняет
незапрошенный restart на статичном экране; текущий backend **fa099aa**.
RTT/fleet load, длительный soak и сеть между городами остаются отдельной приёмкой.

GET stream status пока использует локальную статистику; его cross-worker смысл
ещё требует исправления. Один viewer на device внутри worker сохраняется;
несколько viewer workers допускаются. Pub/Sub не гарантирует доставку при outage:
после восстановления запрашиваются свежие кадры. Redis сам остаётся зависимостью,
HA/failover Redis и полный network partition не подтверждены этим connection-loss test.
