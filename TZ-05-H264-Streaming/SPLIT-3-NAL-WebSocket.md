# SPLIT-3 — NAL Units over WebSocket (Transport Layer)

**ТЗ-родитель:** TZ-05-H264-Streaming  
**Ветка:** `stage/5-streaming`  
**Задача:** `SPHERE-028`  
**Исполнитель:** Android + Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-05 SPLIT-4, SPLIT-5

---

## Цель Сплита

Передача H.264 NAL units как бинарных WebSocket фреймов. Кастомный binary header для синхронизации. Обработка подключения нового viewer (SPS/PPS replay).

---

## Шаг 1 — Binary Frame Format

```
Формат бинарного фрейма (Big Endian):
┌─────────────────────────────────────────────────────┐
│ [0]    Version (1 byte)  = 0x01                     │
│ [1]    Flags (1 byte)    bit0=keyframe               │
│ [2:10] Timestamp (8 bytes) = ms since stream start  │
│ [10:14] Frame size (4 bytes)                         │
│ [14:]  Raw H.264 NAL data                           │
└─────────────────────────────────────────────────────┘
```

```kotlin
// AndroidAgent/streaming/FramePackager.kt
object FramePackager {
    // FIX-5.1: Header расширен с 10 до 14 байт.
    // Причина: 4-байтный timestamp (UInt32) переполняется через 49.7 дней.
    // Long (8 байт) = 292 миллиона лет — достаточно для 24/7 фермы.
    const val HEADER_SIZE = 14
    const val VERSION = 0x01.toByte()
    const val FLAG_KEYFRAME = 0x01
    
    fun pack(nalData: ByteArray, metadata: H264Encoder.FrameMetadata, startTimeMs: Long): ByteArray {
        val timestamp = System.currentTimeMillis() - startTimeMs  // Long — нет overflow!
        val flags = if (metadata.isKeyFrame) FLAG_KEYFRAME else 0x00
        
        return ByteBuffer.allocate(HEADER_SIZE + nalData.size).apply {
            put(VERSION)
            put(flags.toByte())
            putLong(timestamp)    // 8 байт вместо 4
            putInt(nalData.size)
            put(nalData)
        }.array()
    }
}
```

---

## Шаг 2 — Streaming Manager (Android)

```kotlin
// AndroidAgent/streaming/StreamingManager.kt
@Singleton
class StreamingManager @Inject constructor(
    private val wsClient: SphereWebSocketClient,
    private val adaptiveBitrate: AdaptiveBitrateController,
) {
    private var encoder: H264Encoder? = null
    private var virtualDisplayManager: VirtualDisplayManager? = null
    private var streamStartTime: Long = 0
    private var isStreaming = false
    
    // Кеш SPS/PPS для новых viewer'ов
    @Volatile private var cachedSps: ByteArray? = null
    @Volatile private var cachedPps: ByteArray? = null
    
    fun start(mediaProjection: MediaProjection) {
        if (isStreaming) return
        streamStartTime = System.currentTimeMillis()
        
        encoder = H264Encoder(H264Encoder.EncoderConfig()) { nalData, metadata ->
            onFrameReady(nalData, metadata)
        }
        
        // ⚠️ ИСПРАВЛЕНО: null!! → NullPointerException во время выполнения
        // start() возвращает Surface, которую нужно передать в VirtualDisplayManager
        val encoderSurface = encoder!!.start()
        virtualDisplayManager = VirtualDisplayManager(App.context, mediaProjection)
        virtualDisplayManager!!.createDisplay(VirtualDisplayManager.DisplayConfig(), encoderSurface)
        
        isStreaming = true
    }
    
    private fun onFrameReady(nalData: ByteArray, metadata: H264Encoder.FrameMetadata) {
        if (!isStreaming) return
        
        // Обновить кеш SPS/PPS
        if (metadata.isKeyFrame) {
            // Сохраняем I-frame для replay
        }
        
        val packed = FramePackager.pack(nalData, metadata, streamStartTime)
        
        // Отправить через WebSocket как бинарный фрейм
        val sent = wsClient.sendBinary(packed)
        if (!sent) {
            adaptiveBitrate.onFrameDropDetected()
            if (metadata.isKeyFrame) {
                // I-frame потерян — критично! Пересоздать соединение или запросить повтор
                Timber.w("Key frame failed to send! Queue may be full.")
            }
        } else {
            adaptiveBitrate.onSuccessfulDelivery()
        }
    }
    
    fun stop() {
        isStreaming = false
        encoder?.stop()
        encoder = null
        virtualDisplayManager?.release()
        virtualDisplayManager = null
    }
    
    fun onViewerConnected() {
        // Новый viewer подключился — запросить I-frame немедленно
        encoder?.requestKeyFrame()
        // SPS/PPS отправляются первыми (гарантируют декодирование)
        // FIX: вместо ... используем синтетический FrameMetadata для пересылки SPS/PPS:
        //   isKeyFrame=true (конфигурационные NAL), presentationTimeUs=0 (время запроса незначимо)
        cachedSps?.let {
            val meta = H264Encoder.FrameMetadata(isKeyFrame = true, presentationTimeUs = 0L, sizeBytes = it.size)  // HIGH-7: поле sizeBytes (не size) — соответствует data class
            wsClient.sendBinary(FramePackager.pack(it, meta, streamStartTime))
        }
        cachedPps?.let {
            val meta = H264Encoder.FrameMetadata(isKeyFrame = true, presentationTimeUs = 0L, sizeBytes = it.size)  // HIGH-7
            wsClient.sendBinary(FramePackager.pack(it, meta, streamStartTime))
        }
    }
}
```

