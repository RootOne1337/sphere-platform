package com.sphereplatform.agent.service

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import com.sphereplatform.agent.workers.AutoEnrollmentWorker
import timber.log.Timber

/** Native persisted recovery: does not need WorkManager's boot reschedule receiver.
 * Android controls execution time, including idle/quota/unlock restrictions.
 */
class BootRecoveryJobService : JobService() {
    companion object {
        internal const val FIRST_JOB_ID = 0x5350480
        internal const val SECOND_JOB_ID = FIRST_JOB_ID + 1
        internal const val CHECK_DELAY_MS = 60_000L
        internal const val CHECK_DEADLINE_MS = 90_000L

        /** Keep an existing job's deadline intact during repeated app/service starts. */
        fun schedule(context: Context): Boolean = scheduleNext(context, null)

        internal fun scheduleNext(context: Context, runningId: Int?): Boolean = try {
            val scheduler = context.getSystemService(JobScheduler::class.java)
            val component = ComponentName(context, BootRecoveryJobService::class.java)
            val nextId = if (runningId == FIRST_JOB_ID) SECOND_JOB_ID else FIRST_JOB_ID
            if (scheduler == null) {
                false
            } else {
                val pending = listOf(FIRST_JOB_ID, SECOND_JOB_ID).mapNotNull(scheduler::getPendingJob)
                if (pending.any { it.service != component }) {
                    Timber.e("Boot recovery: job ID conflict; existing job preserved")
                    false
                } else if (pending.any { it.id != runningId && it.isPersisted }) {
                    true
                } else {
                    // Alternating IDs avoid cancelling the currently executing job.
                    // One-shot deadlines give recovery a short window after a reboot,
                    // instead of waiting for WorkManager's 15-minute periodic tick.
                    val job = JobInfo.Builder(nextId, component)
                        .setPersisted(true)
                        .setMinimumLatency(CHECK_DELAY_MS)
                        .setOverrideDeadline(CHECK_DEADLINE_MS)
                        .setBackoffCriteria(30_000L, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                        .build()
                    val accepted = scheduler.schedule(job) == JobScheduler.RESULT_SUCCESS
                    Timber.i("Boot recovery: persisted job scheduled=%s", accepted)
                    accepted
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "Boot recovery: failed to schedule native persisted job")
            false
        }
    }

    override fun onStartJob(params: JobParameters): Boolean {
        Timber.i("Boot recovery: Android started persisted job id=%d", params.jobId)
        // Persist the successor first; enrollment/service errors must not remove recovery.
        val scheduled = scheduleNext(this, params.jobId)
        try {
            if (ServiceWatchdog.isEnrolled(this)) {
                SphereAgentService.start(this)
            } else {
                AutoEnrollmentWorker.schedule(this)
            }
        } catch (e: Exception) {
            Timber.e(e, "Boot recovery: service/enrollment request failed; recovery remains scheduled")
        }
        if (!scheduled) {
            // Retry this job with Android's backoff if no successor could be persisted.
            jobFinished(params, true)
            return true
        }
        return false
    }

    override fun onStopJob(params: JobParameters): Boolean = true
}
