package com.sphereplatform.agent

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import com.sphereplatform.agent.service.SphereAgentService
import dagger.hilt.android.AndroidEntryPoint

/**
 * BootReceiver — запускает SphereAgentService при загрузке устройства.
 * Требует: android.permission.RECEIVE_BOOT_COMPLETED
 */
@AndroidEntryPoint
class BootReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED ||
            intent.action == "android.intent.action.QUICKBOOT_POWERON"
        ) {
            SphereAgentService.start(context)
        }
    }
}
