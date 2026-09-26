package com.sphereplatform.agent.ota

import android.app.Application
import android.content.Intent
import android.content.pm.ApplicationInfo
import android.content.pm.PackageInfo
import android.content.pm.PackageInstaller
import androidx.work.Configuration
import androidx.work.NetworkType
import androidx.work.WorkManager
import androidx.work.testing.SynchronousExecutor
import androidx.work.testing.WorkManagerTestInitHelper
import com.sphereplatform.agent.BuildConfig
import com.sphereplatform.agent.workers.LogUploadWorker
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.supervisorScope
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.Shadows.shadowOf
import org.robolectric.annotation.Config
import java.io.IOException
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class PackageInstallerResultAwaiterTest {
    private val context by lazy { RuntimeEnvironment.getApplication() }
    private lateinit var manager: WorkManager

    @Before fun setUp() {
        WorkManagerTestInitHelper.initializeTestWorkManager(
            context,
            Configuration.Builder().setExecutor(SynchronousExecutor()).build(),
        )
        manager = WorkManager.getInstance(context)
        context.getSharedPreferences("sphere_ota_install_status_v1", 0).edit().clear().commit()
    }

    @After fun tearDown() {
        shadowOf(context.mainLooper).idle()
        WorkManagerTestInitHelper.closeWorkDatabase()
    }

    @Test fun `await remains pending until the PackageInstaller callback arrives`() = runBlocking {
        val sessionId = 77
        val targetVersionCode = BuildConfig.VERSION_CODE + 1
        installTargetPackageVersion(targetVersionCode)
        assertTrue(InstallStatusStore.begin(context, sessionId))
        val awaiting = async(Dispatchers.Default) {
            PackageInstallerResultAwaiter(context).await(sessionId, targetVersionCode, timeoutMs = 2_000)
        }

        delay(100)
        assertFalse("A committed session is not an installed APK", awaiting.isCompleted)
        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_SUCCESS))

        val outcome = awaiting.await()
        assertEquals(PackageInstallOutcome.Installed(targetVersionCode), outcome)
        val upload = manager.getWorkInfosForUniqueWork(LogUploadWorker.IMMEDIATE_WORK_NAME)
            .get(5, TimeUnit.SECONDS).single()
        assertEquals(NetworkType.CONNECTED, upload.constraints.requiredNetworkType)
    }

    @Test fun `callback persisted before waiter starts is still consumed`() = runBlocking {
        val sessionId = 83
        val targetVersionCode = BuildConfig.VERSION_CODE + 1
        installTargetPackageVersion(targetVersionCode)
        assertTrue(InstallStatusStore.begin(context, sessionId))
        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_SUCCESS))

        assertEquals(
            PackageInstallOutcome.Installed(targetVersionCode),
            PackageInstallerResultAwaiter(context).await(sessionId, targetVersionCode, timeoutMs = 2_000),
        )
    }

    @Test fun `success callback with old installed version is rejected`() = runBlocking {
        val sessionId = 84
        val targetVersionCode = BuildConfig.VERSION_CODE + 1
        installTargetPackageVersion(BuildConfig.VERSION_CODE)
        assertTrue(InstallStatusStore.begin(context, sessionId))
        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_SUCCESS))

        val failure = runCatching {
            PackageInstallerResultAwaiter(context).await(sessionId, targetVersionCode, timeoutMs = 2_000)
        }.exceptionOrNull()

        assertTrue(failure is IOException)
        assertEquals("package_installer_version_mismatch", failure?.message)
    }

    @Test fun `pending user action is an explicit non-success outcome`() = runBlocking {
        val sessionId = 78
        assertTrue(InstallStatusStore.begin(context, sessionId))
        val awaiting = async(Dispatchers.Default) {
            PackageInstallerResultAwaiter(context).await(
                sessionId, targetVersionCode = BuildConfig.VERSION_CODE + 1, timeoutMs = 2_000,
            )
        }

        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_PENDING_USER_ACTION))

        assertEquals(PackageInstallOutcome.RequiresUserAction(sessionId), awaiting.await())
    }

    @Test fun `PackageInstaller failure is retained as a failure status`() = runBlocking {
        val sessionId = 79
        assertTrue(InstallStatusStore.begin(context, sessionId))
        val failure = supervisorScope {
            val awaiting = async(Dispatchers.Default) {
                PackageInstallerResultAwaiter(context).await(
                    sessionId, targetVersionCode = BuildConfig.VERSION_CODE + 1, timeoutMs = 2_000,
                )
            }
            InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_FAILURE_INVALID))
            runCatching { awaiting.await() }.exceptionOrNull()
        }
        assertTrue(failure is IOException)
        assertEquals("package_installer_failed_status_${PackageInstaller.STATUS_FAILURE_INVALID}", failure?.message)
    }

    @Test fun `late callback from a prior session cannot complete the active update`() {
        assertTrue(InstallStatusStore.begin(context, sessionId = 81))

        InstallReceiver().onReceive(context, statusIntent(80, PackageInstaller.STATUS_SUCCESS))

        assertEquals(null, InstallStatusStore.read(context, sessionId = 81))
    }

    @Test fun `unsubscribed installer observer does not receive later session events`() {
        val sessionId = 85
        assertTrue(InstallStatusStore.begin(context, sessionId))
        var deliveredStatuses = 0
        val unsubscribe = InstallStatusStore.observe(context, sessionId) { deliveredStatuses++ }

        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_PENDING_USER_ACTION))
        assertEquals(1, deliveredStatuses)

        unsubscribe()
        InstallReceiver().onReceive(context, statusIntent(sessionId, PackageInstaller.STATUS_SUCCESS))
        assertEquals(1, deliveredStatuses)
    }

    @Test fun `missing installer callback times out instead of reporting success`() = runBlocking {
        val sessionId = 82
        assertTrue(InstallStatusStore.begin(context, sessionId))
        val failure = runCatching {
            PackageInstallerResultAwaiter(context).await(
                sessionId, targetVersionCode = BuildConfig.VERSION_CODE + 1, timeoutMs = 50,
            )
        }.exceptionOrNull()

        assertTrue(failure is IOException)
        assertEquals("package_installer_result_timeout", failure?.message)
    }

    private fun statusIntent(sessionId: Int, status: Int) = Intent(context, InstallReceiver::class.java)
        .putExtra(PackageInstaller.EXTRA_SESSION_ID, sessionId)
        .putExtra(PackageInstaller.EXTRA_STATUS, status)

    private fun installTargetPackageVersion(versionCode: Int) {
        val appInfo = ApplicationInfo().apply { packageName = context.packageName }
        val packageInfo = PackageInfo().apply {
            packageName = context.packageName
            applicationInfo = appInfo
            this.versionCode = versionCode
        }
        shadowOf(context.packageManager).installPackage(packageInfo)
    }
}
