package com.sphereplatform.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import timber.log.Timber

/**
 * BootReceiver — запускает SphereAgentService при загрузке устройства.
 * Требует: android.permission.RECEIVE_BOOT_COMPLETED
 *
 * Также планирует [ServiceWatchdog] alarm как дополнительную гарантию
 * непрерывной работы агента (тройная защита: Boot + START_STICKY + AlarmManager).
 *
 * ВАЖНО: Не использует Hilt (@AndroidEntryPoint) — нет @Inject полей.
 * Все вызовы через статику — минимальная нагрузка на critical boot path.
 *
 * На Android 12+ (API 31) запуск Foreground Service из бэкграунд-контекста
 * может бросить ForegroundServiceStartNotAllowedException если система ещё
 * не готова. Поэтому оборачиваем в try-catch — watchdog подхватит позже.
 */
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action
        if (action == Intent.ACTION_BOOT_COMPLETED ||
            action == "android.intent.action.QUICKBOOT_POWERON" ||
            action == Intent.ACTION_USER_PRESENT ||
            action == Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            Timber.i("BootReceiver: триггер ($action) — запускаем агент")

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
            } else {
                // Если мы ещё не прошли enrollment, возможно есть конфиг для Zero-Touch 
                // регистрации на /sdcard или HTTP Endpoint. Пытаемся сделать это в фоне.
                Timber.i("BootReceiver: устройство не зарегистрировано. Запускаем фоновый AutoEnrollmentWorker...")
                com.sphereplatform.agent.workers.AutoEnrollmentWorker.schedule(context)
            }

            // Планируем watchdog alarm (идемпотентно)
            ServiceWatchdog.schedule(context)
        }
    }
}
