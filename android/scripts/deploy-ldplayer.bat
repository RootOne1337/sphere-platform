@echo off
REM ══════════════════════════════════════════════════════════════════════════
REM   SPHERE PLATFORM — МАССОВЫЙ ДЕПЛОЙ НА LDPLAYER (Windows)
REM ══════════════════════════════════════════════════════════════════════════
REM
REM  Запускает N эмуляторов LDPlayer и деплоит агента на каждый.
REM  Использует ldconsole.exe для управления эмуляторами.
REM
REM  Использование:
REM    deploy-ldplayer.bat <путь_к_agent.apk> <кол-во_эмуляторов>
REM
REM  Примеры:
REM    deploy-ldplayer.bat agent.apk 10
REM    deploy-ldplayer.bat C:\builds\agent-dev.apk 1000
REM
REM ══════════════════════════════════════════════════════════════════════════

setlocal enabledelayedexpansion

REM ── Конфигурация ───────────────────────────────────────────────────────
set "APK_PATH=%~1"
set "EMU_COUNT=%~2"
set "PACKAGE_NAME=com.sphereplatform.agent.dev"
set "SERVER_URL=https://zinc-enhancement-walls-role.trycloudflare.com"
set "API_KEY=sphr_dev_enrollment_key_2025"

REM Путь к ldconsole.exe (измените если нужно)
set "LDCONSOLE=ldconsole.exe"
where %LDCONSOLE% >nul 2>&1 || set "LDCONSOLE=C:\LDPlayer\LDPlayer9\ldconsole.exe"
where %LDCONSOLE% >nul 2>&1 || set "LDCONSOLE=C:\Program Files\LDPlayer\LDPlayer9\ldconsole.exe"

if "%APK_PATH%"=="" (
    echo [ERROR] Укажите путь к APK!
    echo Использование: deploy-ldplayer.bat ^<agent.apk^> ^<кол-во^>
    exit /b 1
)

if "%EMU_COUNT%"=="" set "EMU_COUNT=1"

echo.
echo ══════════════════════════════════════════════════════════════
echo   SPHERE PLATFORM — Массовый деплой на LDPlayer
echo   APK: %APK_PATH%
echo   Эмуляторов: %EMU_COUNT%
echo ══════════════════════════════════════════════════════════════
echo.

REM ── Цикл деплоя ───────────────────────────────────────────────────────
set SUCCESS=0
set FAILED=0

for /L %%i in (0,1,%EMU_COUNT%) do (
    if %%i LSS %EMU_COUNT% (
        echo.
        echo ━━━━━ Эмулятор %%i / %EMU_COUNT% ━━━━━

        REM 1. Запускаем эмулятор (если ещё не запущен)
        echo [1/5] Запуск эмулятора %%i...
        %LDCONSOLE% launch --index %%i 2>nul
        timeout /t 15 /nobreak >nul

        REM 2. Установка APK
        echo [2/5] Установка APK...
        %LDCONSOLE% installapp --index %%i --filename "%APK_PATH%" 2>nul

        REM 3. Запускаемаём агента (выводим из Stopped State)
        echo [3/5] Запуск агента...
        %LDCONSOLE% runapp --index %%i --packagename %PACKAGE_NAME% 2>nul
        timeout /t 5 /nobreak >nul

        REM 4. Через ADB выдаём разрешения и отключаем battery optimization
        echo [4/5] Настройка разрешений через ADB...
        REM Находим ADB порт для конкретного эмулятора
        set "ADB_PORT=5555"
        set /a "ADB_PORT=5555 + %%i * 2"

        adb connect 127.0.0.1:!ADB_PORT! 2>nul
        timeout /t 2 /nobreak >nul

        REM Выдаём разрешения
        adb -s 127.0.0.1:!ADB_PORT! shell pm grant %PACKAGE_NAME% android.permission.POST_NOTIFICATIONS 2>nul
        adb -s 127.0.0.1:!ADB_PORT! shell pm grant %PACKAGE_NAME% android.permission.READ_LOGS 2>nul
        adb -s 127.0.0.1:!ADB_PORT! shell pm grant %PACKAGE_NAME% android.permission.SYSTEM_ALERT_WINDOW 2>nul

        REM Отключаем Battery Optimization
        adb -s 127.0.0.1:!ADB_PORT! shell dumpsys deviceidle whitelist +%PACKAGE_NAME% 2>nul
        adb -s 127.0.0.1:!ADB_PORT! shell cmd appops set %PACKAGE_NAME% RUN_IN_BACKGROUND allow 2>nul
        adb -s 127.0.0.1:!ADB_PORT! shell cmd appops set %PACKAGE_NAME% RUN_ANY_IN_BACKGROUND allow 2>nul

        REM Закидываем конфиг авто-энролмента
        echo {"server_url":"%SERVER_URL%","api_key":"%API_KEY%","device_id":"ldp-%%i","auto_register":true}> "%TEMP%\sphere-config-%%i.json"
        adb -s 127.0.0.1:!ADB_PORT! push "%TEMP%\sphere-config-%%i.json" /sdcard/sphere-agent-config.json 2>nul
        del "%TEMP%\sphere-config-%%i.json" 2>nul

        REM Помечаем enrolled=true
        adb -s 127.0.0.1:!ADB_PORT! shell "su -c 'mkdir -p /data/data/%PACKAGE_NAME%/shared_prefs'" 2>nul
        adb -s 127.0.0.1:!ADB_PORT! shell "su -c 'printf \"<?xml version=\\\"1.0\\\" encoding=\\\"utf-8\\\" ?>\n<map><boolean name=\\\"enrolled\\\" value=\\\"true\\\" /></map>\" > /data/data/%PACKAGE_NAME%/shared_prefs/sphere_watchdog.xml'" 2>nul

        echo [5/5] Перезапуск агента...
        %LDCONSOLE% runapp --index %%i --packagename %PACKAGE_NAME% 2>nul

        set /a SUCCESS+=1
        echo [OK] Эмулятор %%i — ГОТОВО

        adb disconnect 127.0.0.1:!ADB_PORT! 2>nul
    )
)

echo.
echo ══════════════════════════════════════════════════════════════
echo   DEPLOY ЗАВЕРШЁН
echo   Успешно: %SUCCESS% / %EMU_COUNT%
echo ══════════════════════════════════════════════════════════════
echo.

endlocal
