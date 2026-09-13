# Статичный экран вызывал повторный запуск захвата

**14 сентября 2026 · AUD-113 · High operational · воспроизведено с настоящим Redis.**

[Аудит](AUDIT-REPORT.md) · [Видео между workers](STREAM-VIDEO-ROUTING.md) ·
[Native crash APK](ANDROID-CAPTURE-LIFECYCLE.md)

## Дефект и причина

После AUD-111 видеоподписка использовала `PubSub.listen()` с production-пулом,
у которого `socket_timeout=5` и `retry_on_timeout=True`. Пауза в кадрах более
пяти секунд приводила к внутреннему reconnect redis-py и повторному subscribe.
Обработчик восстановления отправлял `start_stream` и `viewer_connected`.
На неподвижном экране ImageReader может не давать новых кадров: исправный
захват поэтому перезапускался без обрыва Redis, APK или зрительского WebSocket.

На APK 1.2.5 PID второго Android оставался 386, а журнал содержал повторные
start в 21:41:40, 21:41:51, 21:41:57, 21:42:05 и далее по часам Android.
На старой 1.2.4 повторный lifecycle дополнительно подвергал APK гонке AUD-112.
Это два разных дефекта: исправление native memory lifetime не устраняет
необоснованные серверные команды перезапуска.

## Доказательство, fix и regression

`test_static_screen_does_not_restart_capture_after_redis_read_timeout` использует
настоящие Redis sockets, отдельные worker registries и production socket settings.
После первого кадра дисплей остаётся статичным 6.5 s. **До исправления** тест
получает незапрошенные `start_stream` и `viewer_connected` через 5.006 s и падает.
Прежняя fixture без socket timeout этот сценарий не покрывала.

В `backend/websocket/video_transport.py` чтение заменено на
`get_message(timeout=1.0)`: обычная пауза возвращает `None`, сохраняя подписку.
При фактическом разрыве соединения повторная подписка по-прежнему восстанавливает
захват. Это одно ожидание на worker, не отдельный polling timer на каждое устройство.

**После: 212 tests pass / 36.39 s**, включая idle regression, фактический разрыв
Redis connection pool с восстановлением кадров, slow browser/publisher,
viewer lifecycle, restricted PostgreSQL и авторизацию агентов.
Один существующий FastAPI deprecation warning. [JUnit summary](evidence/stream-idle-summary.json).

```sh
SPHERE_RUN_INTEGRATION=1 python -m pytest tests/production/test_stream_video_routing.py tests/production/test_stream_viewer_tenant_runtime.py tests/production/test_stream_control_routing.py tests/production/test_agent_authorization.py tests/test_ws -q
```

## Границы

Backend **fa099aa**: все required CI checks passed, [workflow/job archive](evidence/ci-fa099aa-summary.json).
Установлен только в новом pilot; OTA catalog/hash и старые
Sphere containers сохранены. Оба Android на APK 1.2.5 одновременно прошли **75 s**
настоящего WSS просмотра: по **одной** start-команде за всё окно, 22/18 кадров
со статичного экрана, SPS/PPS/IDR, **12/12 опросов обоих PID/online и 24/24 echo**.
PID 31803 / 386 сохранились; после закрытия зрителей projection освободилась
автоматически. Это короткая native regression, а не многочасовой farming soak.
Реальный сетевой разрыв по-прежнему может потребовать перезапуска захвата.
Этот тест не подтверждает Redis HA, fleet capacity или непрерывную работу фермы.
