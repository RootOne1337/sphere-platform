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
                SphereAgentService.start(context)
            }

            // Планируем watchdog alarm (идемпотентно)
            ServiceWatchdog.schedule(context)
        }
    }
}
