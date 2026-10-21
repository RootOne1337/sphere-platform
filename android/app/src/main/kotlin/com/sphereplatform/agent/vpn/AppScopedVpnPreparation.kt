package com.sphereplatform.agent.vpn

import android.content.pm.PackageManager
import java.io.BufferedReader
import java.io.StringReader
import java.net.Inet4Address
import java.net.Inet6Address
import java.util.Collections
import java.util.Locale
import org.amnezia.awg.config.Config

/** Stable reason only: upstream parser exceptions may contain private config. */
internal class VpnPreparationException(val reason: String) : Exception(reason)

internal class AppTrafficSelection(
    includedPackages: List<String>,
    val mode: String = "selected_apps",
    val controlPlane: String = "bypass",
    val killSwitch: String = "selected_apps",
    val ipv6: String = "block",
) {
    val packages: List<String> = Collections.unmodifiableList(includedPackages.toList())
}

internal interface AppIdentitySource {
    fun uid(packageName: String): Int?
    fun packagesForUid(uid: Int): Set<String>?
}

internal class AndroidAppIdentitySource(private val manager: PackageManager) : AppIdentitySource {
    override fun uid(packageName: String): Int? = try {
        manager.getApplicationInfo(packageName, 0).uid
    } catch (_: PackageManager.NameNotFoundException) { null }
      catch (_: SecurityException) { null }

    override fun packagesForUid(uid: Int): Set<String>? = try {
        manager.getPackagesForUid(uid)?.toSet()
    } catch (_: SecurityException) { null }
}

internal class ResolvedAppSelection(packages: List<String>, uids: Set<Int>, val ipv6: String) {
    val packages: List<String> = Collections.unmodifiableList(packages.toList())
    val uids: Set<Int> = Collections.unmodifiableSet(uids.toSet())
}

/** Point-in-time package snapshot, to be rechecked immediately before establish.
 * Missing/hidden apps and shared UID ambiguity are errors, never skipped entries.
 */
internal object AppTrafficSelectionResolver {
    private const val SPHERE = "com.sphereplatform.agent"
    private val packageId = Regex("[A-Za-z][A-Za-z0-9_]*(?:\\.[A-Za-z][A-Za-z0-9_]*)+")

    fun resolve(policy: AppTrafficSelection, ownPackage: String, ownUid: Int, source: AppIdentitySource): ResolvedAppSelection {
        fun fail(reason: String): Nothing = throw VpnPreparationException(reason)
        if (policy.mode != "selected_apps" || policy.controlPlane != "bypass" || policy.killSwitch != "selected_apps"
            || policy.ipv6 !in setOf("block", "tunnel")) fail("vpn_traffic_policy_unsupported")
        if (policy.packages.size !in 1..64 || policy.packages.toSet().size != policy.packages.size) fail("vpn_selected_apps_invalid")
        if (ownUid < 10000 || source.uid(ownPackage) != ownUid) fail("vpn_control_uid_unverified")
        val selected = policy.packages.toSet()
        val uids = linkedSetOf<Int>()
        for (pkg in selected) {
            if (pkg.length > 255 || !packageId.matches(pkg)) fail("vpn_selected_apps_invalid")
            if (pkg == ownPackage || pkg == SPHERE || pkg.startsWith("$SPHERE.")) fail("vpn_control_application_forbidden")
            val uid = source.uid(pkg) ?: fail("vpn_selected_application_unavailable")
            if (uid == ownUid) fail("vpn_control_uid_forbidden")
            // System/shared framework UIDs are not eligible for application egress.
            if (uid % 100000 < 10000) fail("vpn_system_uid_forbidden")
            val siblings = source.packagesForUid(uid) ?: fail("vpn_shared_uid_unverified")
            if (siblings.isEmpty() || pkg !in siblings || !selected.containsAll(siblings)) fail("vpn_shared_uid_ambiguous")
            if (siblings.any { it == ownPackage || it == SPHERE || it.startsWith("$SPHERE.") }) fail("vpn_control_uid_forbidden")
            uids.add(uid)
        }
        return ResolvedAppSelection(policy.packages, uids, policy.ipv6)
    }
}

/** Holds a secret-bearing upstream Config; no generated data-class toString. */
internal class PreparedAppScopedConfig internal constructor(internal val nativeConfig: Config, val apps: ResolvedAppSelection) {
    override fun toString() = "PreparedAppScopedConfig([redacted])"
}

/** Upstream SDK syntax validation is read-only and does NOT resolve endpoint DNS.
 * No network, native load, TUN, root command or Android Builder is used here.
 */
