package com.sphereplatform.agent.logging

import android.app.Application
import android.content.Context
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class CrashHandlerTest {
    @Test fun `uncaught exception is persisted and delegated to Android handler`() {
        val context: Context = RuntimeEnvironment.getApplication()
        val crashFile = CrashHandler.crashLogFile(context)
        crashFile.delete()
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        var delegated = false
        val platformHandler = Thread.UncaughtExceptionHandler { _, _ -> delegated = true }

        try {
            Thread.setDefaultUncaughtExceptionHandler(platformHandler)
            CrashHandler.install(context)
            val installed = Thread.getDefaultUncaughtExceptionHandler()

            assertNotSame("CrashHandler must wrap Android's handler", platformHandler, installed)
            installed!!.uncaughtException(
                Thread.currentThread(),
                IllegalStateException("crash-handler-regression-marker"),
            )

            assertTrue(crashFile.readText().contains("crash-handler-regression-marker"))
            assertTrue("the platform handler must still terminate/report the process", delegated)
        } finally {
            Thread.setDefaultUncaughtExceptionHandler(previous)
            crashFile.delete()
        }
    }
}
