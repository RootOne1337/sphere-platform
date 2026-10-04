package com.sphereplatform.agent.workers

import androidx.work.Configuration
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class EnrollmentSchedulingTest {
    @Test fun `app and package replaced scheduling preserve the pending attempt`() {
        val context = RuntimeEnvironment.getApplication()
        WorkManagerTestInitHelper.initializeTestWorkManager(context,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build())
        try {
            val manager = WorkManager.getInstance(context)
            AutoEnrollmentWorker.schedule(context)
            val first = manager.getWorkInfosForUniqueWork(AutoEnrollmentWorker.WORK_NAME).get(5, TimeUnit.SECONDS).single()
            assertEquals(WorkInfo.State.ENQUEUED, first.state) // Network constraint remains unmet.
            AutoEnrollmentWorker.schedule(context)
            val after = manager.getWorkInfosForUniqueWork(AutoEnrollmentWorker.WORK_NAME).get(5, TimeUnit.SECONDS)
            assertEquals(1, after.size)
            assertEquals(first.id, after.single().id)
            assertEquals(WorkInfo.State.ENQUEUED, after.single().state)
        } finally { WorkManagerTestInitHelper.closeWorkDatabase() }
    }
}
