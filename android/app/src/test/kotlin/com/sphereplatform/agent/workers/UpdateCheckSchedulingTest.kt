package com.sphereplatform.agent.workers

import androidx.work.Configuration
import androidx.work.NetworkType
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class UpdateCheckSchedulingTest {
    @Test fun `startup and reconnect checks coalesce and wait for network`() {
        val context = RuntimeEnvironment.getApplication()
        WorkManagerTestInitHelper.initializeTestWorkManager(
            context,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build(),
        )
        try {
            val manager = WorkManager.getInstance(context)
            UpdateCheckWorker.scheduleImmediate(context)
            val first = manager.getWorkInfosForUniqueWork(UpdateCheckWorker.IMMEDIATE_WORK_NAME)
                .get(5, TimeUnit.SECONDS).single()

            UpdateCheckWorker.scheduleImmediate(context)
            val afterReconnectBurst = manager
                .getWorkInfosForUniqueWork(UpdateCheckWorker.IMMEDIATE_WORK_NAME)
                .get(5, TimeUnit.SECONDS)

            assertEquals(1, afterReconnectBurst.size)
            assertEquals(first.id, afterReconnectBurst.single().id)
            assertEquals(WorkInfo.State.ENQUEUED, afterReconnectBurst.single().state)
            assertEquals(NetworkType.CONNECTED, afterReconnectBurst.single().constraints.requiredNetworkType)

            UpdateCheckWorker.schedule(context)
            val periodic = manager.getWorkInfosForUniqueWork("sphere_update_check")
                .get(5, TimeUnit.SECONDS).single()
            assertTrue(periodic.periodicityInfo != null)
            assertEquals(NetworkType.CONNECTED, periodic.constraints.requiredNetworkType)
        } finally {
            WorkManagerTestInitHelper.closeWorkDatabase()
        }
    }
}