internal object AppScopedConfigPreparation {
    private val baseInterface = setOf("privatekey", "address", "dns", "mtu", "listenport")
    private val peerFields = setOf("publickey", "presharedkey", "allowedips", "endpoint", "persistentkeepalive")
    private val awg1 = setOf("jc", "jmin", "jmax", "s1", "s2", "h1", "h2", "h3", "h4")
    private val cps = setOf("i1", "i2", "i3", "i4", "i5")
    private val awg2 = setOf("s3", "s4")
    private val awg31 = setOf("headerprotectionkey", "contentpaddingaddition", "rekeyaftertime", "rekeytimeout", "rejectaftertime", "keepalivetimeout", "maxhandshakeattempts", "randomtrailers", "disablecookies")

    fun prepare(text: String, protocol: String, version: String, apps: ResolvedAppSelection): PreparedAppScopedConfig {
        fun fail(reason: String): Nothing = throw VpnPreparationException(reason)
        if (protocol !in setOf("wireguard", "amneziawg") || version !in setOf("1", "1.5", "2", "3.1")
            || protocol == "wireguard" && version != "1") fail("vpn_protocol_version_unsupported")
        if (text.isEmpty() || text.length > 65536 || text.toByteArray(Charsets.UTF_8).size > 65536 || '\u0000' in text) fail("vpn_config_bounds_invalid")
        val allowed = baseInterface + if (protocol == "wireguard") emptySet() else awg1 +
            (if (version != "1") cps else emptySet()) + (if (version in setOf("2", "3.1")) awg2 else emptySet()) +
            (if (version == "3.1") awg31 else emptySet())
        var section = ""
        val seenSections = mutableSetOf<String>()
        val keys = mutableMapOf<String, MutableSet<String>>()
        text.lineSequence().forEach { raw ->
            if (raw.length > 8192 || raw.any { it.code < 32 && it != '\t' }) fail("vpn_config_bounds_invalid")
            val line = raw.substringBefore('#').trim()
            if (line.isEmpty()) return@forEach
            if (line.startsWith("[")) {
                section = line.lowercase(Locale.ROOT)
                if (section !in setOf("[interface]", "[peer]") || !seenSections.add(section)) fail("vpn_config_sections_invalid")
            } else {
                if ('=' !in line || section.isEmpty()) fail("vpn_config_syntax_invalid")
                val key = line.substringBefore('=').trim().lowercase(Locale.ROOT)
                if (key !in (if (section == "[interface]") allowed else peerFields)) fail("vpn_config_field_forbidden")
                if (!keys.getOrPut(section) { mutableSetOf() }.add(key)) fail("vpn_config_duplicate_field")
            }
        }
        if (seenSections != setOf("[interface]", "[peer]")) fail("vpn_config_sections_invalid")
        if (protocol == "amneziawg" && !keys["[interface]"].orEmpty().containsAll(awg1)) fail("vpn_awg_parameters_required")
        val parsed = try { Config.parse(BufferedReader(StringReader(text))) }
            catch (_: Exception) { fail("vpn_sdk_config_invalid") }
        if (parsed.peers.size != 1 || parsed.peers.single().endpoint.isEmpty) fail("vpn_peer_invalid")
        val iface = parsed.`interface`
        if (!iface.keyPair.privateKey.bytes.any { it != 0.toByte() } || !parsed.peers.single().publicKey.bytes.any { it != 0.toByte() }
            || parsed.peers.single().preSharedKey.map { key -> !key.bytes.any { it != 0.toByte() } }.orElse(false)) fail("vpn_zero_key_forbidden")
        if (iface.includedApplications.isNotEmpty() || iface.excludedApplications.isNotEmpty()) fail("vpn_embedded_app_policy_forbidden")
        if (iface.addresses.none { it.address is Inet4Address }) fail("vpn_ipv4_address_required")
        val routes = parsed.peers.single().allowedIps
        if (routes.none { it.address is Inet4Address && it.mask == 0 }) fail("vpn_ipv4_default_route_required")
        val hasV6Address = iface.addresses.any { it.address is Inet6Address }
        val hasV6Route = routes.any { it.address is Inet6Address }
        if (apps.ipv6 == "block" && (hasV6Address || hasV6Route || iface.dnsServers.any { it is Inet6Address })) fail("vpn_ipv6_policy_conflict")
        if (apps.ipv6 == "tunnel" && (!hasV6Address || routes.none { it.address is Inet6Address && it.mask == 0 })) fail("vpn_ipv6_default_route_required")
        return PreparedAppScopedConfig(parsed, apps)
    }
}
