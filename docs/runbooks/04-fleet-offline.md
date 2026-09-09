# 04 — Массово пропали устройства

**Обновлено 10 сентября 2026.** Потеря управления большим парком — эксплуатационный P0.
[APK contract](../android-agent.md) · [Backend](01-backend-outage.md) ·
[Связь и failover](../operations/READINESS.md)

## Разделить симптомы

Offline в UI, нет Redis presence, WS закрыт, auth отклонён и APK process остановлен
— разные состояния. Продолжение локального DAG возможно, но не гарантировано для
любого действия/OS/process death. Прежнее обещание «весь парк вернётся за пять минут»
не имело измеренного основания и удалено.

1. Зафиксируйте время, долю затронутых устройств, их станции, APK версии и последнюю
   успешную команду/heartbeat. Общая станция/route/build помогает локализовать сбой.
2. Проверьте backend readiness и proxy. Не отправляйте reconnect/reenroll всему парку
   одновременно, пока сервер ещё восстанавливается.
3. Для одного устройства определите сохранённый server URL, device ID, состояние
   сервиса и category последнего отказа. Credentials не включайте в evidence.
4. Сопоставьте WS close codes: 4001/4003/4004 связаны с auth/device lookup, 4008 —
   heartbeat; network/handshake failure отдельно. Коды помогают локализации, но
   проверка actual server logs определяет причину.
5. Проверьте источник CONFIG_URL и доступность текущего endpoint отдельно. GitHub
   outage сам по себе не требует нового enrollment, если сохранённый адрес работает.

## Текущие сроки и ограничения

APK retry после AUD-67 имеет jitter: первое окно 1–2 s, cap 15–30 s; clean server
close тоже проходит через delay. Circuit cooldown — 60 s после десяти network
failures. Handshake timeout — 20 s. Это policy windows, а не SLA восстановления.
Backend application heartbeat задан 30 s и проверяет age >45 s на цикле; Android
watchdog использует 90 s без application ping. Нельзя считать номинальный threshold
точным wall-clock временем обнаружения. Старые APK имеют другую reconnect policy.

ConfigWatchdog: первая проверка через 5 s, затем 120 s connected / 60 s disconnected.
Enterprise CONFIG_URL может быть пуст; один сохранённый URL не является двумя
независимыми путями. Secondary endpoint и versioned LAN discovery пока в плане.

## Вернуть парк без потери идентичности

Восстановите readiness/маршрут, наблюдайте одну станцию и одну задачу, затем
постепенно расширяйте проверку. Сохраняйте device identity и journal; reinstall,
clear data, массовое удаление Redis keys или выдача новых IDs не являются обычным
reconnect recovery. При broken refresh rotation нужно сохранить evidence lost
response/expiry, а не скрыть проблему повторной регистрацией.

Если UI показывает offline после реального pong, сверяйте presence/fencing и
fleet events. Если задача закончилась локально без server result, сверяйте журнал,
result receipt и ACK. Не повторяйте физическое действие только из-за таймаута UI.

## Критерии завершения

Зафиксированы фактические device recovery p50/p95/p99 и число невосстановившихся;
одинаковые device IDs, отсутствие повторного действия, проверенные terminal/unknown
outcomes и наблюдаемый backlog. После инцидента добавить regression и обновить
capacity/recovery budget. Реальный изолированный fleet drill ещё требуется.
