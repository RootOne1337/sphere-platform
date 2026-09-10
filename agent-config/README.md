# Конфигурация Android-агента

**Текущий контракт: AUD-74, 10 сентября 2026.** Здесь находятся шаблоны,
конфигурации окружений и генератор JSON. Они помогают подготовить provisioning;
успешная генерация файла не подтверждает enrollment или ёмкость парка.

[APK guide](../docs/android-agent.md) · [Сохранённый резерв](../docs/architecture/ANDROID-SAVED-ROUTES.md) ·
[Discovery](../docs/architecture/ANDROID-DISCOVERY-RECOVERY.md) · [Readiness](../docs/operations/READINESS.md)

## Файлы

| Путь | Назначение |
| --- | --- |
| `environments/{development,staging,production}.json` | Вход генератора; имя production само по себе не подтверждает пригодность настроек |
| `schema.json` | Формат полного bootstrap-конфига; генератор проверяет только required fields и префикс ключа |
| `templates/ldplayer-clone.json`, `templates/physical-device.json` | Примеры полного конфига |
| [templates/lan-routes.json](templates/lan-routes.json) | Только адреса для уже зарегистрированного APK; без bootstrap credentials |
| `scripts/generate_device_config.py` | Отдельный Python CLI; проверка запуска через конкретный PC-agent/ADB ещё требуется |

## Основной и резервный адрес

```json
{
  "server_url": "https://sphere.example.internal",
  "fallback_server_url": "https://sphere-backup.example.internal"
}
```

Замените примеры адресами **одной установки** с общими identity/SQL/ключами.
APK сохраняет пару и перебирает её для WS и refresh без доступности GitHub.
Новый маршрут становится активным только после `auth_ok` нужного устройства.
Discovery не отключает рабочий WS. Отсутствующий/null fallback в обновлении
сохраняет старый резерв; явное новое provisioning через `saveServerRoutes`
заменяет пару. Откат серверной config version пока не реализован.

Уже зарегистрированный агент читает route-only MDM/файл при старте сервиса.
Для MDM используются `sphere_server_url` и `sphere_fallback_server_url`.
Файловые источники: `/sdcard/sphere-agent-config.json`, затем external files и
internal files приложения. MDM имеет приоритет; доступ к файлу зависит от Android
storage/permissions. Изменение локального файла не означает немедленный hot reload.

## Начальная регистрация

Незарегистрированному APK нужен действующий ключ. JSON принимает `api_key` либо
`enrollment_api_key`; MDM — `sphere_api_key`. HTTP config дополнительно передаёт
`features.auto_register`. Проверьте реальные grants ключа и server enrollment
policy; префикс `sphr_` не доказывает его разрешения.

Из корня `agent-config`, после настройки `environments/development.json`:

```bash
python scripts/generate_device_config.py --env development --workstation-id ws-PC-FARM-01 --count 10 --start-index 0 --location lab --output-dir ./output
```

В режиме `--count 1` используйте `--instance-index` без workstation ID либо
`--start-index` вместе с ним: текущий CLI выбирает индекс по этому правилу.
Генератор переносит `fallback_server_url` из окружения. Аргумент `--template`
не реализован; файлы в `templates/` являются примерами для ручной подготовки.
Доставка конфигураций через ADB и запуск APK — отдельные операции оператора.

SetupActivity сначала пытается зарегистрироваться с переданным ключом, затем
может перейти к legacy API-key пути. Фоновые workers имеют отдельные условия
выбора enrollment/static-key пути; полностью unattended provisioning требует
отдельного runtime drill. Новые tests подтверждают перенос полей генератором и
разбор APK, а не полный запуск клона. Пара маршрутов сохраняется независимо от
credentials; при успешной регистрации APK сохраняет использованный request URL,
а иной advertised URL становится кандидатом, если явный резерв не задан.

## HTTP discovery после регистрации

`GET BuildConfig.CONFIG_URL` публичный, без device credentials, с HTTP budget
10 s и ограничением body 64 KiB. Watchdog делает первую проверку через 5 s,
затем через 120 s connected / 60 s disconnected. Поле
`config_poll_interval_seconds` парсится, но пока не управляет этим расписанием.
`config_version` не является применяемой APK durable revision.

Enterprise CONFIG_URL задаётся при сборке, по умолчанию пуст; dev использует
GitHub Raw. Список нескольких HTTP discovery источников ещё не реализован.
Backend `/api/v1/config/agent` читает файл, выбранный его настройками, с кешем:
изменение GitHub файла не означает мгновенного обновления всех APK/backend.

Bootstrap-файлы могут содержать секрет регистрации. Нет обещания автоматического
удаления файла или ключа из всех источников после enrollment. Проверяйте Android
TLS/flavor/pinning и храните конфигурацию как часть управления установкой.
Чтение локального файла пока использует `readText().take(...)`; HTTP body limit
не ограничивает память этого файлового пути.

## Проверено и открыто

- Генератор: сохранение optional fallback, включая legacy отсутствие поля.
- APK: route-only MDM/файл, generated enrollment key, переключение WS/refresh,
  сохранение пары, late callbacks, отказ двух адресов и client pin mapping.
- Backend: публичный optional fallback и retry потерянного refresh response через
  другой ASGI origin с реальным PostgreSQL commit.

Физические OS/network/fleet drills, enrollment response loss, полный фоновый
provisioning, durable config rollback и инфраструктурная HA остаются открытыми.
Доказательства и точные ограничения: [AUD-74](../docs/audits/2026-09-05/AUDIT-REPORT.md).
