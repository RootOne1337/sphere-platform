package com.sphereplatform.agent.ota

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import timber.log.Timber

/**
 * InstallReceiver — получает результат установки APK через PackageInstaller Sessions API.
 */
class InstallReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, -1)
        val message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE)

        when (status) {
            PackageInstaller.STATUS_SUCCESS -> {
                Timber.i("OTA: install SUCCESS")
            }

            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                // Требуется подтверждение пользователя (без root)
                val confirmIntent = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                confirmIntent?.let {
                    it.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    context.startActivity(it)
                }
            }

            else -> {
                Timber.e("OTA: install FAILED status=$status: $message")
            }
        }
    }
}
