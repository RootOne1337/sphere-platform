package com.sphereplatform.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.Build
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.service.SphereAgentService
import com.sphereplatform.agent.workers.KeepAliveWorker
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
            action == Intent.ACTION_LOCKED_BOOT_COMPLETED ||
            action == Intent.ACTION_USER_PRESENT ||
            action == Intent.ACTION_MY_PACKAGE_REPLACED
        ) {
            Timber.i("BootReceiver: триггер ($action) — запускаем агент")

            // ── ВСЕГДА планируем KeepAliveWorker (главная гарантия автостарта) ────
            // PeriodicWork через JobScheduler переживает reboot и не зависит от
            // Stopped State. Даже если все остальные механизмы откажут —
            // KeepAliveWorker подхватит через ≤15 мин.
            KeepAliveWorker.schedule(context)

            // ── Планируем AlarmManager watchdog (дополнительный слой, 5 мин) ────
            ServiceWatchdog.schedule(context)

            // ── Запуск сервиса / enrollment ────────────────────────────────────
            if (ServiceWatchdog.isEnrolled(context)) {
                try {
                    SphereAgentService.start(context)
                } catch (e: Exception) {
                    // Android 12+ (API 31): ForegroundServiceStartNotAllowedException
                    // Не фатально — KeepAliveWorker и ServiceWatchdog подхватят.
                    Timber.e(e, "BootReceiver: не удалось запустить сервис — KeepAliveWorker подхватит")
                }
            } else if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) {
                // ── Android 9-11 (API 28-30): безусловный старт сервиса ────────────
                // На API < 31 нет FGS-ограничений → startForegroundService() из
                // BroadcastReceiver работает всегда. Запускаем сервис ДАЖЕ если
                // enrollment не пройден — сервис сам обнаружит отсутствие токена
                // и не подключится к WS, но процесс будет жив.
                // KeepAliveWorker выполнит enrollment при появлении конфига/сети.
                try {
                    SphereAgentService.start(context)
                    Timber.i("BootReceiver: сервис запущен безусловно (API ${Build.VERSION.SDK_INT} < 31)")
                } catch (e: Exception) {
                    Timber.e(e, "BootReceiver: не удалось запустить сервис")
                }
                // Параллельно запускаем enrollment
                com.sphereplatform.agent.workers.AutoEnrollmentWorker.schedule(context)
            } else {
                // Android 12+ (API 31): нельзя стартовать FGS из бэкграунда без enrolled.
                // Немедленная попытка Zero-Touch enrollment (не ждём 15 мин тик).
                Timber.i("BootReceiver: устройство не зарегистрировано → AutoEnrollmentWorker + KeepAliveWorker")
                com.sphereplatform.agent.workers.AutoEnrollmentWorker.schedule(context)
            }
        }
    }
}
