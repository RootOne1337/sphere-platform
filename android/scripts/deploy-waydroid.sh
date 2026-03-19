#!/bin/bash
#
# ══════════════════════════════════════════════════════════════════════════
#   SPHERE PLATFORM — ДЕПЛОЙ АГЕНТА НА WAYDROID (Linux контейнер)
# ══════════════════════════════════════════════════════════════════════════
#
#  Один запуск — и агент навсегда работает в Waydroid.
#  При каждом перезапуске waydroid-container агент стартует автоматически.
#
#  Что делает:
#  1. Устанавливает APK как системное приложение через waydroid shell
#  2. Выдаёт ВСЕ разрешения без подтверждений
#  3. Отключает battery optimization
#  4. Закидывает конфиг для авто-энролмента
#  5. Помечает enrolled=true
#  6. Создаёт systemd-сервис для автозапуска агента при старте контейнера
#  7. Запускает агента
#
#  Использование:
#    sudo ./deploy-waydroid.sh <путь_к_agent.apk>
#
# ══════════════════════════════════════════════════════════════════════════

set -euo pipefail

# ── Конфигурация ─────────────────────────────────────────────────────────
PACKAGE_NAME="com.sphereplatform.agent"
PACKAGE_NAME_DEV="${PACKAGE_NAME}.dev"
MAIN_ACTIVITY=".ui.SetupActivity"
SERVICE_CLASS=".service.SphereAgentService"
DEST_DIR="/system/priv-app/SphereAgent"

# Серверная конфигурация (измените под вашу инфраструктуру)
SERVER_URL="${SPHERE_SERVER_URL:?SPHERE_SERVER_URL is required}"
API_KEY="${SPHERE_API_KEY:-sphr_dev_enrollment_key_2025}"
DEVICE_ID="${SPHERE_DEVICE_ID:-waydroid-$(hostname)}"

APK_PATH="${1:?Ошибка: укажите путь к APK. Использование: sudo ./deploy-waydroid.sh <agent.apk>}"

