package com.sphereplatform.agent.commands

import android.content.ContextWrapper
import android.content.pm.ApplicationInfo
import android.media.projection.MediaProjection
import android.os.Process
import android.os.SystemClock
import com.sphereplatform.agent.streaming.CaptureInputSession
import com.sphereplatform.agent.streaming.StreamingManager
import kotlinx.coroutines.*
import kotlinx.serialization.json.*
import java.io.ByteArrayOutputStream
import java.util.concurrent.atomic.AtomicLong
import java.util.concurrent.atomic.AtomicReference

/** Root-only standalone diagnostic entry point; absent from every release source set and manifest. */
object ContinuousInputCanary {
    @JvmStatic fun main(args: Array<String>) {
        require(Process.myUid() == 0 && args.size == 3)
        val apk = System.getenv("CLASSPATH") ?: error("canary_classpath_missing")
        require(apk.startsWith("/data/local/tmp/") && apk.endsWith(".apk") && apk.length <= 256 && !apk.contains('\n'))
        val capture = AtomicReference(CaptureInputSession("canary_epoch_1234", args[0].toInt(), args[1].toInt(), args[0].toInt(), args[1].toInt(), args[2].toInt()))
        val connection = AtomicLong(1)
        val context = object : ContextWrapper(null) {
            override fun getApplicationInfo() = ApplicationInfo().apply { sourceDir = apk }
        }
        val streaming = object : StreamingManager {
            override fun start(projection: MediaProjection) = error("canary_does_not_capture_video")
            override fun stop() {}
            override fun isActive() = true
            override fun getInputSession() = capture.get()
        }
        val job = SupervisorJob()
        val scope = CoroutineScope(job + Dispatchers.IO)
        val adb = AdbActionExecutor(context)
        val outputLock = Any()
        fun output(message: JsonObject) = synchronized(outputLock) { println(message); System.out.flush() }
        val controller = ContinuousInputController(scope,
            OwnedTouchPipeFactory(adb.inputOwnership, adb::prepareContinuousInput, RootTouchPipeFactory(context)),
            streaming, connection::get, { expected, message ->
                if (connection.get() != expected) false else { output(message); true }
            }, SystemClock::uptimeMillis, true,
        )
        output(buildJsonObject { put("type", "canary_ready") })
        try {
            repeat(128) {
                val line = readBoundedLine() ?: return@repeat
                val message = Json.parseToJsonElement(line).jsonObject
                when (message["type"]?.jsonPrimitive?.content) {
                    "canary_capture_restart" -> {
                        capture.set(capture.get().copy(epoch = "canary_epoch_5678"))
                        controller.invalidate()
                    }
                    "canary_disconnect" -> { connection.incrementAndGet(); controller.invalidate() }
                    "canary_discrete" -> {
                        val rejected = try { adb.keyEvent(4); false } catch (_: DeviceInputBusyException) { true }
                        output(buildJsonObject { put("type", "canary_discrete_result"); put("rejected", rejected) })
                    }
                    else -> controller.handle(message)
                }
            }
        } finally {
            controller.invalidate()
            runBlocking { withTimeoutOrNull(5_000) { while (job.children.any()) delay(10) } }
            job.cancel()
            adb.closeRootSession()
        }
    }

    private fun readBoundedLine(): String? {
        val line = ByteArrayOutputStream(2048)
        while (true) {
            val value = System.`in`.read()
            if (value < 0) return if (line.size() == 0) null else error("canary_line_truncated")
            if (value == '\n'.code) return line.toString("UTF-8").removeSuffix("\r")
            check(line.size() < 2048) { "canary_line_budget" }
            line.write(value)
        }
    }
}
