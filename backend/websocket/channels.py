# backend/websocket/channels.py
# ВЛАДЕЛЕЦ: TZ-03 SPLIT-2. Redis channel naming convention.
# MERGE-4: REDIS KEYSPACE MAP — полная карта всех Redis ключей проекта.
# При merge ОБЯЗАТЕЛЬНО проверить что нет коллизий.
#
# | Префикс              | TZ      | Тип      | Назначение                      |
# |----------------------|---------|----------|---------------------------------|
# | sphere:agent:cmd:*   | TZ-03   | PubSub   | Команды к агенту                |
# | sphere:org:events:*  | TZ-03   | PubSub   | Broadcast событий организации   |
# | sphere:stream:video:*| TZ-03   | PubSub   | Видеопоток от агента            |
# | sphere:agent:result:*| TZ-03   | PubSub   | Ответы на команды               |
# | device:status:*      | TZ-02   | Key/Val  | Live статус устройства (msgpack)|
# | task:queue:*         | TZ-04   | ZSet     | Очередь задач для dispatch      |
# | vpn:pool:*           | TZ-06   | Hash     | VPN конфигурации пула           |
# | session:*            | TZ-01   | Key/Val  | Refresh token sessions          |
#
# ПРАВИЛО: sphere:* = PubSub каналы (TZ-03), остальные = data keys.
# Коллизий НЕТ при соблюдении префиксов.


class ChannelPattern:
    """
    Стандартные паттерны Redis каналов.
    Префикс "sphere:" — избегает коллизий в shared Redis (TZ-06 тоже использует Redis).
    """

    # Команды к конкретному агенту
    AGENT_CMD = "sphere:agent:cmd:{device_id}"

    # Broadcast событий организации (статусы, алерты)
    ORG_EVENTS = "sphere:org:events:{org_id}"

    # Видеопоток (от агента к API воркеру)
    VIDEO_STREAM = "sphere:stream:video:{device_id}"

    # Ответы на команды
    AGENT_RESULT = "sphere:agent:result:{device_id}:{command_id}"

    @staticmethod
    def agent_cmd(device_id: str) -> str:
        return f"sphere:agent:cmd:{device_id}"

    @staticmethod
    def org_events(org_id: str) -> str:
        return f"sphere:org:events:{org_id}"

    @staticmethod
    def video_stream(device_id: str) -> str:
        return f"sphere:stream:video:{device_id}"

    @staticmethod
    def agent_result_pattern(device_id: str) -> str:
        return f"sphere:agent:result:{device_id}:*"
