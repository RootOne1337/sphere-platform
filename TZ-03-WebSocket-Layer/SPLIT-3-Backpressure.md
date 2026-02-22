# SPLIT-3 — Backpressure & Frame Drop (Управление потоком данных)

**ТЗ-родитель:** TZ-03-WebSocket-Layer  
**Ветка:** `stage/3-websocket`  
**Задача:** `SPHERE-018`  
**Исполнитель:** Backend  
**Оценка:** 1 день  
**Блокирует:** TZ-03 SPLIT-4, SPLIT-5
**Интеграция при merge:** TZ-05 H.264 работает с собственным backpressure; при merge унифицировать

---

## Цель Сплита

Предотвратить переполнение буфера при медленном клиенте. Dropping стратегия для видеопотока с принудительным сохранением I-frame.

---

## Шаг 1 — Typed Frame Schema

```python
# backend/websocket/frames.py
from enum import IntEnum

class FrameType(IntEnum):
    """H.264 NAL unit types для приоритизации."""
    IDR_SLICE = 5    # I-frame — ключевой, НЕЛЬЗЯ дropать
    NON_IDR = 1     # P-frame — можно дропать
    SEI = 6          # SEI metadata — можно дропать
    SPS = 7          # SPS — критично для декодера
    PPS = 8          # PPS — критично для декодера
    UNKNOWN = 0

def detect_nal_type(data: bytes) -> FrameType:
    """Определить тип NAL unit по первым байтам (после start code)."""
    if len(data) < 5:
        return FrameType.UNKNOWN
    
    # Найти start code 0x00 0x00 0x00 0x01
    start = -1
    for i in range(len(data) - 4):
        if data[i:i+4] == b'\x00\x00\x00\x01':
            start = i + 4
            break
    
    if start == -1 or start >= len(data):
        return FrameType.UNKNOWN
    
    nal_unit_type = data[start] & 0x1F
    try:
        return FrameType(nal_unit_type)
    except ValueError:
        return FrameType.UNKNOWN

class VideoFrame:
    __slots__ = ("data", "nal_type", "timestamp", "device_id")
    
    def __init__(self, data: bytes, device_id: str):
        self.data = data
        self.device_id = device_id
        self.nal_type = detect_nal_type(data)
        self.timestamp = time.monotonic()
    
    @property
    def is_critical(self) -> bool:
        """I-frame, SPS, PPS — нельзя дропать."""
        return self.nal_type in (FrameType.IDR_SLICE, FrameType.SPS, FrameType.PPS)
    
    @property
    def size_kb(self) -> float:
        return len(self.data) / 1024
```

---

## Шаг 2 — Bounded Video Queue с Drop Strategy

```python
# backend/websocket/video_queue.py
import asyncio
import structlog
from collections import deque

logger = structlog.get_logger()

class VideoStreamQueue:
    """
    Очередь с backpressure для видеопотока.
    
    Стратегия дропа при переполнении:
    1. Дроп устаревших P-frames сначала
    2. SEI metadata дропается первым
    3. I-frames (IDR/SPS/PPS) НИКОГДА не дропаются
    """
    
    MAX_SIZE = 50         # Макс фреймов в буфере
    MAX_LATENCY_MS = 200  # Дроп фреймов старше 200ms
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self._queue: deque[VideoFrame] = deque()
        self._lock = asyncio.Lock()
        
        # Метрики
        self.frames_queued = 0
        self.frames_dropped = 0
        self.frames_sent = 0
    
    async def put(self, frame: VideoFrame) -> bool:
        """
        Добавить фрейм. Returns True если добавлен, False если дропнут.
        """
        async with self._lock:
            # Сначала выбросить устаревшие фреймы
            await self._evict_stale()
            
            if len(self._queue) >= self.MAX_SIZE:
                # Очередь полная — нужно дропнуть что-то
                dropped = await self._drop_one_droppable()
                if not dropped and not frame.is_critical:
                    # Нет что дропать, дропаем входящий P-frame
                    self.frames_dropped += 1
                    logger.debug("Frame dropped (queue full)", 
                                device_id=self.device_id, nal_type=frame.nal_type)
                    return False
            
            self._queue.append(frame)
            self.frames_queued += 1
            return True
    
    async def get(self) -> VideoFrame | None:
        """Неблокирующее получение следующего фрейма."""
        async with self._lock:
            if not self._queue:
                return None
            frame = self._queue.popleft()
            self.frames_sent += 1
            return frame
    
    async def _evict_stale(self):
        """Удалить P-frames старше MAX_LATENCY_MS."""
        now = time.monotonic()
        stale_count = 0
        fresh_queue: deque[VideoFrame] = deque()
        
        for frame in self._queue:
            age_ms = (now - frame.timestamp) * 1000
            if not frame.is_critical and age_ms > self.MAX_LATENCY_MS:
                self.frames_dropped += 1
                stale_count += 1
            else:
                fresh_queue.append(frame)
        
        if stale_count > 0:
            self._queue = fresh_queue
            logger.debug("Evicted stale frames", device_id=self.device_id, count=stale_count)
    
    async def _drop_one_droppable(self) -> bool:
        """Дропнуть один не-критичный фрейм из очереди. Returns True если дропнул."""
        # Дропаем первый SEI или P-frame
        for i, frame in enumerate(self._queue):
            if not frame.is_critical:
                del self._queue[i]  # deque поддерживает O(n)
                self.frames_dropped += 1
                return True
        return False
    
    @property
    def drop_ratio(self) -> float:
        total = self.frames_queued
        return self.frames_dropped / total if total > 0 else 0.0
```

