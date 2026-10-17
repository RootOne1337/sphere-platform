# CI: Docker Hub 429 и проверенные official-image digests

10 октября 2026, UTC+5. Source correction, не installed receipt.

Backend run 37990900646 для 6fa5a15b завершился до тестов в двух попытках:
PostgreSQL service pull получил unauthenticated pull rate limit; Python base
manifest HEAD вернул 429. Lint/mypy, security и RLS jobs прошли. Прогон тестов
и production image этим отрицательным результатом не подтверждены.

Исправление CI использует Docker Official Images из Docker publisher namespace
в Amazon ECR Public, закреплённые за Linux/amd64 manifest digest. Это официальный
mirror, а не сторонняя пересборка. [Docker publisher gallery](https://gallery.ecr.aws/docker/),
[ECR Public pull documentation](https://docs.aws.amazon.com/AmazonECR/latest/public/docker-pull-ecr-image.html).
У ECR также есть quotas: замена не гарантирует безотказность любого registry.

## Проверка происхождения перед изменением

Прочитаны raw OCI indexes Docker Hub и ECR для каждого тега. Linux/amd64
descriptor совпал побайтово по digest на обоих registries:

| Docker Hub tag | Manifest SHA-256, закреплён в CI |
| --- | --- |
| python:3.12-slim | 2b4f19dae3a777dfc3b76730bda1e82e1f66ab2a2686fa93ca78edbfb4f04ffe |
| postgres:15-alpine | 25d430274d8a31184f9435cc5b2f56aff254952065bbbcac0c51acedb5a1d1e7 |
| redis:7.2-alpine | 84bab713067f5494d94c24e99ae3fa3ae2388c037152edcbcf301f7cfaeb3048 |

Команда чтения: docker buildx imagetools inspect --raw IMAGE:TAG.
Сравнение относится к этому срезу, а не ко всем будущим значениям mutable tags.
Не скачивались layers и не менялась локальная Docker registry конфигурация.
Первый рекурсивный metadata inspect ECR сам получил rate exceeded; чтение одного
raw index вместо всех архитектур прошло. Успех полного CI ещё требуется.

## Граница изменения

backend/Dockerfile получил PYTHON_BASE_IMAGE ARG со старым default python:3.12-slim.
CI передаёт проверенный ECR digest; обычная сборка без ARG сохраняет прежний выбор.
CI PostgreSQL/Redis services используют проверенные digests. Изолированные runtime
и init probes читают SPHERE_AUDIT_POSTGRES_IMAGE/SPHERE_AUDIT_REDIS_IMAGE из job env;
локальные defaults и ограничения owned containers/networks/volumes сохранены.
Рабочие PostgreSQL/Redis, схема, credentials, requirements и action contract не менялись.
Reviewed API installer допускает проверенные две строки Dockerfile; все остальные
dependency/schema/source fences остаются. New artifact требует полного CI и bootstrap.

## Обновление и откат

При обновлении сначала сверить raw indexes обоих official registries для выбранных
версий и архитектуры. Поменять digests в одном review вместе с этим provenance,
затем выполнить весь image bootstrap, init/restart, four-worker, unit/real-service CI.
Один digest не переносить между разными image names или CPU architectures.
Для отката исходников вернуть отдельный CI commit; runtime откатывать только через
проверенный предыдущий image, а не изменением работающих database volumes.

[Broadcast source audit](BROADCAST-BINARY-PRESENCE.md) ·
[Действующий статус](../../operations/WORK-STATUS.md).
