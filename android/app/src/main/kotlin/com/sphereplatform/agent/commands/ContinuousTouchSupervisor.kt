package com.sphereplatform.agent.commands

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.isActive
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.atomic.AtomicReference

/** No wire route/capability is exposed until server-issued ownership and capture epochs are connected. */
internal class ContinuousTouchSupervisor(
    private val scope: CoroutineScope,
    private val factory: TouchPipeFactory,
    private val uptime: () -> Long,
    private val isCurrent: (TouchBinding) -> Boolean,
    private val onReceipt: (TouchBinding, Receipt) -> Unit,
) {
    enum class Stage { STARTUP, INPUT, RELEASE }
    data class Receipt(val sequence: Int, val status: Int, val deviceUptimeMs: Long, val stage: Stage)
    private data class Owner(val mailbox: ContinuousTouchMailbox, val job: Job)
    private val lifecycle = Mutex()
    private var current: Owner? = null
    private val admitted = AtomicReference<ContinuousTouchMailbox?>()
    @Volatile private var resetRequired = false

    /** No implicit takeover: an active owner must be explicitly closed before another open. */
    suspend fun open(binding: TouchBinding): Boolean = lifecycle.withLock {
        if (current?.job?.isActive == true) return@withLock false
        retireCurrent()
        if (resetRequired || !scope.isActive || !isCurrent(binding)) return@withLock false
        val mailbox = ContinuousTouchMailbox(binding, uptime())
        admitted.set(mailbox)
        val job = scope.launch(Dispatchers.IO) {
            var pipe: TouchPipe? = null
            var attemptedSequence = 0
            try {
                if (!isCurrent(binding) || mailbox.isRetired()) return@launch
                pipe = factory.open(binding)
                if (synchronized(mailbox) { mailbox.expired(uptime()) } || !isCurrent(binding)) return@launch
                emit(binding, Receipt(0, 0, uptime(), Stage.STARTUP))
                while (!synchronized(mailbox) { mailbox.expired(uptime()) } && isCurrent(binding)) {
                    val sample = synchronized(mailbox) { mailbox.poll(uptime()) }
                    if (sample == null) { delay(10); continue }
                    // Recheck ownership/epoch after dequeuing, before any privileged delivery.
                    if (mailbox.isRetired() || !isCurrent(binding)) break
                    attemptedSequence = sample.sequence
                    val ack = pipe.send(sample)
                    emit(binding, Receipt(ack.sequence, ack.status, ack.uptimeMs, Stage.INPUT))
                    if (ack.status !in setOf(1, 2, 3)) break
                }
            } catch (failure: Exception) {
                // Input may have been consumed. No replay and no exception/private data in receipts.
                emit(binding, Receipt(attemptedSequence, 6, uptime(), if (attemptedSequence == 0) Stage.STARTUP else Stage.INPUT))
                if (failure is TouchPipeCleanupUnknownException) resetRequired = true
            } finally {
                mailbox.retire()
                admitted.compareAndSet(mailbox, null)
                withContext(NonCancellable + Dispatchers.IO) {
                    val confirmed = (pipe?.let { runCatching { it.closeAndConfirm() }.getOrDefault(false) } ?: true) && !resetRequired
                    if (!confirmed) resetRequired = true
                    emit(binding, Receipt(0, if (confirmed) 3 else 6, uptime(), Stage.RELEASE))
                }
            }
        }
        job.invokeOnCompletion {
            mailbox.retire()
            admitted.compareAndSet(mailbox, null)
        }
        current = Owner(mailbox, job)
        true // Starting, not ready or successful Android execution. Only receipt0/0 means ready.
    }

    fun offer(owner: String, epoch: String, sequence: Int, gesture: Long, action: Int, x: Int, y: Int): ContinuousTouchMailbox.Admission {
        val mailbox = admitted.get() ?: return ContinuousTouchMailbox.Admission.RETIRED
        return synchronized(mailbox) {
            mailbox.offer(owner, epoch, TouchSample(sequence, gesture, action, x, y, uptime()))
        }
    }

    suspend fun close() = lifecycle.withLock { retireCurrent() }

    /** Immediate fencing, usable from disconnect/stop callbacks before asynchronous cleanup. */
    fun invalidate() { admitted.getAndSet(null)?.retire() }
    fun needsReset(): Boolean = resetRequired

    private suspend fun retireCurrent() {
        val previous = current ?: return
        previous.mailbox.retire()
        admitted.compareAndSet(previous.mailbox, null)
        // Do not cancel while root input may be executing. Retire, then wait for its bounded pipe deadline.
        previous.job.join()
        current = null
    }

    private fun emit(binding: TouchBinding, receipt: Receipt) {
        // A failed outbound transport must not terminate local cleanup or create recursive error sends.
        runCatching { onReceipt(binding, receipt) }
    }
}

internal fun interface TouchPipeFactory { suspend fun open(binding: TouchBinding): TouchPipe }
internal interface TouchPipe {
    suspend fun send(sample: TouchSample): RootTouchWire.Ack
    /** True only after EOF cancellation and normal owned helper termination were confirmed. */
    suspend fun closeAndConfirm(): Boolean
}
