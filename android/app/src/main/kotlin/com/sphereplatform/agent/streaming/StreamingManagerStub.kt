package com.sphereplatform.agent.streaming

import android.media.projection.MediaProjection
import timber.log.Timber
import javax.inject.Inject

/**
 * No-op [StreamingManager] placeholder used until SPLIT-2 (MediaCodec encoder)
 * is implemented. Replaced in StreamingModule once H264Encoder is available.
 */
class StreamingManagerStub @Inject constructor() : StreamingManager {

    @Volatile private var active = false

    override fun start(projection: MediaProjection) {
        active = true
        Timber.d("StreamingManagerStub.start() — encoder not yet implemented (SPLIT-2)")
    }

    override fun stop() {
        active = false
        Timber.d("StreamingManagerStub.stop()")
    }

    override fun isActive(): Boolean = active
}
