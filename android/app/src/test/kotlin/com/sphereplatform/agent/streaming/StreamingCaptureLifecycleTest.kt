package com.sphereplatform.agent.streaming

import android.app.Application
import android.graphics.Bitmap
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.view.Surface
import io.mockk.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.RuntimeEnvironment
import org.robolectric.annotation.Config
import java.nio.ByteBuffer
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [28], manifest = Config.NONE, application = Application::class)
class StreamingCaptureLifecycleTest {
    private lateinit var manager: StreamingManagerImpl
    private val reader = mockk<ImageReader>(relaxed = true)
    private val bitmap = mockk<Bitmap>(relaxed = true)
    private val listeners = mutableListOf<ImageReader.OnImageAvailableListener>()
    private val projection = mockk<MediaProjection>(relaxed = true)

    @Before fun setup() {
        mockkStatic(ImageReader::class)
        mockkStatic(Bitmap::class)
        mockkConstructor(H264Encoder::class)
        mockkConstructor(VirtualDisplayManager::class)
        every { anyConstructed<H264Encoder>().start() } returns mockk<Surface>(relaxed = true)
        every { anyConstructed<H264Encoder>().stop() } just Runs
        every { anyConstructed<VirtualDisplayManager>().createDisplay(any(), any()) } returns mockk(relaxed = true)
        every { anyConstructed<VirtualDisplayManager>().release() } just Runs
        every { ImageReader.newInstance(any(), any(), any(), any()) } returns reader
        every { reader.setOnImageAvailableListener(any(), any()) } answers {
            firstArg<ImageReader.OnImageAvailableListener?>()?.let { listeners.add(it) }
        }
        val image = mockk<Image>(relaxed = true)
        val plane = mockk<Image.Plane>()
        every { image.planes } returns arrayOf(plane)
        every { image.width } returns 4
        every { image.height } returns 4
        every { plane.rowStride } returns 16
        every { plane.pixelStride } returns 4
        every { plane.buffer } returns ByteBuffer.allocateDirect(64)
        every { reader.acquireLatestImage() } returns image
        every { Bitmap.createBitmap(any<Int>(), any<Int>(), Bitmap.Config.ARGB_8888) } returns bitmap
        every { bitmap.isRecycled } returns false
        manager = StreamingManagerImpl(RuntimeEnvironment.getApplication(), mockk(relaxed = true),
            mockk(relaxed = true), mockk(relaxed = true))
    }

    @After fun cleanup() {
        manager.stop()
        unmockkAll()
    }

    @Test fun `stop cannot close reader or recycle bitmap during native copy`() {
        val entered = CountDownLatch(1)
        val release = CountDownLatch(1)
        val readerClosed = CountDownLatch(1)
        val recycled = CountDownLatch(1)
        every { bitmap.copyPixelsFromBuffer(any()) } answers {
            entered.countDown()
            check(release.await(5, TimeUnit.SECONDS))
        }
        every { reader.close() } answers { readerClosed.countDown() }
        every { bitmap.recycle() } answers { recycled.countDown() }
        manager.start(projection)
        val executor = Executors.newFixedThreadPool(2)
        val frame = executor.submit { listeners.last().onImageAvailable(reader) }
        var stop: java.util.concurrent.Future<*>? = null
        try {
            assertTrue(entered.await(3, TimeUnit.SECONDS))
            val stopping = CountDownLatch(1)
            stop = executor.submit { stopping.countDown(); manager.stop() }
            assertTrue(stopping.await(3, TimeUnit.SECONDS))
            assertFalse("ImageReader native buffer freed while copy is active", readerClosed.await(200, TimeUnit.MILLISECONDS))
            assertEquals("Bitmap recycled while copy is active", 1L, recycled.count)
        } finally {
            release.countDown()
            frame.get(3, TimeUnit.SECONDS)
            stop?.get(3, TimeUnit.SECONDS)
            executor.shutdownNow()
        }
        assertTrue(readerClosed.await(1, TimeUnit.SECONDS))
        assertEquals(0L, recycled.count)
    }

    @Test fun `queued image callback after stop cannot touch released reader`() {
        manager.start(projection)
        val callback = listeners.last()
        manager.stop()
        callback.onImageAvailable(reader)
        verify(exactly = 0) { reader.acquireLatestImage() }
        verify(exactly = 0) { bitmap.copyPixelsFromBuffer(any()) }
    }

    @Test fun `previous capture callback cannot render into a new session`() {
        manager.start(projection)
        val previous = listeners.last()
        manager.start(projection)
        previous.onImageAvailable(reader)
        verify(exactly = 0) { reader.acquireLatestImage() }
        listeners.last().onImageAvailable(reader)
        verify(exactly = 1) { bitmap.copyPixelsFromBuffer(any()) }
    }

    @Test fun `repeated stop releases each native resource once`() {
        manager.start(projection)
        listeners.last().onImageAvailable(reader)
        manager.stop()
        manager.stop()
        verify(exactly = 1) { reader.close() }
        verify(exactly = 1) { bitmap.recycle() }
        assertFalse(manager.isActive())
    }
}
