package com.sphereplatform.agent.vpn

import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE)
class AppScopedConfigPreparationTest {
    private val key = "AQIDBAUGBwgJCgsMDQ4PEBESExQVFhcYGRobHB0eHyA="
    private val text = """[Interface]
        |PrivateKey = $key
        |Address = 10.100.0.2/32
        |DNS = 1.1.1.1
        |MTU = 1280
        |[Peer]
        |PublicKey = $key
        |Endpoint = deliberately-unresolvable.invalid:51820
        |AllowedIPs = 0.0.0.0/0
        |PersistentKeepalive = 25
    """.trimMargin()
    private val apps = ResolvedAppSelection(listOf("org.example.game"), setOf(10002), "block")
    private val awg = "Jc = 4\nJmin = 40\nJmax = 70\nS1 = 20\nS2 = 30\nH1 = 1\nH2 = 2\nH3 = 3\nH4 = 4\n"
    private fun prepare(value: String = text, protocol: String = "wireguard", version: String = "1", selected: ResolvedAppSelection = apps) = AppScopedConfigPreparation.prepare(value, protocol, version, selected)
    private fun denied(reason: String, block: () -> Unit) {
        try { block(); fail("Config was accepted") } catch (error: VpnPreparationException) {
            assertEquals(reason, error.reason); assertNull(error.cause); assertFalse(error.toString().contains(key))
        }
    }
    @Test fun `SDK parser validates without resolving endpoint or exposing config`() {
        val prepared = prepare()
        assertEquals("deliberately-unresolvable.invalid", prepared.nativeConfig.peers.single().endpoint.get().host)
        assertEquals("PreparedAppScopedConfig([redacted])", prepared.toString())
    }
    @Test fun `supported protocol versions pass SDK syntax but never execute`() {
        for (version in listOf("1", "1.5", "2", "3.1")) {
            val prepared = prepare(text.replace("[Peer]", awg + "[Peer]"), "amneziawg", version)
            assertEquals(1, prepared.nativeConfig.peers.size)
        }
        denied("vpn_protocol_version_unsupported") { prepare(protocol = "wireguard", version = "3.1") }
    }
    @Test fun `AWG31 ranges CPS and header protection survive the SDK conversion`() {
        val fields = awg.replace("H1 = 1", "H1 = 10-19").replace("S1 = 20", "S1 = 12").replace("S2 = 30", "S2 = 12") +
            "S3 = 12\nS4 = 12\nHeaderProtectionKey = $key\nContentPaddingAddition = 0-32\nI1 = <b 0xaabb><rc 8><t><r 20>\nRandomTrailers = on\nDisableCookies = off\n"
        val config = prepare(text.replace("[Peer]", fields + "[Peer]"), "amneziawg", "3.1").nativeConfig.`interface`.toAwgUserspaceString()
        for (expected in listOf("h1=10-19\n", "content_padding_addition=0-32\n", "i1=<b 0xaabb><rc 8><t><r 20>\n", "random_trailers=1\n", "disable_cookies=0\n", "header_protection_key=010203040506")) assertTrue(config.contains(expected))
    }
    @Test fun `embedded application routing and hooks cannot override selected policy`() {
        for (field in listOf("IncludedApplications = org.example.other", "ExcludedApplications = com.sphereplatform.agent", "PostUp = secret-command", "Table = off", "FwMark = 10")) {
            denied("vpn_config_field_forbidden") { prepare(text.replace("[Peer]", "$field\n[Peer]")) }
        }
    }
    @Test fun `duplicate sections fields and missing AWG cannot silently downgrade`() {
        denied("vpn_config_duplicate_field") { prepare(text.replace("MTU = 1280", "MTU = 1280\nMTU = 1400")) }
        denied("vpn_config_sections_invalid") { prepare(text + "\n[Peer]\nPublicKey = $key") }
        denied("vpn_awg_parameters_required") { prepare(protocol = "amneziawg", version = "3.1") }
    }
    @Test fun `IPv6 address route and DNS cannot override block mode`() {
        for (value in listOf(text.replace("DNS = 1.1.1.1", "DNS = 2606:4700:4700::1111"), text.replace("10.100.0.2/32", "10.100.0.2/32, fd00::2/128"), text.replace("0.0.0.0/0", "0.0.0.0/0, ::/0"))) {
            denied("vpn_ipv6_policy_conflict") { prepare(value) }
        }
        val dual = text.replace("10.100.0.2/32", "10.100.0.2/32, fd00::2/128").replace("0.0.0.0/0", "0.0.0.0/0, ::/0")
        assertEquals(1, prepare(dual, selected = ResolvedAppSelection(apps.packages, apps.uids, "tunnel")).nativeConfig.peers.size)
    }
    @Test fun `size controls zero keys and SDK errors are sanitized`() {
        denied("vpn_config_bounds_invalid") { prepare("x".repeat(65537)) }
        denied("vpn_config_bounds_invalid") { prepare(text + "\n\u0000") }
        denied("vpn_zero_key_forbidden") { prepare(text.replace(key, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=")) }
        denied("vpn_sdk_config_invalid") { prepare(text.replace(key, "SECRET-INVALID-KEY")) }
    }
    @Test fun `selected IPv4 and IPv6 defaults must be explicit`() {
        denied("vpn_ipv4_default_route_required") { prepare(text.replace("0.0.0.0/0", "192.0.2.0/24")) }
        denied("vpn_ipv6_default_route_required") { prepare(selected = ResolvedAppSelection(apps.packages, apps.uids, "tunnel")) }
    }
}
