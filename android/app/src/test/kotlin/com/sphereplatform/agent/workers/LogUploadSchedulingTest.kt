package com.sphereplatform.agent.workers

import android.app.Application
import androidx.work.Configuration
import androidx.work.NetworkType
import androidx.work.WorkInfo
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import com.sphereplatform.agent.logging.CrashHandler
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class LogUploadSchedulingTest {
    private val context by lazy { RuntimeEnvironment.getApplication() }
    private lateinit var manager: WorkManager

    @Before fun setUp() {
        WorkManagerTestInitHelper.initializeTestWorkManager(
            context,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build(),
        )
        manager = WorkManager.getInstance(context)
        CrashHandler.crashLogFile(context).delete()
    }

    @After fun tearDown() {
        CrashHandler.crashLogFile(context).delete()
        WorkManagerTestInitHelper.closeWorkDatabase()
    }

    @Test fun `no crash record does not create one-time crash upload`() {
        LogUploadWorker.schedule(context)

        assertTrue(
            manager.getWorkInfosForUniqueWork(LogUploadWorker.CRASH_UPLOAD_WORK_NAME)
                .get(5, TimeUnit.SECONDS).isEmpty(),
        )
    }

    @Test fun `pending crash queues one network-constrained upload and coalesces boot bursts`() {
        CrashHandler.crashLogFile(context).writeText("persisted startup crash")

        LogUploadWorker.schedule(context)
        val first = manager.getWorkInfosForUniqueWork(LogUploadWorker.CRASH_UPLOAD_WORK_NAME)
            .get(5, TimeUnit.SECONDS).single()

        LogUploadWorker.schedule(context)
        val afterRepeatedStartup = manager
            .getWorkInfosForUniqueWork(LogUploadWorker.CRASH_UPLOAD_WORK_NAME)
            .get(5, TimeUnit.SECONDS)

        assertEquals(1, afterRepeatedStartup.size)
        assertEquals(first.id, afterRepeatedStartup.single().id)
        assertEquals(WorkInfo.State.ENQUEUED, first.state)
        assertEquals(NetworkType.CONNECTED, first.constraints.requiredNetworkType)
    }
}
