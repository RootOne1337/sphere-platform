package com.sphereplatform.agent.direct

import org.junit.Assert.*
import org.junit.Test

class DirectProbeProgressTest {
    @Test fun repeatedCallbacksCannotGrowLogsOrHideTheFirstObservation() {
        val progress = DirectProbeProgress(100)
        assertEquals(0L, progress.record(ProbeStage.OFFER_RECEIVED, 100)!!.elapsedMs)
        repeat(10000) { assertNull(progress.record(ProbeStage.OFFER_RECEIVED, 1000)) }
        assertEquals(5L, progress.record(ProbeStage.REMOTE_SET, 105)!!.elapsedMs)
        assertEquals(6L, progress.record(ProbeStage.GATHERING, 106)!!.elapsedMs)
    }

    @Test fun terminalObservationFencesAllLateCallbacksIncludingSuccessfulOnes() {
        for (terminal in ProbeStage.entries.filter { it.terminal }) {
            val progress = DirectProbeProgress(0)
            assertNotNull(progress.record(terminal, 1))
            for (late in ProbeStage.entries) assertNull(progress.record(late, 2))
        }
    }

    @Test fun invalidClockDoesNotConsumeAStageAndElapsedIsBounded() {
        val progress = DirectProbeProgress(100)
        assertNull(progress.record(ProbeStage.REMOTE_SET, 99))
        assertEquals(1L, progress.record(ProbeStage.REMOTE_SET, 101)!!.elapsedMs)
        assertNull(progress.record(ProbeStage.LOCAL_SET, 100))
        assertEquals(30000L, progress.record(ProbeStage.EXPIRED, Long.MAX_VALUE)!!.elapsedMs)
        assertNull(DirectProbeProgress(-1).record(ProbeStage.OFFER_RECEIVED, 0))
    }
}
