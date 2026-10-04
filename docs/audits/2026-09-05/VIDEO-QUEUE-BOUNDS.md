# Ограничение памяти видеопотока

**13 сентября 2026 · AUD-109 · High operational · regression до/после.**

## Дефект и доказательство

`VideoStreamQueue.put()` обходил `MAX_SIZE=50`, если очередь содержала только
IDR/SPS/PPS и приходил ещё один ключевой кадр. Повтор production-класса:
200 ключевых кадров без consumer → размер **200**, несмотря на лимит 50.
При зависшем браузере это позволяло памяти backend расти без ограничения.

## Исправление

Очередь ограничена одновременно **50 кадрами и 8 MiB payload**. Некритичные
кадры удаляются первыми; если очередь состоит из ключевых, вытесняется самый
старый. Один кадр сверх byte limit отклоняется. Drop ratio использует число
всех поступивших кадров, поэтому остаётся в диапазоне 0–1. Ожидание через Event
заменяет периодический опрос; byte accounting обновляется при каждом удалении.

Affected: `backend/websocket/video_queue.py`.
Regression: `tests/test_ws/test_video_queue_limits.py` — critical flood,
large frames, oversize rejection, drain и сброс счётчика байтов/Event.
До: один regression failed; после: оба новых сценария и существующие queue tests pass.

```sh
python -m pytest tests/test_ws/test_video_queue.py tests/test_ws/test_video_queue_limits.py -q
```

## Residual risk

Это предел payload одной очереди, без Python object/transport overhead;
совокупная память зависит от числа одновременно открытых потоков. Отбрасывание
кадров может требовать нового IDR для восстановления декодера. Fleet capacity,
нагрузка на Redis и длительный просмотр отдельно измеряются; этот тест их не доказывает.
