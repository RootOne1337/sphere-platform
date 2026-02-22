# SPLIT-4 — Frame Drop & Quality Control

**ТЗ-родитель:** TZ-05-H264-Streaming  
**Ветка:** `stage/5-streaming`  
**Задача:** `SPHERE-029`  
**Исполнитель:** Android + Backend  
**Оценка:** 0.5 дня  
**Блокирует:** TZ-05 SPLIT-5 (Frontend decoder)

---

## Цель Сплита

Управление качеством на стороне Android при нехватке QoS. Throttle на уровне Surface. Метрики качества потока доступны для мониторинга.

---

## Шаг 1 — Android-side Frame Throttle

```kotlin
// AndroidAgent/streaming/FrameThrottle.kt
class FrameThrottle(
    private val targetFps: Int = 30,
) {
    private val frameDurationNs = 1_000_000_000L / targetFps
    private var lastFrameTimeNs = 0L
    private var droppedFrames = 0
    private var totalFrames = 0
    
    /**
     * Returns true если фрейм нужно рендерить, false если пропустить.
     * Вызывается в Choreographer.FrameCallback.
     */
    fun shouldRenderFrame(frameTimeNs: Long): Boolean {
        totalFrames++
        val elapsed = frameTimeNs - lastFrameTimeNs
        
        if (elapsed < frameDurationNs * 0.8) {
            // Слишком быстро — пропустить
            droppedFrames++
            return false
        }
        
        lastFrameTimeNs = frameTimeNs
        return true
    }
    
    val dropRatio: Float get() = droppedFrames.toFloat() / totalFrames.coerceAtLeast(1)
}
```

---

## Шаг 2 — Streaming Quality Monitor

```kotlin
// AndroidAgent/streaming/StreamQualityMonitor.kt
class StreamQualityMonitor {
    private val frameTimestamps = ArrayDeque<Long>()
    private var bytesSentTotal = 0L
    private var frameCount = 0
    private var keyFrameCount = 0
    
    fun recordFrame(sizeBytes: Int, isKeyFrame: Boolean) {
        val now = SystemClock.elapsedRealtime()
        frameTimestamps.add(now)
        // Удалить фреймы старше 1 секунды
        while (frameTimestamps.isNotEmpty() && (now - frameTimestamps.first()) > 1000) {
            frameTimestamps.removeFirst()
        }
        bytesSentTotal += sizeBytes
        frameCount++
        if (isKeyFrame) keyFrameCount++
    }
    
    fun getStats(): StreamStats = StreamStats(
        currentFps = frameTimestamps.size,
        totalFrames = frameCount,
        totalBytesSent = bytesSentTotal,
        keyFrameRatio = keyFrameCount.toFloat() / frameCount.coerceAtLeast(1),
        avgFrameSizeKb = if (frameCount > 0) (bytesSentTotal / frameCount / 1024f) else 0f,
    )
    
    data class StreamStats(
        val currentFps: Int,
        val totalFrames: Int,
        val totalBytesSent: Long,
        val keyFrameRatio: Float,
        val avgFrameSizeKb: Float,
    )
}
```

---

## Шаг 3 — Telemetry в Heartbeat Pong

```kotlin
// Добавить в HeartbeatHandler
fun handlePing(pingMsg: JsonObject) {
    val stats = streamQualityMonitor.getStats()
    
    val response = buildJsonObject {
        put("type", "pong")
        put("ts", pingMsg["ts"]?.jsonPrimitive?.doubleOrNull ?: 0.0)
        put("battery", deviceStatusProvider.getBatteryLevel())
        put("cpu", deviceStatusProvider.getCpuUsage())
        
        // Стриминг телеметрия
        if (streamingManager.isStreaming) {
            putJsonObject("stream") {
                put("fps", stats.currentFps)
                put("bytes_sent", stats.totalBytesSent)
                put("key_frame_ratio", stats.keyFrameRatio)
                put("avg_frame_kb", stats.avgFrameSizeKb)
            }
        }
    }
    wsClient.sendJson(response)
}
```

---

## Шаг 4 — Backend: Stream Quality Metrics

```python
# backend/websocket/stream_metrics.py
# HIGH-1: импортируем метрики из backend/metrics.py (канонический реестр TZ-11)
# Копировать их ЗДЕСЬ — это дублирование — DUPLICATE при регистрации metric с одинаковым именем!
from backend.metrics import (
    stream_fps as sphere_stream_fps,
    stream_bitrate_kbps as sphere_stream_bitrate_kbps,
    stream_frame_drops_total as sphere_stream_frame_drops_total,
    cleanup_stream_metrics,
)

class StreamMetrics:
    def __init__(self, device_id: str):
        self.device_id = device_id
    
    def record_frame(self, frame_size: int, is_key_frame: bool):
        sphere_stream_fps.labels(device_id=self.device_id).set(0)  # обновляется из pong телеметрики
        
    def update_from_pong(self, stream_data: dict):
        if not stream_data:
            return
        sphere_stream_fps.labels(device_id=self.device_id).set(
            stream_data.get("fps", 0)
        )
        sphere_stream_frame_drops_total.labels(device_id=self.device_id).inc(
            max(0, 30 - stream_data.get("fps", 30))  # приблизительное число дропов
        )
    
    def cleanup(self):
        """Cleanup при остановке стриминга — вызывать из StreamingManager.stop()"""
        cleanup_stream_metrics(self.device_id)
```

---

## MERGE-1: Интеграция с TZ-03 SPLIT-3 Backpressure

> [!IMPORTANT]
> **При merge `stage/5-streaming` + `stage/3-websocket`:**
>
> TZ-05 и TZ-03 реализуют backpressure на РАЗНЫХ уровнях — это НЕ дублирование, а **двухуровневый pipeline**:
>
> | Уровень | Компонент | Где работает | Что делает |
> |---------|-----------|-------------|-----------|
> | L1 — Источник | `FrameThrottle` (TZ-05 SPLIT-4) | Android-агент | Throttle по FPS (60→30) до отправки в WS |
> | L2 — Транзит | `VideoStreamQueue` (TZ-03 SPLIT-3) | Backend сервер | Drop P-frames при медленном viewer |
>
> **Действия при merge:**
>
> 1. `FrameThrottle` остаётся в `AndroidAgent/streaming/` — agent-side throttle
> 2. `VideoStreamQueue` остаётся в `backend/websocket/video_queue.py` — server-side backpressure
> 3. `StreamQualityMonitor.getStats()` → передаётся в heartbeat pong → `StreamMetrics.update_from_pong()` (TZ-05 SPLIT-4 Шаг 4)
> 4. **НЕ НУЖНО:** дублировать FrameType enum из TZ-03 в Android (Android использует MediaCodec NAL types)
>
> ```
> [Android FrameThrottle] → WS → [Backend VideoStreamQueue] → WS → [Browser WebCodecs]
>        L1: fps cap                    L2: drop stale P-frames
> ```

---

## Критерии готовности

- [ ] FrameThrottle: при 60fps источнике + target 30fps → ~50% фреймов пропускаются
- [ ] StreamQualityMonitor: FPS рассчитывается за скользящее окно 1 секунда
- [ ] Heartbeat pong включает streaming метрики (fps, bytes, key_frame_ratio)
- [ ] Prometheus метрики для каждого device_id
- [ ] Drop ratio > 0.3 → AdaptiveBitrate снижает bitrate автоматически
