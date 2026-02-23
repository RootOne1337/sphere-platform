package com.sphereplatform.agent.di

import com.sphereplatform.agent.streaming.StreamingManager
import com.sphereplatform.agent.streaming.StreamingManagerImpl
import com.sphereplatform.agent.ws.SphereWebSocketClientContract
import com.sphereplatform.agent.ws.SphereWebSocketClientLive
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class StreamingModule {

    @Binds
    @Singleton
    abstract fun bindStreamingManager(impl: StreamingManagerImpl): StreamingManager

    /**
     * Binds the real [SphereWebSocketClient]-backed adapter for binary frame
     * sending. TZ-07 SPLIT-2 provides the implementation; this wiring
     * completes the TZ-05 ↔ TZ-07 integration.
     */
    @Binds
    @Singleton
    abstract fun bindWsClient(live: SphereWebSocketClientLive): SphereWebSocketClientContract
}
