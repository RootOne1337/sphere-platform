package com.sphereplatform.agent.service

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
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
         * Вызывать после успешного enrollment в SetupActivity.
         */
        fun markEnrolled(context: Context) {
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .edit()
                .putBoolean(KEY_ENROLLED, true)
                .apply()
        }

        /** Проверяет, прошло ли устройство enrollment. */
        fun isEnrolled(context: Context): Boolean =
            context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
                .getBoolean(KEY_ENROLLED, false)

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

        // Не запускаем сервис если устройство ещё не прошло enrollment
        if (!isEnrolled(context)) {
            Timber.d("ServiceWatchdog: tick — enrollment не пройден, пропускаем")
            return
        }

        Timber.d("ServiceWatchdog: tick — гарантируем работу SphereAgentService")
        SphereAgentService.start(context)
    }
}
