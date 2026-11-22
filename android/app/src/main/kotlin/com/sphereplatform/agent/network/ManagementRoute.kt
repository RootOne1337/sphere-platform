package com.sphereplatform.agent.network

import okhttp3.CertificatePinner
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit

/** Operator-provisioned HTTP(S) base URL, never credentials or a redirect target. */
internal fun normalizeManagementUrl(value: String): String {
    val url = value.trim().toHttpUrlOrNull() ?: error("Invalid management URL")
    require(url.username.isEmpty() && url.password.isEmpty() && url.query == null && url.fragment == null) {
        "Invalid management URL"
    }
    return url.toString().trimEnd('/')
}

/** Reuses the pool/dispatcher; management credentials never follow HTTP redirects. */
internal fun OkHttpClient.forManagementRoute(url: String): OkHttpClient {
    val host = normalizeManagementUrl(url).toHttpUrlOrNull()!!.host
    val pins = certificatePinner.pins.map { it.toString() }.distinct()
    val builder = newBuilder().followRedirects(false).followSslRedirects(false)
    if (pins.isNotEmpty()) {
        // All configured installation pins also apply to its explicitly saved routes.
        builder.certificatePinner(CertificatePinner.Builder().add(host, *pins.toTypedArray()).build())
    }
    return builder.build()
}

/**
 * Management traffic already has server JSON ping/pong and a client watchdog.
 * A remote transport that fails to relay RFC 6455 control pong must not kill an
 * otherwise authenticated session after OkHttp's short ping interval. Keep the
 * base HTTP client unchanged; only the management WebSocket omits control pings.
 */
internal fun OkHttpClient.forManagementWebSocket(url: String): OkHttpClient =
    forManagementRoute(url).newBuilder().pingInterval(0, TimeUnit.MILLISECONDS).build()
