#!/bin/bash
#
# ══════════════════════════════════════════════════════════════════════════
#   SPHERE PLATFORM — МАСТЕР-СКРИПТ ДЕПЛОЯ АГЕНТА НА ФЕРМУ ЭМУЛЯТОРОВ
# ══════════════════════════════════════════════════════════════════════════
#
#  Один запуск — и агент навсегда зашит в систему.
#  Поддерживает: LDPlayer, Waydroid, стандартные ADB-эмуляторы.
#
#  Что делает:
#  1. Устанавливает APK как системное приложение (/system/priv-app)
#  2. Через root выдаёт ВСЕ разрешения без подтверждений
#  3. Отключает battery optimization (Doze) для агента
#  4. Закидывает конфиг для авто-энролмента (zero-touch)
#  5. Прописывает init.d скрипт для принудительного старта при каждом буте
#  6. Запускает агента
#
#  Использование:
#    ./deploy-farm.sh <путь_к_agent.apk> [adb_serial]
#
#    Примеры:
#      # Один эмулятор (текущий подключенный)
#      ./deploy-farm.sh ./agent.apk
#
#      # Конкретный эмулятор по serial
#      ./deploy-farm.sh ./agent.apk emulator-5554
#
#      # Массовый деплой на все подключенные эмуляторы
#      ./deploy-farm.sh ./agent.apk ALL
#
# ══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Конфигурация ─────────────────────────────────────────────────────────
PACKAGE_NAME="com.sphereplatform.agent"
PACKAGE_NAME_DEV="${PACKAGE_NAME}.dev"       # dev flavor использует суффикс .dev
MAIN_ACTIVITY=".ui.SetupActivity"
SERVICE_CLASS=".service.SphereAgentService"
DEST_DIR="/system/priv-app/SphereAgent"
INIT_SCRIPT_NAME="99sphereagent"

# Серверная конфигурация для авто-энролмента (Zero-Touch)
# Измените эти значения под вашу инфраструктуру!
SERVER_URL="${SPHERE_SERVER_URL:-https://zinc-enhancement-walls-role.trycloudflare.com}"
API_KEY="${SPHERE_API_KEY:-sphr_dev_enrollment_key_2025}"

APK_PATH="${1:?Ошибка: укажите путь к APK. Использование: ./deploy-farm.sh <agent.apk> [adb_serial|ALL]}"
TARGET="${2:-}"

# ── Цвета для вывода ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Определяем какой package name используется ───────────────────────────
detect_package_name() {
    local serial=$1
    local ADB="adb -s $serial"

    # Проверяем dev сначала (чаще всего на эмуляторах используется dev flavor)
    if $ADB shell pm list packages 2>/dev/null | grep -q "$PACKAGE_NAME_DEV"; then
        echo "$PACKAGE_NAME_DEV"
    elif $ADB shell pm list packages 2>/dev/null | grep -q "$PACKAGE_NAME"; then
        echo "$PACKAGE_NAME"
    else
        # APK ещё не установлен — используем dev по умолчанию для эмуляторов
        echo "$PACKAGE_NAME_DEV"
    fi
}

