# Серверные границы задержки continuous input

9 октября 2026. EP-020/029, SF26-05 остаются OPEN.
**Source validated; CI/image/install/live pending.** UI 86354350/API be803773
сохранены. Это диагностическая инструментализация, не исправление idle timeout.

[Правила чтения и PromQL](../../operations/CONTINUOUS-INPUT-TIMINGS.md) ·
[Browser failure и установленный UI](STREAM-DIAGNOSTICS-INSTALLED-ACCEPTANCE.md) ·
[Fingerprint и конечные проверки](CONTINUOUS-SERVER-TIMINGS.json).

## Основание

Предыдущая PH011 idle canary сохранила heartbeat age 512ms, tick gap 15ms,
last ACK RTT 248ms и WS OPEN/0B. Причина не определена. Source-path review:
viewer admission → Redis Lua publish → последовательный Pub/Sub route → exact
APK socket → mailbox/native pipe → authenticated reply relay → Redis receipt
→ viewer validation/send. Общий dispatch действительно await-ит route serially;
это возможная точка ожидания, но source inspection не доказывает её вину.

Не было серверных histogram границ именно для continuous input. Browser RTT
не отличал локальную обработку, socket await и unobserved network/APK время.

## Изменение

Добавлена одна центральная Prometheus histogram с семью source-defined stages
и тремя outcomes. Inclusive duration берётся локальным monotonic clock вокруг
существующих coroutine. Отдельная таблица границ находится в runbook.
`returned` не превращает rejected/UNKNOWN в выполненную команду. Exceptions и
cancellation сохраняются; сбой metrics/clock не меняет ownership или cleanup.

Новые subscriptions/keys/queues/tasks/poll/retry не создаются; ни payload, ни
идентификаторы, координаты, текст или кадры не записываются. Максимум 21 label
combination на worker; количество устройств и команд его не увеличивает.
Нет нового per-MOVE/file log. Бюджеты 250ms server operation / 500ms delivery
и browser receipt, heartbeat 250ms, lease/auth 1500ms не изменены.

## Проверки исходника

- Continuous protocol/lease/runtime/observability: **175 passed**.
- Все WebSocket и monitoring: **560 passed, 44 subtests passed**.
- После расширения four-worker fixture: **2 passed**; новые count/sum/buckets
  агрегируются после retirement/replacement. При всех 21 комбинациях меток
  initial four-worker registry сохраняет предел 16 mmap files / 1MiB.
  Ранний набор из 12 finite buckets с длинным HELP выделял 1.25MiB; итоговые
  9 buckets и краткий HELP возвращают прежний 1MiB fixture bound. Пороговые
  границы 250/400/500ms сохранены. Это не host RSS или production churn soak.
- Scoped Ruff и mypy пяти затронутых transport/observability модулей проходят.
- Полный локальный mypy проверил 246 модулей и сообщил одну ошибку в неизменённом
  backend/schemas/game_accounts.py:61 (Field default_factory typing). Узкий
  mypy проходит; полный exact-source CI на штатных зависимостях ещё необходим.
- Новые regressions сохраняют original UNKNOWN result, exact exception,
  cancellation/native cleanup; metric failure не меняет ход операции; invalid
  clocks не рисуют zero; private payload cardinality и protocol shape сохранены.
- Первый локальный прогон остановился из-за отсутствия `lupa` у fakeredis (EVAL
  unknown), а не найденной ошибки source. Изолированный test-only wheel 2.8
  установлен в .local-pilot; unit DB/Redis URLs направлены на неслужебный port9.
  Работающий PostgreSQL/Redis не использовался тестами.

## Граница доказательства

No runtime restart/install/APK change выполнен этим source этапом. Не измерены
время в очереди Pub/Sub до route, browser/network или native pipe на Android.
Nested histograms не суммируются. Global samples не коррелируют конкретный
sequence, а tail percentile требует достаточного count. Не заявлены нулевая
задержка, устранение idle failure, fleet SLO или отсутствие disk/RAM утечки.

Для следующей установки нужны exact-source CI/image admission и отдельный
runtime receipt. После этого — конечная одноустройственная idle canary с browser
snapshot, server deltas и resource counters; затем локализованное исправление.
Счётчик продукта остаётся **9 принято / 41 открыто**, legacy7 отдельно.
