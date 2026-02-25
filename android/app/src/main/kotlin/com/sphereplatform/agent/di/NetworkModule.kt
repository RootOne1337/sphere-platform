package com.sphereplatform.agent.di

import com.sphereplatform.agent.store.AuthTokenStore
import com.sphereplatform.agent.ws.SphereWebSocketClient
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.serialization.json.Json
import okhttp3.OkHttpClient
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    @Provides
    @Singleton
    fun provideWebSocketClient(
        httpClient: OkHttpClient,
        authStore: AuthTokenStore,
        json: Json,
    ): SphereWebSocketClient = SphereWebSocketClient(httpClient, authStore, json)
}
