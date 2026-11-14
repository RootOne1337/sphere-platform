package com.sphereplatform.agent.vpn

import android.app.Application
import android.content.Context
import android.os.Build
import java.io.File

internal object VpnProcessIdentity {
    fun isVpnProcess(context: Context): Boolean {
        val name = if (Build.VERSION.SDK_INT >= 28) Application.getProcessName() else {
            val bytes = ByteArray(256)
            val length = File("/proc/self/cmdline").inputStream().use { it.read(bytes) }
            if (length <= 0) "" else bytes.copyOf(length).toString(Charsets.UTF_8).substringBefore('\u0000')
        }
        return name == context.packageName + ":vpn"
    }
}
