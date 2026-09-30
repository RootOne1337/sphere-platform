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
