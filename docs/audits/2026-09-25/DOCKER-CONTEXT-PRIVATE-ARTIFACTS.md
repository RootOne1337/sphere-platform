# AUD-174 · Приватные pilot-файлы попадали в Docker build context

**Дата:** 25 сентября 2026 · **Severity:** P2 · **Статус:** корневая причина исправлена; Docker probe и CI regression добавлены.

[Docker context probe](../../../tests/containers/dockerignore_probe.py) · [Local pilot](../../operations/LOCAL-PILOT.md) · [Документация](../../README.md)

## Наблюдение и воздействие

`.gitignore` исключал `.local-pilot/`, но корневой `.dockerignore` этого не делал. Git ignore не управляет Docker build context. Поэтому при сборке backend или другого image из корня репозитория локальные APK-кандидаты, сырые runtime-логи, конфигурационные и test-evidence файлы могли быть переданы Docker daemon или удалённому BuildKit builder. Если такой каталог содержит чувствительные данные, их границу определяет только Docker ignore-файл.

В этом проходе root-context image до исправления не собирался; доказательств фактической передачи приватных данных нет. Frontend smoke image собирался с `frontend/` как контекстом и не включал `.local-pilot/`.

## Reproduction и fix

Регрессионный probe создаёт в `.local-pilot/` синтетический sentinel и временный Dockerfile с `COPY` этого файла. До исключения в `.dockerignore` сборка могла бы скопировать sentinel. После fix Docker сообщает, что source недоступен в контексте, и probe проходит. Sentinel содержит только тестовый текст и удаляется в `finally`.

Корневой `.dockerignore` теперь исключает `.local-pilot/`. Тот же probe запускается в CI перед production image build, где build context берётся из корня репозитория.

## Проверка и residual risk

- `python tests/containers/dockerignore_probe.py` проверяет фактическое поведение Docker BuildKit, а не только наличие строки в ignore-файле.
- Ни один APK, credential, raw log или локальный pilot evidence намеренно не передавался в этот probe.
- Исключение действует только на Docker build context. Оно не заменяет управление доступом к локальной папке, очищение других build-context путей или контроль содержимого образов.
