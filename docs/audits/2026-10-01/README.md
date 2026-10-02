# Аудит Sphere Web — 1 октября 2026

[Полный документ](WEB-FULL-CAPABILITY-AUDIT.md) — 21,190 строк, 41 замечание с source anchors и критериями закрытия.

Source: `1354d66660041ba17afb64399d567ca29dd91866`. Режим замороженного аудита: документация без изменения приложения и данных.

- 29 маршрутов / 30 page declarations; 22 sidebar sections.
- 565 AST-контролов, 41 Dialog content declaration.
- 169 REST-операций, 151 schema, 1112 properties, 4 WebSocket handlers.
- 9/9 изолированных source-contract доказательств; это не E2E.
- Свежий Prometheus screenshot; Sphere screenshots — только historical. Полный current visual walkthrough заблокирован browser URL policy.

Исходные приоритеты аудита: [F03](WEB-FULL-CAPABILITY-AUDIT.md#f03), [F04](WEB-FULL-CAPABILITY-AUDIT.md#f04), [F05](WEB-FULL-CAPABILITY-AUDIT.md#f05): запись после failed load и потеря dirty draft; затем [F01](WEB-FULL-CAPABILITY-AUDIT.md#f01)/[F02](WEB-FULL-CAPABILITY-AUDIT.md#f02): достоверность результатов. В рамках замороженного аудита исправления не выполнялись.

[Evidence JSON](WEB-FULL-CAPABILITY-AUDIT-EVIDENCE.json) фиксирует источники/хэши/статусы/ограничения. Каталоги структурные, не заявления о принятии всех controls.

Текущее продолжение: [журнал исправлений и статусы F01–F41](WEB-AUDIT-REMEDIATION.md). Исторический аудит остаётся неизменным.

Последний review UI **e2362eb**, backend **933164e**,2 октября16:18 UTC+5:29 source fixes/12 исходных OPEN,96 suites/777 frontend tests. F38 user form/role/deactivation dialogs исправлен, finite negative API accepted; N04/N05 proofs сохранены. N01/N03 и browser visual OPEN. [F38 и receipts](../2026-10-02/USER-ACCESS.md) · [Validation](WEB-AUDIT-FIXES-VALIDATION.json). Старые runtime/restart/canary results сохраняют собственные даты.

## Runtime и Android follow-up — 2 октября 04:51 UTC+5

Native review процессы исчезли после ранее записанной установки; причина не установлена. Review [3015](http://127.0.0.1:3015/) восстановлен в Docker: UI0f4530c / API5fcf18a, оба healthy, login/API/Prometheus/Grafana/events WS и restart passed. Все 14 прежних контейнеров сохранены. На remote PH025/10240 два variable-only задания completed/success; rerun исполнил pinned v1 после изменения latest v2. N01 upload, browser visual, массовые сценарии и video latency остаются открытыми. [Подробности и receipts](../2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md).
