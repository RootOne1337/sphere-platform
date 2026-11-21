# Изолированные проверки конфигурации мониторинга

Использовались локальные Docker images и отдельные временные контейнеры с `--pull never --network none --read-only`, read-only файлами из checkout и `--tmpfs /tmp:rw,nosuid,nodev,size=32m` для тестовой БД promtool. Сетевых обращений и отправки уведомлений не было.

| Образ и команда внутри контейнера | Результат |
|---|---|
| `prom/alertmanager:v0.26.0`, `amtool check-config` на [legacy YAML](../../../../infrastructure/monitoring/alertmanager.yml) | Код 1. Строка 46, строка с переменной не преобразуется в `int64`. |
| `prom/prometheus:v3.15.0`, `promtool check config` на [collection](../../../../infrastructure/monitoring/collection/prometheus.yml) с его [rules](../../../../infrastructure/monitoring/collection/rules.yml) | Код 0. Конфигурация и файл с одним правилом приняты. |
| `prom/prometheus:v2.48.0`, `promtool test rules` на [существующем наборе](../../../../tests/alert_test.yml) | Код 1. Четыре несовпадения. `HighAgentOfflineRate` ожидается при ровно 20%, а правило требует строго больше 20%. Для `DatabasePoolExhausted`, `HighTaskQueueDepth` и `VPNPoolLow` совпадает сам алерт, фикстура не содержит фактических аннотаций. |
| `prom/prometheus:v2.48.0`, `promtool test rules` на [фикстуре 5xx](prometheus-error-rate.yml) | Код 0. Фикстура фиксирует дефект: 99 успешных ответов/с и 1 ошибка/с дают активный алерт с 100%. |
