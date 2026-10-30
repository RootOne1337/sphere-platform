package com.sphereplatform.agent.streaming

import android.content.Context
import com.sphereplatform.agent.direct.DirectEncodedVideoSource
import org.webrtc.PeerConnectionFactory

/** One process initialization shared by capture and peers, including startup before an offer. */
internal object NativeWebRtcRuntime {
    private var initialized = false
    @Synchronized fun ensure(context: Context) {
        if (initialized) return
        PeerConnectionFactory.initialize(PeerConnectionFactory.InitializationOptions.builder(context)
            .setFieldTrials(DirectEncodedVideoSource.FIELD_TRIALS)
            .setEnableInternalTracer(false).createInitializationOptions())
        NativeRgbaToI420.activate()
        initialized = true
    }
}
