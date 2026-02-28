package com.sphereplatform.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber

/**
 * BootReceiver — запускает SphereAgentService при загрузке устройства.
 * Требует: android.permission.RECEIVE_BOOT_COMPLETED
 *
 * Также планирует [ServiceWatchdog] alarm как дополнительную гарантию
 * непрерывной работы агента (тройная защита: Boot + START_STICKY + AlarmManager).
 *
 * ВАЖНО: На Android 12+ (API 31) запуск Foreground Service из бэкграунд-контекста
 * может бросить ForegroundServiceStartNotAllowedException если система ещё
 * не готова. Поэтому оборачиваем в try-catch — watchdog подхватит позже.
 */
@AndroidEntryPoint
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == "android.intent.action.QUICKBOOT_POWERON"
        ) {
            Timber.i("BootReceiver: устройство загружено — запускаем агент")

            // Запускаем сервис только если enrollment пройден
            if (ServiceWatchdog.isEnrolled(context)) {
                try {
                    SphereAgentService.start(context)
                } catch (e: Exception) {
                    // На Android 12+ может прийти ForegroundServiceStartNotAllowedException
                    // если система ещё в restricted-режиме после загрузки.
                    // Watchdog AlarmManager подхватит запуск через 5 минут.
                    Timber.e(e, "BootReceiver: не удалось запустить сервис при загрузке — watchdog подхватит")
                }
            }

            // Планируем watchdog alarm (идемпотентно)
            ServiceWatchdog.schedule(context)
        }
    }
}
