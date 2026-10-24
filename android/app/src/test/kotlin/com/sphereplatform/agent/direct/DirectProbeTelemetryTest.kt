package com.sphereplatform.agent.direct

import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

class DirectProbeTelemetryTest {
    @Test fun finalRetainsTheAgeOfTheMeasuredNetworkInsteadOfFabricatingFreshCounters() {
        val journal = DirectProbeTelemetry(1000)
        val summary = DirectProbeNetwork.summary(listOf(ProbeStatsRow("candidate-pair", mapOf(
            "state" to "in-progress", "requestsSent" to 237L, "responsesReceived" to 0L,
            "address" to "10.0.0.1", "certificate" to "private-key"))))!!
        journal.observe(summary, 1900)
        val sample = journal.report(ProbeStage.ANSWER_SENT, "public-stun", true, 2000)!!
        assertEquals(100L, sample["network_sample_age_ms"]!!.jsonPrimitive.long)
        assertEquals(0L, sample["network"]!!.jsonObject["responses_received"]!!.jsonPrimitive.long)
        assertEquals(JsonNull, sample["network"]!!.jsonObject["requests_received"])
        val final = journal.report(ProbeStage.CLOSED, "public-stun", true, 5000)!!
        assertEquals("final", final["kind"]!!.jsonPrimitive.content)
        assertEquals(3100L, final["network_sample_age_ms"]!!.jsonPrimitive.long)
        assertEquals(900L, final["network_sample_elapsed_ms"]!!.jsonPrimitive.long)
        assertNull(journal.report(ProbeStage.CHANNEL_OPEN, "public-stun", true, 6000))
        for (forbiddenValue in listOf("address", "10.0.0.1", "private-key", "certificate"))
            assertFalse(final.toString().contains(forbiddenValue))
        assertTrue(final.toString().toByteArray().size < 2048)
    }

    @Test fun absentOrJavascriptOverflowingMeasurementsRemainUnknown() {
        val absent = DirectProbeTelemetry(0).report(ProbeStage.OPEN_FAILED, "host", false, 20)!!
        assertEquals(JsonNull, absent["network"])
        assertEquals(JsonNull, absent["network_sample_age_ms"])
        val journal = DirectProbeTelemetry(0)
        val summary = DirectProbeNetwork.summary(listOf(ProbeStatsRow("candidate-pair", mapOf(
            "requestsSent" to Long.MAX_VALUE, "responsesReceived" to 9007199254740991L))))!!
        journal.observe(summary, 0)
        val network = journal.report(ProbeStage.PEER_READY, "host", false, 1000)!!["network"]!!.jsonObject
        assertEquals(JsonNull, network["requests_sent"])
        assertEquals(9007199254740991L, network["responses_received"]!!.jsonPrimitive.long)
    }

    @Test fun finiteSparseBudgetAndClockFencesNeverCreateAnUnboundedJournal() {
        val journal = DirectProbeTelemetry(0)
        assertNotNull(journal.report(ProbeStage.PEER_READY, "host", false, 0))
        assertNull(journal.report(ProbeStage.PEER_READY, "host", false, 999))
        assertNull(journal.report(ProbeStage.PEER_READY, "host", false, -1))
        assertNull(journal.report(ProbeStage.PEER_READY, "private-endpoint", false, 1000))
        for (index in 1 until DirectProbeTelemetry.MAX_REPORTS - 1)
            assertNotNull(journal.report(ProbeStage.CHANNEL_OPEN, "host", true, index * 1000L))
        assertNull(journal.report(ProbeStage.CHANNEL_OPEN, "host", true, 4000000))
        assertNotNull(journal.report(ProbeStage.EXPIRED, "host", true, 4000000))
        assertNull(journal.report(ProbeStage.CLOSED, "host", true, 5000000))
    }

    @Test fun sustainedStatsReuseOneCallbackWithSparseSamplingAfterSetup() {
        val budget = ProbeStatsBudget(sustained = true)
        for (index in 0 until 32) {
            assertTrue(budget.begin(index * 1000L)); assertTrue(budget.complete())
        }
        assertFalse(budget.begin(32000))
        assertFalse(budget.begin(40999))
        assertTrue(budget.begin(41000))
        assertFalse(budget.begin(51000)) // Existing callback must finish first.
        assertTrue(budget.complete())
        for (index in 33 until 2912) {
            assertTrue(budget.begin(41000 + (index - 32) * 10000L)); assertTrue(budget.complete())
        }
        assertFalse(budget.begin(DirectProbeTelemetry.MAX_ELAPSED_MS))
        budget.retire()
        assertFalse(budget.begin(DirectProbeTelemetry.MAX_ELAPSED_MS + 10000))
    }
}
