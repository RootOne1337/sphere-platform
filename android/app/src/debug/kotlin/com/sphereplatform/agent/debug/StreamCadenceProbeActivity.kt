package com.sphereplatform.agent.debug

import android.app.Activity
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.os.Bundle
import android.os.SystemClock
import android.view.Choreographer
import android.view.View
import android.view.MotionEvent
import timber.log.Timber

/**
 * Visible continuous-motion/legibility canary, not a synthetic encoder timer.
 * Explicit local launch only, no exported component; root support can launch
 * through the existing authenticated shell. No apps/accounts/settings altered.
 * Auto-finishes after 30 s, separate task, removed from recents; debug APK only.
 */
class StreamCadenceProbeActivity : Activity(), Choreographer.FrameCallback {
    private var deadline = 0L
    private lateinit var pattern: Pattern

    override fun onCreate(state: Bundle?) {
        super.onCreate(state)
        deadline = SystemClock.elapsedRealtime() + 30_000
        pattern = Pattern(this)
        setContentView(pattern)
    }
    override fun onResume() { super.onResume(); Choreographer.getInstance().postFrameCallback(this) }
    override fun onPause() { Choreographer.getInstance().removeFrameCallback(this); super.onPause() }
    override fun doFrame(frameTimeNanos: Long) {
        if (isFinishing || SystemClock.elapsedRealtime() >= deadline) { finish(); return }
        pattern.phase = (frameTimeNanos % 2_000_000_000L).toFloat() / 2_000_000_000f
        pattern.invalidate()
        Choreographer.getInstance().postFrameCallback(this)
    }

    private class Pattern(context: Context) : View(context) {
        var phase = 0f
        private val paint = Paint(Paint.ANTI_ALIAS_FLAG)
        private var reportedTouches = 0
        override fun onTouchEvent(event: MotionEvent): Boolean {
            if (event.actionMasked == MotionEvent.ACTION_UP && reportedTouches < 3) {
                reportedTouches++
                // Only this artificial pattern, never another application's UI.
                Timber.i("Video canary touch x=%d y=%d", event.x.toInt(), event.y.toInt())
            }
            return true
        }
        override fun onDraw(canvas: Canvas) {
            canvas.drawColor(Color.rgb(15, 23, 42))
            paint.color = Color.WHITE
            paint.textSize = 24f
            canvas.drawText("Sphere video canary · automatic return after 30 seconds", 12f, 36f, paint)
            paint.textSize = 18f
            canvas.drawText("ABCDEFGHIJKLMN 0123456789 · moving bar + fine detail", 12f, 64f, paint)
            paint.color = Color.rgb(56, 189, 248)
            val x = phase * (width - 32).coerceAtLeast(0)
            canvas.drawRect(x, 86f, x + 32f, height.toFloat(), paint)
            paint.color = Color.WHITE
            paint.strokeWidth = 1f
            for (line in 0..20) {
                val y = 100f + line * 8f
                canvas.drawLine(12f, y, (width / 3).toFloat(), y, paint)
            }
            paint.color = Color.rgb(250, 204, 21)
            canvas.drawCircle(width * (1 - phase), height * .75f, 24f, paint)
        }
    }
}
