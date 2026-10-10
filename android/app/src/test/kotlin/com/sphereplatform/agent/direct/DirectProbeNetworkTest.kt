package com.sphereplatform.agent.direct

import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.long
import org.junit.Assert.*
import org.junit.Test
import java.math.BigInteger

class DirectProbeNetworkTest {
    private fun pair(vararg members: Pair<String, Any?>) = ProbeStatsRow("candidate-pair", mapOf(*members))

    @Test fun nativeReceiveAndSendCountersDoNotExportPrivateRtcStats() {
        val summary = DirectProbeNetwork.summary(listOf(
            ProbeStatsRow("local-candidate", mapOf("address" to "10.0.0.2", "port" to 1234)),
            ProbeStatsRow("remote-candidate", mapOf("address" to "private.local", "usernameFragment" to "secret")),
            pair("state" to "in-progress", "requestsSent" to BigInteger.valueOf(4), "requestsReceived" to 3L,
                "responsesSent" to 2L, "responsesReceived" to 1L, "remoteCandidateId" to "private-id"),
            pair("state" to "succeeded", "requestsSent" to 6, "requestsReceived" to 7L,
                "responsesSent" to 8L, "responsesReceived" to 9L),
            ProbeStatsRow("transport", mapOf("dtlsState" to "connecting", "selectedCandidatePairId" to "secret")),
            ProbeStatsRow("certificate", mapOf("fingerprint" to "secret")),
        ))!!
        assertEquals(1L, summary["localCandidates"]!!.jsonPrimitive.long)
        assertEquals(2L, summary["pairs"]!!.jsonPrimitive.long)
        for (key in listOf("requestsSent", "requestsReceived", "responsesSent", "responsesReceived"))
            assertEquals(10L, summary[key]!!.jsonPrimitive.long)
        for (forbidden in listOf("address", "port", "10.0.0.2", "private", "secret", "fingerprint", "CandidateId"))
            assertFalse(summary.toString().contains(forbidden))
        assertEquals("connecting", summary["dtlsState"]!!.jsonPrimitive.content)
    }

    @Test fun missingMalformedOrOverflowingCountersRemainUnknown() {
        assertEquals(JsonNull, DirectProbeNetwork.summary(emptyList())!!["requestsReceived"])
        for (value in listOf(null, -1L, 1.5, "3", true, BigInteger.ONE.shiftLeft(64))) {
            assertEquals(JsonNull, DirectProbeNetwork.summary(listOf(pair("requestsReceived" to value)))!!["requestsReceived"])
        }
        assertEquals(JsonNull, DirectProbeNetwork.summary(listOf(pair("requestsReceived" to 1L), pair()))!!["requestsReceived"])
        assertEquals(JsonNull, DirectProbeNetwork.summary(listOf(
            pair("requestsReceived" to Long.MAX_VALUE), pair("requestsReceived" to 1L)))!!["requestsReceived"])
        assertEquals(0L, DirectProbeNetwork.summary(listOf(pair("requestsReceived" to 0L)))!!["requestsReceived"]!!.jsonPrimitive.long)
    }

    @Test fun oversizedReportAndAmbiguousDtlsAreNotReportedAsValid() {
        assertNull(DirectProbeNetwork.summary(List(257) { pair() }))
        for (states in listOf(listOf("connecting", "connected"), listOf("connected", "secret-state"))) {
            val rows = states.map { ProbeStatsRow("transport", mapOf("dtlsState" to it)) }
            assertEquals(JsonNull, DirectProbeNetwork.summary(rows)!!["dtlsState"])
        }
    }

    @Test fun bigIntegerCountersStayExactAtTheSignedLongBoundaryOnOlderAndroid() {
        val maximum = BigInteger.valueOf(Long.MAX_VALUE)
        val accepted = DirectProbeNetwork.summary(listOf(pair("requestsReceived" to maximum)))!!
        assertEquals(Long.MAX_VALUE, accepted["requestsReceived"]!!.jsonPrimitive.long)
        for (value in listOf(maximum + BigInteger.ONE, BigInteger.valueOf(Long.MIN_VALUE), -BigInteger.ONE)) {
            assertEquals(JsonNull, DirectProbeNetwork.summary(listOf(pair("requestsReceived" to value)))!!["requestsReceived"])
        }
    }

    @Test fun oneOutstandingCallbackAndRateLimitPreventNativeStatsBacklog() {
        val budget = ProbeStatsBudget()
        assertTrue(budget.begin(0))
        assertFalse(budget.begin(1000))
        assertTrue(budget.complete())
        assertFalse(budget.complete())
        assertFalse(budget.begin(999))
        assertTrue(budget.begin(1000))
        assertTrue(budget.complete())
        assertFalse(budget.begin(500))
    }

    @Test fun finiteBudgetAndRetirementFenceLateCallbacks() {
        val budget = ProbeStatsBudget()
        for (index in 0 until 32) {
            assertTrue(budget.begin(index * 1000L))
            assertTrue(budget.complete())
        }
        assertFalse(budget.begin(32000))
        val late = ProbeStatsBudget()
        assertTrue(late.begin(0))
        late.retire()
        assertFalse(late.complete())
        assertFalse(late.begin(1000))
    }
}
