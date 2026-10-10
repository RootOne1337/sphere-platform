package com.sphereplatform.agent.commands

import android.content.Context
import io.mockk.*
import kotlinx.coroutines.runBlocking
import org.junit.Assert.*
import org.junit.Test
import java.io.*

class ProcessTouchPipeTest {
    private fun response(seq: Int, status: Int, time: Long = 1000): ByteArray = ByteArrayOutputStream().also {
        RootTouchWire.ack(it,seq,status,time)
    }.toByteArray()
    private fun process(bytes: ByteArray, exit: Int = 0): Pair<Process,ByteArrayOutputStream> {
        val output = ByteArrayOutputStream()
        val p = mockk<Process>()
        every {p.inputStream} returns ByteArrayInputStream(bytes)
        every {p.errorStream} returns ByteArrayInputStream(ByteArray(0))
        every {p.outputStream} returns output
        every {p.isAlive} returns false
        every {p.exitValue()} returns exit
        return p to output
    }

    @Test fun `root factory construction does not access context or request root`() {
        val context = mockk<Context>()
        RootTouchPipeFactory(context)
        verify { context wasNot Called }
    }

    @Test fun `packet is sent once and matching acknowledgement preserves device clock`() = runBlocking {
        val (process,output) = process(response(1,1,1234))
        val pipe = ProcessTouchPipe(process)
        val ack = pipe.send(TouchSample(1,1,0,100,120,1000))
        assertEquals(1,ack.status)
        assertEquals(1234L,ack.uptimeMs)
        val packet = RootTouchWire.read(ByteArrayInputStream(output.toByteArray()))
        assertEquals(1,packet.sequence)
        assertEquals(0,packet.action)
        assertEquals(RootTouchWire.INPUT_LINE_BYTES,output.size())
        assertTrue(pipe.closeAndConfirm())
        assertFalse(pipe.closeAndConfirm())
        Unit
    }

    @Test fun `reordered duplicate send never writes a second packet`() = runBlocking {
        val (process,output) = process(response(2,1))
        val pipe = ProcessTouchPipe(process)
        pipe.send(TouchSample(2,1,0,100,120,1000))
        assertThrows(IOException::class.java) { runBlocking {pipe.send(TouchSample(2,1,2,110,120,1000))} }
        assertEquals(RootTouchWire.INPUT_LINE_BYTES,output.size())
        pipe.closeAndConfirm()
        Unit
    }

    @Test fun `wrong acknowledgement and action status are unknown rather than replayed`() = runBlocking {
        for (bytes in listOf(response(0,4),response(2,1),response(1,0),response(1,2))) {
            val (process,output) = process(bytes)
            val pipe = ProcessTouchPipe(process)
            assertThrows(IOException::class.java) { runBlocking {pipe.send(TouchSample(1,1,0,100,120,1000))} }
            assertEquals(RootTouchWire.INPUT_LINE_BYTES,output.size())
            pipe.closeAndConfirm()
        }
    }

    @Test fun `negative acknowledgement returns outcome without resubmitting`() = runBlocking {
        for (status in 4..6) {
            val (process,output) = process(response(1,status))
            val pipe = ProcessTouchPipe(process)
            assertEquals(status,pipe.send(TouchSample(1,1,0,100,120,1000)).status)
            assertEquals(RootTouchWire.INPUT_LINE_BYTES,output.size())
            pipe.closeAndConfirm()
        }
    }

    @Test fun `CRLF converted acknowledgement remains canonical`() = runBlocking {
        val bytes = String(response(1,1),Charsets.US_ASCII).replace("\n","\r\n").toByteArray()
        val (process,_) = process(bytes)
        val pipe = ProcessTouchPipe(process)
        assertEquals(1,pipe.send(TouchSample(1,1,0,100,120,1000)).sequence)
        pipe.closeAndConfirm()
        Unit
    }

    @Test fun `missing truncated and oversized acknowledgement never succeeds`() = runBlocking {
        for (bytes in listOf(ByteArray(0),response(1,1).copyOf(10),ByteArray(100) {'a'.code.toByte()})) {
            val (process,_) = process(bytes)
            val pipe = ProcessTouchPipe(process)
            assertThrows(IOException::class.java) { runBlocking {pipe.send(TouchSample(1,1,0,100,120,1000))} }
            pipe.closeAndConfirm()
        }
    }

    @Test fun `process failure is not cancellation confirmation and no cleanup starts a helper`() = runBlocking {
        val (process,_) = process(ByteArray(0),exit=2)
        val pipe = ProcessTouchPipe(process)
        assertFalse(pipe.closeAndConfirm())
        verify(exactly=0) {process.destroyForcibly()}
        Unit
    }

    @Test fun `stdin failure is not replayed and closure still checks owned process`() = runBlocking {
        val (process,_) = process(ByteArray(0))
        val broken = object : OutputStream() {
            var calls = 0
            override fun write(value: Int) {calls++;throw IOException("private pipe detail")}
        }
        every {process.outputStream} returns broken
        val pipe = ProcessTouchPipe(process)
        assertThrows(IOException::class.java) {runBlocking {pipe.send(TouchSample(1,1,0,100,120,1000))}}
        assertEquals(1,broken.calls)
        assertTrue(pipe.closeAndConfirm())
        Unit
    }
}
