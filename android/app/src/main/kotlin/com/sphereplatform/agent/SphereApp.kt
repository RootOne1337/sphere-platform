package com.sphereplatform.agent

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.root.RootAutoStart
import com.sphereplatform.agent.service.ServiceWatchdog
import com.sphereplatform.agent.workers.KeepAliveWorker
import com.sphereplatform.agent.workers.LogUploadWorker
import com.sphereplatform.agent.workers.UpdateCheckWorker
import dagger.hilt.android.HiltAndroidApp
import timber.log.Timber
import javax.inject.Inject

/**
 * HiltAndroidApp — точка входа DI-графа Hilt.
 * Также реализует Configuration.Provider для WorkManager с Hilt-интеграцией.
 */
@HiltAndroidApp
class SphereApp : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    @Inject
    lateinit var fileLoggingTree: FileLoggingTree

    override fun onCreate() {
        super.onCreate()
        // Always plant file tree first so logs are never lost
        Timber.plant(fileLoggingTree)
        if (BuildConfig.DEBUG) {
            Timber.plant(Timber.DebugTree())
        }

        // ── ROOT: снятие ВСЕХ системных ограничений на рутованных устройствах ─────
        // На LDPlayer / Android 9 с root: снимает Stopped State, whitelist battery,
        // разрешает фоновую работу, включает BootReceiver. Идемпотентно.
        // Без root — тихо пропускается.
        Thread { RootAutoStart.configure(this) }.start()

        // Schedule background workers (KEEP policy — idempotent)
        LogUploadWorker.schedule(this)
        UpdateCheckWorker.schedule(this)

        // ── КРИТИЧНО: KeepAliveWorker планируется БЕЗУСЛОВНО ───────────────────
        // WorkManager PeriodicWork (15 мин) хранится в SQLite и использует системный
        // JobScheduler с setPersisted(true). Это ЕДИНСТВЕННЫЙ механизм Android,
        // который переживает reboot И не зависит от Stopped State.
        // После первого запуска APK — агент гарантированно стартует при каждом boot.
        // Пятислойная защита: BootReceiver + AlarmManager + KeepAliveWorker + START_STICKY + AutoEnrollment
        KeepAliveWorker.schedule(this)

        if (ServiceWatchdog.isEnrolled(this)) {
            ServiceWatchdog.schedule(this)
        } else {
            // Немедленная попытка enrollment (OneTime) — не ждём 15 мин тика KeepAliveWorker.
            com.sphereplatform.agent.workers.AutoEnrollmentWorker.schedule(this)
        }
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
