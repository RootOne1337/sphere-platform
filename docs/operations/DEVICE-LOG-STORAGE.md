# Хранение полученных Android-журналов

Обновлено 6 октября 2026, Asia/Yekaterinburg. Область: файлы upload `/logs/upload`,
а не Docker stdout, Logcat, PostgreSQL, Windows-диск или все события платформы.

## Путь и жизненный цикл

Full, production и local-pilot Compose задают `SPHERE_LOGS_DIR=/var/lib/sphere/device-logs`
и один project-scoped named volume `device_logs` на этот путь. Production image
создаёт каталог с владельцем UID1001 заранее: Docker копирует его permissions при
инициализации нового пустого тома. Метрики `/tmp/sphere-metrics` остаются отдельным
bounded tmpfs; OTA-том не меняется. Внешний путь не принимает HTTP-параметры.

Restart/recreate контейнера сохраняет том. `docker compose down -v`, удаление тома
и потеря host storage уничтожают историю; named volume не заменяет backup/restore.
Запуск backend вне этих Compose без `SPHERE_LOGS_DIR` сохраняет прежний временный
fallback `/tmp/sphere_device_logs`; это не production storage policy.

## Перенос существующего временного каталога

Добавление пустого mount не переносит старые файлы автоматически. Сначала проверить
актуальные image/container IDs, путь и отсутствие перекрывающего mount; подготовить
и проверить новую конфигурацию/образ, rollback и соседние контейнеры.

1. Graceful stop только backend: дождаться остановки всех writer workers.
2. Скопировать каталог из **остановленного** контейнера в приватный staging;
   проверить число файлов, byte budget, отсутствие symlinks и SHA256 каждого файла.
3. Сохранить этот staging как rollback archive. Не публиковать device IDs/содержимое.
4. Создать отдельный project-scoped том. Переносить только в подтверждённо пустой
   том, ограниченным helper без сети; установить UID1001 и сравнить все hashes.
5. Только после проверки заменить backend с новым mount. Не удалять staging/том.
6. Проверить ready/build, сохранность исходных byte prefixes, права non-root writer,
   authenticated GET и новую upload активность. Контроль количества online отдельный.

Если ошибка возникла до recreate, запустить прежний контейнер: его filesystem
сохранён. После recreate rollback использует прежний image **с новым постоянным
mount/path**, чтобы не потерять поступившие после переключения строки. Возвращение
к `/tmp` без обратного переноса не является безопасным rollback.

## Открытые ограничения

Текущая upload policy ограничивает body после buffering, вращает дневной файл после
50 MiB и удаляет старые файлы только при новом upload. Это не глобальный per-org/disk
budget или независимый retention sweeper. Concurrency rotation, forecast/drop
counters, multi-replica shared storage и backup/restore приёмка ещё открыты.
EP-033 остаётся OPEN. Необъяснённое уменьшение свободного Windows C: этим не закрыто.

[Контракт ограниченного reader](../audits/2026-10-06/DEVICE-LOG-READ-BUDGET.md) ·
[Приоритеты и открытые gates](../audits/2026-10-06/ENTERPRISE-PRIORITIES.md) ·
[Актуальная установка](CURRENT-STATE.md).
