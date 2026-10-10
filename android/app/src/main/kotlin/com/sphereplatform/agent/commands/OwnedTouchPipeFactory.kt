package com.sphereplatform.agent.commands

import java.io.IOException

/** Claim before draining old input; release only after known helper teardown. */
internal class OwnedTouchPipeFactory(
    private val ownership: DeviceInputOwnership,
    private val prepare: suspend (String) -> Unit,
    private val delegate: TouchPipeFactory,
) : TouchPipeFactory {
    override suspend fun open(binding: TouchBinding): TouchPipe {
        if (!ownership.claimContinuous(binding.owner)) throw IOException("device_input_busy")
        val pipe = try {
            prepare(binding.owner)
            delegate.open(binding)
        } catch (failure: Exception) {
            val unknown = failure is TouchPipeCleanupUnknownException || failure is RootCommandOutcomeUnknownException ||
                failure is kotlinx.coroutines.CancellationException
            ownership.release(binding.owner, !unknown)
            if (unknown) throw TouchPipeCleanupUnknownException()
            throw failure
        }
        return object : TouchPipe {
            private var closed = false
            override suspend fun send(sample: TouchSample): RootTouchWire.Ack = pipe.send(sample)
            override suspend fun closeAndConfirm(): Boolean {
                if (closed) return false
                closed = true
                var confirmed = false
                try {
                    confirmed = pipe.closeAndConfirm()
                    return confirmed
                } finally { ownership.release(binding.owner, confirmed) }
            }
        }
    }
}
