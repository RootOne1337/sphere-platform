package com.sphereplatform.agent.vpn

import android.app.Activity
import android.net.VpnService
import android.os.Bundle
import com.sphereplatform.agent.BuildConfig

/** Explicit Android consent only. It never replays a pending apply operation. */
class AppVpnConsentActivity : Activity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (!BuildConfig.APP_SCOPED_VPN_CANARY) { finish(); return }
        val consent = VpnService.prepare(this)
        if (consent == null) finish() else if (savedInstanceState == null) startActivityForResult(consent, 1)
    }
    @Deprecated("Android consent activity callback")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: android.content.Intent?) {
        super.onActivityResult(requestCode, resultCode, data); finish()
    }
}
