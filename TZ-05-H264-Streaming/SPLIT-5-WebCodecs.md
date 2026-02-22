# SPLIT-5 — WebCodecs Frontend Decoder

**ТЗ-родитель:** TZ-05-H264-Streaming  
**Ветка:** `stage/5-streaming`  
**Задача:** `SPHERE-030`  
**Исполнитель:** Frontend (TypeScript)  
**Оценка:** 1.5 дня  
**Блокирует:** —
**Интеграция при merge:** TZ-10 SPLIT-3 использует этот H264Decoder; при merge удалить дубль из TZ-10

> [!WARNING]
> **MERGE-5: При merge `stage/5-streaming` + `stage/10-frontend`:**
>
> 1. **Удалить** `frontend/src/lib/h264-decoder.ts` (темпоральная копия из TZ-10 SPLIT-3)
> 2. **Обновить импорты** в `components/sphere/DeviceStream.tsx`:
>
>    ```diff
>    -import { H264Decoder } from '@/lib/h264-decoder';
>    +import { H264Decoder } from '@/lib/streaming/H264Decoder';
>    ```
>
> 3. **Адаптировать API**: TZ-05 версия принимает `canvas` в конструкторе, TZ-10 — `onFrame` callback.
>    Использовать **TZ-05 версию** (она полнее: auth, reconnect, stats).
> 4. **Удалить** `buildAVCCExtradata()` из TZ-10 — TZ-05 использует SPS напрямую как `description`.

---

## Цель Сплита

Браузерный H.264 декодер через WebCodecs API. Рендеринг в Canvas без Flash/Plugin. Конвертация кликов на canvas → tap команды для агента.

---

## Шаг 1 — H264Decoder Class

```typescript
// frontend/src/lib/streaming/H264Decoder.ts

const FRAME_HEADER_SIZE = 10;

interface FrameHeader {
  version: number;
  isKeyFrame: boolean;
  timestamp: number;
  frameSize: number;
}

function parseHeader(data: ArrayBuffer): FrameHeader | null {
  if (data.byteLength < FRAME_HEADER_SIZE) return null;
  const view = new DataView(data);
  const version = view.getUint8(0);
  if (version !== 0x01) return null;
  
  return {
    version,
    isKeyFrame: (view.getUint8(1) & 0x01) !== 0,
    timestamp: view.getUint32(2, false),  // Big-endian
    frameSize: view.getUint32(6, false),
  };
}

export class H264Decoder {
  private decoder: VideoDecoder | null = null;
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private ws: WebSocket | null = null;
  
  private framesDecoded = 0;
  private frameDrops = 0;
  private configured = false;
  
  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d")!;
  }
  
  async init(deviceId: string, authToken: string): Promise<void> {
    if (!("VideoDecoder" in window)) {
      throw new Error("WebCodecs API not supported. Use Chrome 94+ or Edge 94+");
    }
    
    this.decoder = new VideoDecoder({
      output: (frame: VideoFrame) => this.renderFrame(frame),
      error: (error: Error) => {
        console.error("Decoder error:", error);
        this.reconfigure();
      },
    });
    
    await this.connectWebSocket(deviceId, authToken);
  }
  
  private async connectWebSocket(deviceId: string, token: string): Promise<void> {
    const wsUrl = `${import.meta.env.VITE_WS_URL}/ws/stream/${deviceId}`;
    this.ws = new WebSocket(wsUrl);
    this.ws.binaryType = "arraybuffer";
    
    this.ws.onopen = () => {
      // First-message auth
      this.ws!.send(JSON.stringify({ token, device_id: deviceId }));
    };
    
    this.ws.onmessage = (event: MessageEvent) => {
      if (event.data instanceof ArrayBuffer) {
        this.handleVideoFrame(event.data);
      } else {
        this.handleControlMessage(JSON.parse(event.data as string));
      }
    };
    
    this.ws.onclose = (event: CloseEvent) => {
      console.log(`Stream closed: ${event.code} ${event.reason}`);
      this.onDisconnect?.();
    };
  }
  
  private handleVideoFrame(data: ArrayBuffer): void {
    const header = parseHeader(data);
    if (!header) return;
    
    const nalData = data.slice(FRAME_HEADER_SIZE);
    
    // Конфигурация из SPS/PPS (NAL type 7/8)
    if (!this.configured && this.isSpsOrPps(nalData)) {
      this.configureDecoder(nalData);
      return;
    }
    
    if (!this.configured) return;
    
    const chunk = new EncodedVideoChunk({
      type: header.isKeyFrame ? "key" : "delta",
      timestamp: header.timestamp * 1000,  // мс → мкс
      data: nalData,
    });
    
    try {
      this.decoder!.decode(chunk);
      this.framesDecoded++;
    } catch (e) {
      this.frameDrops++;
      if (this.frameDrops % 30 === 0) {
        console.warn(`Frame drops: ${this.frameDrops}`);
      }
    }
  }
  
  private configureDecoder(spsData: ArrayBuffer): void {
    // Минимальная конфигурация для Baseline Profile
    this.decoder!.configure({
      codec: "avc1.42E01F",  // FIX: Level 3.1 (было 3.0=42E01E) — соответствует encoder AVCLevel31 (TZ-05 SPLIT-2)
      description: new Uint8Array(spsData),
      optimizeForLatency: true,   // Ключевой параметр для real-time!
      hardwareAcceleration: "prefer-hardware",
    });
    this.configured = true;
  }
  
  private renderFrame(frame: VideoFrame): void {
    this.canvas.width = frame.displayWidth;
    this.canvas.height = frame.displayHeight;
    this.ctx.drawImage(frame, 0, 0);
    frame.close();  // КРИТИЧНО: освободить память!
  }
  
  private isSpsOrPps(data: ArrayBuffer): boolean {
    const view = new Uint8Array(data);
    if (view.length < 5) return false;
    // Найти start code
    const startCode = view[0] === 0 && view[1] === 0 && view[2] === 0 && view[3] === 1;
    if (!startCode) return false;
    const nalType = view[4] & 0x1F;
    return nalType === 7 || nalType === 8;  // SPS=7, PPS=8
  }
  
  private async reconfigure(): Promise<void> {
    this.configured = false;
    this.decoder?.reset();
    // Запросить I-frame
    this.ws?.send(JSON.stringify({ type: "request_keyframe" }));
  }
  
  // ─── Touch/Click mapping ───
  
  sendTap(canvasX: number, canvasY: number): void {
    const deviceX = Math.round((canvasX / this.canvas.clientWidth) * this.canvas.width);
    const deviceY = Math.round((canvasY / this.canvas.clientHeight) * this.canvas.height);
    
    this.ws?.send(JSON.stringify({
      type: "click",
      x: deviceX,
      y: deviceY,
    }));
  }
  
  destroy(): void {
    this.decoder?.close();
    this.ws?.close();
  }
  
  onDisconnect?: () => void;
  
  get stats() {
    return {
      framesDecoded: this.framesDecoded,
      frameDrops: this.frameDrops,
      dropRatio: this.frameDrops / Math.max(1, this.framesDecoded),
    };
  }
}
```