---

## Шаг 3 — StreamBridge: Agent → Viewer

```python
# backend/websocket/stream_bridge.py
class VideoStreamBridge:
    """Мост от Android агента к viewer'у (браузер)."""
    
    def __init__(self, manager: ConnectionManager):
        self.manager = manager
        self._queues: dict[str, VideoStreamQueue] = {}
        self._viewer_sockets: dict[str, WebSocket] = {}
        self._viewer_tasks: dict[str, asyncio.Task] = {}
    
    async def register_viewer(self, device_id: str, viewer_ws: WebSocket, session_id: str):
        """Зарегистрировать viewer для получения потока."""
        self._queues[device_id] = VideoStreamQueue(device_id)
        self._viewer_sockets[device_id] = viewer_ws
        
        # FIX-3.1: Спавним отдельную Task для каждого viewer.
        # Эта Task в цикле читает из очереди и шлёт фреймы — медленный viewer
        # НЕ блокирует чтение от агента.
        task = asyncio.create_task(self._viewer_send_loop(device_id))
        self._viewer_tasks[device_id] = task
        
        # Запросить агента начать стриминг
        await self.manager.send_to_device(device_id, {
            "type": "start_stream",
            "quality": "720p",
            "bitrate": 2_000_000,
        })
    
    async def unregister_viewer(self, device_id: str):
        # Остановить фоновую задачу viewer'а
        task = self._viewer_tasks.pop(device_id, None)
        if task:
            task.cancel()
        self._queues.pop(device_id, None)
        self._viewer_sockets.pop(device_id, None)
        await self.manager.send_to_device(device_id, {"type": "stop_stream"})
    
    async def handle_agent_frame(self, device_id: str, frame_data: bytes):
        """
        Принять фрейм от агента. ТОЛЬКО кладёт в очередь — НЕ шлёт напрямую!
        FIX-3.1: Прямая отправка блокировала цикл поллинга агента.
        """
        queue = self._queues.get(device_id)
        if not queue:
            return  # Нет viewer'а
        
        frame = VideoFrame(frame_data, device_id)
        await queue.put(frame)
    
    async def _viewer_send_loop(self, device_id: str):
        """
        FIX-3.1: Фоновая задача — читает из очереди и шлёт viewer'у.
        Полностью развязывает Producer (агент) и Consumer (браузер).
        """
        queue = self._queues.get(device_id)
        viewer_ws = self._viewer_sockets.get(device_id)
        if not queue or not viewer_ws:
            return
        
        try:
            while True:
                frame = await queue.get()
                if frame is None:
                    # Пустая очередь — подождать немного
                    await asyncio.sleep(0.005)  # 5ms — не грузить CPU
                    continue
                try:
                    await viewer_ws.send_bytes(frame.data)
                except Exception:
                    await self.unregister_viewer(device_id)
                    return
        except asyncio.CancelledError:
            pass  # Нормальное завершение при unregister
```

---

## MERGE-1: Интеграция с TZ-05 SPLIT-4 Frame Drop

> [!IMPORTANT]
> **При merge `stage/3-websocket` + `stage/5-streaming`:**
>
> `VideoStreamQueue` (этот файл) = **L2 server-side backpressure**.  
> `FrameThrottle` (TZ-05 SPLIT-4) = **L1 agent-side throttle**.
>
> Это **двухуровневый pipeline**, НЕ дублирование:
>
> - L1 (Android) → ограничивает FPS перед отправкой в WS
> - L2 (Backend) → дропает stale P-frames при медленном viewer
>
> **При merge оба компонента сохраняются. Конфликтов нет.**

---

## Критерии готовности

- [ ] При медленном viewer: P-frames дропаются, I-frames доставляются всегда
- [ ] Фреймы старше 200ms дропаются автоматически (evict_stale)
- [ ] `drop_ratio` возвращает реальный процент дропов
- [ ] Нет блокировки event loop при работе с очередью (asyncio.Lock, не threading.Lock)
- [ ] SPS/PPS фреймы НИКОГДА не дропаются
- [ ] 30fps входящий поток, медленный viewer → queue не растёт бесконечно
