@echo off
:: install.bat — установка Sphere PC Agent как Windows Service через NSSM
:: Требования: nssm.exe доступен в PATH или лежит рядом со скриптом
:: Использование:  install.bat [путь до python.exe]

setlocal

set "SERVICE_NAME=SpherePCAgent"
set "AGENT_DIR=%~dp0"
set "PYTHON=%~1"

if "%PYTHON%"=="" (
    :: попробуем найти python в PATH
    where python >nul 2>&1
    if errorlevel 1 (
        echo [ERROR] python.exe не найден. Передайте путь первым аргументом.
        exit /b 1
    )
    set "PYTHON=python"
)

where nssm >nul 2>&1
if errorlevel 1 (
    echo [ERROR] nssm.exe не найден в PATH.
    echo Скачайте NSSM с https://nssm.cc/download и добавьте в PATH.
    exit /b 1
)

echo [INFO] Устанавливаем сервис "%SERVICE_NAME%"...

nssm install %SERVICE_NAME% "%PYTHON%"
nssm set    %SERVICE_NAME% AppDirectory   "%AGENT_DIR%"
nssm set    %SERVICE_NAME% AppParameters  "-m agent.main"
nssm set    %SERVICE_NAME% AppStdout      "%AGENT_DIR%logs\agent_stdout.log"
nssm set    %SERVICE_NAME% AppStderr      "%AGENT_DIR%logs\agent_stderr.log"
nssm set    %SERVICE_NAME% AppRotateFiles 1
nssm set    %SERVICE_NAME% AppRotateSeconds 86400
nssm set    %SERVICE_NAME% Start           SERVICE_AUTO_START
nssm set    %SERVICE_NAME% AppRestartDelay 5000

:: Создать директорию для логов, если нет
if not exist "%AGENT_DIR%logs" mkdir "%AGENT_DIR%logs"

sc start %SERVICE_NAME%
if errorlevel 1 (
    echo [WARN] Не удалось запустить сервис сейчас. Проверьте конфигурацию.
) else (
    echo [OK] Сервис "%SERVICE_NAME%" запущен.
)

endlocal
