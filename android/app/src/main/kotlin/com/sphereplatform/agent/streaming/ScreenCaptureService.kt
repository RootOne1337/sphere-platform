package com.sphereplatform.agent.streaming

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import androidx.core.app.NotificationCompat
import com.sphereplatform.agent.R
import dagger.hilt.android.AndroidEntryPoint
import timber.log.Timber
import javax.inject.Inject

/**
 * Foreground service that holds the MediaProjection token for the duration
 * of the screen-capture session. Delegates encoding to [StreamingManager].
 *
 * Start via [ScreenCaptureRequestActivity] — never start this service directly
 * without a valid result code / data from MediaProjectionManager.
 */
@AndroidEntryPoint
class ScreenCaptureService : Service() {

    companion object {
        const val ACTION_START = "action.START_CAPTURE"
        const val ACTION_STOP = "action.STOP_CAPTURE"
        const val EXTRA_RESULT_CODE = "result_code"
        const val EXTRA_RESULT_DATA = "result_data"
        const val NOTIFICATION_ID = 1001

        private const val CHANNEL_ID = "screen_capture"
    }

    @Inject lateinit var streamingManager: StreamingManager

    private var mediaProjection: MediaProjection? = null

    private val mediaProjectionManager by lazy {
        getSystemService(MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }

    // -------------------------------------------------------------------------
    // Lifecycle
    // -------------------------------------------------------------------------

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> handleStart(intent)
            ACTION_STOP -> handleStop()
        }
        return START_NOT_STICKY
    }

    private fun handleStart(intent: Intent) {
        // Повторный старт при уже активном стриминге — корректный restart
        if (streamingManager.isActive()) {
            Timber.d("ScreenCaptureService: restart requested while active — stopping first")
            streamingManager.stop()
            mediaProjection?.unregisterCallback(projectionCallback)
            mediaProjection?.stop()
            mediaProjection = null
        }

        startForeground(NOTIFICATION_ID, buildNotification())

        val resultCode = intent.getIntExtra(EXTRA_RESULT_CODE, Activity.RESULT_CANCELED)
        val resultData = intent.getParcelableExtra<Intent>(EXTRA_RESULT_DATA)
        if (resultData == null) {
            Timber.e("ScreenCaptureService: missing result data, stopping")
            stopSelf()
            return
        }

        mediaProjection = mediaProjectionManager
            .getMediaProjection(resultCode, resultData)
            .also { projection ->
                projection.registerCallback(projectionCallback, null)
                streamingManager.start(projection)
            }
    }

    private fun handleStop() {
        streamingManager.stop()
        mediaProjection?.unregisterCallback(projectionCallback)
        mediaProjection?.stop()
        mediaProjection = null
        stopForeground(STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    // -------------------------------------------------------------------------
    // MediaProjection callback — system-initiated stop (e.g. user taps Stop)
    // -------------------------------------------------------------------------

    private val projectionCallback = object : MediaProjection.Callback() {
        override fun onStop() {
            Timber.d("ScreenCaptureService: MediaProjection stopped by system")
            streamingManager.stop()
            mediaProjection = null
            stopForeground(STOP_FOREGROUND_REMOVE)
            stopSelf()
        }
    }

    // -------------------------------------------------------------------------
    // Notification
    // -------------------------------------------------------------------------

    private fun buildNotification(): Notification {
        val channel = NotificationChannel(
            CHANNEL_ID,
            "Screen Capture",
            NotificationManager.IMPORTANCE_LOW,
        )
        getSystemService(NotificationManager::class.java)
            .createNotificationChannel(channel)

        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(R.drawable.ic_screen_share)
            .setContentTitle("Sphere Platform")
            .setContentText("Screen sharing active")
            .setOngoing(true)
            .build()
    }

    override fun onBind(intent: Intent?) = null
}
