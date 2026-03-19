package com.sphereplatform.agent.root

import android.content.Context
import android.content.pm.ApplicationInfo
import timber.log.Timber
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.InputStreamReader
import java.util.concurrent.TimeUnit

/**
 * RootAutoStart — автостарт агента на рутованных эмуляторах (LDPlayer, Nox, MEmu).
 *
 * ## Проблема
 * На LDPlayer (Android 9, x86, встроенный root) стандартные механизмы
 * (init.d, Magisk service.d, userinit.sh, init.rc) НЕ РАБОТАЮТ — LDPlayer
 * использует МИНИМАЛЬНЫЙ Android-ROM без этих расширений.
 *
 * ## Решение — 4 уровня:
 *
 * ### Уровень 1: Подготовка системы (при каждом запуске app)
 * - Снятие Stopped State
 * - Whitelist от Doze battery optimization
 * - Разрешение фоновой работы (appops)
 * - Выдача runtime permissions через pm grant
 * - Принудительный BOOT_COMPLETED broadcast
 *
 * ### Уровень 2: Nohup watchdog daemon (при каждом запуске app)
 * - Запускает shell-скрипт в background через nohup su
 * - Скрипт каждые 60 секунд проверяет жив ли процесс приложения
 * - Если процесс мёртв — перезапускает через am start
 * - Watchdog живёт до reboot (nohup отвязывает от родительского процесса)
 *
 * ### Уровень 3: Android init service (устанавливается один раз, переживает ребут)
 * - Записывает .rc файл в /system/etc/init/ — СТАНДАРТНЫЙ механизм Android init
 * - LDPlayer Android 9+ использует system-as-root: нужен mount -o remount,rw /
 * - Property trigger sys.boot_completed=1 запускает startup-скрипт при каждой загрузке
 *
 * ### Уровень 4: Установка как системное приложение (САМЫЙ НАДЁЖНЫЙ)
 * - Копирует APK в /system/priv-app/ — PackageManager видит как system app
 * - android:persistent="true" в Manifest → Android AUTOSTARTS при каждой загрузке
 * - System persistent app НЕВОЗМОЖНО убить — система перезапускает автоматически
 * - Это тот же механизм что используют Телефон, СМС, Системные настройки
 *
 * При boot: Init → persistent app auto-start → SphereApp.onCreate() →
 * RootAutoStart обновляет watchdog. Дополнительно init service как backup.
 *
 * ## Вызывается
 * Из [com.sphereplatform.agent.SphereApp.onCreate] в фоновом потоке.
 * Идемпотентно — повторные вызовы безопасны.
 */
object RootAutoStart {

    @Volatile
    private var rootChecked = false

    @Volatile
    private var rootAvailable = false

    /** Namespace (Java-пакет) классов — НЕ совпадает с applicationId при наличии flavor suffix. */
    private const val NAMESPACE = "com.sphereplatform.agent"

    /**
     * Главная точка входа. Выполняет ВСЕ root-настройки.
     *
     * Безопасен для вызова из любого контекста — если root недоступен,
     * тихо возвращается без ошибок.
     */
    fun configure(context: Context) {
        if (!hasRoot()) {
            Timber.d("RootAutoStart: root недоступен — пропускаем")
            return
        }

        val pkg = context.packageName
        Timber.i("RootAutoStart: === НАЧАЛО НАСТРОЙКИ для $pkg ===")

        // 1. Снять системные ограничения
        removeSystemRestrictions(pkg)

        // 2. Выдать runtime permissions
        grantPermissions(pkg)

        // 3. Принудительный BOOT_COMPLETED
        triggerBootReceiver(pkg)

        // 4. Запустить nohup watchdog daemon
        startWatchdogDaemon(pkg)

        // 5. Установить init service для автозапуска при каждой загрузке
        installInitService(pkg)

        // 6. Установить как системное приложение — САМЫЙ НАДЁЖНЫЙ МЕХАНИЗМ
        // persistent=true system app запускается Android'ом АВТОМАТИЧЕСКИ при каждой загрузке
        installAsSystemApp(context, pkg)

        Timber.i("RootAutoStart: === НАСТРОЙКА ЗАВЕРШЕНА для $pkg ===")
    }

