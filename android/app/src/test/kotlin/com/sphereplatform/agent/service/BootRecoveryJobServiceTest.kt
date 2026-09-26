package com.sphereplatform.agent.service

import android.app.Application
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.content.ComponentName
import android.content.Context
import com.sphereplatform.agent.workers.AutoEnrollmentWorker
import io.mockk.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.Robolectric
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class BootRecoveryJobServiceTest {
    private lateinit var context: Context
    private lateinit var scheduler: JobScheduler

    @Before fun setup() {
        context = RuntimeEnvironment.getApplication()
        scheduler = context.getSystemService(JobScheduler::class.java)
        scheduler.cancelAll()
        mockkObject(ServiceWatchdog.Companion, SphereAgentService.Companion, AutoEnrollmentWorker.Companion)
        every { ServiceWatchdog.isEnrolled(any()) } returns true
        every { SphereAgentService.start(any()) } just Runs
        every { AutoEnrollmentWorker.schedule(any()) } just Runs
    }

    @After fun cleanup() {
        scheduler.cancelAll()
        unmockkObject(ServiceWatchdog.Companion, SphereAgentService.Companion, AutoEnrollmentWorker.Companion)
    }

    @Test fun `bootstrap job actually persists with no network or charging dependency`() {
        assertTrue(BootRecoveryJobService.schedule(context))
        val job = scheduler.allPendingJobs.single()
        assertTrue(job.isPersisted)
        assertFalse(job.isPeriodic)
        assertEquals(60_000L, job.minLatencyMillis)
        assertEquals(90_000L, job.maxExecutionDelayMillis)
        assertEquals(JobInfo.NETWORK_TYPE_NONE, job.networkType)
        assertFalse(job.isRequireCharging)
        assertFalse(job.isRequireDeviceIdle)
        assertEquals(ComponentName(context, BootRecoveryJobService::class.java), job.service)
    }

    @Test fun `repeat setup preserves existing deadline and never accumulates jobs`() {
        BootRecoveryJobService.schedule(context)
        val original = scheduler.allPendingJobs.single()
        repeat(10) { assertTrue(BootRecoveryJobService.schedule(context)) }
        assertEquals(listOf(original), scheduler.allPendingJobs)
    }

    private fun runJob(id: Int): Boolean {
        val service = Robolectric.buildService(BootRecoveryJobService::class.java).create().get()
        val params = mockk<JobParameters> { every { jobId } returns id }
        return service.onStartJob(params)
    }

    @Test fun `successor uses another ID while current job is still executing`() {
        BootRecoveryJobService.schedule(context)
        assertFalse(runJob(BootRecoveryJobService.FIRST_JOB_ID))
        assertEquals(setOf(BootRecoveryJobService.FIRST_JOB_ID, BootRecoveryJobService.SECOND_JOB_ID), scheduler.allPendingJobs.map { it.id }.toSet())
        verify(exactly = 1) { SphereAgentService.start(any()) }
        scheduler.cancel(BootRecoveryJobService.FIRST_JOB_ID) // Android completes the current job.
        assertFalse(runJob(BootRecoveryJobService.SECOND_JOB_ID))
        scheduler.cancel(BootRecoveryJobService.SECOND_JOB_ID)
        assertTrue(scheduler.allPendingJobs.single().isPersisted)
    }

    @Test fun `failed service activation still leaves persisted recovery`() {
        every { SphereAgentService.start(any()) } throws IllegalStateException("FGS temporarily denied")
        assertFalse(runJob(BootRecoveryJobService.FIRST_JOB_ID))
        assertTrue(scheduler.allPendingJobs.single().isPersisted)
    }

    @Test fun `unregistered device schedules enrollment without opening activity`() {
        every { ServiceWatchdog.isEnrolled(any()) } returns false
        assertFalse(runJob(BootRecoveryJobService.FIRST_JOB_ID))
        verify(exactly = 1) { AutoEnrollmentWorker.schedule(any()) }
        verify(exactly = 0) { SphereAgentService.start(any()) }
    }

    @Test fun `failed enrollment scheduling cannot remove successor`() {
        every { ServiceWatchdog.isEnrolled(any()) } returns false
        every { AutoEnrollmentWorker.schedule(any()) } throws IllegalStateException("WorkManager unavailable")
        assertFalse(runJob(BootRecoveryJobService.FIRST_JOB_ID))
        assertTrue(scheduler.allPendingJobs.single().isPersisted)
    }

    @Test fun `scheduling exception is reported without crashing application startup`() {
        val unavailable = mockk<Context> { every { getSystemService(JobScheduler::class.java) } throws IllegalStateException("unavailable") }
        assertFalse(BootRecoveryJobService.schedule(unavailable))
    }

    @Test fun `foreign job in reserved slot is preserved`() {
        val foreign = JobInfo.Builder(BootRecoveryJobService.FIRST_JOB_ID, ComponentName(context.packageName, "other.JobService"))
            .setMinimumLatency(10_000L).build()
        scheduler.schedule(foreign)
        assertFalse(BootRecoveryJobService.schedule(context))
        assertEquals(listOf(foreign), scheduler.allPendingJobs)
    }

    @Test fun `scheduler refusal is not reported as persisted success`() {
        val refused = mockk<JobScheduler> {
            every { getPendingJob(any()) } returns null
            every { schedule(any()) } returns JobScheduler.RESULT_FAILURE
        }
        val testContext = mockk<Context> {
            every { getSystemService(JobScheduler::class.java) } returns refused
            every { packageName } returns context.packageName
        }
        assertFalse(BootRecoveryJobService.schedule(testContext))
    }

    @Test fun `no persisted successor requests OS retry without suppressing service startup`() {
        mockkObject(BootRecoveryJobService.Companion)
        try {
            every { BootRecoveryJobService.scheduleNext(any(), any()) } returns false
            val service = spyk(Robolectric.buildService(BootRecoveryJobService::class.java).create().get())
            val params = mockk<JobParameters> { every { jobId } returns BootRecoveryJobService.FIRST_JOB_ID }
            every { service.jobFinished(params, true) } just Runs
            assertTrue(service.onStartJob(params))
            verify(exactly = 1) { service.jobFinished(params, true) }
            verify(exactly = 1) { SphereAgentService.start(service) }
            assertTrue(service.onStopJob(params))
        } finally {
            unmockkObject(BootRecoveryJobService.Companion)
        }
    }
}
