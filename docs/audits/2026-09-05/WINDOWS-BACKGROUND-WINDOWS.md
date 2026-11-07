# AUD-101: консольные окна фоновых задач Windows

**13 сентября 2026 · Medium / operator disruption · исправлено на текущей станции.**

Пользователь сообщил о временном консольном окне. Точный PID уже закрывшегося окна
не захвачен. Найдены пути создания консоли: scheduled tasks запускали PowerShell
и `python.exe`; publisher вызывал `gh`/`docker` без `CREATE_NO_WINDOW`. Локальные
Gradle helpers также запускали `.bat` без запрета консоли. Не объявляем один из
этих путей доказанным источником конкретного окна; устраняем их в наших процессах.

## Fix и evidence

[Установщик watchdog](../../../scripts/Install-LDPlayerWatchdog.ps1) и
[publisher](../../../scripts/Install-DiscoveryPublisher.ps1) регистрируют напрямую
`pythonw.exe -m ...`, без PowerShell wrapper. GUI interpreter обязателен.
Старый exact action мигрирует только при совпадении SID пользователя. Проверка
SID также исправила отказ обновления своей задачи: Task Scheduler возвращал
`dimas`, а код ожидал `DOMAIN\dimas`.

[Publisher](../../../scripts/discovery_publisher.py) запускает дочерние команды с
`CREATE_NO_WINDOW`; NAT adapter уже использовал этот флаг. Локальные ignored
Gradle helpers исправлены аналогично. Чужие процессы/задачи не изменялись.
Обе задачи обновлены: `LastTaskResult=0`, state files свежие и `status=ok`.
Publisher сохранил signed v8 без лишней публикации.
[Native evidence](evidence/windows-background-tasks-20260913.json).

## Regression и residual risk

**97 passed**: publisher, NAT repair/watchdog, 13 сценариев исполнения PowerShell
installer с mock scheduler и два console tests. Проверены новый/старый/current
action, short owner name, чужой SID/action, отсутствие GUI interpreter и неверный
config. Настоящий `pythonw` probe и его дочерний console executable через publisher
возвращают `GetConsoleWindow() == 0`.
[Installer](../../../tests/test_ldplayer_watchdog_installer.py) ·
[Console probes](../../../tests/test_background_process_windows.py).

Диагностика по-прежнему требует свежего status и `Get-ScheduledTaskInfo`. Ошибка
до записи status отражается exit code. Требуется вход пользователя; reboot не
принят. Проверка относится к нашим задачам/helpers, не всем программам Windows.
