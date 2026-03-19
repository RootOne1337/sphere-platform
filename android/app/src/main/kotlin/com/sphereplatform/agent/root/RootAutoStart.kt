package com.sphereplatform.agent.root

import android.content.Context
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
 * ## Решение — 3 уровня:
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
 * - Property trigger sys.boot_completed=1 запускает startup-скрипт при каждой загрузке
 * - Startup-скрипт запускает приложение и watchdog daemon
 * - Это ЕДИНСТВЕННЫЙ механизм гарантированного запуска на LDPlayer:
 *   init.d, Magisk, userinit.sh — НЕ работают на минимальном ROM
 *
 * При boot: init → sphere_startup.sh → am start → SphereApp.onCreate() →
 * RootAutoStart обновляет watchdog. Цепочка замыкается без BootReceiver.
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
     * Это ЕДИНСТВЕННЫЙ механизм который работает на LDPlayer:
     * init.d, Magisk service.d, userinit.sh — НЕ работают на минимальном ROM.
     * Init property trigger — стандартный механизм ядра Android.
     *
     * Идемпотентно — перезаписывает файлы при каждом запуске (дёшево).
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

            // === 1. Записываем startup-скрипт (выполняется init при каждом boot) ===
            stdin.writeBytes("cat > $startupScript << 'STARTUP_EOF'\n")
            stdin.writeBytes("#!/system/bin/sh\n")
            stdin.writeBytes("# Sphere Platform — автостарт при загрузке\n")
            stdin.writeBytes("# Запускается Android init через property trigger sys.boot_completed=1\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Переключаем SELinux в permissive для гарантированного запуска\n")
            stdin.writeBytes("setenforce 0 2>/dev/null\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Ждём полной инициализации Android framework\n")
            stdin.writeBytes("sleep 15\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Снимаем stopped state — гарантия доставки broadcast\n")
            stdin.writeBytes("cmd package set-stopped-state $pkg false 2>/dev/null\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Попытка 1: запуск через Activity\n")
            stdin.writeBytes("am start -a android.intent.action.MAIN -n $activityComponent 2>/dev/null\n")
            stdin.writeBytes("sleep 5\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# BOOT_COMPLETED для BootReceiver\n")
            stdin.writeBytes("am broadcast -a android.intent.action.BOOT_COMPLETED -n $receiverComponent --include-stopped-packages 2>/dev/null\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Retry loop — до 3 попыток с проверкой процесса\n")
            stdin.writeBytes("for i in 1 2 3; do\n")
            stdin.writeBytes("  sleep 10\n")
            stdin.writeBytes("  pidof $pkg > /dev/null 2>&1 && break\n")
            stdin.writeBytes("  am start -a android.intent.action.MAIN -n $activityComponent 2>/dev/null\n")
            stdin.writeBytes("done\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("# Запускаем watchdog для постоянного мониторинга\n")
            stdin.writeBytes("exec sh $watchdogScript\n")
            stdin.writeBytes("STARTUP_EOF\n")
            stdin.writeBytes("chmod 755 $startupScript\n")

            // === 2. Монтируем /system в rw и записываем .rc файл ===
            stdin.writeBytes("mount -o remount,rw /system 2>/dev/null\n")
            stdin.writeBytes("cat > $rcPath << 'RC_EOF'\n")
            stdin.writeBytes("service sphere_autostart /system/bin/sh /data/local/tmp/sphere_startup.sh\n")
            stdin.writeBytes("    class late_start\n")
            stdin.writeBytes("    user root\n")
            stdin.writeBytes("    group root\n")
            stdin.writeBytes("    oneshot\n")
            stdin.writeBytes("    disabled\n")
            stdin.writeBytes("    seclabel u:r:shell:s0\n")
            stdin.writeBytes("\n")
            stdin.writeBytes("on property:sys.boot_completed=1\n")
            stdin.writeBytes("    start sphere_autostart\n")
            stdin.writeBytes("RC_EOF\n")
            stdin.writeBytes("chmod 644 $rcPath\n")
            stdin.writeBytes("mount -o remount,ro /system 2>/dev/null\n")

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
