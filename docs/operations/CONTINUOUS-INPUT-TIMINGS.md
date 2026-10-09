# Серверные тайминги непрерывного управления

[Реестр работ](WORK-STATUS.md) · [Текущая установка](CURRENT-STATE.md) ·
[Prometheus](OBSERVABILITY.md) · [Исходная проверка](../audits/2026-10-09/CONTINUOUS-SERVER-TIMINGS.md)

**Установленные UI/API369654a0 сохраняют эти измерения.**
[Текущая доставка и границы](../audits/2026-10-10/BROADCAST-INSTALLED-ACCEPTANCE.md) ·
[Исторический wording/контраст](../audits/2026-10-09/IDLE-CONTROL-UX-INSTALLED.md).
Последний public idle timeout остаётся открытым; метрики не доказывают native ACK.

**Историческая доставка 9 октября, 15:17 UTC / 20:17 UTC+5: установлено в API d720232e.**
UI 86354350 / APK 10249 сохранены. [Exact CI/image/install и failed idle canary receipt](../audits/2026-10-09/CONTINUOUS-SERVER-TIMINGS-INSTALLED.md):
PH011 heartbeat timeout 510 мс / last ACK RTT 256 мс повторился, все наблюдаемые spans <25 мс.
До callback queues/network/APK/native не локализованы; SF26-05 OPEN. Диагностика
не меняет deadline/replay/routing и не является подтверждением Android ACK.
Reviewed installer допускает только проверенный packaged delta; dependency/action
Hashes/schema/Compose/container fences сохранены; 19 finite host tests passed.

## Что измеряется

`sphere_continuous_stage_duration_seconds{stage,outcome}` — histogram длительности
локального coroutine по monotonic clock, включая его awaits. Фиксированные
границы определены исходником; значения wire payload не используются как метки.

| stage | Начало и конец | Ограничение |
| --- | --- | --- |
| viewer_admission | ContinuousRuntime.handle: проверка сообщения, binding или публикация input | Probe/open/close также входят; periodic RBAC check и ожидание browser WS до вызова не входят |
| redis_lease_operation | ContinuousLeaseStore._operation: создание envelope и bounded Lua EVAL | Все lease операции вместе; это не самостоятельная native ACK latency |
| pubsub_dispatch | ContinuousRuntime.route: разбор полученного envelope и последовательная обработка | Не включает ожидание в Pub/Sub до вызова route; включает nested spans |
| agent_delivery | deliver_continuous: guard, exact authenticated socket attempt, возможный fence | SOCKET_SENT означает только серверную отправку; UNKNOWN/rejected тоже возвращаются |
| agent_reply_relay | ContinuousRuntime.agent_message: topology и relay публикация ответа | Включает offers и receipts; не начинается в момент native ACK на Android |
| viewer_receipt_validation | viewer_receipt: identity/shape/expiry и Redis TIME | Возврат None также наблюдается; WS send вынесен в другую границу |
| viewer_socket_send | ContinuousRuntime.send: exact viewer send и retirement при ошибке | Включает cleanup при сбое; завершение send не доказывает browser получение |

`outcome` имеет только три значения: `returned`, `raised`, `cancelled`.
`returned` — завершение coroutine с любым обычным результатом, включая None,
rejected и UNKNOWN. Это **не** статус выполнения Android. `raised` не раскрывает
класс или текст исключения. Cancellation сохраняется, native cleanup продолжается.

Buckets в секундах: 0.001, 0.01, 0.025, 0.05, 0.1, 0.25, 0.4, 0.5,
1.0 и +Inf. Границы около 250/500ms позволяют увидеть долю медленных
операций; это не новые protocol deadlines. Nested durations нельзя складывать.

## Ресурсы и приватность

Семь stages × три outcomes: максимум 21 комбинация меток независимо от парка,
числа viewers, gestures и sequences. Нет device/org/user/session/owner/epoch
меток, координат, текста, кадров, сырых envelope или individual latency rows.
Новые tasks, очереди, Redis subscriptions/keys/commands, retries и polling не создаются.
Histogram обновляется в существующем потоке; дополнительных файловых логов нет.
Ошибки clocks/metrics пропускают измерение без изменения original result/error/cancel.
Неизмеренная или некорректная duration не заменяется нулём.

Production multiprocess collector суммирует histogram workers. Завершённый worker
оставляет cumulative histogram history внутри существующего master lifecycle;
следуйте [политике метрик](OBSERVABILITY.md), не удаляйте mmap live worker вручную.
Конечная four-process fixture проверяет aggregate count/sum/buckets и замену
worker; она не заменяет нагрузочный CPU/RSS/disk soak.

## Чтение после подтверждённой установки

Проверьте source revision контейнера, свежесть scrape и наличие активности.
Пустая серия означает отсутствие наблюдаемого ряда; она не доказывает здоровье.
Для короткой canary сохраните delta count/sum/buckets до и после; при малом числе
измерений percentile ненадёжен. Метрики общие для workers и не идентифицируют
конкретный viewer или sequence.

Частота наблюдаемых coroutine завершений (это не RPS input):

```promql
sum by (stage, outcome) (
  rate(sphere_continuous_stage_duration_seconds_count{job="sphere-backend"}[5m])
)
```

При достаточной выборке — p95 локальной inclusive duration:

```promql
histogram_quantile(0.95,
  sum by (le, stage, outcome) (
    rate(sphere_continuous_stage_duration_seconds_bucket{job="sphere-backend"}[5m])
  )
)
```

Доля observations дольше 250ms по stage/outcome:

```promql
1 - (
  sum by (stage, outcome) (
    rate(sphere_continuous_stage_duration_seconds_bucket{job="sphere-backend",le="0.25"}[5m])
  )
  /
  sum by (stage, outcome) (
    rate(sphere_continuous_stage_duration_seconds_count{job="sphere-backend"}[5m])
  )
)
```

Нулевой знаменатель остаётся NaN/unknown; не подставляйте zero/healthy.
Не складывайте эти значения с browser RTT и не трактуйте их как input-to-picture.

## Следующая конечная проверка SF26-05

1. Проверить актуальный admitted source/runtime receipt и freshness `/metrics`;
   установленный API369654a0 и последний canary receipt указаны выше. Исторический
   d720232e не является текущей установкой. Не подменять отсутствие activity нулём.
2. На одном разрешённом тестовом viewer начать Control без DOWN/UP/text/record/run.
   Сохранить time window, browser oldest heartbeat/actual ACK RTT/tick/buffer,
   server histogram deltas и resource observation freshness.
3. После idle timeout выбрать View; не повторять unknown input и не расширять
   deadlines. Если server spans медленные, локализовать включённые awaits.
   Если spans быстрые, продолжить измерение queued/network/APK/native участка.
4. Причину и fix принимать отдельно, затем повторить idle/failure canary и soak.
   Одни новые метрики не закрывают EP-020/029 или SF26-05.

Read-only Pub/Sub подписчик на input-channel тоже меняет subscriber count.
Он может скрыть отсутствие рабочего receiver от no-subscriber fence. Для этой
проверки новый подписчик не используется; production routing остаётся прежним.