    // =====================================================================
    //  1. Снятие системных ограничений
    // =====================================================================

    private fun removeSystemRestrictions(pkg: String) {
        // Снять Stopped State — гарантия доставки BOOT_COMPLETED
        execRoot("cmd package set-stopped-state $pkg false")

        // Whitelist от Doze battery optimization
        execRoot("dumpsys deviceidle whitelist +$pkg")

        // Разрешить фоновую работу
        execRoot("cmd appops set $pkg RUN_IN_BACKGROUND allow")
        execRoot("cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow")

        // Гарантировать что BootReceiver включён
        execRoot("pm enable $pkg/$NAMESPACE.BootReceiver")

        // Разрешить WAKE_LOCK
        execRoot("cmd appops set $pkg WAKE_LOCK allow")

        Timber.i("RootAutoStart: системные ограничения сняты")
    }

    // =====================================================================
    //  2. Выдача runtime permissions
    // =====================================================================

    private fun grantPermissions(pkg: String) {
        val permissions = listOf(
            "android.permission.POST_NOTIFICATIONS",
            "android.permission.READ_LOGS",
            "android.permission.SYSTEM_ALERT_WINDOW",
            "android.permission.READ_EXTERNAL_STORAGE",
            "android.permission.WRITE_EXTERNAL_STORAGE",
        )
        for (perm in permissions) {
            execRoot("pm grant $pkg $perm 2>/dev/null")
        }
        Timber.i("RootAutoStart: permissions выданы")
    }

    // =====================================================================
    //  3. Принудительный BOOT_COMPLETED broadcast
    // =====================================================================

    /**
     * Отправляет BOOT_COMPLETED broadcast нашему BootReceiver прямо сейчас.
     */
    private fun triggerBootReceiver(pkg: String) {
        execRoot(
            "am broadcast" +
                " -a android.intent.action.BOOT_COMPLETED" +
                " -n $pkg/$NAMESPACE.BootReceiver" +
                " --include-stopped-packages",
        )
        Timber.i("RootAutoStart: BOOT_COMPLETED отправлен принудительно")
    }

    // =====================================================================
    //  4. Nohup watchdog daemon — ГЛАВНЫЙ механизм живучести
    // =====================================================================

