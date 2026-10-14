package com.sphereplatform.agent.commands

/** Read the IME service's live selection, not an emulator's possibly stale settings mirror.
 * The dump is transient: no editor fields, surrounding text or raw dump are retained.
 */
internal object RemoteImeSelection {
    private val component = Regex("[A-Za-z0-9_.]+/[A-Za-z0-9_.]+")
    private val selected = Regex("(?:^|\\s)(?:mCurMethodId|mSelectedMethodId)=([A-Za-z0-9_./]+)(?=\\s|$)")
    fun valid(value: String) = component.matches(value)
    fun read(dump: String): String? {
        val values = selected.findAll(dump).map { it.groupValues[1] }.filter(::valid).distinct().toList()
        // A dump containing different per-user selections must not authorize changing another user.
        return values.singleOrNull()
    }
    fun enabled(list: String, id: String) = list.lineSequence().map(String::trim).any { it == id }
}

/** Serialized by the caller. Saves restoration before any change and keeps uncertain cleanup pending. */
internal class RemoteImeLease(private val component: String, private val gateway: Gateway, private val store: Store) {
    init { require(RemoteImeSelection.valid(component)) }
    data class Saved(val previous: String, val wasEnabled: Boolean)
    interface Store {
        fun pending(): Boolean
        fun read(): Saved?
        fun save(value: Saved): Boolean
        fun clear(): Boolean
    }
    interface Gateway {
        suspend fun selected(): String?
        suspend fun enabled(id: String): Boolean?
        suspend fun enable(id: String): Boolean
        suspend fun disable(id: String): Boolean
        suspend fun select(id: String): Boolean
    }
    enum class Failure { NONE, RESTORE, SELECTION_READ, ENABLED_READ, SAVE, ENABLE, SELECT, SELECTION_CONFIRM }
    var failure = Failure.NONE
        private set
    suspend fun acquire(): Boolean {
        failure = Failure.NONE
        if (store.pending() && !restore()) return refuse(Failure.RESTORE)
        val previous = gateway.selected()?.takeIf(RemoteImeSelection::valid)
            ?.takeIf { it != component } ?: return refuse(Failure.SELECTION_READ)
        val enabled = gateway.enabled(component) ?: return refuse(Failure.ENABLED_READ)
        if (!store.save(Saved(previous, enabled))) return refuse(Failure.SAVE)
        val refused = when {
            !gateway.enable(component) -> Failure.ENABLE
            !gateway.select(component) -> Failure.SELECT
            gateway.selected() != component -> Failure.SELECTION_CONFIRM
            else -> Failure.NONE
        }
        if (refused == Failure.NONE) return true
        // Keep the marker if cleanup could not be confirmed; the next acquisition must restore first.
        restore()
        return refuse(refused)
    }
    suspend fun restore(): Boolean {
        if (!store.pending()) return true
        val saved = store.read()?.takeIf { RemoteImeSelection.valid(it.previous) && it.previous != component } ?: return false
        val selected = gateway.selected()?.takeIf(RemoteImeSelection::valid) ?: return false
        // A physical user choosing a third IME wins; do not overwrite that choice.
        if (selected == component && (!gateway.select(saved.previous) || gateway.selected() != saved.previous)) return false
        if (!saved.wasEnabled && !gateway.disable(component)) return false
        return store.clear()
    }
    private fun refuse(reason: Failure): Boolean { failure = reason; return false }
}
