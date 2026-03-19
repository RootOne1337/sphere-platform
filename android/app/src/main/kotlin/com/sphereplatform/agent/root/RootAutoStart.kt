package com.sphereplatform.agent.root

import android.content.Context
import timber.log.Timber
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.InputStreamReader
import java.util.concurrent.TimeUnit

/**
 * RootAutoStart — **бронебойный** автостарт агента на рутованных эмуляторах.
 *
 * ## Проблема
 * На LDPlayer / Nox / MEmu (Android 9, x86) стандартные Android-механизмы
 * автостарта (BOOT_COMPLETED, WorkManager/JobScheduler, AlarmManager) могут
 * НЕ РАБОТАТЬ из-за кастомных модификаций ОС в эмуляторах.
 *
 * ## Решение
 * При первом запуске APK через **root (su)** регистрируем системный boot-скрипт
 * который при КАЖДОЙ загрузке ОС запускает наше приложение. Пробуем ВСЕ
 * известные пути одновременно — хотя бы один сработает:
 *
 * 1. `/system/etc/init.d/99sphere` — классический init.d (busybox init)
 * 2. `/data/adb/service.d/sphere_autostart.sh` — Magisk service скрипт
 * 3. `/data/local/userinit.sh` — Android-x86 / BlissOS / некоторые эмуляторы
 *
 * Дополнительно:
 * - Снимает Stopped State (BOOT_COMPLETED доставляется)
 * - Whitelist от Doze battery optimization
 * - Разрешает фоновую работу
 * - Выдаёт runtime permissions через `pm grant`
 * - Форсит BOOT_COMPLETED broadcast (немедленный запуск BootReceiver)
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

    /** Имя файла-маркера что boot-скрипт уже создан. */
    private const val MARKER_FILE = "root_boot_script_installed"

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

        // ── 1. Снять системные ограничения ──────────────────────────────
        removeSystemRestrictions(pkg)

        // ── 2. Выдать runtime permissions ───────────────────────────────
        grantPermissions(pkg)

        // ── 3. Установить boot-скрипт (один раз) ───────────────────────
        installBootScript(context, pkg)

        // ── 4. Форсировать BOOT_COMPLETED прямо сейчас ──────────────────
        triggerBootReceiver(pkg)

        Timber.i("RootAutoStart: === НАСТРОЙКА ЗАВЕРШЕНА для $pkg ===")
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  1. Снятие системных ограничений
    // ═══════════════════════════════════════════════════════════════════════

    private fun removeSystemRestrictions(pkg: String) {
        // Снять Stopped State — гарантия доставки implicit broadcasts
        // ВАЖНО: НЕ используем am force-stop — это убьёт наш собственный процесс!
        execRoot("cmd package set-stopped-state $pkg false")

        // Whitelist от Doze battery optimization
        execRoot("dumpsys deviceidle whitelist +$pkg")

        // Разрешить фоновую работу
        execRoot("cmd appops set $pkg RUN_IN_BACKGROUND allow")
        execRoot("cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow")

        // Гарантировать что BootReceiver включён
        execRoot("pm enable $pkg/.BootReceiver")

        // Отключить battery restrictions для пакета
        execRoot("cmd appops set $pkg WAKE_LOCK allow")

        Timber.i("RootAutoStart: системные ограничения сняты")
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  2. Выдача runtime permissions
    // ═══════════════════════════════════════════════════════════════════════

    private fun grantPermissions(pkg: String) {
        // Основные permissions (через root — без диалога)
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

    // ═══════════════════════════════════════════════════════════════════════
    //  3. Boot-скрипт — ГЛАВНЫЙ механизм автостарта
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Создаёт boot-скрипт во ВСЕХ известных путях одновременно.
     *
     * Скрипт при загрузке ОС:
     * 1. Ждёт завершения загрузки (sys.boot_completed == 1)
     * 2. Ждёт поднятия сети
     * 3. Отправляет BOOT_COMPLETED broadcast нашему BootReceiver
     * 4. Запускает SphereAgentService напрямую
     *
     * Пути boot-скриптов:
     * - /system/etc/init.d/ — классический busybox init (LDPlayer, многие ROM)
     * - /data/adb/service.d/ — Magisk (если установлен)
     * - /data/local/userinit.sh — Android-x86, BlissOS, некоторые эмуляторы
     */
    private fun installBootScript(context: Context, pkg: String) {
        // Проверяем маркер — скрипт уже установлен?
        val markerFile = context.getFileStreamPath(MARKER_FILE)
        if (markerFile.exists()) {
            Timber.d("RootAutoStart: boot-скрипт уже установлен (маркер найден)")
            return
        }

        // Содержимое boot-скрипта
        val bootScript = buildBootScript(pkg)

        // ── Путь A: /system/etc/init.d/ ──────────────────────────────────
        val initdInstalled = installToInitD(bootScript)

        // ── Путь B: /data/adb/service.d/ (Magisk) ───────────────────────
        val magiskInstalled = installToMagiskServiceD(bootScript)

        // ── Путь C: /data/local/userinit.sh (Android-x86) ───────────────
        val userinitInstalled = installToUserinit(bootScript, pkg)

        if (initdInstalled || magiskInstalled || userinitInstalled) {
            // Создаём маркер-файл
            runCatching { markerFile.writeText("installed") }
            Timber.i(
                "RootAutoStart: boot-скрипт установлен [init.d=%s, magisk=%s, userinit=%s]",
                initdInstalled, magiskInstalled, userinitInstalled,
            )
        } else {
            Timber.w("RootAutoStart: НЕ УДАЛОСЬ установить boot-скрипт ни в один путь!")
        }
    }

    /**
     * Генерирует shell-скрипт для автостарта при boot.
     */
    private fun buildBootScript(pkg: String): String {
        // Определяем component name для BootReceiver и Service
        val receiverComponent = "$pkg/.BootReceiver"
        val serviceComponent = "$pkg/.service.SphereAgentService"
        val activityComponent = "$pkg/.ui.SetupActivity"

        return """
            |#!/system/bin/sh
            |# ══════════════════════════════════════════════════════════════
            |# Sphere Platform Agent — автостарт при загрузке ОС
            |# Создан автоматически из RootAutoStart
            |# ══════════════════════════════════════════════════════════════
            |
            |# Ждём завершения загрузки ОС
            |while [ "$(getprop sys.boot_completed)" != "1" ]; do
            |  sleep 1
            |done
            |
            |# Даём системе стабилизироваться
            |sleep 10
            |
            |# Снимаем Stopped State (на случай если обновили APK)
            |cmd package set-stopped-state $pkg false 2>/dev/null
            |
            |# Отправляем BOOT_COMPLETED нашему BootReceiver
            |am broadcast \
            |  -a android.intent.action.BOOT_COMPLETED \
            |  -n $receiverComponent \
            |  --include-stopped-packages 2>/dev/null
            |
            |# Запускаем foreground service напрямую (fallback)
            |am startservice -n $serviceComponent 2>/dev/null
            |
            |# Если сервис не запустился — открываем activity (100% гарантия)
            |sleep 5
            |am start -n $activityComponent --activity-clear-top 2>/dev/null
        """.trimMargin()
    }

    /**
     * Путь A: Установка в /system/etc/init.d/
     * Работает на ROM с busybox init (LDPlayer, многие x86 ROM).
     */
    private fun installToInitD(script: String): Boolean {
        val path = "/system/etc/init.d/99sphere"
        return execRootScript(
            """
            mount -o rw,remount /system 2>/dev/null
            mkdir -p /system/etc/init.d
            cat > $path << 'SPHERE_BOOT_EOF'
            $script
            SPHERE_BOOT_EOF
            chmod 755 $path
            mount -o ro,remount /system 2>/dev/null
            """.trimIndent(),
        )
    }

    /**
     * Путь B: Установка в /data/adb/service.d/ (Magisk)
     * Работает на устройствах с Magisk root.
     */
    private fun installToMagiskServiceD(script: String): Boolean {
        val path = "/data/adb/service.d/sphere_autostart.sh"
        return execRootScript(
            """
            mkdir -p /data/adb/service.d
            cat > $path << 'SPHERE_BOOT_EOF'
            $script
            SPHERE_BOOT_EOF
            chmod 755 $path
            """.trimIndent(),
        )
    }

    /**
     * Путь C: Дописываем в /data/local/userinit.sh (Android-x86)
     * Работает на Android-x86, BlissOS и некоторых эмуляторах.
     */
    private fun installToUserinit(script: String, pkg: String): Boolean {
        // Проверяем, не дописан ли уже наш блок
        val checkResult = execRootWithOutput("grep -c 'sphere_autostart' /data/local/userinit.sh 2>/dev/null")
        if (checkResult.trim() != "0" && checkResult.isNotBlank()) {
            Timber.d("RootAutoStart: userinit.sh уже содержит наш скрипт")
            return true
        }

        return execRootScript(
            """
            touch /data/local/userinit.sh
            chmod 755 /data/local/userinit.sh
            cat >> /data/local/userinit.sh << 'SPHERE_BOOT_EOF'

            # === sphere_autostart ===
            $script
            # === /sphere_autostart ===
            SPHERE_BOOT_EOF
            """.trimIndent(),
        )
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  4. Форсированный BOOT_COMPLETED
    // ═══════════════════════════════════════════════════════════════════════

    /**
     * Отправляет BOOT_COMPLETED broadcast нашему BootReceiver прямо сейчас.
     *
     * Зачем: BootReceiver планирует KeepAliveWorker, ServiceWatchdog и запускает
     * сервис. Если при boot BootReceiver не сработал (Stopped State, LDPlayer quirk) —
     * эта команда гарантирует что он сработает хотя бы при первом ручном запуске.
     */
    private fun triggerBootReceiver(pkg: String) {
        execRoot(
            "am broadcast" +
                " -a android.intent.action.BOOT_COMPLETED" +
                " -n $pkg/.BootReceiver" +
                " --include-stopped-packages",
        )
        Timber.i("RootAutoStart: BOOT_COMPLETED отправлен принудительно")
    }

    // ═══════════════════════════════════════════════════════════════════════
    //  Root execution helpers
    // ═══════════════════════════════════════════════════════════════════════

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
                Timber.d("RootAutoStart: ✓ $command")
            } else {
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                Timber.w("RootAutoStart: ✗ $command → exit=${process.exitValue()} $stderr")
            }
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: ошибка: $command")
        }
    }

    /**
     * Выполняет многострочный скрипт через su (stdin pipe).
     * Используется для здесь-документов (heredoc) и цепочек команд.
     *
     * @return true если скрипт завершился с exit code 0
     */
    private fun execRootScript(script: String): Boolean {
        return try {
            val process = Runtime.getRuntime().exec("su")
            val stdin = DataOutputStream(process.outputStream)
            stdin.writeBytes(script)
            stdin.writeBytes("\nexit\n")
            stdin.flush()
            stdin.close()

            val completed = process.waitFor(15, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут скрипта")
                return false
            }

            val exitCode = process.exitValue()
            if (exitCode == 0) {
                Timber.d("RootAutoStart: ✓ скрипт выполнен (exit=0)")
            } else {
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                Timber.w("RootAutoStart: ✗ скрипт exit=$exitCode $stderr")
            }
            exitCode == 0
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: ошибка выполнения скрипта")
            false
        }
    }

    /**
     * Выполняет команду через su и возвращает stdout.
     */
    private fun execRootWithOutput(command: String): String {
        return try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
            val completed = process.waitFor(5, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                return ""
            }
            process.inputStream.bufferedReader().readText()
        } catch (e: Exception) {
            ""
        }
    }
}