---

## Шаг 3 — Backend: Binary WebSocket Handler

```python
# backend/api/v1/streaming/binary_handler.py  — CRIT-1+PROC-3: файл принадлежит TZ-05 (не TZ-03!)
# Старый путь backend/api/ws/android.py взят у TZ-03 — он не принадлежит TZ-05.
async def handle_agent_binary(device_id: str, data: bytes, stream_bridge: VideoStreamBridge):
    """Принять H.264 фрейм от агента, направить viewer'у."""
    if len(data) < 10:
        return  # Слишком маленький — не наш формат
    
    version = data[0]
    if version != 0x01:
        logger.warning(f"Unknown frame version {version}")
        return
    
    flags = data[1]
    timestamp = int.from_bytes(data[2:6], "big")
    frame_size = int.from_bytes(data[6:10], "big")
    
    if len(data) != 10 + frame_size:
        logger.warning(f"Frame size mismatch: expected {frame_size}, got {len(data)-10}")
        return
    
    await stream_bridge.handle_agent_frame(device_id, data)
```

---

## Шаг 4 — Viewer WebSocket (получение потока)

```python
# backend/api/ws/stream/router.py  — HIGH-4: выделен в подпакет stream/ (освобождает имён для stream/__init__.py, stream/schemas.py)
@router.websocket("/ws/stream/{device_id}")
async def stream_viewer_ws(
    ws: WebSocket,
    device_id: str,
    db: AsyncSession = Depends(get_db),
    stream_bridge: VideoStreamBridge = Depends(get_stream_bridge),
):
    await ws.accept()
    
    # Auth
    try:
        first = await asyncio.wait_for(ws.receive_json(), timeout=10.0)
        user = await authenticate_ws_token(first.get("token", ""), db)
    except (asyncio.TimeoutError, HTTPException):
        await ws.close(code=4001)
        return
    
    # Зарегистрировать viewer
    session_id = secrets.token_hex(8)
    await stream_bridge.register_viewer(device_id, ws, session_id)
    
    # Сообщить агенту о новом viewer (для SPS/PPS replay + I-frame)
    await manager.send_to_device(device_id, {
        "type": "viewer_connected",
        "session_id": session_id,
    })
    
    try:
        while True:
            data = await ws.receive_json()
            match data.get("type"):
                case "click":
                    # Конвертировать координаты viewer → device координаты
                    await handle_viewer_click(device_id, data, user)
                case "request_keyframe":
                    await manager.send_to_device(device_id, {"type": "request_keyframe"})
    except WebSocketDisconnect:
        pass
    finally:
        await stream_bridge.unregister_viewer(device_id)
```

---

## Критерии готовности

- [ ] Binary header версия: неверная версия → фрейм отброшен без краша
- [ ] Frame size mismatch → Warning лог, фрейм пропущен
- [ ] Новый viewer: SPS/PPS отправляются до первого P-frame
- [ ] I-frame запрашивается при подключении нового viewer
- [ ] Viewer click → конвертируется в tap команду для агента
- [ ] Latency end-to-end (screen → browser): ≤ 300ms на LAN
