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
     * Принудительный запуск приложения через root.
     *
     * Вызывается из [KeepAliveWorker] при каждом тике (каждые 15 мин).
     * Не зависит от enrollment, FGS ограничений, Doze mode.
     * Идемпотентно — если сервис уже работает, am startservice ничего не сделает.
     *
     * Цепочка: WorkManager (переживает ребут) → ensureRunning() → root am start →
     * приложение запущено. Это ЕДИНСТВЕННАЯ цепочка не зависящая от /system.
     */
    fun ensureRunning(context: Context) {
        if (!hasRoot()) return
        val pkg = context.packageName

        // Снять stopped state — гарантия что broadcast и service start сработают
        execRoot("cmd package set-stopped-state $pkg false")

        // Запустить foreground service напрямую через am (минуя startForegroundService Java API)
        execRoot("am startservice -n $pkg/$NAMESPACE.service.SphereAgentService")

        // Отправить BOOT_COMPLETED для BootReceiver — активирует ВСЕ защитные механизмы
        // (KeepAliveWorker.schedule, ServiceWatchdog.schedule, AutoEnrollment)
        execRoot(
            "am broadcast -a android.intent.action.BOOT_COMPLETED" +
                " -n $pkg/$NAMESPACE.BootReceiver --include-stopped-packages",
        )

        Timber.d("RootAutoStart: ensureRunning — принудительный запуск через root для $pkg")
    }

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

        // 5+6. Установить ВСЕ механизмы автозапуска через ОДНУ su-сессию:
        //       init service (.rc файлы) + system app (/system/priv-app/)
        //       С отключением SELinux, записью во ВСЕ пути, верификацией
        installSystemAutostart(context, pkg)

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
    //  5 + 6. ПОЛНАЯ установка автозапуска (init service + system app)
    //  Выполняется через ОДНУ su-сессию для атомарности и скорости
    // =====================================================================

    /**
     * Устанавливает ВСЕ механизмы автозапуска через одну root-сессию:
     *
     * 1. Отключает SELinux (КРИТИЧЕСКИ ВАЖНО — без этого запись в /system блокируется)
     * 2. Монтирует / и /system в rw (4 стратегии)
     * 3. Записывает startup-скрипт в /data/local/tmp/ (100% writable)
     * 4. Записывает .rc файл в КАЖДЫЙ возможный путь init (system, vendor, odm, product)
     * 5. Дописывает import в СУЩЕСТВУЮЩИЕ init.rc файлы (fallback)
     * 6. Копирует APK в /system/priv-app/ (system app с persistent=true)
     * 7. Устанавливает правильные SELinux labels (chcon)
     * 8. Верифицирует ВСЕ записи с логированием в logcat
     *
     * ВАЖНО: SELinux на LDPlayer мог БЛОКИРОВАТЬ запись файлов даже при rw mount.
     * Предыдущие версии НЕ отключали SELinux перед записью → файлы не создавались.
     */
    private fun installSystemAutostart(context: Context, pkg: String) {
        val startupScript = "/data/local/tmp/sphere_startup.sh"
        val watchdogScript = "/data/local/tmp/sphere_watchdog.sh"
        val activityComponent = "$pkg/$NAMESPACE.ui.SetupActivity"
        val receiverComponent = "$pkg/$NAMESPACE.BootReceiver"
        val sourceApk = context.applicationInfo.sourceDir
        val systemDir = "/system/priv-app/SphereAgent"
        val systemApk = "$systemDir/base.apk"
        val isAlreadySystemApp = isSystemApp(context)

        try {
            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)

            // ═══════════════════════════════════════════════════════════════
            //  ДИАГНОСТИКА: пишем в logcat каждый шаг
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("log -t SphereAutoStart '=== НАЧАЛО УСТАНОВКИ АВТОЗАПУСКА ==='\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 0: ОТКЛЮЧИТЬ SELINUX — БЕЗ ЭТОГО НИЧЕГО НЕ РАБОТАЕТ
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("log -t SphereAutoStart 'SELinux до: '\$(getenforce)\n")
            stdin.writeBytes("setenforce 0\n")
            // supolicy — снятие SELinux restrictions если su от SuperSU/phh
            stdin.writeBytes("supolicy --live 'allow * * * *' 2>/dev/null\n")
            stdin.writeBytes("log -t SphereAutoStart 'SELinux после: '\$(getenforce)\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 1: МОНТИРОВАНИЕ — ВСЕ СТРАТЕГИИ
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("log -t SphereAutoStart 'Монтируем /system в rw...'\n")
            // system-as-root (LDPlayer Android 9+)
            stdin.writeBytes("mount -o remount,rw / && log -t SphereAutoStart 'mount / rw: OK' || log -t SphereAutoStart 'mount / rw: FAIL'\n")
            // Классический remount
            stdin.writeBytes("mount -o remount,rw /system && log -t SphereAutoStart 'mount /system rw: OK' || log -t SphereAutoStart 'mount /system rw: FAIL'\n")
            // Через blockdevice
            stdin.writeBytes("SYSDEV=\$(mount | grep ' /system ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$SYSDEV\" ] && mount -o remount,rw \"\$SYSDEV\" /system && log -t SphereAutoStart \"mount blockdev /system rw: OK (\$SYSDEV)\" || true\n")
            stdin.writeBytes("ROOTDEV=\$(mount | grep ' / ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$ROOTDEV\" ] && mount -o remount,rw \"\$ROOTDEV\" / && log -t SphereAutoStart \"mount blockdev / rw: OK (\$ROOTDEV)\" || true\n")
            // Через /proc/mounts — ищем system partition
            stdin.writeBytes("SYSBLK=\$(cat /proc/mounts | grep -E '/system|/ ' | head -1 | awk '{print \$1}')\n")
            stdin.writeBytes("[ -n \"\$SYSBLK\" ] && blockdev --setrw \"\$SYSBLK\" 2>/dev/null && mount -o remount,rw \"\$SYSBLK\" /system 2>/dev/null\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 2: STARTUP-СКРИПТ в /data/local/tmp/ (100% writable)
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("cat > $startupScript << 'STARTUP_EOF'\n")
            stdin.writeBytes("#!/system/bin/sh\n")
            stdin.writeBytes("log -t SphereAutoStart 'BOOT STARTUP: скрипт запущен'\n")
            stdin.writeBytes("setenforce 0 2>/dev/null\n")
            stdin.writeBytes("sleep 15\n")
            stdin.writeBytes("log -t SphereAutoStart 'BOOT STARTUP: запускаем приложение'\n")
            stdin.writeBytes("cmd package set-stopped-state $pkg false\n")
            stdin.writeBytes("am start -a android.intent.action.MAIN -n $activityComponent\n")
            stdin.writeBytes("sleep 5\n")
            stdin.writeBytes("am startservice -n $pkg/$NAMESPACE.service.SphereAgentService\n")
            stdin.writeBytes("am broadcast -a android.intent.action.BOOT_COMPLETED -n $receiverComponent --include-stopped-packages\n")
            stdin.writeBytes("for i in 1 2 3 4 5 6 7 8 9 10; do\n")
            stdin.writeBytes("  sleep 10\n")
            stdin.writeBytes("  if pidof $pkg > /dev/null 2>&1; then\n")
            stdin.writeBytes("    log -t SphereAutoStart \"BOOT STARTUP: процесс жив после попытки \$i\"\n")
            stdin.writeBytes("    break\n")
            stdin.writeBytes("  fi\n")
            stdin.writeBytes("  log -t SphereAutoStart \"BOOT STARTUP: retry \$i\"\n")
            stdin.writeBytes("  am start -a android.intent.action.MAIN -n $activityComponent\n")
            stdin.writeBytes("  am startservice -n $pkg/$NAMESPACE.service.SphereAgentService\n")
            stdin.writeBytes("done\n")
            stdin.writeBytes("log -t SphereAutoStart 'BOOT STARTUP: переход к watchdog'\n")
            stdin.writeBytes("exec sh $watchdogScript\n")
            stdin.writeBytes("STARTUP_EOF\n")
            stdin.writeBytes("chmod 755 $startupScript\n")
            stdin.writeBytes("log -t SphereAutoStart 'startup-скрипт записан: $startupScript'\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 3: .RC ФАЙЛ — ВО ВСЕ ВОЗМОЖНЫЕ ПУТИ
            // ═══════════════════════════════════════════════════════════════
            val rcContent = """service sphere_autostart /system/bin/sh $startupScript
    class late_start
    user root
    group root
    oneshot
    disabled
    seclabel u:r:su:s0

on property:sys.boot_completed=1
    start sphere_autostart
"""
            // Эскейпим и записываем через printf для надёжности
            val rcEscaped = rcContent.replace("\\", "\\\\").replace("'", "'\\''")

            // Пути для .rc файлов — Android init ищет во ВСЕХ этих директориях
            val rcPaths = listOf(
                "/system/etc/init/sphere_autostart.rc",
                "/vendor/etc/init/sphere_autostart.rc",
                "/odm/etc/init/sphere_autostart.rc",
                "/product/etc/init/sphere_autostart.rc",
            )
            for (rcPath in rcPaths) {
                val dir = rcPath.substringBeforeLast('/')
                stdin.writeBytes("mkdir -p $dir 2>/dev/null\n")
                stdin.writeBytes("printf '%s' '$rcEscaped' > $rcPath 2>/dev/null\n")
                stdin.writeBytes("chmod 644 $rcPath 2>/dev/null\n")
                // КРИТИЧЕСКИ ВАЖНО: правильный SELinux label!
                stdin.writeBytes("chcon u:object_r:system_file:s0 $rcPath 2>/dev/null\n")
                stdin.writeBytes("[ -f $rcPath ] && log -t SphereAutoStart 'rc ЗАПИСАН: $rcPath' || log -t SphereAutoStart 'rc НЕ записан: $rcPath'\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 4: IMPORT В СУЩЕСТВУЮЩИЕ init.rc (fallback)
            // ═══════════════════════════════════════════════════════════════
            // Также записываем .rc в /data/ и добавляем import в существующие файлы
            stdin.writeBytes("printf '%s' '$rcEscaped' > /data/local/tmp/sphere_autostart.rc\n")
            stdin.writeBytes("chmod 644 /data/local/tmp/sphere_autostart.rc\n")
            val importLine = "import /data/local/tmp/sphere_autostart.rc"
            val initRcPaths = listOf(
                "/system/etc/init/hw/init.rc",
                "/init.rc",
                "/system/etc/init/hw/init.target.rc",
            )
            for (initRc in initRcPaths) {
                stdin.writeBytes("if [ -f $initRc ]; then\n")
                stdin.writeBytes("  grep -q sphere_autostart $initRc || echo '$importLine' >> $initRc\n")
                stdin.writeBytes("  grep -q sphere_autostart $initRc && log -t SphereAutoStart 'import ДОБАВЛЕН в $initRc' || log -t SphereAutoStart 'import НЕ добавлен в $initRc'\n")
                stdin.writeBytes("fi\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 5: SYSTEM APP — копируем APK в /system/priv-app/
            // ═══════════════════════════════════════════════════════════════
            if (!isAlreadySystemApp) {
                stdin.writeBytes("log -t SphereAutoStart 'Копируем APK в /system/priv-app/...'\n")
                stdin.writeBytes("mkdir -p $systemDir\n")
                stdin.writeBytes("cp $sourceApk $systemApk\n")
                stdin.writeBytes("chmod 644 $systemApk\n")
                stdin.writeBytes("chmod 755 $systemDir\n")
                stdin.writeBytes("chcon -R u:object_r:system_file:s0 $systemDir 2>/dev/null\n")
                stdin.writeBytes("[ -f $systemApk ] && log -t SphereAutoStart 'system app APK СКОПИРОВАН: $systemApk' || log -t SphereAutoStart 'system app APK НЕ скопирован!'\n")
            } else {
                stdin.writeBytes("log -t SphereAutoStart 'Приложение уже system app — пропускаем копирование'\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 6: ВОЗВРАЩАЕМ /system в ro
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("mount -o remount,ro /system 2>/dev/null\n")
            stdin.writeBytes("mount -o remount,ro / 2>/dev/null\n")
            stdin.writeBytes("log -t SphereAutoStart '=== УСТАНОВКА АВТОЗАПУСКА ЗАВЕРШЕНА ==='\n")

            stdin.writeBytes("exit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(30, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут установки автозапуска (30с)")
                return
            }

            Timber.i("RootAutoStart: автозапуск установлен — проверь logcat -s SphereAutoStart")
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: не удалось установить автозапуск")
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
