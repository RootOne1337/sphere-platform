# AUD-175 · Fleet viewer мог показывать остановившееся видео как live

**Дата:** 25 сентября 2026 · **Severity:** P1 · **Статус:** исправлено в source,
локально проверено; pilot rollout ещё не выполнен.

[Fleet stream implementation](../../../frontend/components/sphere/DeviceStream.tsx) ·
[Regression](../../../frontend/__tests__/stream/reconnect.test.tsx) ·
[Stream diagnostics](./ANDROID-STREAM-OBSERVABILITY.md) ·
[Remote ingress evidence](../2026-09-24/REMOTE-INGRESS-AB.md)

## Дефект и воспроизведение

Fleet viewer считал соединение здоровым, пока WebSocket получал любое сообщение.
Backend продолжает отправлять контрольные `ping`, поэтому потеря или остановка
видеокадров не запускала socket watchdog. После первого декодированного кадра UI
мог оставаться в состоянии `live` без новых изображений неограниченно долго.

Воспроизводимая последовательность: открыть viewer, принять и нарисовать один
кадр, затем продолжать присылать WebSocket `ping`, но не присылать бинарные
video-пакеты. До fix после 10 секунд UI всё ещё объявлял поток `live`. Это не
доказывает причину остановки кадров на конкретном Android или маршруте; это
ошибка статуса и восстановления во frontend.

## Root cause и исправление

Один watchdog использовал `lastReceived`, который обновлялся как на binary frames,
так и на строковых control messages. Отдельного времени последнего декодированного
кадра не было.

Теперь декодированный кадр запускает собственный 10-секундный таймер. Если за это
время новый кадр не нарисован, viewer показывает `Нет новых видеокадров более 10
секунд` и возобновляет keyframe requests с экспоненциальным интервалом. Следующий
успешно нарисованный кадр возвращает `live`. Таймер очищается при reconnect, close и
unmount. До первого кадра UI остаётся в состоянии ожидания, а сокет продолжает
отдельно контролироваться по входящим сообщениям.

## Проверки и границы

- Regression `marks video stale when control pings continue but decoded frames
  stop, then recovers on a new frame` проходит.
- Полный frontend Jest: **35 suites / 277 tests passed**; `npm run type-check`
  passed.
- GitHub frontend CI на предыдущем commit прошёл; новый source change требует
  отдельного CI прогона.
- Изменение ещё не развёрнуто в pilot.

Этот fix делает статус после потери уже начавшегося видео достоверным и запускает
повторный запрос keyframe. Он не объясняет отсутствие первого IDR/P от удалённого
APK, не подтверждает удалённый WAN egress и не устраняет сам путь потери кадра.
Для этого остаётся нужен addressable remote canary со свежими Android counters,
backend ingress receipts и браузерным decode evidence.