---

## Шаг 2 — React Component

```tsx
// frontend/src/components/streaming/DeviceStream.tsx
import { useEffect, useRef, useState } from "react";
import { H264Decoder } from "@/lib/streaming/H264Decoder";
import { useAuth } from "@/hooks/useAuth";

interface DeviceStreamProps {
  deviceId: string;
  className?: string;
}

export function DeviceStream({ deviceId, className }: DeviceStreamProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const decoderRef = useRef<H264Decoder | null>(null);
  const { token } = useAuth();
  const [status, setStatus] = useState<"connecting" | "streaming" | "offline">("connecting");
  
  useEffect(() => {
    if (!canvasRef.current || !token) return;
    
    const decoder = new H264Decoder(canvasRef.current);
    decoderRef.current = decoder;
    
    decoder.onDisconnect = () => setStatus("offline");
    
    decoder.init(deviceId, token)
      .then(() => setStatus("streaming"))
      .catch((e) => {
        console.error("Stream init failed:", e);
        setStatus("offline");
      });
    
    return () => decoder.destroy();
  }, [deviceId, token]);
  
  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current!.getBoundingClientRect();
    decoderRef.current?.sendTap(e.clientX - rect.left, e.clientY - rect.top);
  };
  
  return (
    <div className={`relative ${className}`}>
      <canvas
        ref={canvasRef}
        onClick={handleCanvasClick}
        className="w-full h-full cursor-pointer"
        style={{ touchAction: "none" }}
      />
      {status !== "streaming" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 text-white">
          {status === "connecting" ? "Подключение..." : "Оффлайн"}
        </div>
      )}
    </div>
  );
}
```

---

## Критерии готовности

- [ ] `frame.close()` вызывается после каждого renderFrame (нет memory leak)
- [ ] Decoder error → reconfigure() запрашивает keyframe, не крашится
- [ ] `optimizeForLatency: true` включён
- [ ] Canvas click → JSON `{type: "click", x, y}` с правильными device-координатами
- [ ] Chrome 94+: работает; Safari 15.4+: работает; Firefox 130+: работает
- [ ] Скриншот: DrawImage на canvas с видимым изображением (не чёрный экран)