# ── Цвета для вывода ────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
log_ok()    { echo -e "${GREEN}[OK]${NC}    $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── Проверки ─────────────────────────────────────────────────────────────
if [ ! -f "$APK_PATH" ]; then
    log_error "APK файл не найден: $APK_PATH"
    exit 1
fi

if ! command -v waydroid &>/dev/null; then
    log_error "waydroid не найден! Установите: https://docs.waydro.id"
    exit 1
fi

# Проверяем, что контейнер запущен
if ! waydroid status 2>/dev/null | grep -qi "running"; then
    log_info "Запускаем waydroid-container..."
    sudo systemctl start waydroid-container
    sleep 5
fi

# ── Определяем фактический package name ──────────────────────────────────
detect_package_name() {
    if waydroid shell pm list packages 2>/dev/null | grep -q "$PACKAGE_NAME_DEV"; then
        echo "$PACKAGE_NAME_DEV"
    elif waydroid shell pm list packages 2>/dev/null | grep -q "$PACKAGE_NAME"; then
        echo "$PACKAGE_NAME"
    else
        echo "$PACKAGE_NAME_DEV"
    fi
}

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
log_info "Деплой Sphere Agent на Waydroid"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Шаг 1: Установка APK как системное приложение ────────────────────────
log_info "[1/7] Установка APK как System App..."

# Удаляем старую версию
waydroid shell pm uninstall "$PACKAGE_NAME" 2>/dev/null || true
waydroid shell pm uninstall "$PACKAGE_NAME_DEV" 2>/dev/null || true
waydroid shell rm -rf "$DEST_DIR" 2>/dev/null || true

# Копируем APK в контейнер
# Через mount point waydroid'а
WAYDROID_DATA=$(waydroid prop get waydroid.host_data_path 2>/dev/null || echo "/var/lib/waydroid/data")

# Копируем через tmp
cp "$APK_PATH" /tmp/sphere-agent.apk
waydroid shell mkdir -p "$DEST_DIR"
# Используем adb или прямое копирование через waydroid
# waydroid shell напрямую не поддерживает push, используём обходной путь
if command -v lxc-attach &>/dev/null; then
    # Прямое копирование через LXC
    CONTAINER_NAME=$(lxc-ls 2>/dev/null | grep waydroid || echo "waydroid")
    lxc-attach -n "$CONTAINER_NAME" -- mkdir -p "$DEST_DIR" 2>/dev/null || true
    lxc-attach -n "$CONTAINER_NAME" -- cp /host_tmp/sphere-agent.apk "$DEST_DIR/base.apk" 2>/dev/null || {
        # Альтернатива: установка через waydroid app install
        waydroid app install /tmp/sphere-agent.apk
        log_warn "Установлен как обычное приложение (не System App), но скрипт автозапуска компенсирует"
    }
else
    # Используем waydroid app install (обычная установка)
    waydroid app install /tmp/sphere-agent.apk
    log_warn "lxc-attach недоступен — установлен как обычное приложение"
fi

rm -f /tmp/sphere-agent.apk
log_ok "APK установлен"

# Обновляем package name
PKG=$(detect_package_name)
log_info "Актуальный Package: $PKG"

# ── Шаг 2: Выдача разрешений ────────────────────────────────────────────
log_info "[2/7] Выдача всех разрешений через root..."

for PERM in \
    android.permission.POST_NOTIFICATIONS \
    android.permission.READ_LOGS \
    android.permission.REQUEST_INSTALL_PACKAGES \
    android.permission.SYSTEM_ALERT_WINDOW \
    android.permission.READ_EXTERNAL_STORAGE \
    android.permission.WRITE_EXTERNAL_STORAGE
do
    waydroid shell pm grant "$PKG" "$PERM" 2>/dev/null || true
done

log_ok "Все разрешения выданы"

# ── Шаг 3: Отключение Battery Optimization ───────────────────────────────
log_info "[3/7] Отключение оптимизации батареи..."
waydroid shell dumpsys deviceidle whitelist +"$PKG" 2>/dev/null || true
waydroid shell am set-standby-bucket "$PKG" active 2>/dev/null || true
waydroid shell cmd appops set "$PKG" RUN_IN_BACKGROUND allow 2>/dev/null || true
waydroid shell cmd appops set "$PKG" RUN_ANY_IN_BACKGROUND allow 2>/dev/null || true
log_ok "Battery optimization отключена"

# ── Шаг 4: Конфиг авто-энролмента ───────────────────────────────────────
log_info "[4/7] Создание конфига авто-энролмента..."

cat << JSONEOF > /tmp/sphere-agent-config.json
{
    "server_url": "${SERVER_URL}",
    "api_key": "${API_KEY}",
    "device_id": "${DEVICE_ID}",
    "auto_register": true
}
JSONEOF

# Копируем конфиг в /sdcard/ внутри контейнера
waydroid shell mkdir -p /sdcard/ 2>/dev/null || true
if command -v lxc-attach &>/dev/null; then
    CONTAINER_NAME=$(lxc-ls 2>/dev/null | grep waydroid || echo "waydroid")
    cp /tmp/sphere-agent-config.json /tmp/wd-config.json
    lxc-attach -n "$CONTAINER_NAME" -- cp /host_tmp/wd-config.json /sdcard/sphere-agent-config.json 2>/dev/null || true
    rm -f /tmp/wd-config.json
fi

rm -f /tmp/sphere-agent-config.json
log_ok "Конфиг создан: server=$SERVER_URL device=$DEVICE_ID"

# ── Шаг 5: Пометить enrolled=true ───────────────────────────────────────
log_info "[5/7] Устанавливаем enrolled=true в SharedPreferences..."

SP_DIR="/data/data/$PKG/shared_prefs"
waydroid shell mkdir -p "$SP_DIR" 2>/dev/null || true
waydroid shell "echo '<?xml version=\"1.0\" encoding=\"utf-8\" standalone=\"yes\" ?>' > $SP_DIR/sphere_watchdog.xml" 2>/dev/null || true
waydroid shell "echo '<map><boolean name=\"enrolled\" value=\"true\" /></map>' >> $SP_DIR/sphere_watchdog.xml" 2>/dev/null || true

log_ok "enrolled=true установлен"

# ── Шаг 6: Создание systemd-сервиса для автозапуска ──────────────────────
log_info "[6/7] Создание systemd-сервиса для автозапуска при каждом старте контейнера..."

SYSTEMD_SERVICE="/etc/systemd/system/sphere-agent.service"

sudo tee "$SYSTEMD_SERVICE" > /dev/null << SVCEOF
[Unit]
Description=Sphere Platform Agent — автозапуск в Waydroid
After=waydroid-container.service
Requires=waydroid-container.service

[Service]
Type=oneshot
RemainAfterExit=yes
# Ждём пока Android внутри контейнера полностью загрузится
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 60); do waydroid shell getprop sys.boot_completed 2>/dev/null | grep -q 1 && break; sleep 2; done'
# Запускаем Foreground Service агента
ExecStart=/usr/bin/waydroid shell am start-foreground-service -n ${PKG}/${SERVICE_CLASS}
# Запасной вариант: открываем Activity (она сделает auto-enroll если нужно)
ExecStartPost=/usr/bin/waydroid shell am start -n ${PKG}/${MAIN_ACTIVITY}

[Install]
WantedBy=multi-user.target
SVCEOF

sudo systemctl daemon-reload
sudo systemctl enable sphere-agent.service

log_ok "systemd-сервис создан и включён: sphere-agent.service"

# ── Шаг 7: Первый запуск ────────────────────────────────────────────────
log_info "[7/7] Запускаем агента..."
waydroid shell am start -n "$PKG/$MAIN_ACTIVITY" 2>/dev/null || true
sleep 3
waydroid shell am start-foreground-service -n "$PKG/$SERVICE_CLASS" 2>/dev/null || true

echo ""
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅  Waydroid — ГОТОВО. Агент работает.${NC}"
echo -e "${GREEN}  📌  Systemd-сервис: sphere-agent.service (автозапуск при буте)${NC}"
echo -e "${GREEN}  📌  Управление: sudo systemctl [start|stop|status] sphere-agent${NC}"
echo -e "${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
