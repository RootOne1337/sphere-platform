package com.sphereplatform.agent.commands

import android.os.Process
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.ExecutorCoroutineDispatcher
import kotlinx.coroutines.Job
import kotlinx.coroutines.asCoroutineDispatcher
import java.util.concurrent.Executors

/** One lifecycle-owned input thread, independent of encoder/file/network IO pools.
 * Display priority is a scheduling hint, not realtime scheduling or input authority.
 */
internal fun inputDispatcher(
    scope: CoroutineScope,
    configureThread: () -> Unit = { Process.setThreadPriority(Process.THREAD_PRIORITY_DISPLAY) },
): ExecutorCoroutineDispatcher {
    val lifecycle = requireNotNull(scope.coroutineContext[Job]) { "input_dispatcher_requires_lifecycle" }
    val executor = Executors.newSingleThreadExecutor { work ->
        Thread({
            try { configureThread() }
            catch (_: SecurityException) { timber.log.Timber.w("Input thread priority unavailable") }
            work.run()
        }, "sphere-native-input").apply { isDaemon = true }
    }
    val dispatcher = executor.asCoroutineDispatcher()
    lifecycle.invokeOnCompletion { dispatcher.close() }
    return dispatcher
}
