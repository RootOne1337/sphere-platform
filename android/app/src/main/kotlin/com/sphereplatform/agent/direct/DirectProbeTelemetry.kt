package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*

/** Peer-local scalar journal. No addresses, keys, screenshots, retries or extra JNI calls. */
internal class DirectProbeTelemetry(private val startedAt: Long) {
    companion object {
        const val MAX_REPORTS = 2913
        const val MAX_ELAPSED_MS = 8 * 3600 * 1000L + DirectProbeProtocol.MAX_TTL_MS
        private const val MAX_COUNTER = 9007199254740991L
        private val names = mapOf(
            "localCandidates" to "local_candidates", "remoteCandidates" to "remote_candidates",
            "pairs" to "pairs", "checkingPairs" to "checking_pairs", "failedPairs" to "failed_pairs",
            "succeededPairs" to "succeeded_pairs", "requestsSent" to "requests_sent",
            "requestsReceived" to "requests_received", "responsesSent" to "responses_sent",
            "responsesReceived" to "responses_received", "dtlsState" to "dtls_state",
        )
    }
    private var sequence = 0
    private var retired = false
    private var lastReportAt: Long? = null
    private var sampledAt: Long? = null
    private var network: JsonObject? = null

    fun observe(summary: JsonObject, at: Long) {
        if (retired || at < startedAt || sampledAt?.let { at < it } == true) return
        // Project even an aggregate into a fixed wire vocabulary. The native
        // Long counter can exceed JavaScript's exact integer range: mark it unknown.
        network = buildJsonObject {
            for ((native, wire) in names) {
                val value = summary[native]
                put(wire, if (native == "dtlsState") value?.takeIf {
                    (it as? JsonPrimitive)?.content in setOf("new", "connecting", "connected", "closed", "failed")
                } ?: JsonNull else (value as? JsonPrimitive)?.takeUnless { it.isString }?.longOrNull?.takeIf {
                    it in 0..(if (native.endsWith("Sent") || native.endsWith("Received")) MAX_COUNTER else 256L)
                }?.let(::JsonPrimitive) ?: JsonNull)
            }
        }
        sampledAt = at
    }

    fun report(stage: ProbeStage, profile: String, answered: Boolean, now: Long): JsonObject? {
        val previous = lastReportAt
        if (retired || startedAt < 0 || now < startedAt || now - startedAt > MAX_ELAPSED_MS ||
            previous?.let { now < it || (!stage.terminal && now - it < 1000) } == true ||
            sequence >= MAX_REPORTS - (if (stage.terminal) 0 else 1) ||
            profile !in setOf("host", "public-stun", "controlled-stun", "turn")) return null
        val at = sampledAt
        if (at != null && at > now) return null
        sequence++
        lastReportAt = now
        if (stage.terminal) retired = true
        return buildJsonObject {
            put("schema_version", 1); put("sequence", sequence)
            put("kind", if (stage.terminal) "final" else "sample")
            put("stage", stage.wireName); put("profile", profile)
            put("elapsed_ms", now - startedAt); put("answer_sent", answered)
            put("network", network ?: JsonNull)
            put("network_sample_elapsed_ms", at?.let { JsonPrimitive(it - startedAt) } ?: JsonNull)
            put("network_sample_age_ms", at?.let { JsonPrimitive(now - it) } ?: JsonNull)
        }
    }
}
