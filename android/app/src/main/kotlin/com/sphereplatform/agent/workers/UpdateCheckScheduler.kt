package com.sphereplatform.agent.workers

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/** Keeps lifecycle owners independent from WorkManager's static API. */
@Singleton
class UpdateCheckScheduler @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    fun scheduleImmediate() = UpdateCheckWorker.scheduleImmediate(context)
}
