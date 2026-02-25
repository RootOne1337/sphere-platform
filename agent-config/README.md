# Sphere Agent Config Repository

> Централизованное хранилище конфигураций для автоматического provisioning Android/PC агентов.  
> Используется при zero-touch enrollment 1000+ устройств.

## Структура

```
agent-config/
├── README.md                    ← этот файл
├── schema.json                  ← JSON Schema для валидации конфигов
├── environments/
│   ├── production.json          ← боевой конфиг
│   ├── staging.json             ← тестовый стенд
│   └── development.json         ← локальная разработка (10.0.2.2)
├── templates/
│   ├── ldplayer-clone.json      ← шаблон для PC-Agent при клонировании
│   └── physical-device.json     ← шаблон для реальных телефонов
└── scripts/
    └── generate_device_config.py ← генератор конфигов для массового деплоя
```

## Использование

### 1. Автоматический enrollment (LDPlayer клоны)

PC-Agent при клонировании эмулятора:
1. Читает `environments/{env}.json` → получает `server_url`, `enrollment_api_key`
2. Генерирует `sphere-agent-config.json` для конкретного инстанса (с `instance_index`, `workstation_id`)
3. Пушит конфиг через `adb push` в эмулятор
4. Агент при загрузке находит конфиг → auto-enrollment → WS подключение

### 2. Ручной enrollment

```bash
# Сгенерировать конфиг для конкретного устройства
python scripts/generate_device_config.py \
  --env production \
  --workstation-id ws-PC-FARM-01 \
  --instance-index 42 \
  --location msk-office-1

# Запушить в эмулятор
adb -s emulator-5554 push output/sphere-agent-config.json /sdcard/sphere-agent-config.json
```

### 3. Android Agent — цепочка обнаружения конфига

```
1. EncryptedSharedPreferences (уже enrolled)
2. Android Enterprise Managed Config (MDM)
3. /sdcard/sphere-agent-config.json            ← adb push
4. <appExternalFiles>/sphere-agent-config.json
5. <appInternalFiles>/sphere-agent-config.json
6. HTTP Config Endpoint (BuildConfig.CONFIG_URL) ← НОВОЕ
7. BuildConfig baked-in defaults
```

## Безопасность

- `enrollment_api_key` (`sphr_enroll_*`) имеет **только** право `device:register` — не может управлять устройствами
- Конфиг не содержит секретов пользователей — только enrollment ключи
- HTTPS обязателен для production (HTTP разрешён только в development)
- Агент при получении JWT сразу удаляет enrollment key из памяти

## Обновление конфига

При изменении `server_url` или других параметров:
1. Обновить `environments/{env}.json` в этом репозитории
2. Backend автоматически раздаёт актуальный конфиг через `GET /api/v1/config/agent`
3. Агенты периодически (1 раз/сутки) проверяют конфиг и обновляют `server_url`
