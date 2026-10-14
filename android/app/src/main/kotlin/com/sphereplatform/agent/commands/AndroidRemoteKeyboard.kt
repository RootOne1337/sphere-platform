package com.sphereplatform.agent.commands

import android.content.Context
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import java.util.concurrent.TimeUnit

/** Only fixed IME configuration reaches a root shell; typed characters never do. */
internal class AndroidRemoteKeyboard(context: Context) : RemoteKeyboardAdapter {
    private val app = context.applicationContext
    private val component = app.packageName + "/com.sphereplatform.agent.commands.RemoteInputMethodService"
    private val preferences = app.getSharedPreferences("remote_keyboard_lease", Context.MODE_PRIVATE)
    private val mutex = Mutex()
    @Volatile private var snapshot = RemoteKeyboardAdapter.State(false, 0, false)
    private var owned = false
    private val owners = mutableSetOf<String>()
    override fun state() = snapshot
    override suspend fun enable(owner: String): Boolean = mutex.withLock {
        require(component.matches(Regex("[A-Za-z0-9_.]+/[A-Za-z0-9_.]+")))
        require(owner.matches(Regex("[A-Za-z0-9_-]{8,128}")))
        if (!owned) {
            // A stale marker belongs to a previous process; restore before admitting a new owner.
            if (preferences.getBoolean("pending", false) && !restore()) return@withLock false
            val previous = shell("settings get secure default_input_method") ?: return@withLock false
            if (!previous.matches(Regex("[A-Za-z0-9_.]+/[A-Za-z0-9_.]+")) || previous == component) return@withLock false
            val enabled = shell("settings get secure enabled_input_methods") ?: return@withLock false
            if (!preferences.edit().putString("previous", previous).putBoolean("was_enabled", enabled.split(':').any { it.substringBefore(';') == component })
                    .putBoolean("pending", true).commit()) return@withLock false
            if (shell("ime enable $component") == null || shell("ime set $component") == null
                || shell("settings get secure default_input_method") != component) { restore(); return@withLock false }
            owned = true
        }
        owners += owner
        refresh()
        true
    }
    override suspend fun disable(owner: String): Boolean = mutex.withLock {
        owners -= owner
        if (owners.isNotEmpty()) return@withLock true
        owned = false
        snapshot = RemoteKeyboardAdapter.State(false, snapshot.editorGeneration, false)
        restore()
    }
    override suspend fun reset(): Boolean = mutex.withLock {
        owners.clear(); owned = false
        snapshot = RemoteKeyboardAdapter.State(false, snapshot.editorGeneration, false)
        restore()
    }
    private suspend fun restore(): Boolean {
        if (!preferences.getBoolean("pending", false)) return true
        val previous = preferences.getString("previous", null) ?: return false
        if (!previous.matches(Regex("[A-Za-z0-9_.]+/[A-Za-z0-9_.]+"))) return false
        val selected = shell("settings get secure default_input_method") ?: return false
        // A local user explicitly selecting another IME must win over our saved setting.
        if (selected == component && (shell("ime set $previous") == null || shell("settings get secure default_input_method") != previous)) return false
        if (!preferences.getBoolean("was_enabled", true) && shell("ime disable $component") == null) return false
        return preferences.edit().clear().commit()
    }
    internal suspend fun recoverInterruptedLease(): Boolean = mutex.withLock { if (owned) true else restore() }
    internal suspend fun refresh() {
        val actual = RemoteInputMethodService.snapshot()
        snapshot = actual.copy(enabled = owned, editorActive = owned && actual.editorActive)
    }
    override suspend fun apply(owner: String, command: RemoteKeyboardCommand, current: () -> Boolean): RemoteKeyboardAdapter.Result {
        if (!owned || !current()) return RemoteKeyboardAdapter.Result.UNAVAILABLE
        val result = if (command.operation == RemoteKeyboardCommand.Operation.RESET) {
            if (release(owner)) RemoteKeyboardAdapter.Result.ACCEPTED else RemoteKeyboardAdapter.Result.UNKNOWN
        } else RemoteInputMethodService.execute(owner, command, current)
        refresh()
        return result
    }
    override suspend fun release(owner: String) = RemoteInputMethodService.release(owner)
    private suspend fun shell(command: String): String? = withContext(Dispatchers.IO) {
        val process = runCatching { ProcessBuilder("su", "-c", command).start() }.getOrNull() ?: return@withContext null
        try {
            if (!process.waitFor(3, TimeUnit.SECONDS)) { process.destroyForcibly(); return@withContext null }
            if (process.exitValue() != 0) return@withContext null
            val output = java.io.ByteArrayOutputStream()
            val buffer = ByteArray(1024)
            while (output.size() <= 8192) {
                val count = process.inputStream.read(buffer, 0, minOf(buffer.size, 8193 - output.size()))
                if (count < 0) break
                output.write(buffer, 0, count)
            }
            val bytes = output.toByteArray()
            if (bytes.size > 8192) return@withContext null
            bytes.toString(Charsets.UTF_8).trim()
        } catch (_: Exception) { null }
        finally { runCatching { process.outputStream.close() }; runCatching { process.inputStream.close() }; runCatching { process.errorStream.close() }; process.destroy() }
    }
}
