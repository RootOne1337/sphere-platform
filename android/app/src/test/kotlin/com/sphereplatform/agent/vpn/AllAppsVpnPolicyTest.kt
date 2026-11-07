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
class AllAppsVpnPolicyTest {
    @get:Rule val temporary = TemporaryFolder()
    private val own = "com.sphereplatform.agent.pilot.debug"
    private fun source(siblings: Set<String>? = setOf(own)) = object : AppIdentitySource {
        override fun uid(packageName: String) = if (packageName == own) 10060 else null
        override fun packagesForUid(uid: Int) = siblings
    }
    private fun policy() = AppTrafficSelection(emptyList(), mode = "all_apps_except_control", killSwitch = "all_apps_except_control")

    @Test fun `wide scope resolves without enumerating or freezing installed application uids`() {
        val resolved = AppTrafficSelectionResolver.resolve(policy(), own, 10060, source(), 28)
        assertEquals("all_apps_except_control", resolved.mode)
        assertEquals(own, resolved.excludedPackage)
        assertTrue(resolved.packages.isEmpty()); assertTrue(resolved.uids.isEmpty())
        val ranges = allAppUidRanges(10060)
        fun covered(uid: Int) = ranges.any { uid in it.first..it.last }
        // Includes a future app, shared application UID, and isolated process;
        // not the control UID, system network helpers, or another Android user.
        for (uid in listOf(10000, 10061, 19999, 55000, 99000, 99999)) assertTrue(covered(uid))
        for (uid in listOf(0, 1000, 9999, 10060, 100000, 110060)) assertFalse(covered(uid))
        assertEquals(listOf(GuardUidRange(10001, 99999)), allAppUidRanges(10000))
        assertFalse(allAppUidRanges(19999).any { 19999 in it.first..it.last })
    }

    @Test fun `unknown shared control identity and unsupported platforms are rejected before kernel changes`() {
        for (api in listOf(25, 33, 34, 36)) {
            try { AppTrafficSelectionResolver.resolve(policy(), own, 10060, source(), api); fail() }
            catch (error: VpnPreparationException) { assertEquals("vpn_all_apps_platform_unsupported", error.reason) }
        }
        for (siblings in listOf(null, emptySet(), setOf(own, "org.example.shared"))) {
            try { AppTrafficSelectionResolver.resolve(policy(), own, 10060, source(siblings), 28); fail() }
            catch (error: VpnPreparationException) { assertEquals("vpn_control_shared_uid_unverified", error.reason) }
        }
        try {
            AppTrafficSelectionResolver.resolve(AppTrafficSelection(listOf("org.example.game"), mode = "all_apps_except_control",
                killSwitch = "all_apps_except_control"), own, 10060, source(), 28); fail()
        } catch (error: VpnPreparationException) { assertEquals("vpn_all_apps_packages_forbidden", error.reason) }
    }

    @Test fun `range journal retains exact scope through allow pause and explicit release`() = runBlocking {
        val journal = UidGuardJournal(File(temporary.root, "guard.json"))
        val scripts = mutableListOf<String>()
        val guard = SelectedUidGuard(journal, GuardRootExecutor { script, _ -> scripts.add(script) })
        val id = UUID.randomUUID()
        val apps = AppTrafficSelectionResolver.resolve(policy(), own, 10060, source(), 28)
        assertEquals(5, guard.block(id, apps, 10060).planVersion)
        guard.allow(id, "tun1", 34)
        val paused = guard.pause(id)
        assertEquals("BLOCKED", paused.phase)
        assertEquals(allAppUidRanges(10060), UidGuardJournal(File(temporary.root, "guard.json")).read()!!.uidRanges)
        assertFalse(scripts.last().contains("rule del"))
        guard.release(id)
        assertEquals("RELEASED", journal.read()!!.phase)
        scripts.forEach {
            assertTrue(it.contains("iptables")); assertTrue(it.contains("ip6tables"))
            assertTrue(it.contains("uidrange 10000-10059")); assertTrue(it.contains("uidrange 10061-99999"))
            assertFalse(it.contains("--uid-owner 10060")); assertFalse(it.contains("mangle"))
            assertFalse(it.contains("-P ")); assertFalse(it.contains("FORWARD"))
        }
        assertTrue(scripts.last().contains("!= '34'"))
    }

    @Test fun `journal cannot widen a range include control or reinterpret a version four guard`() {
        val valid = UidGuardRecord(UUID.randomUUID().toString(), emptyList(), 10060, "INTENT", planVersion = 5, uidRanges = allAppUidRanges(10060))
        for (bad in listOf(valid.copy(uidRanges = listOf(GuardUidRange(0, 99999))),
            valid.copy(uidRanges = listOf(GuardUidRange(10000, 99999))),
            valid.copy(selectedUids = listOf(10061)), valid.copy(planVersion = 4),
            valid.copy(ownerUid = 110060), valid.copy(uidRanges = valid.uidRanges.reversed()))) {
            try { UidGuardPlan.from(bad); fail("Unverified range accepted") } catch (_: IllegalArgumentException) { }
        }
    }

    @Test fun `wire schema cannot silently upgrade v1 into the wider scope`() {
        val id = UUID.randomUUID()
        val raw = """{"schema_version":2,"request_id":"$id","session_id":"$id","action":"apply","profile_revision_id":"$id","profile":{"protocol":"wireguard","protocol_version":"1","config_text":"private-sentinel","traffic_policy":{"mode":"all_apps_except_control","control_plane":"bypass","kill_switch":"all_apps_except_control","ipv6":"block"}}}"""
        assertEquals("apply", AppVpnCommand.parse(raw).action)
        for (bad in listOf(raw.replace("\"schema_version\":2", "\"schema_version\":1"),
            raw.replace("\"control_plane\":\"bypass\"", "\"included_packages\":[],\"control_plane\":\"bypass\""),
            raw.replace("\"kill_switch\":\"all_apps_except_control\"", "\"kill_switch\":\"selected_apps\""))) {
            try { AppVpnCommand.parse(bad); fail("Scope downgrade accepted") }
            catch (error: VpnPreparationException) { assertEquals("vpn_ipc_request_invalid", error.reason); assertFalse(error.message!!.contains("private-sentinel")) }
        }
    }
}
