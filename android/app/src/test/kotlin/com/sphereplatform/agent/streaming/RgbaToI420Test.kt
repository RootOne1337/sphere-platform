package com.sphereplatform.agent.streaming

import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test

class RgbaToI420Test {
    private fun color(r: Int, g: Int, b: Int, alpha: Int = 255): ByteBuffer =
        ByteBuffer.wrap(ByteArray(16) { index -> when (index % 4) {
            0 -> r.toByte(); 1 -> g.toByte(); 2 -> b.toByte(); else -> alpha.toByte()
        } })
    private fun result(input: ByteBuffer): List<Int> {
        val output = ByteBuffer.allocate(6)
        RgbaToI420(2, 2).convert(input, 8, 4, output)
        return output.array().map { it.toInt() and 255 }
    }
    @Test fun `black uses limited range luma and neutral chroma`() {
        assertEquals(listOf(16, 16, 16, 16, 128, 128), result(color(0, 0, 0)))
    }
    @Test fun `white is 235 rather than full range 255`() {
        assertEquals(listOf(235, 235, 235, 235, 128, 128), result(color(255, 255, 255)))
    }
    @Test fun `red preserves RGBA channel order and I420 U then V`() {
        assertEquals(listOf(82, 82, 82, 82, 90, 240), result(color(255, 0, 0)))
    }
    @Test fun `green has the expected BT601 integer reference`() {
        assertEquals(listOf(144, 144, 144, 144, 54, 34), result(color(0, 255, 0)))
    }
    @Test fun `blue does not get interpreted as red`() {
        assertEquals(listOf(41, 41, 41, 41, 240, 110), result(color(0, 0, 255)))
    }
    @Test fun `chroma averages all four pixels without averaging luma`() {
        val rgba = byteArrayOf(-1,0,0,-1, 0,-1,0,-1, 0,0,-1,-1, -1,-1,-1,-1)
        assertEquals(listOf(82, 144, 41, 235, 128, 128), result(ByteBuffer.wrap(rgba)))
    }
    @Test fun `row and pixel padding do not become screen pixels`() {
        val source = ByteBuffer.allocate(36)
        for (y in 0..1) for (x in 0..1) {
            val offset = y * 24 + x * 8
            source.put(offset, -1); source.put(offset + 3, -1)
        }
        // The last row exposes only the final pixel, not 12 trailing pad bytes.
        val output = ByteBuffer.allocate(6)
        RgbaToI420(2, 2).convert(source, 24, 8, output)
        assertEquals(listOf(82,82,82,82,90,240), output.array().map { it.toInt() and 255 })
    }
    @Test fun `caller position is retained and destination contains exactly one frame`() {
        val source = color(255, 0, 0); source.position(13)
        val destination = ByteBuffer.allocate(10); destination.position(7)
        RgbaToI420(2, 2).convert(source, 8, 4, destination)
        assertEquals(13, source.position()); assertEquals(6, destination.position())
    }
    @Test fun `reuse cannot retain an earlier red frame when the next is blue`() {
        val converter = RgbaToI420(2,2); val output = ByteBuffer.allocate(6)
        converter.convert(color(255,0,0),8,4,output)
        converter.convert(color(0,0,255),8,4,output)
        assertEquals(listOf(41,41,41,41,240,110), output.array().map { it.toInt() and 255 })
    }
    @Test fun `alpha does not shift color channels`() {
        assertEquals(result(color(255,0,0)), result(color(255,0,0,0)))
    }
    @Test fun `truncated plane rejected before destination mutation`() {
        val output = ByteBuffer.wrap(ByteArray(6) { 9 })
        assertThrows(IllegalArgumentException::class.java) {
            RgbaToI420(2,2).convert(ByteBuffer.allocate(15),8,4,output)
        }
        assertArrayEquals(ByteArray(6) { 9 }, output.array())
    }
    @Test fun `invalid stride and output buffers fail closed`() {
        val converter = RgbaToI420(2,2)
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),7,4,ByteBuffer.allocate(6)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,3,ByteBuffer.allocate(6)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,4,ByteBuffer.allocate(5)) }
        assertThrows(IllegalArgumentException::class.java) { converter.convert(color(0,0,0),8,4,ByteBuffer.allocate(6).asReadOnlyBuffer()) }
    }
    @Test fun `odd dimensions and excessive sizes are not silently cropped`() {
        for ((width, height) in listOf(3 to 2, 2 to 3, 0 to 2, 8192 to 2)) {
            assertThrows(IllegalArgumentException::class.java) { RgbaToI420(width,height) }
        }
    }
    @Test fun `native direct conversion preserves source position and owns the idle refresh pixels`() {
        var calls = 0
        val original = ByteBuffer.allocateDirect(16)
        val fast = object : NativeRgbaConversion {
            override val available = true
            override fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean {
                calls++
                assertEquals(0,source.position()); assertEquals(8,rowStride)
                assertEquals(2,width); assertEquals(2,height)
                source.put(0,99)
                assertEquals(0,original.get(0).toInt()) // The mapped producer never becomes writable native scratch.
                output.clear(); output.put(byteArrayOf(41,41,41,41,240.toByte(),110))
                return true
            }
        }
        val converter = RgbaToI420(2,2,fast)
        val source = original.apply { position(13) }
        val output = ByteBuffer.allocate(6)
        converter.convert(source,8,4,output)
        assertEquals(13,source.position()); assertEquals(6,output.position()); assertEquals(1,calls)
        val refresh = ByteBuffer.allocate(6)
        converter.copyLastConverted(refresh)
        assertArrayEquals(output.array(),refresh.array())
    }
    @Test fun `a refused native conversion overwrites partial scratch and updates the refresh cache`() {
        var calls = 0
        val fast = object : NativeRgbaConversion {
            override val available = true
            override fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean {
                calls++; output.clear(); output.put(ByteArray(6) { 99 })
                return calls == 1
            }
        }
        val converter = RgbaToI420(2,2,fast)
        val source = ByteBuffer.allocateDirect(16)
        val output = ByteBuffer.allocate(6)
        converter.convert(source,8,4,output)
        assertArrayEquals(ByteArray(6) { 99 },output.array())
        for (i in 0..3) {source.put(i*4+2,255.toByte());source.put(i*4+3,255.toByte())}
        converter.convert(source,8,4,output)
        assertEquals(listOf(41,41,41,41,240,110),output.array().map { it.toInt() and 255 })
        val refresh = ByteBuffer.allocate(6);converter.copyLastConverted(refresh)
        assertArrayEquals(output.array(),refresh.array())
    }
    @Test fun `heap or pixel padded source stays on scalar path and invalid input never reaches JNI`() {
        var calls = 0
        val fast = object : NativeRgbaConversion {
            override val available = true
            override fun convert(source: ByteBuffer, rowStride: Int, width: Int, height: Int, output: ByteBuffer): Boolean {calls++;return false}
        }
        val converter = RgbaToI420(2,2,fast)
        converter.convert(color(255,0,0),8,4,ByteBuffer.allocate(6))
        converter.convert(ByteBuffer.allocateDirect(36),24,8,ByteBuffer.allocate(6))
        assertThrows(IllegalArgumentException::class.java) {converter.convert(ByteBuffer.allocateDirect(15),8,4,ByteBuffer.allocate(6))}
        assertEquals(0,calls)
    }

    @Test fun `borrowed GPU planes copy only valid pixels and own the idle cache`() {
        val y = ByteBuffer.wrap(byteArrayOf(16, 41, 99, 82, 235.toByte())).apply { position(1) }
        val u = ByteBuffer.wrap(byteArrayOf(90)).asReadOnlyBuffer()
        val v = ByteBuffer.wrap(byteArrayOf(240.toByte()))
        val converter = RgbaToI420(2,2)
        val output = ByteBuffer.allocate(6)
        converter.copyFromPlanar(I420Planes(2,2,y,3,u,1,v,1),output)
        assertArrayEquals(byteArrayOf(16,41,82,235.toByte(),90,240.toByte()),output.array())
        assertEquals(1,y.position()); assertEquals(0,u.position()); assertEquals(0,v.position())
        y.put(0,99); v.put(0,99)
        val refreshed = ByteBuffer.allocate(6); converter.copyLastConverted(refreshed)
        assertArrayEquals(output.array(),refreshed.array())
    }

    @Test fun `invalid last chroma plane preserves both destination and prior cached frame`() {
        val converter = RgbaToI420(2,2)
        val output = ByteBuffer.allocate(6)
        converter.convert(color(255,0,0),8,4,output)
        val before = output.array().clone()
        val invalid = I420Planes(2,2,ByteBuffer.allocate(4),2,ByteBuffer.allocate(1),1,ByteBuffer.allocate(0),1)
        assertThrows(IllegalArgumentException::class.java) { converter.copyFromPlanar(invalid,output) }
        assertArrayEquals(before,output.array())
        converter.copyLastConverted(output); assertArrayEquals(before,output.array())
        assertThrows(IllegalArgumentException::class.java) { converter.copyFromPlanar(invalid.copy(width=4),output) }
    }

    @Test fun `GPU packed chroma rows with full-width stride become compact I420 planes`() {
        val y = ByteArray(16) { it.toByte() }
        val planes = I420Planes(4,4,ByteBuffer.wrap(y),4,
            ByteBuffer.wrap(byteArrayOf(10,20,99,99,30,40)),4,
            ByteBuffer.wrap(byteArrayOf(50,60,99,99,70,80)),4)
        val output = ByteBuffer.allocate(24)
        RgbaToI420(4,4).copyFromPlanar(planes,output)
        assertArrayEquals(y + byteArrayOf(10,20,30,40,50,60,70,80),output.array())
    }
}
