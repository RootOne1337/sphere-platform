# Переустановка Windows: код, данные и восстановление Sphere

Проверено 2 ноября 2026 на текущем Windows/Docker Desktop. Основной путь —
**скачать код из GitHub и автоматически создать новый локальный стенд**.
Второй путь — восстановить прежние данные в отдельную установку из закрытого
пакета на SSD. Репозиторий публичный; базы, профили, пароли, чаты и архивы в него
не входят. Все описанные ниже текущие копии пока находятся на C:.

## 1. Новая установка с пустыми данными

Нужны Git, работающий Docker Desktop с Linux containers и Windows PowerShell 5.1
или PowerShell 7. Для сборки Node/Python устанавливаются внутри образов; отдельный
Node на Windows не требуется. Для импорта дампов нужен Python 3.12 или новее.
Compose должен поддерживать `!override` (2.24.4 или новее).

На новой Windows установите Git и Docker Desktop, запустите Docker Desktop и
дождитесь готовности Engine. Если установка WSL/Docker потребовала перезагрузку,
завершите её до запуска Sphere. Выберите каталог на SSD с запасом: установщик
проверяет свободное место и сохраняет минимум 12 GiB на рабочем томе во время
сборки. Для source build он требует 20 GiB перед стартом. Расположение файлов
Docker Desktop на диске задаётся отдельно от расположения Git checkout.

Текущая рабочая версия проекта находится в ветке
`codex/enterprise-audit-20260905`; **обычный clone ветки main не равнозначен ей**.

```powershell
git clone --branch codex/enterprise-audit-20260905 --single-branch https://github.com/RootOne1337/sphere-platform.git
cd sphere-platform
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/new-install.ps1 -Mode New -AdminEmail owner@example.com
```

Замените email на свой. После завершения откройте `http://127.0.0.1:28080/login`.
Установщик сам создаёт PostgreSQL/Redis/MinIO, применяет миграции, создаёт первого
администратора и enrollment key, запускает backend/frontend/nginx/n8n и проверяет
вход через API. Случайный пароль хранится в закрытом
`.local-pilot/new-installs/<имя-проекта>/admin.env`; путь выводится в конце.
Публичная самостоятельная регистрация не требуется для первого администратора.

Порты по умолчанию: Web 28080, n8n 25678, S3 29000, MinIO Console 29001; они
доступны только на этом ПК. Параметры `-GatewayPort`, `-N8nPort`, `-S3Port`,
`-S3ConsolePort` позволяют выбрать другие свободные порты. Существующие проекты
и тома установщик не принимает и не перезаписывает. Повторный `New` создаёт ещё
один стенд: для уже созданного используйте управление ниже.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/manage-install.ps1 -InstallDirectory '.local-pilot/new-installs/<имя-проекта>' -Action Status
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/manage-install.ps1 -InstallDirectory '.local-pilot/new-installs/<имя-проекта>' -Action Start
```

`Stop` останавливает только выбранную установку и сохраняет её тома. Управление
предназначено для законченной установки; при неполном bootstrap нужно разобрать
сохранённые private logs. Пароли/`install.env` не помещайте в issue, Git или чат.

## 2. Сохранить прежние данные на подключённый SSD

Эта команда предназначена для **нынешнего pilot-хоста**, где ещё работают
`sphere-pilot-20260911-*` и доступны локальные записи. Подставьте букву SSD
и новый, ещё не существующий каталог:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/export-to-ssd.ps1 -Destination E:\SphereRecovery-20261102
```

По умолчанию сохраняются:

- Git history и рабочие исходники, включая неотправленные файлы, без временной сборки;
- PostgreSQL `sphereplatform` и `n8n`, роли/права и pilot volumes;
- прежние encryption keys и effective container configuration, настройки хоста,
  SSH, Cloudflared, Tuna, найденные конфигурации Amnezia/Proxifier и задачи Windows;
- исходные видео и входы reconstruction jobs, небольшие метаданные, их SQLite;
- найденная локальная библиотека записей Yandex для origin 3015, включая незавершённые;
- последние APK и найденные signing/configuration files из профиля essential;
- выбранные журналы и квитанции разработки (с явными лимитами и исключениями);
- журналы разговоров, SQLite snapshots, настройки и пользовательские навыки Codex.

