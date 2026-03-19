package com.sphereplatform.agent.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import com.sphereplatform.agent.workers.KeepAliveWorker
import timber.log.Timber

/**
 * ServiceWatchdog — гарантирует что [SphereAgentService] ВСЕГДА запущен после enrollment.
 *
 * Механизм:
 *   - [AlarmManager.setInexactRepeating] каждые 5 минут (ELAPSED_REALTIME_WAKEUP)
 *   - При каждом тике проверяет флаг enrolled в SharedPreferences
 *   - Если enrolled=true → вызывает [SphereAgentService.start]
 *
 * Зачем это нужно (помимо START_STICKY + BootReceiver):
 *   - START_STICKY не гарантирует перезапуск при aggressive battery optimization
 *   - Некоторые OEM (Xiaomi, Huawei, Samsung) убивают foreground service агрессивнее
 *   - AlarmManager работает даже после force-stop на большинстве прошивок
 *   - Двойная/тройная защита: BootReceiver + START_STICKY + AlarmManager = 100% uptime
 *
 * ВАЖНО: Вызов startForegroundService обёрнут в try-catch чтобы не допустить
 * ForegroundServiceStartNotAllowedException на Android 12+ (API 31).
 * Если система не даёт запустить — пропускаем, следующий тик через 5 мин подхватит.
 *
 * Не использует Hilt — работает через простые SharedPreferences для минимальных зависимостей.
 */
class ServiceWatchdog : BroadcastReceiver() {

    companion object {
        /** Интервал проверки (5 минут) */
        private const val WATCHDOG_INTERVAL_MS = 5 * 60 * 1000L

        /** Action для PendingIntent */
        private const val ACTION_WATCHDOG = "com.sphereplatform.agent.WATCHDOG_TICK"

        /** SharedPreferences файл для флага enrollment */
        private const val PREFS_NAME = "sphere_watchdog"

        /** Ключ флага: устройство прошло enrollment */
        private const val KEY_ENROLLED = "enrolled"

        /**
         * Планирует периодический alarm для мониторинга сервиса.
         * Идемпотентно — повторные вызовы обновляют существующий alarm.
         *
         * Вызывается из:
         *   - [SphereAgentService.onCreate]
         *   - [com.sphereplatform.agent.BootReceiver.onReceive]
         *   - [com.sphereplatform.agent.SphereApp.onCreate]
         */
        fun schedule(context: Context) {
            val alarmManager = context.getSystemService(AlarmManager::class.java) ?: return
            val pendingIntent = buildPendingIntent(context)

            alarmManager.setInexactRepeating(
                AlarmManager.ELAPSED_REALTIME_WAKEUP,
                SystemClock.elapsedRealtime() + WATCHDOG_INTERVAL_MS,
                WATCHDOG_INTERVAL_MS,
                pendingIntent,
            )
            Timber.i("ServiceWatchdog: alarm запланирован (каждые ${WATCHDOG_INTERVAL_MS / 60_000} мин)")
        }

        /** Отменяет watchdog alarm (для тестов или полного отключения агента). */
        fun cancel(context: Context) {
            val alarmManager = context.getSystemService(AlarmManager::class.java) ?: return
            alarmManager.cancel(buildPendingIntent(context))
            Timber.i("ServiceWatchdog: alarm отменён")
        }

        /**
         * Устанавливает флаг enrolled=true.
         *
         * Сохраняет в ДВА хранилища:
         * - Device Protected (DE): доступно до разблокировки экрана — для LOCKED_BOOT_COMPLETED
         * - Credential Encrypted (CE): стандартное хранилище — для BOOT_COMPLETED и всех других случаев
         *
         * Вызывать после успешного enrollment в SetupActivity.
         */
        fun markEnrolled(context: Context) {
            // Device Protected Storage (доступен в Direct Boot mode)
            deviceProtectedPrefs(context).edit().putBoolean(KEY_ENROLLED, true).apply()
            // Credential Encrypted Storage (стандартное, fallback и обратная совместимость)
            runCatching {
                context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    .edit().putBoolean(KEY_ENROLLED, true).apply()
            }
        }

        /**
         * Проверяет, прошло ли устройство enrollment.
         *
         * Сначала проверяет Device Protected Storage (работает в Direct Boot),
         * затем Credential Encrypted (если CE доступно) как фоллбэк.
         * Обратная совместимость: устройства сгенерированные до этого фикса читаются через CE,
         * новые enrollment хранятся в обоих хранилищах.
         */
        fun isEnrolled(context: Context): Boolean {
            // DE-хранилище — проверяем первым (работает в Direct Boot mode)
            if (deviceProtectedPrefs(context).getBoolean(KEY_ENROLLED, false)) return true
            // CE-хранилище — fallback (недоступно в Direct Boot, но обратная совместимость)
            return runCatching {
                context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                    .getBoolean(KEY_ENROLLED, false)
            }.getOrDefault(false)
        }

        /**
         * Возвращает SharedPreferences в Device Protected Storage.
         * API 24+ (всегда выполняется, т.к. minSdk=26).
         */
        private fun deviceProtectedPrefs(context: Context) =
            context.createDeviceProtectedStorageContext()
                .getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

        private fun buildPendingIntent(context: Context): PendingIntent {
            val intent = Intent(context, ServiceWatchdog::class.java).apply {
                action = ACTION_WATCHDOG
            }
            return PendingIntent.getBroadcast(
                context,
                0,
                intent,
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
        }
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != ACTION_WATCHDOG) return

        if (!isEnrolled(context)) {
            // Enrollment не пройден — планируем KeepAliveWorker как fallback.
            // KeepAliveWorker (PeriodicWork через JobScheduler) сам попробует enrollment.
            Timber.d("ServiceWatchdog: tick — enrollment не пройден, делегируем KeepAliveWorker")
            KeepAliveWorker.schedule(context)
            return
        }

        Timber.d("ServiceWatchdog: tick — гарантируем работу SphereAgentService")
        try {
            SphereAgentService.start(context)
        } catch (e: Exception) {
            // На Android 12+ (API 31) startForegroundService из бэкграунда запрещён
            // без исключений оптимизации батареи → ForegroundServiceStartNotAllowedException.
            // Не фатально — KeepAliveWorker повторит через ≤15 мин.
            Timber.e(e, "ServiceWatchdog: не удалось запустить сервис — KeepAliveWorker подхватит")
        }
    }
}
