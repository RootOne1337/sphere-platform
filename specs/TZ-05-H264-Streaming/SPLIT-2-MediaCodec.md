# SPLIT-2 — MediaCodec H.264 Encoder Configuration

**ТЗ-родитель:** TZ-05-H264-Streaming  
**Ветка:** `stage/5-streaming`  
**Задача:** `SPHERE-027`  
**Исполнитель:** Android  
**Оценка:** 1 день  
**Блокирует:** TZ-05 SPLIT-3 (NAL units)

---

## Цель Сплита

Настройка асинхронного MediaCodec с минимальной задержкой. Baseline Profile для максимальной совместимости с WebCodecs. Adaptive bitrate при плохой сети.

---

## Шаг 1 — Encoder Configuration

```kotlin
// AndroidAgent/streaming/H264Encoder.kt
class H264Encoder(
    private val config: EncoderConfig,
    private val onFrameReady: (ByteArray, FrameMetadata) -> Unit,
) {
    data class EncoderConfig(
        val width: Int = 1280,
        val height: Int = 720,
        val fps: Int = 30,
        val bitrateBps: Int = 2_000_000,
        val iFrameIntervalSec: Int = 1,
    ) {
        // LOW-3: валидация параметров при создании объекта
        init {
            require(width > 0) { "width must be positive" }
            require(height > 0) { "height must be positive" }
            require(bitrateBps > 0) { "bitrateBps must be positive" }
        }
    }
    
    data class FrameMetadata(
        val isKeyFrame: Boolean,
        val presentationTimeUs: Long,
        val sizeBytes: Int,
    )
    
    private var codec: MediaCodec? = null
    
    fun start(surface: Surface): Surface {
        val mime = MediaFormat.MIMETYPE_VIDEO_AVC
        val format = MediaFormat.createVideoFormat(mime, config.width, config.height).apply {
            setInteger(MediaFormat.KEY_COLOR_FORMAT, MediaCodecInfo.CodecCapabilities.COLOR_FormatSurface)
            setInteger(MediaFormat.KEY_BIT_RATE, config.bitrateBps)
            setInteger(MediaFormat.KEY_FRAME_RATE, config.fps)
            setInteger(MediaFormat.KEY_I_FRAME_INTERVAL, config.iFrameIntervalSec)
            
            // Минимальная задержка — Baseline Profile
            setInteger(MediaFormat.KEY_PROFILE, MediaCodecInfo.CodecProfileLevel.AVCProfileBaseline)
            setInteger(MediaFormat.KEY_LEVEL, MediaCodecInfo.CodecProfileLevel.AVCLevel31)
            
            // Критично для low-latency стриминга
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
                setInteger(MediaFormat.KEY_LOW_LATENCY, 1)
            }
            
            // Приоритет: реальное время > качество
            setInteger(MediaFormat.KEY_PRIORITY, 0)   // 0 = real-time
            
            // CBR для предсказуемого bitrate
            setInteger(MediaFormat.KEY_BITRATE_MODE, MediaCodecInfo.EncoderCapabilities.BITRATE_MODE_CBR)
        }
        
        codec = MediaCodec.createEncoderByType(mime)
        codec!!.setCallback(encoderCallback)
        codec!!.configure(format, null, null, MediaCodec.CONFIGURE_FLAG_ENCODE)
        
        // Input surface для VirtualDisplay
        val inputSurface = codec!!.createInputSurface()
        codec!!.start()
        return inputSurface
    }
    
    private val encoderCallback = object : MediaCodec.Callback() {
        override fun onInputBufferAvailable(codec: MediaCodec, index: Int) {
            // Surface encoder: input buffer не используется
        }
        
        override fun onOutputBufferAvailable(
            codec: MediaCodec,
            index: Int,
            info: MediaCodec.BufferInfo,
        ) {
            if (info.flags and MediaCodec.BUFFER_FLAG_CODEC_CONFIG != 0) {
                // SPS/PPS — сохранить для reconnect
                handleCodecConfig(codec.getOutputBuffer(index)!!, info)
                codec.releaseOutputBuffer(index, false)
                return
            }
            
            if (info.size == 0) {
                codec.releaseOutputBuffer(index, false)
                return
            }
            
            val buffer = codec.getOutputBuffer(index) ?: run {
                codec.releaseOutputBuffer(index, false)
                return
            }
            
            val isKeyFrame = info.flags and MediaCodec.BUFFER_FLAG_KEY_FRAME != 0
            val data = ByteArray(info.size)
            buffer.position(info.offset)
            buffer.get(data)
            
            onFrameReady(data, FrameMetadata(isKeyFrame, info.presentationTimeUs, info.size))
            codec.releaseOutputBuffer(index, false)
        }
        
        override fun onError(codec: MediaCodec, e: MediaCodec.CodecException) {
            Timber.e(e, "MediaCodec error")
            // Попытка восстановления
            restartEncoder()
        }
        
        override fun onOutputFormatChanged(codec: MediaCodec, format: MediaFormat) {
            Timber.i("Encoder output format changed: $format")
        }
    }
    
    // SPS/PPS кеш для отправки при новом подключении viewer
    private var cachedSps: ByteArray? = null
    private var cachedPps: ByteArray? = null
    
    private fun handleCodecConfig(buffer: ByteBuffer, info: MediaCodec.BufferInfo) {
        val data = ByteArray(info.size)
        buffer.position(info.offset)
        buffer.get(data)
        // Парсим SPS (NAL type 7) и PPS (NAL type 8)
        // ...сохраняем для последующей отправки
        cachedSps = data
    }
    
    fun requestKeyFrame() {
        codec?.setParameters(Bundle().apply {
            putInt(MediaCodec.PARAMETER_KEY_REQUEST_SYNC_FRAME, 0)
        })
    }
    
    fun adjustBitrate(newBitrateBps: Int) {
        codec?.setParameters(Bundle().apply {
            putInt(MediaCodec.PARAMETER_KEY_VIDEO_BITRATE, newBitrateBps)
        })
    }
    
    fun stop() {
        codec?.stop()
        codec?.release()
        codec = null
    }
    
    private fun restartEncoder() {
        stop()
        // Логика перезапуска через StreamingManager
    }
}
```

