package com.sphereplatform.agent.root

import android.content.Context
import timber.log.Timber
import java.io.BufferedReader
import java.io.InputStreamReader
import java.util.concurrent.TimeUnit

/**
 * RootAutoStart — утилита для гарантированного автостарта на рутованных устройствах/эмуляторах.
 *
 * **Зачем это нужно:**
 * На LDPlayer и других рутованных Android-эмуляторах (Android 9 / API 28)
 * стандартные механизмы (BOOT_COMPLETED, WorkManager, AlarmManager) могут не сработать из-за:
 * - Stopped State после первой установки APK
 * - Battery Optimization убивает приложение
 * - OEM-специфичные ограничения фоновой работы
 *
 * RootAutoStart использует **root-права (su)** для снятия ВСЕХ этих ограничений
 * на уровне системы, гарантируя 100% автостарт после reboot.
 *
 * **Вызывается:**
 * - Из [com.sphereplatform.agent.SphereApp.onCreate] — при каждом создании процесса
 * - Идемпотентно: повторные вызовы безопасны
 *
 * **Что делает (только при наличии root):**
 * 1. Снимает Stopped State → BOOT_COMPLETED гарантированно доставляется
 * 2. Whitelist от Doze battery optimization → приложение не убивается системой
 * 3. Разрешает фоновую работу → AlarmManager, JobScheduler, WorkManager не блокируются
 * 4. Включает BootReceiver → гарантирует что компонент активен в PackageManager
 */
object RootAutoStart {

    /** Флаг: root уже проверен в текущем процессе (не проверяем при каждом вызове). */
    @Volatile
    private var rootChecked = false

    @Volatile
    private var rootAvailable = false

    /**
     * Выполняет все root-настройки для гарантированного автостарта.
     *
     * Запускается в фоновом потоке из [com.sphereplatform.agent.SphereApp.onCreate].
     * Если root недоступен — тихо возвращается без ошибок.
     *
     * @param context Application context
     */
    fun configure(context: Context) {
        if (!hasRoot()) {
            Timber.d("RootAutoStart: root недоступен — пропускаем")
            return
        }

        val pkg = context.packageName
        Timber.i("RootAutoStart: настройка автостарта для $pkg (root)")

        // 1. Снять Stopped State — после этого BOOT_COMPLETED ВСЕГДА доставляется.
        //    Без этого на Android 3.1+ свежеустановленное приложение не получает
        //    implicit broadcasts (BOOT_COMPLETED, CONNECTIVITY_CHANGE и др.).
        //    Обычно Stopped State снимается при первом ручном запуске Activity,
        //    но через root мы гарантируем это явно.
        execRoot("cmd package set-stopped-state $pkg false")

        // 2. Whitelist от Doze battery optimization.
        //    Без этого система может убить процесс при aggressive battery optimization
        //    (особенно на OEM-прошивках: Xiaomi, Huawei, Samsung).
        execRoot("dumpsys deviceidle whitelist +$pkg")

        // 3. Разрешить фоновую работу.
        //    Некоторые OEM и эмулятор-модификации блокируют RUN_IN_BACKGROUND.
        execRoot("cmd appops set $pkg RUN_IN_BACKGROUND allow")
        execRoot("cmd appops set $pkg RUN_ANY_IN_BACKGROUND allow")

        // 4. Гарантировать что BootReceiver включён в PackageManager.
        //    На некоторых прошивках компоненты могут быть disabled по умолчанию.
        execRoot("pm enable $pkg/.BootReceiver")

        Timber.i("RootAutoStart: все настройки применены для $pkg")
    }

    /**
     * Проверяет наличие root-доступа (su).
     * Кэширует результат — проверка выполняется один раз за жизнь процесса.
     */
    fun hasRoot(): Boolean {
        if (rootChecked) return rootAvailable
        rootAvailable = try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", "id"))
            val exitCode = process.waitFor()
            if (exitCode == 0) {
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
     * Выполняет команду через su.
     * Тихо глотает ошибки — каждая настройка опциональна.
     */
    private fun execRoot(command: String) {
        try {
            val process = Runtime.getRuntime().exec(arrayOf("su", "-c", command))
            val completed = process.waitFor(5, TimeUnit.SECONDS)
            if (!completed) {
                process.destroyForcibly()
                Timber.w("RootAutoStart: таймаут команды: $command")
                return
            }
            if (process.exitValue() == 0) {
                Timber.d("RootAutoStart: ✓ $command")
            } else {
                val stderr = BufferedReader(InputStreamReader(process.errorStream)).readText().trim()
                Timber.w("RootAutoStart: ✗ $command → exit=${process.exitValue()} $stderr")
            }
        } catch (e: Exception) {
            Timber.w(e, "RootAutoStart: ошибка выполнения: $command")
        }
    }
}
