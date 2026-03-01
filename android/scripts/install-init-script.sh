#!/bin/bash
#
# Скрипт для принудительного старта агента при загрузке системы (Boot).
# Использует возможности init.d или su.d (в зависимости от эмулятора).

echo "[1/4] Подготовка скрипта автозапуска..."
cat << 'EOF' > start_agent.sh
#!/system/bin/sh
# Этот скрипт выполняется суперпользователем (root) при загрузке ядра Android

# Ждем 15 секунд, чтобы сервисы Android успели подняться
sleep 15

# Принудительный старт Foreground Service агента
am start-foreground-service -n com.sphereplatform.agent/.service.SphereAgentService

# Добавляем в лог
log -t SphereAgent "Force started by init.d root script"
EOF

echo "[2/4] Загрузка скрипта на эмулятор..."
adb push start_agent.sh /data/local/tmp/99sphereagent
rm start_agent.sh

adb root
adb remount
adb shell "su -c 'mount -o rw,remount /system'"

echo "[3/4] Установка в init.d (и su.d для SuperSU/Magisk)..."
# Стандартный init.d
adb shell "su -c 'mkdir -p /system/etc/init.d'"
adb shell "su -c 'cp /data/local/tmp/99sphereagent /system/etc/init.d/99sphereagent'"
adb shell "su -c 'chmod 755 /system/etc/init.d/99sphereagent'"

# su.d (часто используется кастомными рут-сборками вроде LDPlayer)
adb shell "su -c 'mkdir -p /system/su.d'"
adb shell "su -c 'cp /data/local/tmp/99sphereagent /system/su.d/99sphereagent'"
adb shell "su -c 'chmod 755 /system/su.d/99sphereagent'"

# Очистка
adb shell "rm /data/local/tmp/99sphereagent"

echo "[4/4] Готово! Теперь агент будет принудительно запускаться через ROOT при каждом включении."
