# Аудит Sphere Web — 1 октября 2026

[Полный документ](WEB-FULL-CAPABILITY-AUDIT.md) — 21,190 строк, 41 замечание с source anchors и критериями закрытия.

Source: `1354d66660041ba17afb64399d567ca29dd91867`. Режим замороженного аудита: документация без изменения приложения и данных.

- 29 маршрутов / 30 page declarations; 22 sidebar sections.
- 565 AST-контролов, 41 Dialog content declaration.
- 169 REST-операций, 151 schema, 1112 properties, 4 WebSocket handlers.
- 9/9 изолированных source-contract доказательств; это не E2E.
- Свежий Prometheus screenshot; Sphere screenshots — только historical. Полный current visual walkthrough заблокирован browser URL policy.

Исходные приоритеты аудита: [F03](WEB-FULL-CAPABILITY-AUDIT.md#f03), [F04](WEB-FULL-CAPABILITY-AUDIT.md#f04), [F05](WEB-FULL-CAPABILITY-AUDIT.md#f05): запись после failed load и потеря dirty draft; затем [F01](WEB-FULL-CAPABILITY-AUDIT.md#f01)/[F02](WEB-FULL-CAPABILITY-AUDIT.md#f02): достоверность результатов. В рамках замороженного аудита исправления не выполнялись.

[Evidence JSON](WEB-FULL-CAPABILITY-AUDIT-EVIDENCE.json) фиксирует источники/хэши/статусы/ограничения. Каталоги структурные, не заявления о принятии всех controls.

Текущее продолжение: [журнал исправлений и статусы F01–F41](WEB-AUDIT-REMEDIATION.md). Исторический аудит остаётся неизменным.

Последний review UI **5b20955**, API **cc28e9b**,3 октября02:33 UTC+5:
**32 source findings исправлено/9 OPEN**, F33 PARTIAL.101 suites/867 frontend tests;
120 related PostgreSQL cases,35 cases также внутри production image. Собственный
pipeline v1→v2→inactive, stale409/invalid422 и0 runs подтверждены API.
[F28 evidence](../2026-10-03/PIPELINE-DEFINITION-WORKFLOW.md) · [Validation](WEB-AUDIT-FIXES-VALIDATION.json).

Предыдущий review UI **c989eaa**, API **d2846ef**, 2 октября 23:45 UTC+5:
**31 source findings исправлено / 10 OPEN**, F33 PARTIAL. 100 suites / 846 frontend
tests; 25 real PostgreSQL version/admission cases также внутри production image.
Собственный сценарий v1→v2→новая v3→архив и stale 409 подтверждены через pilot API.
[F27 evidence](../2026-10-02/SCRIPT-VERSION-WORKFLOW.md) · [Validation](WEB-AUDIT-FIXES-VALIDATION.json).
Source/API acceptance не закрывает visual, rollout и fleet/soak gates.

Предыдущий review, 2 октября 18:13 UTC+5: UI **d61ab49**, API **8267b94**;
30 source findings исправлено / 11 OPEN, F33 PARTIAL; 99 suites / 825 tests.
Remote PH013 адресно обновился 10230→10240, receipt/heartbeat confirmed.
[F33 evidence](../2026-10-02/OTA-ADDRESSED-DELIVERY.md). Старые trials сохраняют
даты; visual/bulk/manifest/outbox OPEN.

## Runtime и Android follow-up — 2 октября 04:51 UTC+5

Native review процессы исчезли после ранее записанной установки; причина не установлена. Review [3015](http://127.0.0.1:3015/) восстановлен в Docker: UI0f4530c / API5fcf18a, оба healthy, login/API/Prometheus/Grafana/events WS и restart passed. Все 14 прежних контейнеров сохранены. На remote PH025/10240 два variable-only задания completed/success; rerun исполнил pinned v1 после изменения latest v2. N01 upload, browser visual, массовые сценарии и video latency остаются открытыми. [Подробности и receipts](../2026-10-02/REVIEW-RUNTIME-AND-REMOTE-RERUN.md).
