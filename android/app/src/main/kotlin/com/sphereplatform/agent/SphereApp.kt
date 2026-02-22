package com.sphereplatform.agent

import android.app.Application
import androidx.hilt.work.HiltWorkerFactory
import androidx.work.Configuration
import dagger.hilt.android.HiltAndroidApp
import javax.inject.Inject

/**
 * HiltAndroidApp — точка входа DI-графа Hilt.
 * Также реализует Configuration.Provider для WorkManager с Hilt-интеграцией.
 */
@HiltAndroidApp
class SphereApp : Application(), Configuration.Provider {

    @Inject
    lateinit var workerFactory: HiltWorkerFactory

    override val workManagerConfiguration: Configuration
        get() = Configuration.Builder()
            .setWorkerFactory(workerFactory)
            .build()
}
