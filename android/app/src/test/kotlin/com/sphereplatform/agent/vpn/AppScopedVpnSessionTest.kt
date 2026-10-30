package com.sphereplatform.agent.vpn

import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class AppScopedVpnSessionTest {
    @get:Rule val temporary = TemporaryFolder()
    private val calls = mutableListOf<String>()
    private var protectOk = true
    private var stopOk = true
    private var handshake = 0L
    private val id = UUID.randomUUID()
    private val key = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="
    private fun prepared() = AppScopedConfigPreparation.prepare("""[Interface]
        |PrivateKey = $key
        |Address = 10.213.0.2/32
        |DNS = 10.213.0.1
        |[Peer]
        |PublicKey = $key
        |Endpoint = 127.0.0.1:38213
        |AllowedIPs = 0.0.0.0/0
    """.trimMargin(), "wireguard", "1", ResolvedAppSelection(listOf("org.example.game"), setOf(10002), "block"))
    private fun runtime(failGuard: Boolean = false): AppScopedVpnSession {
        val platform = object : ScopedTunPlatform {
            override val ownerUid = 10001
            override fun assertReady(config: PreparedAppScopedConfig) { calls.add("preflight") }
            override fun establish(config: PreparedAppScopedConfig): HeldAppTun {
                calls.add("establish")
                return object : HeldAppTun {
                    override val name = "tun0"; override val index = 7
                    override fun duplicateForNative(): Int { calls.add("duplicate"); return 42 }
                    override fun close() { calls.add("close-tun") }
                }
            }
            override fun protect(fd: Int): Boolean { calls.add("protect:$fd"); return protectOk }
        }
        val engine = object : ScopedAwgEngine {
            override fun load(): String { calls.add("native-load"); return "pinned-test" }
            override fun start(name: String, fd: Int, config: String): Int {
                calls.add("native-start"); assertEquals(42, fd); assertTrue(config.contains("endpoint=127.0.0.1:38213")); return 9
            }
            override fun sockets(handle: Int) = intArrayOf(20, 21)
            override fun stats(handle: Int) = AwgTransportStats(handshake, 1, 2)
            override fun stop(handle: Int) { calls.add("native-stop"); if (!stopOk) throw IllegalStateException() }
        }
        val journal = UidGuardJournal(File(temporary.root, "guard.json"))
        return AppScopedVpnSession(platform, engine, SelectedUidGuard(journal, GuardRootExecutor { _, marker ->
            calls.add(marker.substringAfter(id.toString() + "_"))
            if (failGuard) throw java.io.IOException()
        }))
    }
    private fun denied(reason: String, action: suspend () -> Unit) = runBlocking {
        try { action(); fail("Operation was accepted") } catch (failure: VpnPreparationException) { assertEquals(reason, failure.reason) }
    }
    @Test fun `guard and protected sockets precede traffic admission and a handshake is separate`() = runBlocking {
        val session = runtime()
        assertEquals("TRANSPORT_READY", session.connect(id, prepared()).phase)
        assertTrue(calls.indexOf("INTENT") < calls.indexOf("establish"))
        assertTrue(calls.indexOf("protect:21") < calls.indexOf("ALLOWING"))
        assertEquals("AWAITING_HANDSHAKE", session.observe().phase)
        handshake = 123
        assertEquals("HANDSHAKE_CONFIRMED", session.observe().phase)
        assertEquals("DISCONNECTED_CONFIRMED", session.disconnect(id).phase)
        assertTrue(calls.indexOf("BLOCKING") < calls.indexOf("native-stop"))
        assertTrue(calls.indexOf("native-stop") < calls.indexOf("close-tun"))
        assertTrue(calls.indexOf("close-tun") < calls.indexOf("RELEASING"))
    }
    @Test fun `protection failure closes owned native state without admitting app traffic`() = runBlocking {
        protectOk = false
        val session = runtime()
        denied("vpn_start_failed_guard_held") { session.connect(id, prepared()) }
        assertFalse(calls.contains("ALLOWING")); assertTrue(calls.contains("native-stop")); assertTrue(calls.contains("close-tun"))
        val receipt = session.observe()
        assertEquals("FAILED_GUARD_HELD", receipt.phase)
        assertEquals("vpn_transport_protection_failed", receipt.reason)
        session.disconnect(id)
        Unit
    }
    @Test fun `uncertain guard cannot be advertised as held or establish a TUN`() = runBlocking {
        val session = runtime(failGuard = true)
        denied("vpn_start_failed_guard_unconfirmed") { session.connect(id, prepared()) }
        assertFalse(calls.contains("establish"))
        assertEquals("GUARD_UNCONFIRMED", session.observe().phase)
    }
    @Test fun `native stop failure cannot release traffic or report disconnected`() = runBlocking {
        val session = runtime(); session.connect(id, prepared()); stopOk = false
        denied("vpn_stop_unknown_guard_held") { session.disconnect(id) }
        assertFalse(calls.contains("RELEASING"))
        assertTrue(calls.contains("close-tun"))
    }
    @Test fun `a second operation cannot replace an existing live session`() = runBlocking {
        val session = runtime(); session.connect(id, prepared())
        denied("vpn_session_reconciliation_required") { session.connect(UUID.randomUUID(), prepared()) }
        denied("vpn_session_reconciliation_required") { session.disconnect(UUID.randomUUID()) }
        assertEquals(1, calls.count { it == "native-start" })
        session.disconnect(id)
        Unit
    }
    @Test fun `pause preserves the guard and resume protects fresh sockets before readmission`() = runBlocking {
        val session = runtime(); val config = prepared(); session.connect(id, config)
        calls.clear()
        assertEquals("PAUSED_GUARD_HELD", session.pause(id).phase)
        assertEquals("PAUSED_GUARD_HELD", session.observe().phase)
        assertEquals(listOf("BLOCKING", "native-stop", "close-tun"), calls)
        session.pause(id)
        assertEquals(3, calls.size)
        denied("vpn_session_reconciliation_required") { session.resume(id, prepared()) }
        assertEquals("TRANSPORT_READY", session.resume(id, config).phase)
        assertTrue(calls.lastIndexOf("protect:21") < calls.lastIndexOf("ALLOWING"))
        assertFalse(calls.contains("RELEASING")); assertFalse(calls.contains("INTENT"))
        assertEquals("DISCONNECTED_CONFIRMED", session.disconnect(id).phase)
    }
    @Test fun `unconfirmed pause never releases or permits resuming a live engine`() = runBlocking {
        val session = runtime(); val config = prepared(); session.connect(id, config); stopOk = false
        denied("vpn_pause_unknown_guard_held") { session.pause(id) }
        assertEquals("UNKNOWN_GUARD_HELD", session.observe().phase)
        denied("vpn_session_reconciliation_required") { session.resume(id, config) }
        assertFalse(calls.contains("RELEASING"))
        assertTrue(calls.contains("close-tun"))
    }
    @Test fun `rotation holds the original guard throughout replacement and allows only the same UID policy`() = runBlocking {
        val session = runtime(); session.connect(id, prepared())
        calls.clear()
        assertEquals("TRANSPORT_READY", session.rotate(id, prepared()).phase)
        assertEquals(1, calls.count { it == "BLOCKING" })
        assertEquals(1, calls.count { it == "ALLOWING" })
        assertTrue(calls.indexOf("close-tun") < calls.indexOf("native-start"))
        assertFalse(calls.contains("INTENT")); assertFalse(calls.contains("RELEASING"))
        val different = prepared().let { PreparedAppScopedConfig(it.nativeConfig,
            ResolvedAppSelection(listOf("org.example.other"), setOf(10004), "block")) }
        calls.clear()
        denied("vpn_rotation_policy_change_requires_disconnect") { session.rotate(id, different) }
        assertTrue(calls.isEmpty())
        session.disconnect(id)
        Unit
    }
}
