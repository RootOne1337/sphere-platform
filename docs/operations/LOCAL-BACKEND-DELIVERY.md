# Локальная упаковка и установка backend

16 октября 2026. Поддерживает обновления без изменения зависимостей, схемы SQL, bootstrap и RBAC.
Это отдельный путь происхождения артефакта; локальный прогон не выдаётся за GitHub-hosted CI.
Наличие инструмента не подтверждает, что конкретная поставка уже выполнена.

## Проверки перед поставкой

1. Коммит находится в доверенной основной рабочей ветке. Полный backend-профиль
   [local_ci.py](../../scripts/pilot/local_ci.py) выполняется на отдельном Git snapshot с временными
   PostgreSQL/Redis. Результат публикуется на точный SHA в GitHub через commit status API.
2. [package_local_backend.py](../../scripts/pilot/package_local_backend.py) проверяет успешную квитанцию,
   оригинальный JUnit, обязательные шаги, завершение временных сервисов и актуальный GitHub status.
3. Родительский образ берётся из здорового установленного API. Все его упакованные файлы сверяются
   с Git. Экспорт исходников отключает Windows autocrlf. Изменение dependency/schema/bootstrap
   или удаление исходника требует отдельной полной сборки и этим инструментом не допускается.
4. Новый образ сохраняет dependency layers, копирует канонический backend и получает новый SHA
   и `io.sphere.local.run`. Старые CI labels очищаются. Build network отключена; pip не запускается.
5. Сверяются все файлы нового образа; выполняются настоящие packaged runtime и multiprocess metrics
   probes на временных контейнерах, без host ports и production source mounts. Live SQL не мигрирует.
6. Квитанция привязана к image ID, исходникам и хешам отчётов. Docker archive на этом же ПК не создаётся.
   Исчезнувший image нельзя заменить неподтверждённым архивом: его нужно пересобрать и проверить.

## Команды

Сначала сохранить изменения в основной ветке, получить полный SHA и выполнить backend CI:

```powershell
.venv-audit/Scripts/python.exe -m scripts.pilot.local_ci `
  --sha FULL_COMMIT_SHA --profiles backend --publish
```

Сохранить `runId` успешного результата. Значения ниже заменяются фактическими SHA и ID:

```powershell
.venv-audit/Scripts/python.exe -m scripts.pilot.package_local_backend `
  --source FULL_COMMIT_SHA --expected-current-source INSTALLED_API_SHA `
  --execution .local-pilot/local-ci/runs/RUN_ID/receipt.json `
  --output .local-pilot/local-backend-FULL_COMMIT_SHA
```

Упаковка не устанавливает образ. Для плана, затем применения используется существующий installer:

```powershell
.venv-audit/Scripts/python.exe -m scripts.pilot.install_reviewed_backend `
  --local-artifact --artifact .local-pilot/local-backend-FULL_COMMIT_SHA `
  --source FULL_COMMIT_SHA --expected-current-source INSTALLED_API_SHA `
  --expected-image-id sha256:VERIFIED_IMAGE_ID
```

Применение добавляет `--apply`. При сохранении действующих direct grants и mDNS передаются те же
явные параметры, что и в прежней поставке; они сверяются с полным Compose baseline. Этот пример
не является готовой командой для изменения разрешений устройств.

## Границы установки

Installer допускает только смену образа своего backend и отдельно проверенные transport settings.
Остальные контейнеры, env/secrets, mounts, схема SQL и OTA-каталог должны сохраниться. После замены
проверяются health, оба опубликованных адреса и schema head. При ошибке возвращается предыдущий
образ backend; SQL rollback не выполняется. Для локального пути автоматическое удаление старых
image/archive не запускается; предыдущий образ остаётся доступен для отката.

Локальные успешные тесты видны в GitHub у коммита. Они не расходуют GitHub-hosted runner minutes;
обращения к GitHub API не являются запуском Actions. Это ещё не перенос всех существующих workflows
и не автоматическое отключение остальных hosted pipeline.

Новый APK имеет отдельную подпись, приёмку и OTA-поставку. Этот backend-инструмент его не устанавливает.
Моторная модель, GPU inference и игровой ввод также не запускаются упаковкой API.
