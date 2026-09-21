# AUD-138: ограничение очереди и восстановление активного видеодекодера

**21 сентября 2026 · F32-06 · P0 / High · source fix; native rollout проверяется отдельно.**

[Fleet32](FLEET32-PREFLIGHT.md) · [Установленная canary 1.2.8](CANARY-20260921.md) · [Evidence](evidence/decoder-recovery.json)

## Причина и воспроизведение

`DeviceStream` импортирует [frontend/lib/h264-decoder.ts](../../../frontend/lib/h264-decoder.ts).
Исправление другой реализации в `src/lib/streaming` не затрагивает этот путь.
До SPS/PPS активный decoder сохранял каждый NAL без лимита. После configure
каждый кадр передавался в WebCodecs без проверки очереди; codec error только
писался в console. Ошибка canvas пропускала `frame.close()`, callbacks старого
codec могли рисовать после reconnect/unmount. Повторная пара SPS/PPS сбрасывала
ожидание IDR даже при неизменной конфигурации.

На базе `cb07eae` **14 из 16 новых проверок упали на assertions, две прошли**;
runtime/import ошибок нет. Настоящий TS decoder использует codec double с
контролируемым потреблением/выводом. Исходный audit probe отдельно фиксировал
2048 NAL / 2 MiB до конфигурации и 1000 submissions зависшему decoder.
Это доказательство неограниченной политики, а не зарегистрированного GPU OOM.

## Исправление

- До валидной пары SPS/PPS и свежего IDR кадры не сохраняются вообще. Старые
  pre-config кадры не воспроизводятся после появления конфигурации.
- Одновременно допускаются до **8** входов без output и до **2 MiB** encoded
  bytes. Проверяется также `decodeQueueSize`; один wire packet ограничен 1 MiB.
  Tracking до output учитывает работу, уже вынутую кодеком из его input queue.
- При следующем input/output с ожиданием дольше **500 ms** старая цепочка
  закрывается целиком. Это локальный возраст очереди, не сетевой frame age.
  Никакого продолжения зависимых delta после произвольного пропуска нет.
- Recovery закрывает старый codec, выдерживает cooldown **1 s**, ждёт IDR и
  использует сохранённые параметры текущей конфигурации. Новый socket очищает
  параметры полностью. Изменённый SPS требует свежего PPS; одинаковые пары
  не вызывают лишнего configure. Backward timestamp на IDR отделяет новый stream.
- Frame закрывается в `finally`; поколение decoder исключает старые callbacks.
  Configure/decode exceptions и async codec error переходят в recovery.
- `DeviceStream` показывает ожидание и через 1.1 s запрашивает keyframe по уже
  существующему WS-контракту, затем не чаще раза в 2 s до output. Это нужно и
  на неподвижном Android-экране. Timers очищаются при output/socket close/unmount.
- Проверяются размер/version/timestamp wire header. Annex-B access unit с
  несколькими NAL превращается в один AVCC chunk с длиной каждого NAL; source
  timestamp передаётся в microseconds. Он **не** доказывает capture-to-render latency.

Условия WebCodecs сверены с [W3C VideoDecoder](https://www.w3.org/TR/webcodecs/#videodecoder-interface):
очередь входа не равна всем внутренним outputs; после новой конфигурации нужен
key chunk. [AVC registration](https://www.w3.org/TR/webcodecs-avc-codec-registration/#encodedvideochunk-data)
описывает access unit как один picture; chunk может содержать несколько NAL.

## Регрессии и результат

[Decoder tests](../../../frontend/__tests__/stream/h264-decoder.test.ts) проверяют
missing config, зависший input, pending output при нулевой `decodeQueueSize`,
count/bytes/age limits, sync/async errors, delayed output, canvas exception,
changed/duplicate SPS/PPS, несколько NAL, reconnect/reset, source timestamp,
malformed headers и 1000 последовательных output без ложного overload.
[Viewer tests](../../../frontend/__tests__/stream/reconnect.test.tsx) проверяют
keyframe cooldown/retry и очистку timers/references.

Полный frontend: **264 passed**, 30 suites; TypeScript без ошибок.
Initial failing suite и итоговые hashes/counters сохранены в evidence; сырые логи
приватные. Автоматические тесты не используют настоящий browser codec.

## Остаточные риски

Native приёмку свежего frontend надо фиксировать с точным source/image отдельно.
Два потока не подтверждают 32 аппаратных decoder sessions. Лимиты относятся к
принятым encoded inputs; это не общий предел GPU/RAM, WebSocket/network backlog
или гарантия end-to-end latency. Возраст проверяется на input/output, а не
отдельным периодическим timer. Recovery ждёт подходящего keyframe; полный отказ
сервера/encoder не может быть исправлен только браузером.

Preview/focus profile, frame freshness, command/video budgets, Redis limits,
реальная нагрузка 32 и длительный soak остаются отдельными открытыми gates.
Legacy decoder не используется страницей и в этом fix не переписан.