---

## Шаг 2 — Adaptive Bitrate Controller

```kotlin
// AndroidAgent/streaming/AdaptiveBitrateController.kt
class AdaptiveBitrateController(
    private val encoder: H264Encoder,
    private val minBitrate: Int = 500_000,
    private val maxBitrate: Int = 4_000_000,
) {
    private var currentBitrate = 2_000_000
    private var consecutiveDrops = 0
    
    fun onFrameDropDetected() {
        consecutiveDrops++
        if (consecutiveDrops >= 3) {
            val newBitrate = (currentBitrate * 0.8).toInt().coerceAtLeast(minBitrate)
            if (newBitrate != currentBitrate) {
                currentBitrate = newBitrate
                encoder.adjustBitrate(currentBitrate)
                Timber.d("Bitrate reduced to ${currentBitrate/1000}kbps")
            }
        }
    }
    
    fun onSuccessfulDelivery() {
        consecutiveDrops = 0
        // Плавное восстановление bitrate
        val newBitrate = (currentBitrate * 1.05).toInt().coerceAtMost(maxBitrate)
        if (newBitrate > currentBitrate + 100_000) {
            currentBitrate = newBitrate
            encoder.adjustBitrate(currentBitrate)
        }
    }
}
```

---

## Критерии готовности

- [ ] H.264 Baseline Profile Level 3.1 (совместимость с WebCodecs)
- [ ] `KEY_LOW_LATENCY=1` установлен (API 30+)
- [ ] SPS/PPS сохраняются и отправляются при reconnect viewer
- [ ] `requestKeyFrame()` работает по команде с сервера
- [ ] AdaptiveBitrate: 3 дропа → bitrate снижается на 20%
- [ ] Encoder restart без краша приложения
