# CI web: registry provenance и диагностика упаковки

Срез 10 октября 2026, UTC+5. Source correction; рабочий UI не переустановлен.

Frontend CI 37991408319 для 2550a61b в двух попытках прошёл Jest, TypeScript,
production build и HTTP probe: 26 страниц, 73 client assets. Упаковка Docker
завершилась сообщением `docker failed (1)`. Произвольный stderr намеренно не
публиковался, поэтому конкретная причина этого отказа UNKNOWN. Успех build
не означает успешную упаковку или установку image.

В соседнем backend CI того же периода Docker Hub 429 доказан отдельно:
[отрицательные результаты и provenance](CI-REGISTRY-LIMIT.md). Это основание
убрать зависимость упаковки web от общего Hub quota, но не доказательство,
что именно 429 вызвал оба frontend отказа.

## Изменение и происхождение

frontend_review.Dockerfile использует прежний закреплённый Docker Official Node
image через официальный Amazon ECR Public namespace. OCI index digest остался
`sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20`.
Raw index ECR прочитан без загрузки layers; Linux/amd64 descriptor:
`sha256:51b1100cc2a83d370c6a60952e3f2989c8a43159d0e38586e090f3b3326efefd`.
Таким образом, registry origin изменён, закреплённое содержимое не заменено.
[Docker publisher](https://gallery.ecr.aws/docker/) ·
[ECR Public pull](https://docs.aws.amazon.com/AmazonECR/latest/public/docker-pull-ecr-image.html).
Mirror также имеет quotas; его безусловная доступность не обещается.

Packaging command сохраняет прежние timeout и 256 KiB output budget. При отказе
публикует только exit code и классификацию: timeout, output_budget,
program_unavailable, registry_rate_limit либо unclassified. Произвольные
stdout/stderr, environment и error message в сообщение не включаются.

Три Node regression tests проверяют классы и отсутствие private content.
Синтаксис packaging module проверен. Следующий exact-source CI должен снова
пройти тесты, standalone probe, packaging и admission; этим source-отчётом
успех нового workflow не объявляется. Local Docker build/prune не выполнялись.

## Откат и дальнейшая диагностика

Откатить отдельный CI commit; рабочие containers/volumes не затрагивать.
При повторном unclassified отказе изучить ограниченный private diagnostic slice
в CI и добавить конкретный безопасный classifier, если причина доказана.
Не ослаблять artifact hash/source/run/attempt admission ради успешной доставки.

[Текущий статус](../../operations/WORK-STATUS.md).
