# CI: isolated gateway image и оставшиеся registry pulls

10 октября 2026, UTC+5. Дополнение к [registry provenance](CI-REGISTRY-LIMIT.md).

Backend CI 37991408378 для 2550a61b прошёл 3427 tests и 252 subtests,
37 skipped; coverage 80.92%. Новый настоящий PostgreSQL/Redis broadcast test
прошёл. Единственный failure: Docker run изолированного upstream Nginx вернул
125 до проверки gateway. Произвольный stderr в старом результате не сохранён;
причина конкретно этого отказа UNKNOWN, 429 ему не приписывается.
Production image bootstrap, lint/mypy, security и RLS прошли. Полный CI не зелёный,
этот image для рабочей установки пока не допущен.

Проверены все image pulls в test/probe helpers. Gateway test теперь читает
SPHERE_AUDIT_NGINX_IMAGE; прежний локальный default nginx:alpine сохранён.
Raw OCI indexes Docker Hub nginx:alpine и Docker Official ECR mirror прочитаны:
совпадающий Linux/amd64 manifest
`sha256:0530961ff0592b58c10f767535cc0abdfccf9e389ff7cc90f87320c1bc7e8506`.
CI закрепляет этот ECR digest. При ошибке test печатает только операцию,
exit code и registry_rate_limit/unclassified; arbitrary output не публикуется.

Redis memory probe также принимает уже проверенный SPHERE_AUDIT_REDIS_IMAGE
из CI вместо дополнительного mutable Hub pull. Compose-derived command,
password, memory/swap cap, pressure/persistence assertions и cleanup сохранены.
Обычный default остаётся image из Compose. Рабочие Redis/Nginx и volumes не менялись.

Нужен новый exact-source CI, включая gateway, Redis memory/persistence probe,
Alembic и image bootstrap. Старый source audit не переписывается как зелёный.
[Текущий статус](../../operations/WORK-STATUS.md).
