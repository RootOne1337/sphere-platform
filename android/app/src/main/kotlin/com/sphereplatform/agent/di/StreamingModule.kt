package com.sphereplatform.agent.di

import com.sphereplatform.agent.streaming.StreamingManager
import com.sphereplatform.agent.streaming.StreamingManagerStub
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class StreamingModule {

    /**
     * Binds the stub implementation until SPLIT-2 (H264Encoder + VirtualDisplay)
     * provides the real [StreamingManagerImpl].
     */
    @Binds
    @Singleton
    abstract fun bindStreamingManager(impl: StreamingManagerStub): StreamingManager
}