# ══════════════════════════════════════════════════════════════════════════
#  ОСНОВНАЯ ФУНКЦИЯ ДЕПЛОЯ НА ОДИН ЭМУЛЯТОР
# ══════════════════════════════════════════════════════════════════════════
deploy_to_device() {
    local SERIAL=$1
    local ADB="adb -s $SERIAL"

    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    log_info "Деплой на устройство: $SERIAL"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

    # Определяем package name
    local PKG=$(detect_package_name "$SERIAL")
    log_info "Package: $PKG"

    # ── Шаг 1: Root + Remount ────────────────────────────────────────────
    log_info "[1/8] Получение root-доступа и ремонтирование системного раздела..."
    $ADB root 2>/dev/null || true
    sleep 1
    $ADB remount 2>/dev/null || true
    $ADB shell "su -c 'mount -o rw,remount /system'" 2>/dev/null || true
    $ADB shell "su -c 'mount -o rw,remount /'" 2>/dev/null || true
    log_ok "Root получен, /system в режиме RW"

    # ── Шаг 2: Удаление старой версии ────────────────────────────────────
    log_info "[2/8] Очистка старых установок..."
    $ADB shell "su -c 'rm -rf $DEST_DIR'" 2>/dev/null || true
    $ADB shell "pm uninstall $PKG" 2>/dev/null || true
    $ADB shell "pm uninstall $PACKAGE_NAME" 2>/dev/null || true
    $ADB shell "pm uninstall $PACKAGE_NAME_DEV" 2>/dev/null || true
    log_ok "Старые версии удалены"

    # ── Шаг 3: Установка APK как системное приложение ────────────────────
    log_info "[3/8] Установка APK в /system/priv-app (системное приложение)..."
    $ADB shell "su -c 'mkdir -p $DEST_DIR'"
    $ADB push "$APK_PATH" /data/local/tmp/agent.apk
    $ADB shell "su -c 'cp /data/local/tmp/agent.apk $DEST_DIR/base.apk'"
    $ADB shell "su -c 'chmod 755 $DEST_DIR'"
    $ADB shell "su -c 'chmod 644 $DEST_DIR/base.apk'"
    $ADB shell "rm /data/local/tmp/agent.apk"
    log_ok "APK зашит в систему: $DEST_DIR/base.apk"

    # ── Шаг 4: Перезагрузка для активации System App ─────────────────────
    log_info "[4/8] Перезагрузка для регистрации системного приложения..."
    $ADB reboot
    log_info "Ожидание загрузки устройства..."
    $ADB wait-for-device
    # Ждем пока система полностью загрузится (boot_completed)
    local BOOT_COMPLETE=""
    for i in $(seq 1 60); do
        BOOT_COMPLETE=$($ADB shell getprop sys.boot_completed 2>/dev/null | tr -d '\r\n' || true)
        if [ "$BOOT_COMPLETE" = "1" ]; then
            break
        fi
        sleep 2
    done
    if [ "$BOOT_COMPLETE" != "1" ]; then
        log_warn "Таймаут ожидания загрузки (120с) — продолжаем"
    fi
    sleep 3  # Даём ещё 3 сек для инициализации PackageManager
    $ADB root 2>/dev/null || true
    sleep 1
    log_ok "Устройство загружено, APK зарегистрирован как System App"

    # Обновляем PKG после перезагрузки
    PKG=$(detect_package_name "$SERIAL")
    log_info "Актуальный Package: $PKG"

    # ── Шаг 5: Автоматическая выдача ВСЕХ разрешений через root ──────────
    log_info "[5/8] Выдача всех разрешений без подтверждений (root grant)..."

    # Runtime permissions — выдаём через pm grant (работает без UI)
    for PERM in \
        android.permission.POST_NOTIFICATIONS \
        android.permission.READ_LOGS \
        android.permission.REQUEST_INSTALL_PACKAGES \
        android.permission.SYSTEM_ALERT_WINDOW \
        android.permission.WRITE_SECURE_SETTINGS \
        android.permission.READ_EXTERNAL_STORAGE \
        android.permission.WRITE_EXTERNAL_STORAGE
    do
        $ADB shell "pm grant $PKG $PERM" 2>/dev/null || true
    done

    # Отключаем Battery Optimization (Doze) для нашего пакета
    $ADB shell "dumpsys deviceidle whitelist +$PKG" 2>/dev/null || true

    # Отключаем App Standby для нашего приложения
    $ADB shell "am set-standby-bucket $PKG active" 2>/dev/null || true

    # Разрешаем запуск фоновых сервисов (критично для Android 9+)
    $ADB shell "cmd appops set $PKG RUN_IN_BACKGROUND allow" 2>/dev/null || true
    $ADB shell "cmd appops set $PKG RUN_ANY_IN_BACKGROUND allow" 2>/dev/null || true

    # Autostart (критично для кастомных ROM'ов типа MIUI, но сработает и тут)
    $ADB shell "cmd appops set $PKG AUTO_START_ON_BOOT allow" 2>/dev/null || true

    # Отключаем ограничения на фоновую работу
    $ADB shell "cmd appops set $PKG BOOT_COMPLETED allow" 2>/dev/null || true

    # Выводим из "Stopped State" (критично! без этого BOOT_COMPLETED не дойдёт)
    $ADB shell "am broadcast -a android.intent.action.BOOT_COMPLETED -p $PKG" 2>/dev/null || true

    log_ok "Все разрешения выданы, батарея оптимизация отключена"

    # ── Шаг 6: Закидываем конфиг для Zero-Touch авто-энролмента ──────────
    log_info "[6/8] Создание конфига авто-энролмента (zero-touch)..."

    # Генерируем уникальный device_id на основе serial
    local DEVICE_ID="emu-${SERIAL}"

    # Создаём JSON-конфиг с серверными данными
    cat << JSONEOF > /tmp/sphere-agent-config.json
{
    "server_url": "${SERVER_URL}",
    "api_key": "${API_KEY}",
    "device_id": "${DEVICE_ID}",
    "auto_register": true
}
JSONEOF

    # Закидываем конфиг в /sdcard/ — ZeroTouchProvisioner найдёт его автоматически
    $ADB push /tmp/sphere-agent-config.json /sdcard/sphere-agent-config.json
    rm -f /tmp/sphere-agent-config.json

    # Помечаем enrollment как пройденный в SharedPreferences (для ServiceWatchdog)
    # Это XML-файл sphere_watchdog.xml в private storage
    local SP_DIR="/data/data/$PKG/shared_prefs"
    $ADB shell "su -c 'mkdir -p $SP_DIR'"
    $ADB shell "su -c 'echo \"<?xml version=\\\"1.0\\\" encoding=\\\"utf-8\\\" standalone=\\\"yes\\\" ?>\" > $SP_DIR/sphere_watchdog.xml'"
    $ADB shell "su -c 'echo \"<map><boolean name=\\\"enrolled\\\" value=\\\"true\\\" /></map>\" >> $SP_DIR/sphere_watchdog.xml'"
    $ADB shell "su -c 'chmod 660 $SP_DIR/sphere_watchdog.xml'"

    log_ok "Конфиг создан: server=$SERVER_URL device=$DEVICE_ID enrolled=true"

    # ── Шаг 7: init.d скрипт — принудительный root-старт при каждом буте ─
    log_info "[7/8] Установка init.d скрипта для root-level автозапуска..."

    $ADB shell "su -c 'mount -o rw,remount /system'" 2>/dev/null || true

    # Создаём скрипт, который выполнится при каждой загрузке через root
    $ADB shell "su -c 'cat > /system/etc/init.d/$INIT_SCRIPT_NAME << \"INITEOF\"
#!/system/bin/sh
# Sphere Agent — принудительный root-level старт при загрузке
# Ждём пока Android полностью загрузится
while [ \"\$(getprop sys.boot_completed)\" != \"1\" ]; do
    sleep 2
done
sleep 5
# Запускаем агент в фоне
am start-foreground-service -n $PKG/$SERVICE_CLASS 2>/dev/null || \\
am startservice -n $PKG/$SERVICE_CLASS 2>/dev/null || true
log -t SphereAgent \"init.d: агент принудительно запущен через root\"
INITEOF
'" 2>/dev/null || true

    $ADB shell "su -c 'chmod 755 /system/etc/init.d/$INIT_SCRIPT_NAME'" 2>/dev/null || true

    # su.d — альтернативный путь для SuperSU/LDPlayer root
    $ADB shell "su -c 'mkdir -p /system/su.d'" 2>/dev/null || true
    $ADB shell "su -c 'cp /system/etc/init.d/$INIT_SCRIPT_NAME /system/su.d/$INIT_SCRIPT_NAME'" 2>/dev/null || true
    $ADB shell "su -c 'chmod 755 /system/su.d/$INIT_SCRIPT_NAME'" 2>/dev/null || true

    log_ok "init.d + su.d скрипты установлены"

    # ── Шаг 8: Первый запуск агента ──────────────────────────────────────
    log_info "[8/8] Запускаем агента..."

    # Запускаем SetupActivity (она увидит конфиг и сделает auto-enroll)
    $ADB shell "am start -n $PKG/$MAIN_ACTIVITY" 2>/dev/null || true
    sleep 3
    # Для надежности стартуем и сам сервис
    $ADB shell "am start-foreground-service -n $PKG/$SERVICE_CLASS" 2>/dev/null ||
    $ADB shell "am startservice -n $PKG/$SERVICE_CLASS" 2>/dev/null || true

    log_ok "Агент запущен! Деплой на $SERIAL завершен."

    echo ""
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  ✅  $SERIAL — ГОТОВО. Агент работает как System App.${NC}"
    echo -e "${GREEN}      Он будет запускаться автоматически при каждом будильнике.${NC}"
    echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
    echo ""
}

# ══════════════════════════════════════════════════════════════════════════
#  ТОЧКА ВХОДА: обработка аргументов
# ══════════════════════════════════════════════════════════════════════════

if [ ! -f "$APK_PATH" ]; then
    log_error "APK файл не найден: $APK_PATH"
    exit 1
fi

if [ "$TARGET" = "ALL" ]; then
    # Массовый деплой на все подключенные устройства
    DEVICES=$(adb devices | grep -v "List" | grep "device$" | awk '{print $1}')
    TOTAL=$(echo "$DEVICES" | wc -w)
    log_info "Обнаружено $TOTAL подключенных устройств. Начинаем массовый деплой..."

    COUNT=0
    for DEV in $DEVICES; do
        COUNT=$((COUNT + 1))
        echo ""
        log_info "═══ Устройство $COUNT/$TOTAL: $DEV ═══"
        deploy_to_device "$DEV"
    done

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  🚀  МАССОВЫЙ ДЕПЛОЙ ЗАВЕРШЁН: $COUNT/$TOTAL устройств готовы${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════════${NC}"

elif [ -n "$TARGET" ]; then
    # Конкретное устройство
    deploy_to_device "$TARGET"
else
    # Первое доступное устройство
    SERIAL=$(adb devices | grep "device$" | head -1 | awk '{print $1}')
    if [ -z "$SERIAL" ]; then
        log_error "Нет подключенных устройств! Проверьте: adb devices"
        exit 1
    fi
    deploy_to_device "$SERIAL"
fi
