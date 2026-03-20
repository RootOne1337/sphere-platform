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

        // Диагностика — факт вызова ensureRunning записываем в файл
        execRoot("echo \"[ENSURE] \$(date) pkg=$pkg\" >> $DIAG_FILE")

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

    /** Файл диагностики — пользователь проверяет через adb shell cat /data/local/tmp/sphere_diag.txt */
    private const val DIAG_FILE = "/data/local/tmp/sphere_diag.txt"

    /**
     * Главная точка входа. Выполняет ВСЕ root-настройки.
     *
     * Безопасен для вызова из любого контекста — если root недоступен,
     * тихо возвращается без ошибок.
     *
     * Пишет диагностику в [DIAG_FILE] — после ребута можно проверить
     * через adb shell cat /data/local/tmp/sphere_diag.txt
     */
    fun configure(context: Context) {
        if (!hasRoot()) {
            Timber.d("RootAutoStart: root недоступен — пропускаем")
            return
        }

        val pkg = context.packageName
        Timber.i("RootAutoStart: === НАЧАЛО НАСТРОЙКИ для $pkg ===")

        // Диагностика — записываем факт запуска в файл (переживает ребут)
        execRoot("echo \"[CONFIGURE] \$(date) pkg=$pkg pid=\$\$\" >> $DIAG_FILE")

        // 1. Снять системные ограничения
        removeSystemRestrictions(pkg)

        // 2. Выдать runtime permissions
        grantPermissions(pkg)

        // 3. Принудительный BOOT_COMPLETED
        triggerBootReceiver(pkg)

        // 4. Запустить nohup watchdog daemon
        startWatchdogDaemon(pkg)

        // 5+6. init service (.rc файлы) + прямая вставка в init.rc +
        //       system app + userinit.sh/init.d + полная диагностика
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
    //  5 + 6. ПОЛНАЯ установка автозапуска
    //  ОДНА su-сессия: SELinux off → mount rw → .rc БЕЗ seclabel →
    //  прямая вставка exec в init.rc → userinit.sh → init.d → system app
    // =====================================================================

    /**
     * Устанавливает ВСЕ механизмы автозапуска через одну root-сессию.
     *
     * ### Исправленные баги (предыдущие версии):
     * - **seclabel u:r:su:s0** — этого SELinux context НЕ СУЩЕСТВУЕТ на LDPlayer →
     *   init ОТКАЗЫВАЛСЯ запускать service → startup script никогда не выполнялся.
     *   ИСПРАВЛЕНО: seclabel УБРАН (setenforce 0 делает его ненужным).
     * - **Только import в init.rc** — import НОВОГО файла может игнорироваться init.
     *   ИСПРАВЛЕНО: ПРЯМАЯ вставка `exec` команды в существующий `on property:sys.boot_completed=1` блок.
     * - **Нет fallback-механизмов** — если .rc не парсится init, ничего не работало.
     *   ИСПРАВЛЕНО: добавлены userinit.sh + init.d + несколько trigger'ов в .rc
     * - **Нет диагностики** — невозможно понять что пошло не так.
     *   ИСПРАВЛЕНО: каждый шаг пишет в /data/local/tmp/sphere_diag.txt
     *
     * ### Механизмы (7 уровней гарантии):
     * 1. .rc файл с trigger'ами: on property:sys.boot_completed=1,
     *    on property:dev.bootcomplete=1, on late-init
     * 2. Прямая вставка exec в существующий init.rc
     * 3. /data/local/userinit.sh (CyanogenMod/Android-x86 legacy)
     * 4. /system/etc/init.d/ скрипт (некоторые ROM)
     * 5. /data/adb/service.d/ скрипт (Magisk-like)
     * 6. System app в /system/priv-app/ (persistent=true)
     * 7. Файловая диагностика для отладки (sphere_diag.txt)
     */
    private fun installSystemAutostart(context: Context, pkg: String) {
        val startupScript = "/data/local/tmp/sphere_startup.sh"
        val watchdogScript = "/data/local/tmp/sphere_watchdog.sh"
        val activityComponent = "$pkg/$NAMESPACE.ui.SetupActivity"
        val receiverComponent = "$pkg/$NAMESPACE.BootReceiver"
        val serviceComponent = "$pkg/$NAMESPACE.service.SphereAgentService"
        val sourceApk = context.applicationInfo.sourceDir
        val systemDir = "/system/priv-app/SphereAgent"
        val systemApk = "$systemDir/base.apk"
        val isAlreadySystemApp = isSystemApp(context)

        try {
            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)

            // ── ДИАГНОСТИКА: файл-лог в /data/local/tmp/ ──────────────────
            fun diag(msg: String) {
                stdin.writeBytes("echo \"[INSTALL] \$(date) $msg\" >> $DIAG_FILE\n")
                stdin.writeBytes("log -t SphereAutoStart '$msg'\n")
            }

            diag("=== НАЧАЛО УСТАНОВКИ АВТОЗАПУСКА ===")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 0: ОТКЛЮЧИТЬ SELINUX
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("echo \"[INSTALL] \$(date) SELinux до: \$(getenforce)\" >> $DIAG_FILE\n")
            stdin.writeBytes("setenforce 0\n")
            stdin.writeBytes("supolicy --live 'allow * * * *' 2>/dev/null\n")
            stdin.writeBytes("echo \"[INSTALL] \$(date) SELinux после: \$(getenforce)\" >> $DIAG_FILE\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 1: МОНТИРОВАНИЕ /system в rw — ВСЕ СТРАТЕГИИ
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("mount -o remount,rw / 2>&1 && echo '[INSTALL] mount / rw: OK' >> $DIAG_FILE || echo '[INSTALL] mount / rw: FAIL' >> $DIAG_FILE\n")
            stdin.writeBytes("mount -o remount,rw /system 2>&1 && echo '[INSTALL] mount /system rw: OK' >> $DIAG_FILE || echo '[INSTALL] mount /system rw: FAIL' >> $DIAG_FILE\n")
            stdin.writeBytes("SYSDEV=\$(mount | grep ' /system ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$SYSDEV\" ] && mount -o remount,rw \"\$SYSDEV\" /system 2>/dev/null\n")
            stdin.writeBytes("ROOTDEV=\$(mount | grep ' / ' | head -1 | cut -d' ' -f1)\n")
            stdin.writeBytes("[ -n \"\$ROOTDEV\" ] && mount -o remount,rw \"\$ROOTDEV\" / 2>/dev/null\n")
            stdin.writeBytes("SYSBLK=\$(cat /proc/mounts | grep -E '/system |/ ' | head -1 | awk '{print \$1}')\n")
            stdin.writeBytes("[ -n \"\$SYSBLK\" ] && blockdev --setrw \"\$SYSBLK\" 2>/dev/null && mount -o remount,rw \"\$SYSBLK\" /system 2>/dev/null\n")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 2: STARTUP-СКРИПТ (запускает app + retry + watchdog)
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("cat > $startupScript << 'STARTUP_EOF'\n")
            stdin.writeBytes("#!/system/bin/sh\n")
            stdin.writeBytes("echo \"[BOOT] \$(date) sphere_startup.sh ЗАПУЩЕН\" >> $DIAG_FILE\n")
            stdin.writeBytes("log -t SphereAutoStart 'BOOT: startup script запущен'\n")
            stdin.writeBytes("setenforce 0 2>/dev/null\n")
            stdin.writeBytes("sleep 10\n")
            stdin.writeBytes("log -t SphereAutoStart 'BOOT: запускаем приложение'\n")
            stdin.writeBytes("cmd package set-stopped-state $pkg false 2>/dev/null\n")
            stdin.writeBytes("am start -a android.intent.action.MAIN -n $activityComponent 2>&1 | log -t SphereAutoStart\n")
            stdin.writeBytes("sleep 3\n")
            stdin.writeBytes("am startservice -n $serviceComponent 2>&1 | log -t SphereAutoStart\n")
            stdin.writeBytes("am broadcast -a android.intent.action.BOOT_COMPLETED -n $receiverComponent --include-stopped-packages 2>&1 | log -t SphereAutoStart\n")
            stdin.writeBytes("for i in 1 2 3 4 5 6 7 8 9 10; do\n")
            stdin.writeBytes("  sleep 10\n")
            stdin.writeBytes("  if pidof $pkg > /dev/null 2>&1; then\n")
            stdin.writeBytes("    echo \"[BOOT] \$(date) процесс жив после попытки \$i\" >> $DIAG_FILE\n")
            stdin.writeBytes("    break\n")
            stdin.writeBytes("  fi\n")
            stdin.writeBytes("  echo \"[BOOT] \$(date) retry \$i\" >> $DIAG_FILE\n")
            stdin.writeBytes("  am start -a android.intent.action.MAIN -n $activityComponent 2>/dev/null\n")
            stdin.writeBytes("  am startservice -n $serviceComponent 2>/dev/null\n")
            stdin.writeBytes("done\n")
            stdin.writeBytes("echo \"[BOOT] \$(date) переход к watchdog\" >> $DIAG_FILE\n")
            stdin.writeBytes("exec sh $watchdogScript\n")
            stdin.writeBytes("STARTUP_EOF\n")
            stdin.writeBytes("chmod 755 $startupScript\n")
            diag("startup-скрипт записан")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 3: .RC ФАЙЛ — БЕЗ seclabel! НЕСКОЛЬКО TRIGGER'ОВ!
            //
            //  КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: убран seclabel u:r:su:s0
            //  Этот SELinux context НЕ СУЩЕСТВУЕТ на LDPlayer Android 9!
            //  Init видел неизвестный seclabel → МОЛЧА отказывался запускать
            //  service → startup script НИКОГДА не выполнялся.
            //  При setenforce 0 seclabel не нужен.
            //
            //  Добавлены множественные trigger'ы:
            //  - on property:sys.boot_completed=1 (стандартный)
            //  - on property:dev.bootcomplete=1 (некоторые ROM)
            //  - on late-init (ранний этап загрузки)
            // ═══════════════════════════════════════════════════════════════
            val rcContent = buildString {
                appendLine("service sphere_autostart /system/bin/sh $startupScript")
                appendLine("    class late_start")
                appendLine("    user root")
                appendLine("    group root")
                appendLine("    oneshot")
                appendLine("    disabled")
                appendLine("")
                appendLine("on property:sys.boot_completed=1")
                appendLine("    start sphere_autostart")
                appendLine("")
                appendLine("on property:dev.bootcomplete=1")
                appendLine("    start sphere_autostart")
                appendLine("")
                appendLine("on late-init")
                appendLine("    start sphere_autostart")
            }

            // Записываем .rc через heredoc — надёжнее printf с escape
            val rcPaths = listOf(
                "/system/etc/init/sphere_autostart.rc",
                "/vendor/etc/init/sphere_autostart.rc",
                "/odm/etc/init/sphere_autostart.rc",
                "/product/etc/init/sphere_autostart.rc",
            )
            for (rcPath in rcPaths) {
                val dir = rcPath.substringBeforeLast('/')
                stdin.writeBytes("mkdir -p $dir 2>/dev/null\n")
                stdin.writeBytes("cat > $rcPath << 'RC_EOF'\n")
                stdin.writeBytes(rcContent)
                stdin.writeBytes("\nRC_EOF\n")
                stdin.writeBytes("chmod 644 $rcPath 2>/dev/null\n")
                stdin.writeBytes("chcon u:object_r:system_file:s0 $rcPath 2>/dev/null\n")
                stdin.writeBytes("if [ -f $rcPath ]; then echo '[INSTALL] rc ЗАПИСАН: $rcPath' >> $DIAG_FILE; else echo '[INSTALL] rc НЕ записан: $rcPath' >> $DIAG_FILE; fi\n")
            }

            // Также в /data/local/tmp/ — гарантированно writable
            stdin.writeBytes("cat > /data/local/tmp/sphere_autostart.rc << 'RC_EOF'\n")
            stdin.writeBytes(rcContent)
            stdin.writeBytes("\nRC_EOF\n")
            stdin.writeBytes("chmod 644 /data/local/tmp/sphere_autostart.rc\n")
            diag("rc в /data/local/tmp/ записан")

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 4: ПРЯМАЯ ВСТАВКА exec В СУЩЕСТВУЮЩИЙ init.rc
            //  Вместо import (который может не парситься) — ВСТАВЛЯЕМ
            //  exec /system/bin/sh -c "sh /data/local/tmp/sphere_startup.sh &"
            //  прямо в блок on property:sys.boot_completed=1
            // ═══════════════════════════════════════════════════════════════
            val execLine = "    exec -- /system/bin/sh -c \"sh $startupScript &\""
            val initRcFiles = listOf(
                "/system/etc/init/hw/init.rc",
                "/init.rc",
                "/system/etc/init/hw/init.target.rc",
            )
            for (initRc in initRcFiles) {
                // Если файл существует и содержит sys.boot_completed —
                // добавляем exec ПОСЛЕ строки property trigger
                stdin.writeBytes("if [ -f $initRc ]; then\n")
                stdin.writeBytes("  if grep -q 'sys.boot_completed=1' $initRc; then\n")
                stdin.writeBytes("    if ! grep -q 'sphere_startup' $initRc; then\n")
                stdin.writeBytes("      sed -i '/sys.boot_completed=1/a\\$execLine' $initRc 2>/dev/null\n")
                stdin.writeBytes("      grep -q 'sphere_startup' $initRc && echo '[INSTALL] exec ВСТАВЛЕН в $initRc' >> $DIAG_FILE || echo '[INSTALL] exec НЕ вставлен (sed fail) в $initRc' >> $DIAG_FILE\n")
                stdin.writeBytes("    else\n")
                stdin.writeBytes("      echo '[INSTALL] exec УЖЕ есть в $initRc' >> $DIAG_FILE\n")
                stdin.writeBytes("    fi\n")
                stdin.writeBytes("  else\n")
                // Нет блока sys.boot_completed — добавляем целый блок в конец
                stdin.writeBytes("    echo '' >> $initRc\n")
                stdin.writeBytes("    echo 'on property:sys.boot_completed=1' >> $initRc\n")
                stdin.writeBytes("    echo '$execLine' >> $initRc\n")
                stdin.writeBytes("    echo '[INSTALL] блок boot_completed ДОБАВЛЕН в конец $initRc' >> $DIAG_FILE\n")
                stdin.writeBytes("  fi\n")
                stdin.writeBytes("else\n")
                stdin.writeBytes("  echo '[INSTALL] нет файла $initRc' >> $DIAG_FILE\n")
                stdin.writeBytes("fi\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 5: userinit.sh — CyanogenMod/Android-x86 fallback
            //  Многие эмуляторы (LDPlayer = Android-x86 based) запускают
            //  /data/local/userinit.sh при каждой загрузке
            // ═══════════════════════════════════════════════════════════════
            val userinitPaths = listOf(
                "/data/local/userinit.sh",
                "/data/local/tmp/userinit.sh",
            )
            for (userinitPath in userinitPaths) {
                stdin.writeBytes("if [ ! -f $userinitPath ] || ! grep -q 'sphere_startup' $userinitPath 2>/dev/null; then\n")
                stdin.writeBytes("  echo '#!/system/bin/sh' > $userinitPath 2>/dev/null\n")
                stdin.writeBytes("  echo 'echo \"[USERINIT] \$(date) userinit.sh запущен\" >> $DIAG_FILE' >> $userinitPath\n")
                stdin.writeBytes("  echo 'sh $startupScript &' >> $userinitPath\n")
                stdin.writeBytes("  chmod 755 $userinitPath\n")
                stdin.writeBytes("  echo '[INSTALL] userinit записан: $userinitPath' >> $DIAG_FILE\n")
                stdin.writeBytes("fi\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 6: init.d — некоторые ROM запускают всё из этой папки
            // ═══════════════════════════════════════════════════════════════
            val initdPaths = listOf(
                "/system/etc/init.d",
                "/data/adb/service.d",
            )
            for (initdDir in initdPaths) {
                stdin.writeBytes("mkdir -p $initdDir 2>/dev/null\n")
                val initdScript = "$initdDir/99sphere"
                stdin.writeBytes("cat > $initdScript << 'INITD_EOF'\n")
                stdin.writeBytes("#!/system/bin/sh\n")
                stdin.writeBytes("echo \"[INITD] \$(date) init.d скрипт запущен\" >> $DIAG_FILE\n")
                stdin.writeBytes("sh $startupScript &\n")
                stdin.writeBytes("INITD_EOF\n")
                stdin.writeBytes("chmod 755 $initdScript 2>/dev/null\n")
                stdin.writeBytes("chcon u:object_r:system_file:s0 $initdScript 2>/dev/null\n")
                stdin.writeBytes("[ -f $initdScript ] && echo '[INSTALL] init.d записан: $initdScript' >> $DIAG_FILE || echo '[INSTALL] init.d НЕ записан: $initdScript' >> $DIAG_FILE\n")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 7: SYSTEM APP — /system/priv-app/
            // ═══════════════════════════════════════════════════════════════
            if (!isAlreadySystemApp) {
                diag("копируем APK в /system/priv-app/...")
                stdin.writeBytes("mkdir -p $systemDir\n")
                stdin.writeBytes("cp $sourceApk $systemApk\n")
                stdin.writeBytes("chmod 644 $systemApk\n")
                stdin.writeBytes("chmod 755 $systemDir\n")
                stdin.writeBytes("chcon -R u:object_r:system_file:s0 $systemDir 2>/dev/null\n")
                stdin.writeBytes("if [ -f $systemApk ]; then echo '[INSTALL] system app APK СКОПИРОВАН' >> $DIAG_FILE; else echo '[INSTALL] system app APK НЕ скопирован!' >> $DIAG_FILE; fi\n")
            } else {
                diag("уже system app — пропускаем")
            }

            // ═══════════════════════════════════════════════════════════════
            //  ШАГ 8: ВОЗВРАТ /system в ro + финальная диагностика
            // ═══════════════════════════════════════════════════════════════
            stdin.writeBytes("mount -o remount,ro /system 2>/dev/null\n")
            stdin.writeBytes("mount -o remount,ro / 2>/dev/null\n")

            // Финальная сводка — показать ВСЕ установленные файлы
            stdin.writeBytes("echo '--- ФАЙЛЫ ---' >> $DIAG_FILE\n")
            stdin.writeBytes("ls -la $startupScript >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("ls -la /system/etc/init/sphere_autostart.rc >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("ls -la /vendor/etc/init/sphere_autostart.rc >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("ls -la $systemDir/base.apk >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("ls -la /data/local/userinit.sh >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("ls -la /system/etc/init.d/99sphere >> $DIAG_FILE 2>&1\n")
            stdin.writeBytes("echo '--- КОНЕЦ ---' >> $DIAG_FILE\n")

            diag("=== УСТАНОВКА ЗАВЕРШЕНА ===")

            stdin.writeBytes("exit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(30, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут установки автозапуска (30с)")
                return
            }

            Timber.i("RootAutoStart: автозапуск установлен — диагностика: adb shell cat $DIAG_FILE")
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
