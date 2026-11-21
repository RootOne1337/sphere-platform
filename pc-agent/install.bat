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

sc query "%SERVICE_NAME%" >nul 2>&1
if not errorlevel 1 (
    echo [ERROR] Service "%SERVICE_NAME%" already exists. Existing installations require a separate migration.
    exit /b 1
)

if not exist "%AGENT_DIR%logs" mkdir "%AGENT_DIR%logs" || exit /b 1

echo [INFO] Устанавливаем сервис "%SERVICE_NAME%"...

nssm install %SERVICE_NAME% "%PYTHON%" || exit /b 1
nssm set    %SERVICE_NAME% AppDirectory   "%AGENT_DIR%" || goto rollback
nssm set    %SERVICE_NAME% AppParameters  "-m agent.windows_service" || goto rollback
nssm set    %SERVICE_NAME% AppRestartDelay 5000 || goto rollback
nssm set    %SERVICE_NAME% Start           SERVICE_AUTO_START || goto rollback

sc start %SERVICE_NAME%
if errorlevel 1 (
    echo [WARN] Не удалось запустить сервис сейчас. Проверьте конфигурацию.
) else (
    echo [OK] Сервис "%SERVICE_NAME%" запущен.
)

endlocal
exit /b 0

:rollback
echo [ERROR] Service configuration failed. Removing the newly created service.
nssm remove %SERVICE_NAME% confirm
exit /b 1
