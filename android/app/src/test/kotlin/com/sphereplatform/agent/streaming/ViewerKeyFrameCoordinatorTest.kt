package com.sphereplatform.agent.streaming

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

class ViewerKeyFrameCoordinatorTest {
    @Test
    fun requestReceivedBeforeCaptureReadinessIsFlushedOnceWhenEncoderStarts() {
        val coordinator = ViewerKeyFrameCoordinator()
        var keyFrameRequests = 0

        assertFalse(coordinator.request { keyFrameRequests++ })
        assertEquals(0, keyFrameRequests)

        coordinator.markEncoderReady { keyFrameRequests++ }
        assertEquals(1, keyFrameRequests)

        coordinator.markEncoderReady { keyFrameRequests++ }
        assertEquals("the same early request must not be replayed twice", 1, keyFrameRequests)
    }

    @Test
    fun severalEarlyViewersCoalesceAndRequestsAfterReadinessAreImmediate() {
        val coordinator = ViewerKeyFrameCoordinator()
        var keyFrameRequests = 0

        repeat(3) { assertFalse(coordinator.request { keyFrameRequests++ }) }
        assertEquals(0, keyFrameRequests)

        coordinator.markEncoderReady { keyFrameRequests++ }
        assertEquals(1, keyFrameRequests)

        assertTrue(coordinator.request { keyFrameRequests++ })
        assertEquals(2, keyFrameRequests)
    }

    @Test
    fun requestAfterStopWaitsForTheNextEncoderStart() {
        val coordinator = ViewerKeyFrameCoordinator()
        var keyFrameRequests = 0

        coordinator.markEncoderReady { keyFrameRequests++ }
        assertEquals(0, keyFrameRequests)
        coordinator.markEncoderStopped()
        assertFalse(coordinator.request { keyFrameRequests++ })
        assertEquals(0, keyFrameRequests)

        coordinator.markEncoderReady { keyFrameRequests++ }
        assertEquals(1, keyFrameRequests)
    }

    @Test
    fun concurrentEarlyViewerRequestsAreCoalescedWithoutLosingThePendingRequest() {
        val coordinator = ViewerKeyFrameCoordinator()
        val requestCount = AtomicInteger()
        val ready = CountDownLatch(1)
        val executor = Executors.newFixedThreadPool(8)
        try {
            val requests = (1..64).map {
                executor.submit {
                    assertTrue(ready.await(3, TimeUnit.SECONDS))
                    assertFalse(coordinator.request { requestCount.incrementAndGet() })
                }
            }
            ready.countDown()
            requests.forEach { it.get(3, TimeUnit.SECONDS) }

            coordinator.markEncoderReady { requestCount.incrementAndGet() }
            assertEquals(1, requestCount.get())
        } finally {
            executor.shutdownNow()
            assertTrue(executor.awaitTermination(3, TimeUnit.SECONDS))
        }
    }
}
