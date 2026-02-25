package com.sphereplatform.agent.commands.model

import kotlinx.serialization.Serializable

@Serializable
enum class CommandType {
    // Управление устройством
    WAKE_SCREEN, LOCK_SCREEN, REBOOT, SHELL,
    // ADB-примитивы
    TAP, SWIPE, TYPE_TEXT, KEY_EVENT, SCREENSHOT,
    // DAG-скрипт
    EXECUTE_DAG,
    // VPN
    VPN_CONNECT, VPN_DISCONNECT, VPN_RECONNECT,
    // OTA обновления (реализация в SPLIT-5)
    OTA_UPDATE,
    // Агент
    PING, UPDATE_CONFIG, REQUEST_STATUS,
    // Логирование (по требованию)
    REQUEST_LOGS, UPLOAD_LOGCAT,
}
