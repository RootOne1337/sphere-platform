package com.sphereplatform.agent.logging

import org.junit.Assert.assertArrayEquals
import org.junit.Test
import java.io.ByteArrayInputStream

class LogcatCollectorTest {
    @Test
    fun `bounded capture retains only the newest bytes`() {
        val result = ByteArrayInputStream("0123456789".toByteArray()).readBoundedTail(4)

        assertArrayEquals("6789".toByteArray(), result)
    }

    @Test
    fun `bounded capture preserves all output below the limit`() {
        val result = ByteArrayInputStream("Sphere diagnostic".toByteArray()).readBoundedTail(128)

        assertArrayEquals("Sphere diagnostic".toByteArray(), result)
    }
}
