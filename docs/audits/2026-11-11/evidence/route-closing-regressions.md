# Целевой прогон Route Studio на 38b342de

Проверены рабочие исходники на `38b342de`. Все сценарии локальные и используют тестовые данные.

| Прогон | Результат |
|---|---|
| Jest `image-route-review.test.tsx`, `route-preparation.test.ts`, `teaching-review.test.tsx` | 3 suites, 68/68 passed |
| Pytest `test_image_route_review.py`, `test_image_route_workspace.py`, `test_reconstruct_route.py`, `test_route_only_recovery_pipeline.py` | 56 passed, 2 failed, 1 skipped. Оба отказа `RuntimeError: resource_guard`, находка `commit_headroom_low`. Symlink пропущен по привилегиям Windows. |
| Повтор двух падавших случаев с фиксированным допустимым снимком Windows | 2 passed. Подменён только `reconstruct_route.collect`. Настоящая проверка ресурса и утверждения декодера выполнились. |

При двух отказах свободный commit составлял около 12,83 и 12,66 ГиБ, свободная физическая RAM около 9,16 и 9,05 ГиБ. Защита проверяет процент Windows commit независимо от свободной RAM. В контроле заданы 42/80 ГиБ commit, 20/64 ГиБ доступной/общей RAM и 60 ГиБ свободного диска, статус тома `Healthy/OK`. Ни реальная загрузка модели, ни системные настройки не изменялись.
