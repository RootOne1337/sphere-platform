package com.sphereplatform.agent.ota

import android.content.Context
import android.os.Build
import android.content.pm.PackageInstaller
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import java.util.concurrent.atomic.AtomicBoolean
import java.util.concurrent.atomic.AtomicReference
import java.io.IOException
import kotlin.coroutines.resume
import javax.inject.Inject
import javax.inject.Singleton

internal sealed interface PackageInstallOutcome {
    data class Installed(val versionCode: Int) : PackageInstallOutcome
    data class RequiresUserAction(val sessionId: Int) : PackageInstallOutcome
}

/** Waits for the OS install callback and verifies the version that PackageManager actually exposes. */
@Singleton
class PackageInstallerResultAwaiter @Inject constructor(
    @ApplicationContext private val context: Context,
) {
    companion object {
        private const val CALLBACK_TIMEOUT_MS = 120_000L
    }

    internal suspend fun await(
        sessionId: Int,
        targetVersionCode: Int,
        timeoutMs: Long = CALLBACK_TIMEOUT_MS,
    ): PackageInstallOutcome {
        require(sessionId >= 0) { "invalid_package_installer_session" }
        require(timeoutMs > 0) { "invalid_package_installer_timeout" }
        val callbackStatus = withTimeoutOrNull(timeoutMs) {
            InstallStatusStore.read(context, sessionId) ?: suspendCancellableCoroutine { continuation ->
                val delivered = AtomicBoolean(false)
                val cleanup = AtomicReference<(() -> Unit)?>(null)
                fun unsubscribe() {
                    cleanup.getAndSet(null)?.invoke()
                }
                fun deliver(status: Int) {
                    if (delivered.compareAndSet(false, true)) {
                        unsubscribe()
                        if (continuation.isActive) continuation.resume(status)
                    }
                }
                val stopObserving = InstallStatusStore.observe(context, sessionId, ::deliver)
                cleanup.set(stopObserving)
                // A callback can race listener registration. If it won before
                // cleanup was published, unregister it now.
                if (delivered.get()) unsubscribe()
                continuation.invokeOnCancellation { unsubscribe() }
                // Close the race between the initial read and listener registration.
                InstallStatusStore.read(context, sessionId)?.let(::deliver)
            }
        } ?: throw IOException("package_installer_result_timeout")

        return when (callbackStatus) {
            PackageInstaller.STATUS_SUCCESS -> {
                val installedVersionCode = installedVersionCode()
                if (targetVersionCode > 0 && installedVersionCode < targetVersionCode) {
                    throw IOException("package_installer_version_mismatch")
                }
                PackageInstallOutcome.Installed(installedVersionCode)
            }
            PackageInstaller.STATUS_PENDING_USER_ACTION -> PackageInstallOutcome.RequiresUserAction(sessionId)
            else -> throw IOException("package_installer_failed_status_$callbackStatus")
        }
    }

    internal fun verifyInstalledVersion(targetVersionCode: Int): Int {
        val installedVersionCode = installedVersionCode()
        if (targetVersionCode > 0 && installedVersionCode < targetVersionCode) {
            throw IOException("root_install_version_mismatch")
        }
        return installedVersionCode
    }

    @Suppress("DEPRECATION")
    private fun installedVersionCode(): Int {
        val packageInfo = context.packageManager.getPackageInfo(context.packageName, 0)
        val versionCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
            packageInfo.longVersionCode
        } else {
            packageInfo.versionCode.toLong()
        }
        if (versionCode <= 0L || versionCode > Int.MAX_VALUE.toLong()) {
            throw IOException("installed_version_code_unavailable")
        }
        return versionCode.toInt()
    }
}