`-IncludeImages` дополнительно сохраняет точные работающие Docker images;
`-IncludeModelsAndOldApks` включает большой профиль с прежними APK и моделями.
`-SkipCodex` или `-SkipBrowserData` — осознанное исключение этих данных.
`-Plan` показывает состав без записи. Архивы закрытые: используйте личный
защищённый накопитель. Скрипты устанавливают private ACL на NTFS; SHA-256 проверяет
целостность, но не заменяет шифрование и не удостоверяет источник manifest.

Размеры текущих проверенных копий, округлённо:

| Слой | Размер | Что подтверждено |
|---|---:|---|
| Pilot DB/volumes | 114 MB | Дампы читаются; обе базы восстановлены, роли и ACL проверялись в отдельной копии |
| Essential config/последние APK | 143 MB | 452 исходных пути; 403 blobs прочитаны и проверены |
| Входы маршрутов | 479 MB | Все 14 `input/video.h264`, входы и малые метаданные |
| SQLite маршрутов | 651 MB | 20 SQLite snapshots, quick_check и повторная проверка SHA |
| Yandex origin 3015 | 525 MB в ZIP | 581 файл; 23 директории записей, 9 без COMPLETE; согласованность живого LevelDB не доказана |
| Codex | 5.40 GB в ZIP | 543 файла с проверкой SHA; история содержит ранее повреждённые записи, см. отдельный раздел |
| Точные running images, опция | 1.41 GB | 12 образов, 14 исходных контейнеров; tar/SHA проверены |

Это разные слои с возможными дубликатами, а не расчёт точного размера следующего
экспорта. 35 GB, обсуждавшиеся в начале, были **свободным местом на C:**.
Большая часть 104 GiB обследованного `.local-pilot` — другие сборки, окружения,
модели, промежуточные результаты и прежние копии. Essential не переносит их все;
исключения перечислены в [DATA-RECOVERY.md](DATA-RECOVERY.md). Для полного
сохранения всех экспериментов предусмотрите отдельную копию исходного каталога
на SSD; считать все исключённые производные файлы воспроизводимыми нельзя.

Экспорт не останавливает приложения: PostgreSQL dumps согласованы каждый внутри
своей базы, но разные базы и live volumes не образуют общий атомарный снимок.
Перед окончательным переносом нужен согласованный финальный cutover; браузер и
Codex следует окончательно сохранить после полного закрытия. RAID и копия на
том же C: не защищают от стирания этого диска при переустановке.

## 3. Скачать код и подключить прежние данные

После clone той же версии и подключения SSD не накатывайте дамп поверх новой
пустой установки. Восстановите **ещё один новый проект**; он сам использует
оригинальные ключи из закрытого снимка и не запускает migrations/новый enrollment:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/new-install.ps1 -Mode Restore -Snapshot E:\SphereRecovery-20261102\data
```

Если порт 28080 занят созданным ранее пустым стендом, остановите тот стенд через
`manage-install.ps1`, либо выберите свободный `-GatewayPort` и три остальных
порта. Вход — старой учётной записью. Восстановительный стенд изолирован от
настоящих устройств и внешних workflow; n8n, VPN и туннели автоматически не
включаются. Сначала сверяются данные. Для возврата браузерной библиотеки
существенен прежний origin; перенос `3015 → 28080` сам по себе не переносит OPFS.

Файлы, которые не лежат в PostgreSQL, импортируются отдельно, сначала в новый
временный каталог для осмотра:

```powershell
python scripts/migration/import_local_state.py E:\SphereRecovery-20261102
python scripts/migration/import_local_state.py E:\SphereRecovery-20261102 --apply
```

Первая команда строит read-only план, вторая добавляет проверенные route files
в `.local-pilot` нового checkout; отличающиеся существующие файлы не перезаписывает.
Worker 3342 должен быть остановлен до импорта. `--include-private-config` явно
включает прежние private files под `.local-pilot`; настройки реестра Windows и
`.android` этот инструмент не импортирует. Ключи не подменяйте вновь
сгенерированными. Особенности восстановления SQLite и browser
пакетов описаны отдельно; их нельзя вслепую распаковывать поверх живого профиля.

Переход к внешним агентам требует прежнего reachable URL/DNS/TLS, подходящих
туннелей, состояния VPN-router и согласованности refresh tokens. Это отдельный
cutover после локальной приёмки, а не следствие HTTP 200:
[AGENT-AND-VPN-REJOIN.md](AGENT-AND-VPN-REJOIN.md),
[INFRASTRUCTURE-RESTORE.md](INFRASTRUCTURE-RESTORE.md).

## 4. Дополнительный локальный обработчик Route Studio

Compose не устанавливает Windows worker на 3342. Для него нужны Python 3.12 и
дополнительные инструменты/веса по описанию [SOURCE-HANDOFF.md](SOURCE-HANDOFF.md).
Сначала посмотрите план, затем на новой машине создайте окружения:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/setup-route-runtime.ps1 -Plan
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/migration/setup-route-runtime.ps1 -Install -BrowserOrigin http://127.0.0.1:28080
```

