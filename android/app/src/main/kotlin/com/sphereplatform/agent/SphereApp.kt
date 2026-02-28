package com.sphereplatform.agent

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.logging.FileLoggingTree
import com.sphereplatform.agent.service.ServiceWatchdog
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
        // Schedule background workers (KEEP policy — idempotent)
        LogUploadWorker.schedule(this)
        UpdateCheckWorker.schedule(this)

        // ServiceWatchdog: AlarmManager как доп. гарантия непрерывной работы агента.
        // Тройная защита: BootReceiver + START_STICKY + AlarmManager = 100% uptime.
        if (ServiceWatchdog.isEnrolled(this)) {
            ServiceWatchdog.schedule(this)
        }
    }

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
