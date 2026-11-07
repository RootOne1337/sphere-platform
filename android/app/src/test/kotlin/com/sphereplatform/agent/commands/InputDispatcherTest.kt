package com.sphereplatform.agent.commands

import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.util.concurrent.ExecutorService
import java.util.concurrent.atomic.AtomicInteger

class InputDispatcherTest {
    @Test fun `input resumes on one owned thread and retires after its scope`() = runBlocking {
        val lifecycle = SupervisorJob()
        val scope = CoroutineScope(lifecycle)
        val configured = AtomicInteger()
        val dispatcher = inputDispatcher(scope) { configured.incrementAndGet() }
        val threads = (1..10).map {
            scope.async(dispatcher) {
                val first = Thread.currentThread().id
                delay(1)
                assertEquals(first, Thread.currentThread().id)
                first
            }
        }.awaitAll()
        assertEquals(1, threads.toSet().size)
        assertEquals(1, configured.get())
        lifecycle.cancel(); lifecycle.join()
        assertTrue((dispatcher.executor as ExecutorService).isShutdown)
    }

    @Test fun `priority refusal leaves an ordinary isolated input thread available`() = runBlocking {
        val lifecycle = SupervisorJob()
        val scope = CoroutineScope(lifecycle)
        val dispatcher = inputDispatcher(scope) { throw SecurityException("fixture") }
        assertEquals(7, scope.async(dispatcher) { 7 }.await())
        lifecycle.cancel(); lifecycle.join()
        assertTrue((dispatcher.executor as ExecutorService).isShutdown)
    }
}
