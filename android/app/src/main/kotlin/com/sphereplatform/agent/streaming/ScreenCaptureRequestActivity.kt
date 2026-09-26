package com.sphereplatform.agent.streaming

import android.app.Activity
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Bundle
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import com.sphereplatform.agent.root.RootScreenCapturePermission
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * Transparent, UI-less Activity whose sole purpose is to trigger the system
 * MediaProjection permission dialog and forward the result to
 * [ScreenCaptureService].
 *
 * Declared with Theme.Translucent.NoTitleBar so it is invisible to the user.
 */
@AndroidEntryPoint
class ScreenCaptureRequestActivity : AppCompatActivity() {

    @Inject lateinit var rootPermission: RootScreenCapturePermission

    private val projectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startForegroundService(
                Intent(this, ScreenCaptureService::class.java).apply {
                    action = ScreenCaptureService.ACTION_START
                    putExtra(ScreenCaptureService.EXTRA_RESULT_CODE, result.resultCode)
                    putExtra(ScreenCaptureService.EXTRA_RESULT_DATA, result.data)
                }
            )
        } else {
            // User denied — notify the backend so it can update device status
            sendBroadcast(Intent("sphere.SCREEN_CAPTURE_DENIED"))
        }
        finish()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (savedInstanceState == null) {
            lifecycleScope.launch {
                // Root work runs on IO. Never block the UI or WS heartbeat on su.
                // Unsupported/denied root retains Android's normal consent flow.
                rootPermission.prepare()
                val mpManager = getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
                projectionLauncher.launch(mpManager.createScreenCaptureIntent())
            }
        }
    }
}
