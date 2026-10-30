package com.sphereplatform.agent.vpn

import org.junit.Assert.*
import org.junit.Test

class AppTrafficSelectionTest {
    private val own = "com.sphereplatform.agent.debug"
    private val game = "org.example.game"
    private fun source(rows: Map<String, Int> = mapOf(own to 10001, game to 10002)) = object : AppIdentitySource {
        override fun uid(packageName: String) = rows[packageName]
        override fun packagesForUid(uid: Int) = rows.filterValues { it == uid }.keys
    }
    private fun resolve(policy: AppTrafficSelection = AppTrafficSelection(listOf(game)), rows: Map<String, Int> = mapOf(own to 10001, game to 10002)) =
        AppTrafficSelectionResolver.resolve(policy, own, 10001, source(rows))
    private fun denied(reason: String, block: () -> Unit) {
        try { block(); fail("Policy was accepted") } catch (error: VpnPreparationException) { assertEquals(reason, error.reason); assertNull(error.cause) }
    }

    @Test fun `selected app never expands into all applications`() {
        val result = resolve()
        assertEquals(listOf(game), result.packages)
        assertEquals(setOf(10002), result.uids)
        denied("vpn_selected_apps_invalid") { resolve(AppTrafficSelection(emptyList())) }
        denied("vpn_selected_application_unavailable") { resolve(rows = mapOf(own to 10001)) }
    }
    @Test fun `Sphere package and all variants are protected even with a different uid`() {
        for (pkg in listOf("com.sphereplatform.agent", own, "com.sphereplatform.agent.dev", "com.sphereplatform.agent.enterprise")) {
            denied("vpn_control_application_forbidden") { resolve(AppTrafficSelection(listOf(pkg)), mapOf(own to 10001, pkg to 10001)) }
        }
    }
    @Test fun `another package sharing Sphere uid is forbidden`() {
        denied("vpn_control_uid_forbidden") { resolve(rows = mapOf(own to 10001, game to 10001)) }
    }
    @Test fun `shared uid cannot implicitly include an unselected app`() {
        val rows = mapOf(own to 10001, game to 10002, "org.example.other" to 10002)
        denied("vpn_shared_uid_ambiguous") { resolve(rows = rows) }
        assertEquals(setOf(10002), resolve(AppTrafficSelection(listOf(game, "org.example.other")), rows).uids)
    }
    @Test fun `unverified package snapshots are not accepted`() {
        val incomplete = object : AppIdentitySource {
            override fun uid(packageName: String) = if (packageName == own) 10001 else 10002
            override fun packagesForUid(uid: Int): Set<String>? = null
        }
        denied("vpn_shared_uid_unverified") { AppTrafficSelectionResolver.resolve(AppTrafficSelection(listOf(game)), own, 10001, incomplete) }
        denied("vpn_control_uid_unverified") { resolve(rows = mapOf(own to 10003, game to 10002)) }
    }
    @Test fun `system uid and invalid app lists are rejected`() {
        denied("vpn_system_uid_forbidden") { resolve(rows = mapOf(own to 10001, game to 1000)) }
        for (packages in listOf(emptyList(), listOf(game, game), listOf("org.example.game;sh"), List(65) { "org.example.app$it" })) {
            denied("vpn_selected_apps_invalid") { resolve(AppTrafficSelection(packages)) }
        }
    }
    @Test fun `policy modes cannot weaken isolation`() {
        for (p in listOf(AppTrafficSelection(listOf(game), mode = "all"), AppTrafficSelection(listOf(game), controlPlane = "vpn"),
            AppTrafficSelection(listOf(game), killSwitch = "global"), AppTrafficSelection(listOf(game), ipv6 = "bypass"))) {
            denied("vpn_traffic_policy_unsupported") { resolve(p) }
        }
    }
    @Test fun `callers cannot mutate prepared selection through original lists`() {
        val original = mutableListOf(game)
        val selection = AppTrafficSelection(original)
        original.clear()
        assertEquals(listOf(game), resolve(selection).packages)
    }
}
