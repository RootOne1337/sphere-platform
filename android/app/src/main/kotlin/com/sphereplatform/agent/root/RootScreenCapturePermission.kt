package com.sphereplatform.agent.root

import android.content.Context
import android.os.Process
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import timber.log.Timber
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit
import javax.inject.Inject

/** Prepare this app's projection app-op on devices that authorize its own su process.
 * The normal Android projection intent must still create a fresh capture token.
 */
class RootScreenCapturePermission internal constructor(
    private val packageName: String,
    private val userId: Int,
    private val cacheDir: File,
    private val startProcess: (List<String>, File) -> java.lang.Process,
) {
    @Inject constructor(@ApplicationContext context: Context) : this(
        context.packageName,
        Process.myUid() / 100_000,
        context.cacheDir,
        { command, output ->
            ProcessBuilder(command).redirectErrorStream(true).redirectOutput(output).start()
        },
    )

    suspend fun prepare(): Boolean = withContext(Dispatchers.IO) {
        // Only the installed package and Android user may be changed; no remote input.
        if (!packageName.matches(Regex("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+")) || userId < 0) {
            return@withContext false
        }
        var output: File? = null
        var process: java.lang.Process? = null
        try {
            output = File.createTempFile("projection-permission-", ".txt", cacheDir)
            val target = "--user $userId $packageName PROJECT_MEDIA"
            // Read back the actual mode: some vendor commands exit 0 on errors.
            val command = "cmd appops set $target allow && cmd appops get $target"
            process = startProcess(listOf("su", "-c", command), output)
            if (!process.waitFor(8, TimeUnit.SECONDS)) {
                process.destroyForcibly()
                Timber.w("Screen capture: root permission preparation timed out")
                return@withContext false
            }
            val result = output.inputStream().use { input ->
                val bytes = ByteArray(4096)
                val count = input.read(bytes)
                if (count > 0) String(bytes, 0, count, Charsets.UTF_8) else ""
            }
            val allowed = process.exitValue() == 0 &&
                Regex("(?m)^\\s*PROJECT_MEDIA: allow(?:;|\\s|$)").containsMatchIn(result)
            Timber.i("Screen capture: root projection permission verified=%s", allowed)
            allowed
        } catch (e: IOException) {
            Timber.w("Screen capture: root permission preparation unavailable (%s)", e.javaClass.simpleName)
            false
        } finally {
            process?.let {
                if (it.isAlive) it.destroyForcibly()
                runCatching { it.inputStream.close() }
                runCatching { it.errorStream.close() }
                runCatching { it.outputStream.close() }
            }
            output?.delete()
        }
    }
}
