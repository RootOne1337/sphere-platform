# PyJWT: dependency advisory и проверка авторизации

**Дата:** 30 сентября 2026, Asia/Yekaterinburg.<br />
**Область:** backend dependency / fixed-key JWT verifier; Android, парковые команды и туннели не изменяются.

[Текущее состояние](../../operations/CURRENT-STATE.md) ·
[Readiness](../../operations/READINESS.md) ·
[Контракт авторизации](../../../tests/auth/test_jwt_verifier_contract.py) ·
[PR #19](https://github.com/RootOne1337/sphere-platform/pull/19)

## Подтверждённый сигнал

Security job docs commit `60d9698` завершился failure: pip-audit сообщил
`PyJWT 2.14.0 / CVE-2026-101918 / fix 2.15.0`. Предыдущий source `4024ccf`
завершил security job success; это отдельные срезы изменяемого advisory feed.
Причина расхождения cache/feed не устанавливалась. Failure не подавлялся.

[GitHub Reviewed advisory GHSA-42vr-xj54-vc7v](https://github.com/advisories/GHSA-42vr-xj54-vc7v)
описывает необработанный RecursionError при deeply nested JWT payload в
pre-verification decode/JWKS flow; affected `>=2.0.0a1, <=2.14.0`, first patched
`2.15.0`. Подтверждённый эффект — исключение отдельного запроса, а не доказанный
process crash или обход авторизации. Metadata GitHub Advisory Database получена
30 сентября; published_at 15:41:05 UTC / updated_at 15:41:07 UTC.

Sphere использует фиксированный серверный ключ, allow-list алгоритма и проверку
подписи. Header `jku` не запускает запрос к внешнему signing-key endpoint.
Неправильно подписанный вложенный payload отвергается до JSON parsing. Это
доказанный контракт проверенных функций, не объявление публичного endpoint
эксплуатируемым и не объяснение прежних stream/OTA обрывов.

## Изменение и регрессии

Закреплена **PyJWT 2.15.1**: она включает security fix 2.15.0 и compatibility
fix Base64URL padding. Основания — [changelog производителя](https://pyjwt.readthedocs.io/en/latest/changelog.html)
и [release metadata PyPI](https://pypi.org/project/PyJWT/2.15.1/).
Allow-list, signature verification, required claims и logout semantics сохранены.

Две функции приложения проверяются с ограниченным signed JSON payload глубины
20 000: обычный access decoder и decoder для logout с expired token. На
установленной **2.14.0** два regression cases failed с raw RecursionError;
остальные 14 verifier cases passed. Два отдельных cases с неверной подписью
подтвердили отказ до parsing. На **2.15.1** повреждённый signed payload выдаёт
documented DecodeError, входящий в InvalidTokenError, который ловят auth handlers.

Первый черновой опыт использовал старую local venv 2.13.0 и недостаточную глубину
`sys.getrecursionlimit()+100`: C JSON parser Python 3.12 не обязан следовать
этому лимиту. Такой запуск не является доказательством CVE. Финальная baseline
выше выполнена после проверки package version с фиксированной bounded глубиной.

Targeted application auth / WS auth / auth-service suite: **79 passed / 1
deprecation warning**. Dependency-aware mypy **219 files clean**, targeted Ruff
и pip check passed. Полный pip-audit backend + pc-agent requirements:
**No known vulnerabilities found**; были cache-deserialization warnings,
невалидные cache entries проигнорированы самим инструментом.

## Границы приёмки

Full CI и exact packaged-image/runtime acceptance нового dependency source
записываются отдельно в [CURRENT-STATE](../../operations/CURRENT-STATE.md).
На момент исходного source commit pilot backend `4024ccf` ещё содержал PyJWT
2.14.0. Изменение requirements не считается обновлением работающего контейнера.
Нужен новый immutable image, successful gates, controlled backend-only rollout,
обычный login и восстановление baseline fleet. APK/signing keys, парковые
команды и public UI этим исправлением не публикуются и не переисполняются.

## Exact-image и живой follow-up — 30 сентября, 21:37–21:44 UTC+5

Source `85c8014` прошёл обязательные GitHub jobs; backend **2124 passed / 15
Windows-only skipped / 5 warnings**, 703.21 s, coverage **77.87%**. Frontend
71 suites / 526 Jest tests + Node transport/types/build success, security,
RLS, Alembic single head, lint/types, packaged bootstrap и Android smoke success.
Exact image `sha256:b2a0d4bec434c127f522fec5ec8eb3a9c5cc35682b40759acf6c1ee6880e4ccd`
прошёл fresh PG/Redis lifecycle и две серии по 160 known HTTP requests с четырьмя
workers, child/master replacement и cleanup; дополнительный recycle loop
не запускался. Его `scrape_max_ms: 0` не считается измерением производительности.

Readback установленного image выявил также cryptography **50.0.2** вместо
50.0.1: existing lower-bound requirement допустил выпущенный 30 сентября patch.
[Changelog производителя](https://cryptography.io/en/latest/changelog/#v50-0-2)
указывает wheel OpenSSL 4.0.3; это отдельное реальное package difference,
не скрытое под формулировкой «поменялась только PyJWT». Полный dependency lock
остаётся воспроизводимостью следующего build, не ретроактивной гарантией.

Пересоздан только собственный pilot backend, DB head/env кроме build SHA/
соседние контейнеры/OTA hashes сохранены. PyJWT **2.15.1** подтверждена внутри
работающего контейнера; login, auth-me со старым access token, browser session
и встроенная Grafana работают. Browser: WEB 4024ccf8 / API 85c8014e.

Начальная проверка 21:38:10–21:39:10 не прошла критерий непрерывности
(14 → 11 → 14 → 12 online). Последующая bounded read-only проверка требовала
session date после backend StartedAt и heartbeat <45 s: семь срезов
21:40:40–21:41:40 — все 14 baseline devices. Первый failure сохранён;
это recovery acceptance, не uptime/stream/scripts/OTA acceptance. В сохранённом
backend interval нет raw RecursionError/InvalidSignatureError/traceback, но
сохранились 26 unknown OTA receipts и две send warnings. Они не замаскированы
или ACKed. Даты и next gates — в [CURRENT-STATE](../../operations/CURRENT-STATE.md).
