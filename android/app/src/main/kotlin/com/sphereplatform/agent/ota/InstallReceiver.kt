package com.sphereplatform.agent.ota

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import androidx.core.content.IntentCompat
import com.sphereplatform.agent.workers.LogUploadWorker
import timber.log.Timber

/**
 * InstallReceiver — получает результат установки APK через PackageInstaller Sessions API.
 */
class InstallReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -1)
        val sessionId = intent.getIntExtra(PackageInstaller.EXTRA_SESSION_ID, -1)
        if (!InstallStatusStore.record(context, sessionId, status)) {
            Timber.w("OTA: install callback could not be persisted (session/status unavailable)")
        }
        if (sessionId >= 0) LogUploadWorker.scheduleImmediate(context)

        when (status) {
            PackageInstaller.STATUS_SUCCESS -> {
                Timber.i("OTA: PackageInstaller reports install success for session=$sessionId")
            }

            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                Timber.w("OTA: user approval required for PackageInstaller session=$sessionId")
                val confirmIntent = IntentCompat.getParcelableExtra(
                    intent, Intent.EXTRA_INTENT, Intent::class.java,
                )
                if (confirmIntent != null) {
                    try {
                        confirmIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                        context.startActivity(confirmIntent)
                    } catch (error: Exception) {
                        Timber.w(error, "OTA: could not open required install approval UI")
                    }
                }
            }

            else -> {
                // Do not persist PackageInstaller's free-form message; it can contain
                // device-specific paths. The numeric status is enough to correlate.
                Timber.e("OTA: PackageInstaller failed session=$sessionId status=$status")
            }
        }
    }
}
