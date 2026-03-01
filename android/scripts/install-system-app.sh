#!/bin/bash
# 
# Скрипт для превращения Sphere Agent в системное приложение (System App).
# Обязательно требует ROOT-доступ на эмуляторе (LDPlayer/Waydroid).
#
# Зачем это нужно?
# Системные приложения (в /system/app или /system/priv-app) ИГНОРИРУЮТ любые 
# методы энергосбережения Android (Doze Mode, App Standby).
# Они автоматически стартуют при загрузке системы, и система Android НИКОГДА
# не ставит их в состояние "Stopped" (блокирующее BOOT_COMPLETED).

# Конфигурация
APK_PATH=$1
PACKAGE_NAME="com.sphereplatform.agent"
DEST_DIR="/system/priv-app/SphereAgent"

if [ -z "$APK_PATH" ]; then
    echo "Использование: ./install-system-app.sh <путь/к/вашему/agent.apk>"
    exit 1
fi

echo "[1/6] Проверка подключения и root-прав..."
adb root || echo "adb root не удался (на некоторых эмуляторах root доступен по умолчанию)"
adb wait-for-device

echo "[2/6] Ремонтирование системного раздела в режим чтения/записи (Remount RW)..."
adb remount
# Если remount не сработал (часто бывает на Android 9+), пробуем альтернативные команды:
adb shell "su -c 'mount -o rw,remount /system'"
adb shell "su -c 'mount -o rw,remount /'"

echo "[3/6] Очистка старых установок агента..."
adb shell "su -c 'rm -rf $DEST_DIR'"
adb uninstall $PACKAGE_NAME || true

echo "[4/6] Копирование APK в системный раздел (/system/priv-app)..."
# Создаем директорию
adb shell "su -c 'mkdir -p $DEST_DIR'"
# Копируем файл
adb push "$APK_PATH" /data/local/tmp/agent.apk
adb shell "su -c 'mv /data/local/tmp/agent.apk $DEST_DIR/base.apk'"

echo "[5/6] Установка правильных прав доступа (Permissions)..."
# Папка должна иметь 755 (rwxr-xr-x), файл 644 (rw-r--r--)
adb shell "su -c 'chmod 755 $DEST_DIR'"
adb shell "su -c 'chmod 644 $DEST_DIR/base.apk'"

echo "[6/6] Перезагрузка эмулятора для применения системного приложения..."
adb reboot

echo "=========================================================="
echo "УСПЕШНО! Агент SpherePlatform теперь зашит в систему."
echo "После перезагрузки он автоматически и безусловно стартует."
echo "=========================================================="
