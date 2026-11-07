# F38: форма пользователя и адресные изменения доступа

**Дата:** 2 октября 2026, Asia/Yekaterinburg.<br />
**Source:** `e2362eb0a9896505a1d4c78609dfcb07e83eac72`.<br />
**Установленный API:** `933164e2929be0223b9a918902795ade7f0a6dfa`, без замены в этом продолжении.

[Операторский контракт](../../operations/USER-ACCESS.md) ·
[Allowlisted evidence](USER-ACCESS-EVIDENCE.json) ·
[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Frozen finding F38](../2026-10-01/WEB-FULL-CAPABILITY-AUDIT.md#f38) ·
[Журнал F01–F41](../2026-10-01/WEB-AUDIT-REMEDIATION.md)

## Что было доказано

В прежнем source4898577 создание было click handler вне form. Type=email не
запускал native form validation; пароль не проверялся по контракту8..128. 422/409/403
показывались общей ошибкой. Role PUT отправлялся прямо при выборе, deactivation
использовала window.confirm. Ответ другого пользователя или неисполненная команда
могли пройти как success, потому что hooks не проверяли target/receipt.

16 новых tests на архивированных исходниках дали16 assertion failures,0 runtime
errors. После изменения проходят16 workflows и5 прежних hook cases. Противоречивые
hook fixtures с несуществующими ролями admin/operator, неверным echo email и200 вместо
204 исправлены на настоящий контракт; проверки запроса и успеха сохранены.

## Исправление

- Native form submit, required/email, Unicode password bounds, role grant guard.
  422 привязано к полям; known duplicate email409 и assignment403 имеют точный фокус.
- Ошибки не отражают password/validation input и произвольный payload. Draft сохраняется
  после отказа; пароль удаляется при закрытии/подтверждении.
- Role/deactivation dialogs показывают email/UUID/org/current/desired role и последствия.
  Cancel, keyboard dialog semantics и pending lock используют существующий Radix Dialog.
- Текущая роль таблицы сохраняется до подтверждения. PUT проверяет ID/org/role;
  POST — email/org/role/active; deactivate — ровно204. Unknown outcome не становится success.
- Actual backend grant matrix сверена для49 пар ролей; api_user/super_admin не теряются.
  org_admin не может выбрать административное grant, менять роли или отключить owner;
  self deactivate блокируется. Last-owner решает сервер, не количество loaded-page rows.
- Session-scoped catalog с AbortSignal, validation и30-секундным active-tab refetch.
  При cached read failure нет write controls. Изменившийся target не получает новую
  команду из старого dialog. Pending state не переживает смену оператора/сессии.

## Проверки и установка

Frontend: **96 suites /777 tests /0 failures /0 skips**, types и lint passed.
Новых workflows16; к исходному baseline582 совокупно добавлено195 regressions.
Прежних lint warnings44, новых в изменённых files нет. Backend user HTTP: **23 passed**;
это SQLite/ASGI проверка прежнего server contract, не PostgreSQL concurrency canary.
Первый локальный pytest запуск остановился до тестов из-за отсутствующего test JWT
secret; повтор с отдельным синтетическим test key завершился23 passed. Production
секреты для тестов не использовались.

Production Docker build выполнен из immutable Git archive e2362eb с исходным Next
config, Node24.21.0/Next15.5.26. Только review UI/gateway заменены: UI стартовал
**2 октября16:09:45 UTC+5**, gateway16:09:51, оба healthy на loopback3015.
**44 остальных контейнера,14 running**, сохранили IDs/images/StartedAt/running;
в их числе backend, публичный frontend, APK ingress, observability и туннели.

В **16:16:56 UTC+5** проверены настоящий login, same-origin API, compiled SHA и static
asset, Prometheus backend up, короткая HttpOnly/SameSiteStrict Grafana session/health,
events WS snapshot/pong. Каталог19 устройств: reported online14/offline5. Это конечный
срез, не fleet uptime/soak. [Работающий раздел](http://127.0.0.1:3015/users).

В **16:17:56 UTC+5** `/users` вернул настоящий каталог. Invalid email/password POST
дал422 с обоими field locations; unknown role target —404; self deactivate —400.
Пользователи, организации, роли и active states до/после совпадают. Реальные права
не менялись; happy-path browser create/change/deactivate не объявляются проверенными.

Published4898577 отдельно завершил backend/frontend/Android CI success; новый
source/docs head получает собственные checks. Исходный frozen audit1354d66/80fb365
сохранён. Текущий ledger: **29 source fixes /12 исходных OPEN**,5P1/24P2 исправлено.
N04/N05 finite API proofs сохраняются; F39 общей оболочки этим scope не закрыт.
Проверены545 относительных целей документации и41 finding anchors:0 отсутствующих.

## Незакрытые критерии

Browser Sphere URL denial не обходился: визуальная приёмка **OPEN_URL_POLICY_BLOCKED**.
JSDOM не доказывает responsive geometry, а compiled asset не является screenshot.
Нет новой приёмки remote video FPS/quality/input latency, normal/global OTA,
20–30 stream+script fleet, Android artifact upload или golden-image clones.
Backend role CAS/revision, MFA onboarding, reactivate/password reset и durable audit
outbox здесь не добавлялись. Существующие неизвестные OTA grants остаются отдельным
операторским/доставочным вопросом; неизвестные receipts автоматически не подтверждаются.