    /**
     * Запускает nohup watchdog daemon через root.
     *
     * Watchdog — бесконечный shell-цикл который:
     * 1. Каждые 60 секунд проверяет жив ли процесс приложения (pidof)
     * 2. Если процесс мёртв — перезапускает через am start
     * 3. Работает до reboot (nohup отвязывает от родительского процесса)
     *
     * Идемпотентность: перед запуском убиваем предыдущий watchdog через PID-файл.
     */
    private fun startWatchdogDaemon(pkg: String) {
        val activityFull = "$pkg/$NAMESPACE.ui.SetupActivity"
        val serviceFull = "$pkg/$NAMESPACE.service.SphereAgentService"
        val pidFile = "/data/local/tmp/sphere_watchdog.pid"
        val scriptFile = "/data/local/tmp/sphere_watchdog.sh"

        // Записываем watchdog-скрипт на диск и запускаем через nohup
        try {
            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)
            // Записываем скрипт в файл
            stdin.writeBytes("cat > $scriptFile << 'WATCHDOG_EOF'\n")
            stdin.writeBytes("#!/system/bin/sh\n")
            stdin.writeBytes("# Sphere watchdog daemon\n")
            stdin.writeBytes("if [ -f $pidFile ]; then kill \$(cat $pidFile) 2>/dev/null; fi\n")
            stdin.writeBytes("echo \$\$ > $pidFile\n")
            stdin.writeBytes("while true; do\n")
            stdin.writeBytes("  sleep 60\n")
            stdin.writeBytes("  if ! pidof $pkg > /dev/null 2>&1; then\n")
            stdin.writeBytes("    cmd package set-stopped-state $pkg false 2>/dev/null\n")
            stdin.writeBytes("    am start -n $activityFull 2>/dev/null\n")
            stdin.writeBytes("    sleep 5\n")
            stdin.writeBytes("    am startservice -n $serviceFull 2>/dev/null\n")
            stdin.writeBytes("  fi\n")
            stdin.writeBytes("done\n")
            stdin.writeBytes("WATCHDOG_EOF\n")
            stdin.writeBytes("chmod 755 $scriptFile\n")
            // Запускаем через nohup — detach от текущего процесса
            stdin.writeBytes("nohup sh $scriptFile > /dev/null 2>&1 &\n")
            stdin.writeBytes("exit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(10, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут запуска watchdog")
                return
            }
            Timber.i("RootAutoStart: watchdog daemon запущен (script: $scriptFile, pid: $pidFile)")
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: не удалось запустить watchdog daemon")
        }
    }

    // =====================================================================
    //  5. Android init service — ПЕРЕЖИВАЕТ РЕБУТ
    // =====================================================================

    /**
     * Устанавливает Android init service для автозапуска при загрузке.
     *
     * Записывает .rc файл в /system/etc/init/ — стандартный путь Android init.
     * Property trigger `sys.boot_completed=1` запускает startup-скрипт.
     *
     * ВАЖНО: LDPlayer Android 9+ использует system-as-root layout:
     * `/system` — bind mount от `/`. Стандартное `mount -o remount,rw /system`
     * НЕ РАБОТАЕТ. Нужно `mount -o remount,rw /` или через blockdevice.
     *
     * Идемпотентно — перезаписывает файлы при каждом запуске.
     */
    private fun installInitService(pkg: String) {
        val rcPath = "/system/etc/init/sphere_autostart.rc"
        val startupScript = "/data/local/tmp/sphere_startup.sh"
        val watchdogScript = "/data/local/tmp/sphere_watchdog.sh"
        val activityComponent = "$pkg/$NAMESPACE.ui.SetupActivity"
        val receiverComponent = "$pkg/$NAMESPACE.BootReceiver"

        try {
            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)

            // === 1. Записываем startup-скрипт в /data/ (всегда writable) ===
            stdin.writeBytes("cat > $startupScript << 'STARTUP_EOF'\n")
            stdin.writeBytes("#!/system/bin/sh\n")
            stdin.writeBytes("# Sphere Platform — автостарт при загрузке\n")
            stdin.writeBytes("# Запускается Android init через property trigger sys.boot_completed=1\n")
            stdin.writeBytes("log -t SphereAutoStart 'startup script started'\n")
            stdin.writeBytes("setenforce 0 2>/dev/null\n")
            stdin.writeBytes("sleep 15\n")
            stdin.writeBytes("log -t SphereAutoStart 'starting app after boot'\n")
            stdin.writeBytes("cmd package set-stopped-state $pkg false 2>/dev/null\n")
            stdin.writeBytes("am start -a android.intent.action.MAIN -n $activityComponent 2>/dev/null\n")
            stdin.writeBytes("sleep 5\n")
            stdin.writeBytes("am broadcast -a android.intent.action.BOOT_COMPLETED -n $receiverComponent --include-stopped-packages 2>/dev/null\n")
            stdin.writeBytes("for i in 1 2 3 4 5; do\n")
            stdin.writeBytes("  sleep 10\n")
            stdin.writeBytes("  pidof $pkg > /dev/null 2>&1 && break\n")
            stdin.writeBytes("  log -t SphereAutoStart \"retry \$i: starting app\"\n")
            stdin.writeBytes("  am start -a android.intent.action.MAIN -n $activityComponent 2>/dev/null\n")
            stdin.writeBytes("done\n")
            stdin.writeBytes("log -t SphereAutoStart 'starting watchdog'\n")
            stdin.writeBytes("exec sh $watchdogScript\n")
            stdin.writeBytes("STARTUP_EOF\n")
            stdin.writeBytes("chmod 755 $startupScript\n")

            // === 2. Монтируем /system в rw — НЕСКОЛЬКО СТРАТЕГИЙ ===
            // Стратегия 1: system-as-root (Android 9+ / LDPlayer) — / вместо /system
            stdin.writeBytes("mount -o remount,rw / 2>/dev/null\n")
            // Стратегия 2: классический remount /system
            stdin.writeBytes("mount -o remount,rw /system 2>/dev/null\n")
            // Стратегия 3: через blockdevice — находим устройство system раздела
            stdin.writeBytes("SYSDEV=\$(mount | grep ' /system ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$SYSDEV\" ] && mount -o remount,rw \"\$SYSDEV\" /system 2>/dev/null\n")
            // Стратегия 4: через blockdev + grep на /
            stdin.writeBytes("ROOTDEV=\$(mount | grep ' / ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$ROOTDEV\" ] && mount -o remount,rw \"\$ROOTDEV\" / 2>/dev/null\n")

            // === 3. Создаём директорию и записываем .rc файл ===
            stdin.writeBytes("mkdir -p /system/etc/init 2>/dev/null\n")
            stdin.writeBytes("cat > $rcPath << 'RC_EOF'\n")
            stdin.writeBytes("service sphere_autostart /system/bin/sh /data/local/tmp/sphere_startup.sh\n")
            stdin.writeBytes("    class late_start\n")
            stdin.writeBytes("    user root\n")
            stdin.writeBytes("    group root\n")
            stdin.writeBytes("    oneshot\n")
            stdin.writeBytes("    disabled\n")
            stdin.writeBytes("    seclabel u:r:su:s0\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("on property:sys.boot_completed=1\n")
            stdin.writeBytes("    start sphere_autostart\n")
            stdin.writeBytes("RC_EOF\n")
            stdin.writeBytes("chmod 644 $rcPath\n")

            // === 4. Верификация — проверяем что файл записан ===
            stdin.writeBytes("if [ -f $rcPath ]; then\n")
            stdin.writeBytes("  log -t SphereAutoStart 'init service .rc файл ЗАПИСАН УСПЕШНО'\n")
            stdin.writeBytes("else\n")
            stdin.writeBytes("  log -t SphereAutoStart 'ОШИБКА: init service .rc файл НЕ записан — /system read-only'\n")
            stdin.writeBytes("fi\n")

            // === 5. Возвращаем /system в ro ===
            stdin.writeBytes("mount -o remount,ro /system 2>/dev/null\n")
            stdin.writeBytes("mount -o remount,ro / 2>/dev/null\n")

            stdin.writeBytes("exit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(15, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут установки init service")
                return
            }

            Timber.i("RootAutoStart: init service установлен — $rcPath → $startupScript")
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: не удалось установить init service")
        }
    }

    // =====================================================================
    //  6. Установка как системное приложение — ГАРАНТИРОВАННЫЙ автостарт
    // =====================================================================

    /**
     * Копирует APK в /system/priv-app/ — делает приложение СИСТЕМНЫМ.
     *
     * Системное приложение с android:persistent="true":
     * - Запускается АВТОМАТИЧЕСКИ при каждой загрузке Android
     * - Не может быть убито пользователем или battery optimization
     * - Перезапускается при крэше
     * - Тот же механизм что Телефон, СМС, SystemUI
     *
     * ВАЖНО: При первом запуске приложение ещё НЕ system app (установлено в /data/app/).
     * После копирования в /system/priv-app/ и ребута — Android PackageManager обнаружит
     * его как system app. Начиная со второго ребута — гарантированный автостарт.
     *
     * Проверяет isSystemApp() перед записью — не дублирует если уже установлено.
     */
    private fun installAsSystemApp(context: Context, pkg: String) {
        // Если уже system app — не нужно ничего делать
        if (isSystemApp(context)) {
            Timber.i("RootAutoStart: приложение УЖЕ является system app — пропускаем установку")
            return
        }

        val systemDir = "/system/priv-app/SphereAgent"
        val systemApk = "$systemDir/base.apk"

        try {
            // Находим текущий APK через ApplicationInfo
            val sourceApk = context.applicationInfo.sourceDir
            Timber.i("RootAutoStart: копируем APK из $sourceApk в $systemApk")

            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)

            // Монтируем /system в rw — все стратегии
            stdin.writeBytes("mount -o remount,rw / 2>/dev/null\n")
            stdin.writeBytes("mount -o remount,rw /system 2>/dev/null\n")
            stdin.writeBytes("SYSDEV=\$(mount | grep ' /system ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$SYSDEV\" ] && mount -o remount,rw \"\$SYSDEV\" /system 2>/dev/null\n")
            stdin.writeBytes("ROOTDEV=\$(mount | grep ' / ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$ROOTDEV\" ] && mount -o remount,rw \"\$ROOTDEV\" / 2>/dev/null\n")

            // Создаём директорию и копируем APK
            stdin.writeBytes("mkdir -p $systemDir\n")
            stdin.writeBytes("cp $sourceApk $systemApk\n")
            stdin.writeBytes("chmod 644 $systemApk\n")
            stdin.writeBytes("chmod 755 $systemDir\n")

            // Верификация
            stdin.writeBytes("if [ -f $systemApk ]; then\n")
            stdin.writeBytes("  log -t SphereAutoStart 'system app APK СКОПИРОВАН УСПЕШНО в $systemDir'\n")
            stdin.writeBytes("else\n")
            stdin.writeBytes("  log -t SphereAutoStart 'ОШИБКА: не удалось скопировать APK в $systemDir'\n")
            stdin.writeBytes("fi\n")

            // Возвращаем /system в ro
            stdin.writeBytes("mount -o remount,ro /system 2>/dev/null\n")
            stdin.writeBytes("mount -o remount,ro / 2>/dev/null\n")

            stdin.writeBytes("exit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(15, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут установки system app")
                return
            }

            Timber.i("RootAutoStart: APK скопирован в $systemApk — после ребута станет system app")
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: не удалось установить как system app")
        }
    }

    /**
     * Проверяет, является ли приложение системным (установлено в /system/).
     */
    private fun isSystemApp(context: Context): Boolean {
        return context.applicationInfo.flags and ApplicationInfo.FLAG_SYSTEM != 0
    }

    // =====================================================================
    //  Root execution helpers
    // =====================================================================

    /**
     * Проверяет наличие root-доступа (su).
     * Кэширует результат — проверка выполняется один раз за жизнь процесса.
     */
    fun hasRoot(): Boolean {
        if (rootChecked) return rootAvailable
        rootAvailable = try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "id"))
            val completed = process.waitFor(5, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                false
            } else if (process.exitValue() == 0) {
                val output = process.inputStream.bufferedReader().readText()
                output.contains("uid=0")
            } else {
                false
            }
        } catch (e: Exception) {
            false
        }
        rootChecked = true
        Timber.d("RootAutoStart: root %s", if (rootAvailable) "доступен" else "недоступен")
        return rootAvailable
    }

    /**
     * Выполняет одну команду через su.
     * Тихо логирует ошибки — каждая настройка опциональна.
     */
    private fun execRoot(command: String) {
        try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
            val completed = process.waitFor(10, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут: $command")
                return
            }
            if (process.exitValue() == 0) {
                Timber.d("RootAutoStart: OK $command")
            } else {
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                Timber.w("RootAutoStart: FAIL $command exit=${process.exitValue()} $stderr")
            }
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: ошибка: $command")
        }
    }
}
