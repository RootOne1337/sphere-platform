package com.sphereplatform.agent.logging

import android.content.Context
import java.io.File
import java.io.PrintWriter
import java.io.StringWriter
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * CrashHandler — записывает стектрейс необработанных исключений в файл
 * до завершения процесса.
 *
 * Устанавливается в [com.sphereplatform.agent.SphereApp.attachBaseContext]
 * (до инициализации Hilt), чтобы ловить краши при создании DI-графа.
 *
 * Файл: `/data/data/<pkg>/files/sphere_crash.log` — доступен через
 * `ldconsole pull` или `adb pull`.
 */
object CrashHandler {

    private const val CRASH_LOG_FILE = "sphere_crash.log"
    /** Максимальный размер файла крашей — обрезаем начало при переполнении. */
    private const val MAX_FILE_SIZE = 256 * 1024L // 256 KB

    /**
     * Устанавливает Thread.UncaughtExceptionHandler.
     * Сохраняет оригинальный handler и вызывает его ПОСЛЕ записи в файл,
     * чтобы системный диалог "приложение остановлено" сработал как обычно.
     */
    fun install(context: Context) {
        val appContext = context.applicationContext ?: context
        val defaultHandler = Thread.getDefaultUncaughtExceptionHandler()

        Thread.setDefaultUncaughtExceptionHandler { thread, throwable ->
            writeCrashLog(appContext, thread, throwable)
            // Вызываем стандартный handler (системный диалог + убийство процесса)
            defaultHandler?.uncaughtException(thread, throwable)
        }
    }

    /**
     * Записывает стектрейс в файл. Метод намеренно примитивен —
     * никаких зависимостей от DI, Timber, корутин. Только java.io.
     */
    private fun writeCrashLog(context: Context, thread: Thread, throwable: Throwable) {
        try {
            val crashFile = File(context.filesDir, CRASH_LOG_FILE)

            // Формируем запись
            val timestamp = SimpleDateFormat(
                "yyyy-MM-dd'T'HH:mm:ss.SSS",
                Locale.US,
            ).format(Date())
            val sw = StringWriter()
            throwable.printStackTrace(PrintWriter(sw))

            val entry = buildString {
                append("=== CRASH $timestamp thread=${thread.name} ===\n")
                append(sw.toString())
                append("\n\n")
            }

            // Обрезаем файл если превышает лимит
            if (crashFile.exists() && crashFile.length() > MAX_FILE_SIZE) {
                val tail = crashFile.readText().takeLast(MAX_FILE_SIZE.toInt() / 2)
                crashFile.writeText(tail)
            }

            crashFile.appendText(entry)
        } catch (_: Exception) {
            // Если даже запись крашлога не удалась — ничего не делаем,
            // нельзя бросать исключение из UncaughtExceptionHandler.
        }
    }
}
