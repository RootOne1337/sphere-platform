package com.sphereplatform.agent.commands

import android.content.Context
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import timber.log.Timber

/** Only fixed IME configuration reaches a root shell; typed characters never do. */
internal class AndroidRemoteKeyboard(context: Context) : RemoteKeyboardAdapter {
    private val app = context.applicationContext
    private val component = app.packageName + "/com.sphereplatform.agent.commands.RemoteInputMethodService"
    private val preferences = app.getSharedPreferences("remote_keyboard_lease", Context.MODE_PRIVATE)
    private val mutex = Mutex()
    private val processes = BoundedProcessRunner()
    private val lease = RemoteImeLease(component, object : RemoteImeLease.Gateway {
        override suspend fun selected() = shell("dumpsys input_method", 65_536)?.let(RemoteImeSelection::read)
        override suspend fun enabled(id: String) = shell("ime list -s")?.let { RemoteImeSelection.enabled(it, id) }
        override suspend fun enable(id: String) = shell("ime enable $id") != null
        override suspend fun disable(id: String) = shell("ime disable $id") != null
        override suspend fun select(id: String) = shell("ime set $id") != null
    }, object : RemoteImeLease.Store {
        override fun pending() = preferences.getBoolean("pending", false)
        override fun read() = preferences.getString("previous", null)?.let {
            RemoteImeLease.Saved(it, preferences.getBoolean("was_enabled", true))
        }
        override fun save(value: RemoteImeLease.Saved) = preferences.edit().putString("previous", value.previous)
            .putBoolean("was_enabled", value.wasEnabled).putBoolean("pending", true).commit()
        override fun clear() = preferences.edit().clear().commit()
    })
    @Volatile private var snapshot = RemoteKeyboardAdapter.State(false, 0, false)
    @Volatile private var owned = false
    private val owners = mutableSetOf<String>()
    override fun state() = snapshot
    override suspend fun enable(owner: String): Boolean = mutex.withLock {
        require(component.matches(Regex("[A-Za-z0-9_.]+/[A-Za-z0-9_.]+")))
        require(owner.matches(Regex("[A-Za-z0-9_-]{8,128}")))
        if (!owned) {
            if (!lease.acquire()) {
                // Fixed phase only, never shell output, component identifiers or entered text.
                Timber.w("Remote keyboard activation refused: %s", lease.failure.name.lowercase())
                return@withLock false
            }
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
        lease.restore()
    }
    override suspend fun reset(): Boolean = mutex.withLock {
        owners.clear(); owned = false
        snapshot = RemoteKeyboardAdapter.State(false, snapshot.editorGeneration, false)
        lease.restore()
    }
    internal suspend fun recoverInterruptedLease(): Boolean = mutex.withLock { if (owned) true else lease.restore() }
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
    private suspend fun shell(command: String, outputLimit: Int = 8192): String? {
        try {
            val result = processes.run({ ProcessBuilder("su", "-c", command).start() }, 3000, outputLimit, 4096)
            if (result.exitCode != 0 || result.stdout.truncated) return null
            return result.stdout.bytes.toString(Charsets.UTF_8).trim()
        } catch (cancelled: CancellationException) { throw cancelled }
        catch (_: Exception) { return null }
    }
}
