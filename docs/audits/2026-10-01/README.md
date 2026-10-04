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

Последний OTA/API/UI follow-up,3 октября03:17:58 UTC: UI **77fca37** /API
**facba9a**; 14 addressed installs10241 с exact receipt/post-install heartbeat.
14 online на 10241,5 offline вне приёмки;12 finite samples, unchanged epochs и
heartbeat <30 s.104 suites/946 frontend tests, 130 backend в immutable image,
818 passed/1 skip на каждый Android flavor. Backend 2381/16 skipped; schema repair
**5bb36ca backend/frontend/Android CI passed**, schema check passed.33 source-fixed/8 OPEN, F32/F33 PARTIAL.
[Новый отчёт](../2026-10-03/OTA-RELEASE-IDENTITY.md) · [Validation](WEB-AUDIT-FIXES-VALIDATION.json).

Предыдущий fleet follow-up3октября:11 addressed updates10240 confirmed;
14online now10240,5offline outside acceptance.12finite heartbeat readbacks и
unchanged connection epochs; не long soak. Code6d5f280 CI passed,
backend2351/16skipped. [Rollout proof](../2026-10-03/OWNED-PILOT-OTA-ROLLOUT.md).

Предыдущая UI/API установка: UI **a2c4f02** / API **8cd5cf0**, F32,3 октября2026.
**33 source-fixed /8 OPEN**, F32/F33 PARTIAL;103suites/916 frontend tests в
Node24,159 related backend cases также в immutable image. Targets/receipts и
N06 deferred provider init подтверждены tests/live API. Finite online14→11→12;
current inventory14online,3latest/11old. [F32 proof](../2026-10-03/VPN-CONTROL-OUTCOMES.md) ·
[Validation](WEB-AUDIT-FIXES-VALIDATION.json). Browser/rollout/fleet OPEN.

Предыдущий review: UI **8e0aeb5** / API **db6be05**, 3 октября 03:06 UTC+5.
**33 source findings исправлено / 8 OPEN**; 102 suites / 893 frontend tests,
40 PostgreSQL cases и 30 в production image. F26 география/иерархия, null clear,
stale conditions и parent deletion проверены собственным конечным API canary.
[F26 proof](../2026-10-03/LOCATION-HIERARCHY.md) · [Validation](WEB-AUDIT-FIXES-VALIDATION.json).
Visual/rollout/fleet gates остаются открытыми.

Предыдущий review UI **5b20955**, API **cc28e9b**,3 октября02:33 UTC+5:
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
