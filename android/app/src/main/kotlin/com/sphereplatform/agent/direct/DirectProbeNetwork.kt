package com.sphereplatform.agent.direct

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

/** Memory-only projection; summary output excludes identity, addresses and credentials. */
internal data class ProbeStatsRow(val type: String, val members: Map<String, Any?>, val id: String? = null)

internal object DirectProbeNetwork {
    const val MAX_ROWS = 256
    private val dtlsStates = setOf("new", "connecting", "connected", "closed", "failed")

    /** Memory-only identity/address comparison. Only the nullable result may be logged. */
    fun emulatorHostSelected(rows: List<ProbeStatsRow>, hints: List<String>): Boolean? {
        if (rows.size > MAX_ROWS || hints.isEmpty()) return null
        val transports = rows.filter { it.type == "transport" && it.members["dtlsState"] == "connected" }
        val selected = transports.mapNotNull { it.members["selectedCandidatePairId"] as? String }.distinct().singleOrNull()
            ?: return null
        val pair = rows.singleOrNull { it.id == selected && it.type == "candidate-pair" } ?: return null
        if (pair.members["state"] != "succeeded") return null
        val remoteId = pair.members["remoteCandidateId"] as? String ?: return null
        val remote = rows.singleOrNull { it.id == remoteId && it.type == "remote-candidate" } ?: return null
        val address = (remote.members["address"] as? String ?: remote.members["ip"] as? String)
            ?.takeIf { it.isNotEmpty() && !it.endsWith(".local") } ?: return null
        return address in hints
    }

    /** A partial, invalid or overflowing measurement is unknown, never a fabricated zero. */
    fun summary(rows: List<ProbeStatsRow>): JsonObject? {
        if (rows.size > MAX_ROWS) return null
        val pairs = rows.filter { it.type == "candidate-pair" }
        fun count(type: String) = rows.count { it.type == type }
        fun counter(key: String): Long? {
            if (pairs.isEmpty()) return null
            var total = 0L
            for (pair in pairs) {
                // The pinned JNI stats API uses Long/BigInteger for integer counters.
                val value = when (val raw = pair.members[key]) {
                    is Long -> raw
                    is Int -> raw.toLong()
                    // longValueExact requires Android API31; admitted agents include API26+.
                    is java.math.BigInteger -> raw.takeIf { it.signum() >= 0 && it.bitLength() <= 63 }?.toLong()
                    else -> null
                } ?: return null
                if (value < 0 || total > Long.MAX_VALUE - value) return null
                total += value
            }
            return total
        }
        val transports = rows.filter { it.type == "transport" }
        val dtls = transports.map { it.members["dtlsState"] }
            .takeIf { it.isNotEmpty() && it.all { value -> value in dtlsStates } }
            ?.distinct()?.singleOrNull() as? String
        return buildJsonObject {
            put("localCandidates", count("local-candidate"))
            put("remoteCandidates", count("remote-candidate"))
            put("pairs", pairs.size)
            put("checkingPairs", pairs.count { it.members["state"] == "in-progress" })
            put("failedPairs", pairs.count { it.members["state"] == "failed" })
            put("succeededPairs", pairs.count { it.members["state"] == "succeeded" })
            for (key in listOf("requestsSent", "requestsReceived", "responsesSent", "responsesReceived")) {
                put(key, counter(key)?.let(::JsonPrimitive) ?: JsonNull)
            }
            put("dtlsState", dtls?.let(::JsonPrimitive) ?: JsonNull)
        }
    }
}

/** Actor-owned, one outstanding native callback; no cancellation or timeout starts another call. */
internal class ProbeStatsBudget(private val sustained: Boolean = false) {
    private var retired = false
    private var pending = false
    private var attempts = 0
    private var lastStart: Long? = null

    fun begin(now: Long): Boolean {
        val previous = lastStart
        val interval = if (sustained && attempts >= 32) 10000 else 1000
        if (retired || pending || attempts >= (if (sustained) 2912 else 32) || now < 0 ||
            (previous != null && (now < previous || now - previous < interval))) return false
        attempts++
        pending = true
        lastStart = now
        return true
    }

    fun complete(): Boolean {
        if (retired || !pending) return false
        pending = false
        return true
    }

    fun retire() { retired = true; pending = false }
}