`-InstallTask` явно добавляет задание при входе в Windows и не заменяет уже
существующее. Модели, COLMAP/Brush/OpenMVS и результаты обучения не скачиваются
скрытно. Наличие worker не означает приёмку автономного движения или обучения.

## 5. Где хранятся Codex и чаты на этом компьютере

Официальная документация определяет `CODEX_HOME`, по умолчанию `~/.codex`, как
каталог локального состояния: [Config and state locations](https://learn.chatgpt.com/docs/config-file/config-advanced).
Фактически на этой машине:

- `C:\Users\dimas\.codex` — локальные данные; `sessions` и `archived_sessions`
  содержат журналы, `state_5.sqlite` — реестр, `thread_history_1.sqlite` —
  представление истории, `.codex-global-state.json` — состояние интерфейса;
- `C:\Users\dimas\AppData\Roaming\Codex` — профиль приложения и встроенного браузера;
- `C:\Program Files\WindowsApps\OpenAI.Codex_26.1027.3384.0_x64__2p2nqsd0c76g0`
  — установленное приложение; это не папка разговоров;
- runtime пакета имеет отдельный каталог `OpenAI.CodexPrimaryRuntime...`;
  сохранение бинарников вместо `.codex` не сохраняет чаты.

`backup_codex.py` сохраняет разговоры и настройки, делает SQLite online backups,
а при повреждении также сохраняет физические live main/WAL/SHM для исследования.
Auth tokens и browser cookies не переносит: после установки потребуется вход.
Профиль Electron и локальные чаты не являются одним файлом. Официальный
поддерживаемый импорт этих SQLite в любую будущую версию приложения не установлен.

В текущей истории повреждены две исходные строки; подготовлен отдельный
**частичный** кандидат со 173 964 проверенными строками и приватным карантином.
Он не установлен. Сохранены исходный snapshot, физические raw files, журналы и
receipts: [CODEX-HISTORY-RECOVERY.md](CODEX-HISTORY-RECOVERY.md).
На новой Windows сначала устанавливают приложение, закрывают его и проверяют
восстановление в изолированном профиле подходящей версии. Старые абсолютные
пути проектов/журналов и доступы могут потребовать исправления. Активную базу
работающего Codex заменять нельзя.

## Проверенные результаты и оставшиеся границы

Полные New и Restore прошли в отдельных проектах Docker. Исходные образы один
раз собраны из рабочего дерева; окончательные пути запуска повторно проверены
с ними. Новая установка: миграции, администратор, enrollment, readiness и API
login. Восстановление: обе базы/роли/volumes, старый пароль, те же user/org IDs,
21 устройство, цвет одной группы, 61 сценарий и все version/DAG-поля,
10 VPN-профилей; 19/19 зашифрованных VPN revisions расшифровались.
Подробности: [RESTORE-API-OBSERVATION.json](RESTORE-API-OBSERVATION.json).
Стенды остановлены; основной pilot продолжает работать.

Это не полная production-приёмка: внешний VPN/DNS/TLS/туннели, реальное
переподключение Android, браузерный импорт OPFS, n8n credentials и новая Windows
ещё не приняты. В исходном n8n наблюдались 0 credentials и 0 workflows, MinIO
имел 0 buckets/objects: совпадение пустого хранилища не доказывает восстановление
непустого. Background workers могут менять восстановленную рабочую копию.

Веб: [WEB-COVERAGE.md](WEB-COVERAGE.md) — 29 файловых маршрутов, 22 посещены,
7 вкладок и 2 диалога проверены безопасно; 665 JSX controls учтены эвристически.
Нажатие каждой меняющей данные кнопки не выполнялось. Условные source findings
остаются в [реестре аудита](../../audits/2026-11-01/FINDINGS-REGISTER.md).
Полный состав данных, отдельные 85 Docker volumes и неохваченные другие проекты:
[DATA-RECOVERY.md](DATA-RECOVERY.md). Браузерные данные:
[BROWSER-LOCAL-DATA.md](BROWSER-LOCAL-DATA.md).
