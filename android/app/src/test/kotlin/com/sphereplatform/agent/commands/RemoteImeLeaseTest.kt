package com.sphereplatform.agent.commands

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test

class RemoteImeLeaseTest {
    private val remote = "com.sphereplatform.agent.pilot.debug/com.sphereplatform.agent.commands.RemoteInputMethodService"
    private val original = "com.android.inputmethod.pinyin/.InputService"
    private val physical = "com.example.keyboard/.UserIme"
    private class Store : RemoteImeLease.Store {
        var saved: RemoteImeLease.Saved? = null
        var marker = false
        var saveAllowed = true
        override fun pending() = marker
        override fun read() = saved
        override fun save(value: RemoteImeLease.Saved): Boolean {
            if (!saveAllowed) return false
            saved = value; marker = true; return true
        }
        override fun clear(): Boolean { saved = null; marker = false; return true }
    }
    private inner class Gateway : RemoteImeLease.Gateway {
        var active: String? = original
        // This is deliberately stale on LDPlayer; the lease must use active service selection.
        val settingsMirror = original
        val enabled = mutableSetOf(original)
        val operations = mutableListOf<String>()
        var refuseSelection: String? = null
        var failDisable = false
        var cancelSelection = false
        override suspend fun selected() = active
        override suspend fun enabled(id: String) = enabled.contains(id)
        override suspend fun enable(id: String): Boolean { operations += "enable:$id"; enabled += id; return true }
        override suspend fun disable(id: String): Boolean {
            operations += "disable:$id"
            if (failDisable) return false
            enabled -= id; return true
        }
        override suspend fun select(id: String): Boolean {
            operations += "select:$id"
            if (cancelSelection) { active = id; throw CancellationException("test cancellation") }
            if (id != refuseSelection) active = id
            return true
        }
    }
    @Test fun `live selection confirms an IME despite stale emulator settings and restores it`() = runBlocking {
        val gateway = Gateway(); val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); assertEquals(original, gateway.settingsMirror); assertEquals(remote, gateway.active)
        assertEquals(RemoteImeLease.Saved(original, false), store.saved)
        assertTrue(lease.restore()); assertEquals(original, gateway.active); assertFalse(remote in gateway.enabled)
        assertFalse(store.pending())
    }
    @Test fun `physical user selecting another IME wins when remote mode closes`() = runBlocking {
        val gateway = Gateway(); val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); gateway.active = physical
        assertTrue(lease.restore()); assertEquals(physical, gateway.active)
        assertEquals(1, gateway.operations.count { it.startsWith("select:") }); assertFalse(store.pending())
    }
    @Test fun `previously enabled remote IME stays enabled after restoration`() = runBlocking {
        val gateway = Gateway().apply { enabled += remote }; val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); assertTrue(lease.restore()); assertTrue(remote in gateway.enabled)
        assertTrue(gateway.operations.none { it.startsWith("disable:") })
    }
    @Test fun `unconfirmed activation cleans up and exposes its exact fixed phase`() = runBlocking {
        val gateway = Gateway().apply { refuseSelection = remote }; val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertFalse(lease.acquire()); assertEquals(RemoteImeLease.Failure.SELECTION_CONFIRM, lease.failure)
        assertEquals(original, gateway.active); assertFalse(remote in gateway.enabled); assertFalse(store.pending())
    }
    @Test fun `unknown restoration preserves marker and prevents another acquisition`() = runBlocking {
        val gateway = Gateway(); val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); gateway.refuseSelection = original
        assertFalse(lease.restore()); assertTrue(store.pending()); val count = gateway.operations.size
        assertFalse(lease.acquire()); assertEquals(RemoteImeLease.Failure.RESTORE, lease.failure)
        assertEquals(count + 1, gateway.operations.size); assertEquals(remote, gateway.active)
    }
    @Test fun `failed disable remains pending even after prior selection was restored`() = runBlocking {
        val gateway = Gateway(); val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); gateway.failDisable = true
        assertFalse(lease.restore()); assertEquals(original, gateway.active); assertTrue(store.pending())
        gateway.failDisable = false; assertTrue(lease.restore()); assertFalse(store.pending())
    }
    @Test fun `missing or ambiguous selection never changes the keyboard`() = runBlocking {
        val gateway = Gateway().apply { active = null }; val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        assertFalse(lease.acquire()); assertEquals(RemoteImeLease.Failure.SELECTION_READ, lease.failure)
        assertTrue(gateway.operations.isEmpty()); assertFalse(store.pending())
    }
    @Test fun `failed durable save never enables or selects an IME`() = runBlocking {
        val gateway = Gateway(); val store = Store().apply { saveAllowed = false }; val lease = RemoteImeLease(remote, gateway, store)
        assertFalse(lease.acquire()); assertEquals(RemoteImeLease.Failure.SAVE, lease.failure)
        assertTrue(gateway.operations.isEmpty())
    }
    @Test fun `inactive keyboard configuration does not crash dispatcher and refuses invalid acquisition`() = runBlocking {
        val gateway = Gateway(); val store = Store(); val lease = RemoteImeLease("/com.example.RemoteIme", gateway, store)
        assertTrue(lease.restore()); assertFalse(lease.acquire())
        assertEquals(RemoteImeLease.Failure.COMPONENT, lease.failure); assertTrue(gateway.operations.isEmpty())
        store.save(RemoteImeLease.Saved(original, false)); assertFalse(lease.restore()); assertTrue(store.pending())
    }
    @Test fun `interrupted selection keeps recoverable lease without replaying input`() = runBlocking {
        val gateway = Gateway().apply { cancelSelection = true }; val store = Store(); val lease = RemoteImeLease(remote, gateway, store)
        try { lease.acquire(); fail("cancellation swallowed") } catch (_: CancellationException) { /* expected */ }
        assertTrue(store.pending()); assertEquals(remote, gateway.active)
        gateway.cancelSelection = false; assertTrue(lease.restore()); assertEquals(original, gateway.active)
    }
    @Test fun `stale process marker is restored before a new lease saves its original selection`() = runBlocking {
        val gateway = Gateway().apply { active = remote; enabled += remote }
        val store = Store().apply { save(RemoteImeLease.Saved(original, false)) }
        val lease = RemoteImeLease(remote, gateway, store)
        assertTrue(lease.acquire()); assertEquals(RemoteImeLease.Saved(original, false), store.saved)
        assertEquals(listOf("select:$original", "disable:$remote", "enable:$remote", "select:$remote"), gateway.operations)
    }
    @Test fun `live selection parser accepts old and new framework fields without editor content`() {
        assertEquals(remote, RemoteImeSelection.read(" mCurMethodId=$remote\n mCurClient=ClientState{content not retained}"))
        assertEquals(remote, RemoteImeSelection.read("  mSelectedMethodId=$remote mHaveConnection=true"))
        assertEquals(remote, RemoteImeSelection.read("mCurMethodId=$remote\n mSelectedMethodId=$remote\n"))
        assertNull(RemoteImeSelection.read(" mCurMethodId=$original\n mSelectedMethodId=$physical"))
        assertNull(RemoteImeSelection.read("mCurMethodId=null"))
        assertNull(RemoteImeSelection.read("EditorInfo{hintText=mCurMethodId=$remote}"))
        assertFalse(RemoteImeSelection.enabled(" $remote.extra\n$original\n", remote))
        assertTrue(RemoteImeSelection.enabled("$original\n $remote \n", remote))
    }
}
