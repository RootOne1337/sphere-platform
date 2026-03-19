#!/usr/bin/env python3
"""
Black Russia Auto-Login Bot
============================
Автоматизация входа в игру Black Russia (com.br.top) через ADB + UIAutomator dump.

Цикл:  force-stop → sleep → launch → UI scan loop → force-stop → repeat

Зависимости: только стандартная библиотека + loguru
    pip install loguru

Запуск:
    python black_russia_bot.py
    python black_russia_bot.py --device emulator-5554
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from typing import Optional

# loguru — если нет, fallback на print
try:
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}")
    logger.add("bot_{time:YYYYMMDD}.log", rotation="1 day", retention="7 days",
               format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {message}")
except ImportError:
    import logging
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logger = logging.getLogger("bot")  # type: ignore[assignment]

# ─────────────────────────────────────────────────────────────────────────────
# КОНФИГУРАЦИЯ  (редактировать здесь или передавать через CLI)
# ─────────────────────────────────────────────────────────────────────────────

ADB_PATH       = r"C:\LDPlayer\LDPlayer9\adb.exe"
DEVICE_SERIAL  = "emulator-5554"   # из `adb devices` (emulator-5554 / 127.0.0.1:5555)

APP_PACKAGE    = "com.br.top"

PASSWORD       = os.environ.get("BOT_PASSWORD", "")  # пароль для входа И регистрации — задаётся через env BOT_PASSWORD

CHAR_NAME      = "Naf"               # имя нового персонажа (при первом входе)
CHAR_SURNAME   = "Tali"              # фамилия нового персонажа

# Тайминги
START_DELAY    = 10    # сек: ждём после запуска приложения
SCAN_INTERVAL  = 1.5   # сек: пауза между итерациями при наличии действий
IDLE_INTERVAL  = 0.8   # сек: пауза при отсутствии действий (быстрее ловим новые экраны)
MAX_IDLE_ITERS = 25    # итераций подряд без действий → игра загружена, выходим
AFTER_ACT_SLEEP = 1.8  # сек: ждём после каждого действия (анимации / переходы)
CYCLE_DELAY    = 5     # сек: между циклами

# ─────────────────────────────────────────────────────────────────────────────
# ADB HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _adb(*args: str, timeout: int = 15) -> str:
    """Выполнить ADB команду, вернуть stdout (пустую строку при ошибке)."""
    cmd = [ADB_PATH, "-s", DEVICE_SERIAL, *args]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except subprocess.TimeoutExpired:
        logger.warning("ADB timeout: {}", " ".join(args[:3]))
        return ""
    except FileNotFoundError:
        logger.error("ADB не найден: {}", ADB_PATH)
        sys.exit(1)
    except Exception as exc:
        logger.error("ADB ошибка: {}", exc)
        return ""


def adb_tap(x: int, y: int) -> None:
    _adb("shell", "input", "tap", str(x), str(y))


def adb_text(text: str) -> None:
    """Ввести ASCII-текст (пробелы → %s, спецсимволы экранируются)."""
    safe = (
        text
        .replace("\\", "\\\\")
        .replace("'",  "\\'")
        .replace('"',  '\\"')
        .replace(" ",  "%s")
        .replace("&",  "\\&")
        .replace("<",  "\\<")
        .replace(">",  "\\>")
        .replace("|",  "\\|")
        .replace(";",  "\\;")
    )
    _adb("shell", "input", "text", safe)


def adb_clear_field() -> None:
    """Выделить всё + удалить."""
    _adb("shell", "input", "keyevent", "KEYCODE_CTRL_A")
    time.sleep(0.15)
    _adb("shell", "input", "keyevent", "KEYCODE_DEL")
    time.sleep(0.15)


def adb_click_and_type(x: int, y: int, text: str) -> None:
    """Кликнуть на поле → очистить → ввести текст."""
    adb_tap(x, y)
    time.sleep(0.4)
    adb_clear_field()
    time.sleep(0.2)
    adb_text(text)
    time.sleep(0.3)


def dump_ui() -> Optional[str]:
    """UIAutomator dump → вернуть XML-строку или None при неудаче."""
    _adb("shell", "uiautomator", "dump", "/sdcard/__uidump.xml", timeout=12)
    time.sleep(0.25)
    xml = _adb("shell", "cat", "/sdcard/__uidump.xml", timeout=8)
    if xml and "<hierarchy" in xml:
        return xml
    return None


# ─────────────────────────────────────────────────────────────────────────────
# UI ELEMENT WRAPPER
# ─────────────────────────────────────────────────────────────────────────────

class UIElement:
    __slots__ = ("node",)

    def __init__(self, node: ET.Element) -> None:
        self.node = node

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        raw = self.node.get("bounds", "[0,0][0,0]")
        coords = raw.replace("][", ",").strip("[]").split(",")
        return int(coords[0]), int(coords[1]), int(coords[2]), int(coords[3])

    @property
    def center(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return (x1 + x2) // 2, (y1 + y2) // 2

    @property
    def size(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bounds
        return x2 - x1, y2 - y1

    @property
    def clickable(self) -> bool:
        return self.node.get("clickable") == "true"

    @property
    def text(self) -> str:
        return self.node.get("text", "")

    def tap(self) -> None:
        cx, cy = self.center
        logger.debug("  tap ({}, {})", cx, cy)
        adb_tap(cx, cy)

    def tap_at(self, x: int, y: int) -> None:
        logger.debug("  tap_at ({}, {})", x, y)
        adb_tap(x, y)


# ─────────────────────────────────────────────────────────────────────────────
# ELEMENT FINDERS
# ─────────────────────────────────────────────────────────────────────────────

def by_res_id(root: ET.Element, res_id: str) -> Optional[UIElement]:
    for node in root.iter():
        if node.get("resource-id") == res_id:
            return UIElement(node)
    return None


def by_text(root: ET.Element, text: str) -> Optional[UIElement]:
    for node in root.iter():
        if node.get("text") == text or node.get("content-desc") == text:
            return UIElement(node)
    return None


def by_class_clickable(root: ET.Element, class_name: str,
                        max_w: int = 9999, max_h: int = 9999) -> Optional[UIElement]:
    for node in root.iter():
        if node.get("class") == class_name and node.get("clickable") == "true":
            el = UIElement(node)
            w, h = el.size
            if w <= max_w and h <= max_h:
                return el
    return None


# ─────────────────────────────────────────────────────────────────────────────
# GAME-STARTED SIGNAL
# ─────────────────────────────────────────────────────────────────────────────

class GameStarted(Exception):
    """Поднимается когда игра полностью загружена — scan_loop завершает работу."""


# ─────────────────────────────────────────────────────────────────────────────
# ГЛАВНЫЙ ОБРАБОТЧИК ЭКРАНОВ
# ─────────────────────────────────────────────────────────────────────────────

def handle_screen(root: ET.Element) -> bool:
    """
    Анализирует текущий экран и выполняет одно (самое приоритетное) действие.
    Возвращает True если действие было совершено, False если экран не распознан.
    Поднимает GameStarted когда игра запущена и дальше нет что делать.
    """

    # ═══════════════════════════════════════════════════════════════════
    # ПРИЗНАК ИГРЫ В ЭФИРЕ — DonateHeader виден → мы уже в игре
    # ═══════════════════════════════════════════════════════════════════
    if by_res_id(root, "com.br.top:id/donate_header_value_rub"):
        logger.success("[GAME] Главный экран игры виден (donate_header) → завершаем")
        raise GameStarted

    # ═══════════════════════════════════════════════════════════════════
    # СИСТЕМНЫЕ ДИАЛОГИ  (наивысший приоритет)
    # ═══════════════════════════════════════════════════════════════════

    el = by_res_id(root, "com.android.packageinstaller:id/permission_allow_button")
    if el:
        logger.info("[PERM] Диалог разрешений → РАЗРЕШИТЬ")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # ДИАЛОГИ ПРИЛОЖЕНИЯ
    # ═══════════════════════════════════════════════════════════════════

    el = by_res_id(root, "com.br.top:id/button_ok")
    if el:
        logger.info("[DIALOG] button_ok → ОК")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/button_repeat")
    if el:
        logger.info("[DIALOG] button_repeat → ДА, ЗАГРУЗИТЬ")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/dw_button_ok")
    if el:
        logger.info("[DIALOG] dw_button_ok → Выбрать")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/dw_button_cancel")
    if el:
        logger.info("[DIALOG] dw_button_cancel → Закрыть")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # SPLASH / ЗАГОЛОВОК
    # ═══════════════════════════════════════════════════════════════════

    el = by_text(root, "BLACK RUSSIA")
    if el and el.clickable:
        logger.info("[SPLASH] Кликаем BLACK RUSSIA")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # ВЫБОР СЕРВЕРА
    # ═══════════════════════════════════════════════════════════════════

    el_list = by_res_id(root, "com.br.top:id/list_servers_choose")
    if el_list:
        logger.info("[SERVER] Список серверов → выбираем первый")
        # Первый кликабельный FrameLayout внутри списка серверов
        for node in el_list.node.iter():
            if node.get("class") == "android.widget.FrameLayout" and node.get("clickable") == "true":
                srv = UIElement(node)
                logger.info("[SERVER] Тапаем сервер bounds={}", srv.bounds)
                srv.tap()
                return True
        # Если внутри нет кликабельных — тапаем первый дочерний
        el_list.tap()
        return True

    el = by_res_id(root, "com.br.top:id/all_servers_button")
    if el:
        logger.info("[SERVER] all_servers_button → Все сервера")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/br_servers_play")
    if el:
        logger.info("[SERVER] br_servers_play → Играть (выбор сервера)")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # ЭКРАН ВХОДА: поле пароля + кнопка ИГРАТЬ  (одновременно на экране)
    # ═══════════════════════════════════════════════════════════════════

    el_pwd  = by_res_id(root, "com.br.top:id/password_enter")
    el_play = by_res_id(root, "com.br.top:id/play_but")
    if el_pwd and el_play:
        pwd_val = el_pwd.text
        if pwd_val in ("Введите пароль", "", " ") or pwd_val == PASSWORD:
            if pwd_val != PASSWORD:
                logger.info("[LOGIN] Кликаем поле пароля → вводим пароль")
                cx, cy = el_pwd.center
                adb_click_and_type(cx, cy, PASSWORD)
                time.sleep(0.5)
            logger.info("[LOGIN] Нажимаем ИГРАТЬ (play_but)")
            el_play.tap()
            return True

    # ═══════════════════════════════════════════════════════════════════
    # РЕГИСТРАЦИЯ: edit2 (пароль) + edit3 (повтор) + reg_butt
    # ═══════════════════════════════════════════════════════════════════

    el_e2  = by_res_id(root, "com.br.top:id/edit2")
    el_reg = by_res_id(root, "com.br.top:id/reg_butt")
    if el_e2 and el_reg:
        # Поле пароля
        if el_e2.text in ("Пароль", "", " "):
            logger.info("[REG] Вводим пароль в edit2")
            cx, cy = el_e2.center
            adb_click_and_type(cx, cy, PASSWORD)

        # Поле повтора пароля
        el_e3 = by_res_id(root, "com.br.top:id/edit3")
        if el_e3 and el_e3.text in ("Повторите пароль", "", " "):
            logger.info("[REG] Вводим пароль в edit3")
            cx, cy = el_e3.center
            adb_click_and_type(cx, cy, PASSWORD)

        logger.info("[REG] Нажимаем ЗАРЕГИСТРИРОВАТЬСЯ")
        el_reg.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # СОЗДАНИЕ ПЕРСОНАЖА: имя + фамилия + button_play
    # ═══════════════════════════════════════════════════════════════════

    el_name = by_res_id(root, "com.br.top:id/edit_text_name")
    if el_name:
        acted = False

        if el_name.text in ("Введите имя персонажа", "", " "):
            logger.info("[CREATE] Вводим имя: {}", CHAR_NAME)
            cx, cy = el_name.center
            adb_click_and_type(cx, cy, CHAR_NAME)
            acted = True

        el_surn = by_res_id(root, "com.br.top:id/edit_text_surname")
        if el_surn and el_surn.text in ("Введите фамилию персонажа", "", " "):
            logger.info("[CREATE] Вводим фамилию: {}", CHAR_SURNAME)
            cx, cy = el_surn.center
            adb_click_and_type(cx, cy, CHAR_SURNAME)
            acted = True

        el_bp = by_res_id(root, "com.br.top:id/button_play")
        if el_bp:
            logger.info("[CREATE] Нажимаем ИГРАТЬ (button_play)")
            el_bp.tap()
            return True

        if acted:
            return True

    # ═══════════════════════════════════════════════════════════════════
    # ВЫБОР ПОЛА
    # ═══════════════════════════════════════════════════════════════════

    el = by_res_id(root, "com.br.top:id/male_butt")
    if el:
        logger.info("[CHAR] Выбираем мужской пол (male_butt)")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # НИКНЕЙМ ПРИГЛАСИВШЕГО → игнорируем, жмём ПРОДОЛЖИТЬ
    # ═══════════════════════════════════════════════════════════════════

    el_invite = by_res_id(root, "com.br.top:id/invite_nick")
    el_cont   = by_res_id(root, "com.br.top:id/but_continue")
    if el_invite and el_cont:
        logger.info("[INVITE] Поле ника пригласившего → пропускаем, ПРОДОЛЖИТЬ")
        el_cont.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # НАВИГАЦИОННЫЕ КНОПКИ (туториал, подтверждения)
    # ═══════════════════════════════════════════════════════════════════

    el = by_res_id(root, "com.br.top:id/but_continue")
    if el:
        logger.info("[NAV] but_continue → ПРОДОЛЖИТЬ")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/but_skip")
    if el:
        logger.info("[NAV] but_skip → ПРОПУСТИТЬ")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/butt")
    if el:
        logger.info("[NAV] butt → ПРОДОЛЖИТЬ")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/arrow_right")
    if el:
        logger.info("[NAV] arrow_right → →")
        el.tap()
        return True

    el = by_res_id(root, "com.br.top:id/play_butt")
    if el:
        logger.info("[PLAY] play_butt → НАЧАТЬ ИГРУ")
        el.tap()
        return True

    # ═══════════════════════════════════════════════════════════════════
    # НЕКЛИКАБЕЛЬНЫЕ ТЕКСТЫ — тапаем по их координатам
    # ═══════════════════════════════════════════════════════════════════

    el = by_text(root, "Нажмите, чтобы продолжить")
    if el:
        cx, cy = el.center
        logger.info("[NAV] Нажмите, чтобы продолжить → tap ({}, {})", cx, cy)
        adb_tap(cx, cy)
        return True

    el = by_text(root, "Далее")
    if el:
        cx, cy = el.center
        logger.info("[NAV] Далее → tap ({}, {})", cx, cy)
        adb_tap(cx, cy)
        return True

    el = by_text(root, "ЗАКРЫТЬ")
    if el:
        cx, cy = el.center
        logger.info("[NAV] ЗАКРЫТЬ → tap ({}, {})", cx, cy)
        adb_tap(cx, cy)
        return True

    el = by_text(root, "Открыть ×1")
    if el:
        cx, cy = el.center
        logger.info("[BONUS] Открыть ×1 → tap ({}, {})", cx, cy)
        adb_tap(cx, cy)
        return True

    # ═══════════════════════════════════════════════════════════════════
    # GENERIC КЛИКАБЕЛЬНЫЕ ЭЛЕМЕНТЫ  (низший приоритет)
    # ═══════════════════════════════════════════════════════════════════

    # android.view.View (кнопки закрытия туториала, X-крестики)
    el = by_class_clickable(root, "android.view.View", max_w=200, max_h=200)
    if el:
        logger.info("[VIEW] android.view.View кликабельный {}x{} → tap", *el.size)
        el.tap()
        return True

    # FrameLayout малого размера (кнопки на экране, не список серверов)
    el = by_class_clickable(root, "android.widget.FrameLayout", max_w=450, max_h=160)
    if el:
        logger.info("[BTN] FrameLayout {}x{} → tap", *el.size)
        el.tap()
        return True

    # RelativeLayout малого размера (навигационные иконки)
    el = by_class_clickable(root, "android.widget.RelativeLayout", max_w=300, max_h=100)
    if el:
        logger.info("[BTN] RelativeLayout {}x{} → tap", *el.size)
        el.tap()
        return True

    return False  # ничего не найдено


# ─────────────────────────────────────────────────────────────────────────────
# УПРАВЛЕНИЕ ПРИЛОЖЕНИЕМ
# ─────────────────────────────────────────────────────────────────────────────

def stop_app() -> None:
    logger.info("⏹  force-stop {}", APP_PACKAGE)
    _adb("shell", "am", "force-stop", APP_PACKAGE)
    time.sleep(1.5)


def start_app() -> None:
    logger.info("▶  Запускаем {}", APP_PACKAGE)
    _adb(
        "shell", "monkey",
        "-p", APP_PACKAGE,
        "-c", "android.intent.category.LAUNCHER",
        "1",
    )


# ─────────────────────────────────────────────────────────────────────────────
# SCAN LOOP
# ─────────────────────────────────────────────────────────────────────────────

def scan_loop() -> None:
    """
    Непрерывно сканирует UI и реагирует на появляющиеся элементы.
    Завершается:
      - при появлении donate_header (GameStarted)
      - через MAX_IDLE_ITERS итераций подряд без каких-либо действий
    """
    idle    = 0
    total   = 0

    while idle < MAX_IDLE_ITERS:
        total += 1
        logger.debug("[SCAN] #{} | idle {}/{}", total, idle, MAX_IDLE_ITERS)

        xml = dump_ui()
        if xml is None:
            logger.warning("[SCAN] UI dump не получен, пауза...")
            idle += 1
            time.sleep(2.0)
            continue

        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            logger.debug("[SCAN] XML ошибка: {}", exc)
            idle += 1
            time.sleep(IDLE_INTERVAL)
            continue

        try:
            acted = handle_screen(root)
        except GameStarted:
            logger.success("[SCAN] Игра запущена! Выходим из scan loop.")
            return

        if acted:
            idle = 0
            time.sleep(AFTER_ACT_SLEEP)
        else:
            idle += 1
            time.sleep(IDLE_INTERVAL)

    logger.info("[SCAN] {} итераций без действий — считаем игру загруженной", MAX_IDLE_ITERS)


# ─────────────────────────────────────────────────────────────────────────────
# ГЛАВНЫЙ ЦИКЛ
# ─────────────────────────────────────────────────────────────────────────────

def run_cycle(cycle_n: int) -> None:
    sep = "═" * 55
    logger.info("\n{}\n  ЦИКЛ #{}  |  package: {}\n{}", sep, cycle_n, APP_PACKAGE, sep)

    # 1. Остановить приложение
    stop_app()

    # 2. Пауза перед запуском
    logger.info("⏳ Ожидание {} сек...", START_DELAY)
    time.sleep(START_DELAY)

    # 3. Запустить приложение
    start_app()
    logger.info("⏳ Ждём инициализации {} сек...", START_DELAY)
    time.sleep(START_DELAY)

    # 4. Сканируем UI и взаимодействуем
    scan_loop()

    # 5. Остановить приложение после прохождения скрипта
    stop_app()

    logger.info("✓ Цикл #{} завершён", cycle_n)


def main() -> None:
    parser = argparse.ArgumentParser(description="Black Russia Auto-Login Bot")
    parser.add_argument("--device",   default=DEVICE_SERIAL,
                        help="ADB device serial (default: emulator-5554)")
    parser.add_argument("--adb",      default=ADB_PATH,
                        help="Путь к adb.exe")
    parser.add_argument("--password", default=PASSWORD,
                        help="Пароль для входа")
    parser.add_argument("--cycles",   type=int, default=0,
                        help="Кол-во циклов (0 = бесконечно)")
    args = parser.parse_args()

    # Применяем CLI параметры к глобальным переменным
    global DEVICE_SERIAL, ADB_PATH, PASSWORD
    DEVICE_SERIAL = args.device
    ADB_PATH      = args.adb
    PASSWORD      = args.password

    logger.info("╔══════════════════════════════════════════════╗")
    logger.info("║      Black Russia Bot  |  com.br.top         ║")
    logger.info("╠══════════════════════════════════════════════╣")
    logger.info("║  Устройство : {:<30} ║", DEVICE_SERIAL)
    logger.info("║  Пароль     : {:<30} ║", "*" * len(PASSWORD))
    logger.info("║  Циклов     : {:<30} ║", str(args.cycles) if args.cycles else "∞")
    logger.info("╚══════════════════════════════════════════════╝\n")

    # Проверка подключения
    devices = _adb("devices")
    if DEVICE_SERIAL not in devices:
        logger.error("Устройство {} не найдено! Список:\n{}", DEVICE_SERIAL, devices)
        sys.exit(1)

    cycle   = 1
    max_cyc = args.cycles or float("inf")

    try:
        while cycle <= max_cyc:
            run_cycle(cycle)
            cycle += 1
            if cycle <= max_cyc:
                logger.info("⏳ Пауза между циклами {} сек...", CYCLE_DELAY)
                time.sleep(CYCLE_DELAY)
    except KeyboardInterrupt:
        logger.info("\nОстановлено пользователем (Ctrl+C)")
        stop_app()
        sys.exit(0)

    logger.success("Все {} цикл(ов) выполнены.", args.cycles)


if __name__ == "__main__":
    main()
