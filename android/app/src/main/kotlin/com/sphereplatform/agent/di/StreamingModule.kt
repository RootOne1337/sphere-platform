package com.sphereplatform.agent.di

import com.sphereplatform.agent.streaming.StreamingManager
import com.sphereplatform.agent.streaming.StreamingManagerImpl
import com.sphereplatform.agent.ws.SphereWebSocketClientContract
import com.sphereplatform.agent.ws.SphereWebSocketClientStub
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
     * Binds a no-op WS client until TZ-07 SPLIT-2 provides the real
     * [SphereWebSocketClient] implementation.
     */
    @Binds
    @Singleton
    abstract fun bindWsClient(stub: SphereWebSocketClientStub): SphereWebSocketClientContract
}
