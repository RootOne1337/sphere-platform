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

Последний installed source **5fcf18a**: 24 source findings исправлено, 17 открыты; 91 suites / 718 frontend tests, types/production build passed. API и review UI3015/3030 установлены 2 октября в 01:27/01:28 UTC+5. [F16/F17 contracts/evidence](../2026-10-02/TASK-ARTIFACTS-AND-RERUN.md) · [Fix validation](WEB-AUDIT-FIXES-VALIDATION.json). Android screenshot upload N01 и browser visual acceptance открыты.
