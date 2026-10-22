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
class SelectedUidGuardTest {
    @get:Rule val temporary = TemporaryFolder()
    private val operation = UUID.fromString("5ac563ca-6408-4b83-a1ab-9c158d090274")
    private val apps = ResolvedAppSelection(listOf("org.example.game"), setOf(10002, 10003), "block")
    private val file get() = File(temporary.root, "guard.json")
    private fun denied(reason: String, block: suspend () -> Unit) = runBlocking {
        try { block(); fail("Mutation was accepted") } catch (error: VpnPreparationException) { assertEquals(reason, error.reason) }
    }
    @Test fun `write ahead intent is durable before the root process starts`() = runBlocking {
        val journal = UidGuardJournal(file)
        var roots = 0
        val guard = SelectedUidGuard(journal, GuardRootExecutor { script, marker ->
            assertEquals("INTENT", UidGuardJournal(file).read()!!.phase)
            assertTrue(script.contains("--uid-owner 10002")); assertFalse(script.contains("--uid-owner 10001"))
            assertTrue(script.contains(marker)); roots++
        })
        val receipt = guard.block(operation, apps, 10001)
        assertEquals("BLOCKED", receipt.phase); assertEquals(1, roots)
        denied("vpn_guard_reconciliation_required") { guard.block(operation, apps, 10001) }
        assertEquals(1, roots)
    }
    @Test fun `a timeout remains unknown after reconstructing the controller`() = runBlocking {
        val journal = UidGuardJournal(file)
        val guard = SelectedUidGuard(journal, GuardRootExecutor { _, _ -> throw java.io.IOException("timeout") })
        denied("vpn_guard_outcome_unknown") { guard.block(operation, apps, 10001) }
        assertEquals("UNKNOWN", UidGuardJournal(file).read()!!.phase)
        val restarted = SelectedUidGuard(UidGuardJournal(file), GuardRootExecutor { _, _ -> fail("Uncertain mutation was retried") })
        denied("vpn_guard_reconciliation_required") { restarted.block(UUID.randomUUID(), apps, 10001) }
        denied("vpn_guard_reconciliation_required") { restarted.release(operation) }
    }
    @Test fun `allow is bound to operation interface index and isolated blackhole table`() = runBlocking {
        val journal = UidGuardJournal(file)
        val scripts = mutableListOf<String>()
        val guard = SelectedUidGuard(journal, GuardRootExecutor { script, _ -> scripts.add(script) })
        guard.block(operation, apps, 10001)
        denied("vpn_guard_reconciliation_required") { guard.allow(UUID.randomUUID(), "tun0", 7) }
        val allowed = guard.allow(operation, "tun0", 7)
        assertEquals("ALLOWED", allowed.phase)
        assertTrue(scripts.last().contains("/sys/class/net/tun0/ifindex"))
        assertTrue(scripts.last().contains("route add default dev tun0 table"))
        assertTrue(scripts.last().contains("-o tun0 -j RETURN"))
        assertTrue(scripts.last().contains("'^default dev tun0"))
        assertFalse(scripts.last().contains("--mark"))
        assertTrue(scripts.first().contains("route add blackhole default table"))
        assertEquals(7, allowed.interfaceIndex)
        val closed = guard.release(operation)
        assertEquals("RELEASED", closed.phase)
        assertTrue(scripts.last().contains("!= '7'"))
        denied("vpn_guard_operation_id_reused") { guard.block(operation, apps, 10001) }
    }
    @Test fun `guard cannot target its control uid or accept shell input`() {
        val record = UidGuardRecord(operation.toString(), listOf(10002), 10001, "ALLOWING", "tun0", 7)
        for (bad in listOf(record.copy(selectedUids = listOf(10001)), record.copy(selectedUids = emptyList()),
            record.copy(interfaceName = "tun0; reboot"), record.copy(operationId = "$(id)"), record.copy(interfaceIndex = -1),
            record.copy(selectedUids = listOf(1000)), record.copy(phase = "anything"))) {
            try { UidGuardPlan.from(bad); fail("Unvalidated shell data accepted") } catch (_: IllegalArgumentException) { }
        }
        val script = UidGuardPlan.from(record.copy(phase = "INTENT", interfaceName = null, interfaceIndex = null)).block()
        assertFalse(script.contains("-P ")); assertFalse(script.contains("FORWARD")); assertFalse(script.contains("-t nat"))
        assertFalse(script.contains("|| true"))
    }
    @Test fun `pause closes tunnel permission while retaining UID blackhole until explicit release`() = runBlocking {
        val scripts = mutableListOf<String>()
        val journal = UidGuardJournal(file)
        val guard = SelectedUidGuard(journal, GuardRootExecutor { script, _ -> scripts.add(script) })
        guard.block(operation, apps, 10001)
        guard.allow(operation, "tun8", 31)
        val paused = guard.pause(operation)
        assertEquals("BLOCKED", paused.phase); assertFalse(paused.allowRules)
        assertEquals(31, paused.interfaceIndex)
        assertTrue(scripts.last().contains("-D ${UidGuardPlan.from(paused).chain} -o tun8"))
        assertFalse(scripts.last().contains("rule del"))
        assertFalse(scripts.last().contains("-D OUTPUT"))
        guard.release(operation)
        assertTrue(scripts.last().contains("uidrange 10002-10002"))
        assertTrue(scripts.last().contains("uidrange 10003-10003"))
        assertEquals("RELEASED", journal.read()!!.phase)
    }
    @Test fun `unreadable or oversized journals cannot become an empty safe state`() {
        file.writeText("not-json")
        denied("vpn_guard_journal_unreadable") { UidGuardJournal(file).read() }
        file.writeText("x".repeat(16385))
        denied("vpn_guard_journal_unreadable") { UidGuardJournal(file).read() }
    }
    @Test fun `new guard never alters any Android packet marks in any lifecycle stage`() {
        val plan = UidGuardPlan.from(UidGuardRecord(operation.toString(), listOf(10002), 10001, "INTENT"))
        assertEquals(4, plan.record.planVersion)
        val record = plan.record.copy(interfaceName = "tun0", interfaceIndex = 7, allowRules = true)
        for (ipv6 in listOf("block", "tunnel")) {
            val selected = record.copy(ipv6 = ipv6)
            val scripts = listOf(plan.block(),
                UidGuardPlan.from(selected.copy(phase = "ALLOWING")).allow(),
                UidGuardPlan.from(selected.copy(phase = "ALLOWED")).verify(true),
                UidGuardPlan.from(selected.copy(phase = "BLOCKING")).pause(),
                UidGuardPlan.from(selected.copy(phase = "RELEASING")).release())
            scripts.forEach { script ->
                assertFalse(script.contains("MARK")); assertFalse(script.contains("--mark"))
                assertFalse(script.contains("mangle")); assertFalse(script.contains("SPV2M_"))
                assertFalse(script.contains("fwmark")); assertFalse(script.contains("0xffffffff"))
                assertTrue(script.contains("uidrange 10002-10002"))
            }
        }
    }
    @Test fun `version three journals are released with their original exact mark rules only`() = runBlocking {
        val record = UidGuardRecord(operation.toString(), listOf(10002), 10001, "ALLOWED", "tun0", 7, planVersion = 3)
        val journal = UidGuardJournal(file); journal.write(record)
        val scripts = mutableListOf<String>()
        val guard = SelectedUidGuard(journal, GuardRootExecutor { script, _ -> scripts.add(script) })
        val released = guard.release(operation)
        assertEquals(3, released.planVersion); assertEquals("RELEASED", released.phase)
        val script = scripts.single()
        assertTrue(script.contains("-C ${UidGuardPlan.from(record).chain} -o tun0 -m mark --mark"))
        assertTrue(script.contains("-t mangle -D OUTPUT -m owner --uid-owner 10002"))
        assertTrue(script.contains("--set-xmark ${UidGuardPlan.from(record).mark}/0x1fe00000"))
        assertTrue(script.contains("!= '7'"))
        guard.block(UUID.randomUUID(), apps, 10001)
        assertEquals(4, journal.read()!!.planVersion)
        assertFalse(scripts.last().contains("mangle"))
    }
    @Test fun `version three plans cannot create or reopen a tunnel`() {
        val legacy = UidGuardRecord(operation.toString(), listOf(10002), 10001, "INTENT", planVersion = 3)
        val actions = listOf<() -> Unit>(
            { UidGuardPlan.from(legacy).block() },
            { UidGuardPlan.from(legacy.copy(phase = "ALLOWING", interfaceName = "tun0", interfaceIndex = 7, allowRules = true)).allow() },
            { UidGuardPlan.from(legacy.copy(phase = "BLOCKING", interfaceName = "tun0", interfaceIndex = 7, allowRules = true)).pause() },
        )
        actions.forEach { action ->
            try { action(); fail("Legacy activation accepted") }
            catch (error: IllegalArgumentException) { assertEquals("vpn_legacy_guard_cleanup_only", error.message) }
        }
    }
    @Test fun `older journal plans cannot be silently reinterpreted for cleanup`() {
        file.writeText("""{"operationId":"$operation","selectedUids":[10002],"ownerUid":10001,"phase":"BLOCKED"}""")
        denied("vpn_guard_journal_unreadable") { UidGuardJournal(file).read() }
        try { UidGuardPlan.from(UidGuardRecord(operation.toString(), listOf(10002), 10001, "BLOCKED", planVersion = 2)); fail() }
        catch (_: IllegalArgumentException) { }
    }
}
