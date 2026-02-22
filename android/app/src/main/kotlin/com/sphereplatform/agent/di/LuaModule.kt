package com.sphereplatform.agent.di

import com.sphereplatform.agent.commands.AdbActionExecutor
import com.sphereplatform.agent.lua.LuaEngine
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object LuaModule {

    @Provides
    @Singleton
    fun provideLuaEngine(
        adbActions: AdbActionExecutor,
    ): LuaEngine = LuaEngine(adbActions)
}
