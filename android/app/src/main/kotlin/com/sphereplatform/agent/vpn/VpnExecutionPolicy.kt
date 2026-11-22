package com.sphereplatform.agent.vpn

/** Compile-time provider capability, never taken from a remote command payload.
 *
 * The legacy wg-quick backend changes device routes and the global iptables
 * switch cannot isolate the agent's UID, native WebRTC or future LAN peers.
 * Keep it unavailable until an app-scoped provider passes on-device acceptance.
 */
internal object VpnExecutionPolicy {
    const val BLOCK_REASON = "vpn_app_scoped_provider_unavailable"

    fun requireAppScopedProvider(): Nothing = throw VpnException(BLOCK_REASON)
}
