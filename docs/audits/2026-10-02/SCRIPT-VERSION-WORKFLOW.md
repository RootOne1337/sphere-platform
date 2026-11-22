# F27: версии сценариев, архив и подтверждённый Run

**Дата:** 2 октября 2026. Финальный runtime-срез 18:45:43 UTC / 23:45:43 UTC+5.
**API source:** `d2846ef`; **review UI:** `c989eaa`; **F27:** source/test/API исправлено;
browser visual/keyboard acceptance **OPEN_URL_POLICY_BLOCKED**.

[Операторский контракт](../../operations/SCRIPT-VERSIONS.md) · [Evidence JSON](SCRIPT-VERSION-WORKFLOW-EVIDENCE.json) · [CURRENT-STATE](../../operations/CURRENT-STATE.md) · [Frozen F27](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f27) · [Remediation](../2026-10-01/WEB-AUDIT-REMEDIATION.md)

## Воспроизведённые пробелы

Baseline `a408b31` всегда исключал архивные сценарии из `GET /scripts`,
хотя DELETE сохранял их версии. Каталог не предлагал архив/rollback workflow.
Текущая версия могла измениться между открытием карточки и откатом; условие
не проверялось. Update/archive/rollback не сериализовали выделение номера версии
и изменение текущего указателя. Mutation response не предоставлял вычисленный DAG hash.

На отдельном `sphere_audit` PostgreSQL: 16 проверок, **14 failed / 2 controls passed / 0 errors**.
Baseline UI: **11 failed**, отсутствующие controls, без ошибки сборки/коллекции тестов.
Приёмка «новый Run явно показывает версию» также потребовала условия допуска для
одиночного задания и пакета; это добавлено отдельным commit, а не подменено подписью в UI.

## Исправление и проверенные границы

- `b8c916d`: tenant-owned row fence, archived scopes, owned single-version read,
  conditional mutations, active-state checks и полный hash в ответах.
- `b8e2ba7`: archive/history dialog, выбор DAG и redacted structural diff,
  impact confirmation, session/target ownership, безопасные ошибки и запрет blind retries.
- `d2846ef`: shared lock при условном Run, фиксация показанной версии для task/batch,
  номер/hash в окне запуска и проверка принятого version receipt.
- `c989eaa`: рабочая ссылка на обычный журнал задач. Его страница сейчас не
  поддерживает `script_id` URL-filter, поэтому targeted filtering не изображается.

**25 real PostgreSQL tests passed**: 22 новых workflow/admission cases плюс
3 прежних mutation-serialization controls. Тот же набор прошёл внутри
immutable production image `d2846ef`, подключённого только к disposable DB/Redis.
Проверены stale conditions, реальные contested transactions, stale ORM cache,
RLS non-owner tenant scope, immutable v3, сохранность прежних задач и новый pinned Run.

**80 script unit tests passed / 1 skipped**. **100 frontend suites / 846 tests passed**,
из них 21 новый workflow/Run case; 41 связанных scripts tests.
TypeScript, production Ruff0.15.2 и mypy224 source files passed.
OpenAPI экспортирован с production dependencies: **174 operations / 137 paths**.

Оба Docker artifacts собраны из immutable Git archives с обычными production guards.
Next15.5.26 / Node24.21.0, 44 прежних lint warnings не скрывались.
Промежуточный unpublished build `34561c6` отклонил plain `<a>` по Next rule;
правка на `Link` прошла новую сборку `c989eaa`. Failed log сохранён локально.

## Установка и настоящий API canary

Backend установлен **18:39:06 UTC**, review UI финализирован **18:45:41 UTC**.
[Рабочий review /scripts](http://127.0.0.1:3015/scripts): UI `c989eaa`, API `d2846ef`.
Readiness и revisions, login, same-origin API/static chunks, compiled build stamp,
Prometheus backend UP, короткая HttpOnly/SameSiteStrict Grafana session/health,
events WS snapshot/pong passed. Все 43 соседних контейнера сохранили
IDs/images/StartedAt/running. Public frontend, APK, OTA и Tuna не заменялись.

Собственный сценарий `c60612fa-6188-4fac-b5b0-c6aac85c63cf` создан через pilot API,
изменён v1→v2, откатан в **новую v3** и архивирован. v1/v2 остались неизменными.
У v3 хеш v1 `4ad0ec3d53ad76294c4d7ab3b4229246857edbc95d0ce7f8a9d94c3cabe12a73`.
Stale rollback, archive, task admission и batch admission получили **409**.
DELETE с текущей v3 — **204**, fresh archive search/history — **200**, 3 версии сохранены.
Не создано задач/пакетов для Android и не менялись существующие farm scripts.
Тестовый сценарий оставлен в архиве для проверки readback, повтор writes запрещён intent guard.

Первый post-restart срез 18:39:53: catalog19, online12/offline7.
Финальный 18:45:43: **catalog19, online14/offline5**. Это восстановление между
конечными срезами; непрерывная доступность, причины каждого reconnect и soak SLA этим не доказаны.

## CI и оставшаяся приёмка

Для core source `d2846ef` [frontend37048694110](https://github.com/RootOne1337/sphere-platform/actions/runs/37048694110)
success. [Backend37048694138](https://github.com/RootOne1337/sphere-platform/actions/runs/37048694138)
завершился failure: **2268 passed / 2 failed / 16 skipped**, coverage78.42%.
Два старых batch unit fixtures создавали неограниченный `MagicMock`; новое
необязательное поле `expected_current_version_id` стало фиктивным non-null значением
и ошибочно выбрало conditional branch. Commit **da7cf58** заменил request fixture
на реальную `BatchExecutionRequest`: все **8 batch unit tests passed** локально.
Production version checks не ослаблены и backend artifact этим test-only commit
не заменялся. После failure OpenAPI/Redis acceptance этого run были skipped.
Lint/types/security/RLS/production-bootstrap jobs прошли.
[Android37048694126](https://github.com/RootOne1337/sphere-platform/actions/runs/37048694126)
success: all-variant tests и disposable-key release smoke; это не production signer.
Финальный verification/documentation head имеет отдельные checks; завершение
фиксируется в PR #19 без переноса старого green результата на новый SHA.

**31/41 исходных source findings исправлено, 10 остаются открытыми**, включая
F33 PARTIAL. Frozen audit1354d66/document80fb365 не переписан.
Browser visual/keyboard, mobile geometry, history-volume performance и полная
производственная приёмка остаются OPEN. Новые FPS/input latency, APK publication,
20–30-device stream+scripts и произвольное autonomous execution здесь не заявляются.
Следующие source этапы: F28 pipeline detail/edit и F32 настройки/workflows.
