# SPLIT-3 — Remote View (H.264 WebCodecs + Fleet Grid)

**ТЗ-родитель:** TZ-10-Web-Frontend  
**Ветка:** `stage/10-frontend`  
**Задача:** `SPHERE-053`  
**Исполнитель:** Frontend  
**Оценка:** 2 дня  
**Блокирует:** TZ-10 SPLIT-4

---

## Цель Сплита

Страница удалённого просмотра устройства: H.264 декодирование через WebCodecs, canvas-click → tap on device, и fleet grid для одновременного просмотра нескольких устройств.

---

## Шаг 0.5 — API типы из OpenAPI (PROC-4)

```bash
# Генерация TypeScript-типов из OpenAPI схемы (backend экспортирует при startup)
npx openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts
```

> Все API-вызовы используют сгенерированные типы, не ручные `interface`. Добавить в `package.json`:
> ```json
> "scripts": { "gen:types": "openapi-typescript http://localhost:8000/openapi.json -o src/api/types.ts" }
> ```

---

## Шаг 1 — H264Decoder (WebCodecs API)

> **ВАЖНО:** Каноническая реализация H264Decoder находится в TZ-05 SPLIT-5.
> При merge веток использовать **только TZ-05 версию** (`lib/streaming/H264Decoder.ts`).
> Ниже — облегчённый вариант для независимой разработки frontend; при интеграции заменяется на import из TZ-05.

```typescript
// lib/h264-decoder.ts
// MED-8: ТЕМПОРАЛЬНАЯ ВЕРСИЯ — при merge заменить на канонический import:
// import { H264Decoder } from "@/lib/streaming/H264Decoder";  // из TZ-05 SPLIT-5
// НИЖЕ — облегчённый вариант для независимой разработки frontend:
export type FrameCallback = (frame: VideoFrame) => void;

const FRAME_HEADER_SIZE = 10; // version(1) + flags(1) + ts(4) + size(4)

export class H264Decoder {
    private decoder: VideoDecoder | null = null;
    private configured = false;
    private pendingFrames: Uint8Array[] = [];
    private onFrame: FrameCallback;
    
    constructor(onFrame: FrameCallback) {
        this.onFrame = onFrame;
    }
    
    init() {
        this.decoder = new VideoDecoder({
            output: (frame) => {
                this.onFrame(frame);
                frame.close(); // Обязательно освобождаем память
            },
            error: (e) => console.error('VideoDecoder error:', e),
        });
    }
    
    private configure(spsNal: Uint8Array, ppsNal: Uint8Array) {
        if (!this.decoder) return;
        
        // AVC Decoder Configuration Record
        const extradata = buildAVCCExtradata(spsNal, ppsNal);
        
        this.decoder.configure({
            codec: 'avc1.42E01F',  // FIX: Level 3.1 (было 3.0=42E01E) — соответствует encoder TZ-05 SPLIT-2 (Baseline Level 3.1)
            hardwareAcceleration: 'prefer-hardware',
            optimizeForLatency: true,
            description: extradata,
        });
        this.configured = true;
        
        // Процессировать накопившиеся кадры
        this.pendingFrames.forEach(f => this.decodeFrame(f));
        this.pendingFrames = [];
    }
    
    handleBinary(data: ArrayBuffer) {
        const view = new DataView(data);
        if (view.byteLength < FRAME_HEADER_SIZE) return;
        
        const version = view.getUint8(0);
        if (version !== 1) return;
        
        const flags = view.getUint8(1);
        const timestamp = view.getUint32(2, false);
        // size at offset 6 — skip, use actual buffer length
        
        const nalData = new Uint8Array(data, FRAME_HEADER_SIZE);
        const nalType = nalData[0] & 0x1f;
        
        if (nalType === 7 || nalType === 8) {
            // SPS (7) или PPS (8) — пока ждём оба
            // Реальная логика — накапливаем SPS/PPS и вызываем configure
            this.handleSPSPPS(nalType, nalData);
            return;
        }
        
        if (!this.configured) {
            this.pendingFrames.push(nalData);
            return;
        }
        
        this.decodeFrame(nalData);
    }
    
    private spsNal: Uint8Array | null = null;
    private ppsNal: Uint8Array | null = null;
    
    private handleSPSPPS(nalType: number, nal: Uint8Array) {
        if (nalType === 7) this.spsNal = nal;
        if (nalType === 8) this.ppsNal = nal;
        if (this.spsNal && this.ppsNal) {
            this.configure(this.spsNal, this.ppsNal);
        }
    }
    
    private decodeFrame(nal: Uint8Array) {
        if (!this.decoder || !this.configured) return;
        
        // Обернуть в Annex B (добавить start code 0x00000001)
        const annexB = new Uint8Array(4 + nal.length);
        annexB[3] = 1;
        annexB.set(nal, 4);
        
        const isKeyFrame = (nal[0] & 0x1f) === 5;
        
        this.decoder.decode(new EncodedVideoChunk({
            type: isKeyFrame ? 'key' : 'delta',
            timestamp: performance.now() * 1000,
            data: annexB,
        }));
    }
    
    destroy() {
        this.decoder?.close();
        this.decoder = null;
    }
}

function buildAVCCExtradata(sps: Uint8Array, pps: Uint8Array): Uint8Array {
    // AVCDecoderConfigurationRecord
    const buf = new Uint8Array(11 + sps.length + pps.length);
    let off = 0;
    buf[off++] = 1;           // configurationVersion
    buf[off++] = sps[1];      // AVCProfileIndication
    buf[off++] = sps[2];      // profile_compatibility
    buf[off++] = sps[3];      // AVCLevelIndication
    buf[off++] = 0xff;        // lengthSizeMinusOne = 3
    buf[off++] = 0xe1;        // numSequenceParameterSets = 1
    buf[off++] = (sps.length >> 8) & 0xff;
    buf[off++] = sps.length & 0xff;
    buf.set(sps, off); off += sps.length;
    buf[off++] = 1;            // numPictureParameterSets
    buf[off++] = (pps.length >> 8) & 0xff;
    buf[off++] = pps.length & 0xff;
    buf.set(pps, off);
    return buf;
}
```

---

## Шаг 2 — DeviceStream Component

```tsx
// components/sphere/DeviceStream.tsx
'use client';
import { useEffect, useRef, useCallback } from 'react';
import { H264Decoder } from '@/lib/h264-decoder';
import { useAuthStore } from '@/lib/store';

interface DeviceStreamProps {
    deviceId: string;
    width?: number;
    height?: number;
    onTap?: (x: number, y: number) => void;
}

export function DeviceStream({ deviceId, width = 360, height = 640, onTap }: DeviceStreamProps) {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const wsRef = useRef<WebSocket | null>(null);
    const decoderRef = useRef<H264Decoder | null>(null);
    
    const { accessToken } = useAuthStore();
    
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        
        const ctx = canvas.getContext('2d')!;
        
        const decoder = new H264Decoder((frame) => {
            ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        });
        decoder.init();
        decoderRef.current = decoder;
        
        const apiBase = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000';
        const wsUrl = apiBase.replace('http', 'ws') + `/ws/stream/${deviceId}`;
        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;
        
        ws.onopen = () => {
            // First-message auth
            ws.send(JSON.stringify({ token: accessToken }));
        };
        ws.onmessage = (evt) => {
            if (evt.data instanceof ArrayBuffer) {
                decoder.handleBinary(evt.data);
            }
        };
        ws.binaryType = 'arraybuffer';
        
        return () => {
            ws.close();
            decoder.destroy();
        };
    }, [deviceId, accessToken]);
    
    const handleClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
        const canvas = canvasRef.current;
        if (!canvas || !onTap) return;
        
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        
        const x = Math.round((e.clientX - rect.left) * scaleX);
        const y = Math.round((e.clientY - rect.top) * scaleY);
        
        // Отправить tap через REST (или WS)
        onTap(x, y);
        wsRef.current?.send(JSON.stringify({ type: 'tap', x, y }));
    }, [onTap]);
    
    return (
        <canvas
            ref={canvasRef}
            width={width}
            height={height}
            onClick={handleClick}
            className="cursor-pointer rounded border border-gray-700 bg-black"
            style={{ width: '100%', height: 'auto' }}
        />
    );
}
```

---

## Шаг 3 — Fleet Grid (несколько устройств)

```tsx
// app/(dashboard)/stream/page.tsx
'use client';
import { useState } from 'react';
import { DeviceStream } from '@/components/sphere/DeviceStream';
import { useDevices } from '@/lib/hooks/useDevices';

const GRID_SIZES = [1, 2, 4, 6, 9] as const;

export default function FleetStreamPage() {
    const [gridSize, setGridSize] = useState<typeof GRID_SIZES[number]>(4);
    const { data } = useDevices({ status: 'online', page_size: 9 });
    const devices = data?.items ?? [];
    
    const cols = gridSize <= 2 ? gridSize : gridSize <= 4 ? 2 : 3;
    
    return (
        <div className="p-4 space-y-4">
            <div className="flex gap-2 items-center">
                <span className="text-sm text-muted-foreground">Grid:</span>
                {GRID_SIZES.map(s => (
                    <button
                        key={s}
                        onClick={() => setGridSize(s)}
                        className={`px-2 py-1 rounded text-sm ${gridSize === s ? 'bg-primary text-primary-foreground' : 'bg-secondary'}`}
                    >
                        {s}x
                    </button>
                ))}
            </div>
            
            <div
                className="grid gap-2"
                style={{ gridTemplateColumns: `repeat(${cols}, 1fr)` }}
            >
                {devices.slice(0, gridSize).map(device => (
                    <div key={device.id} className="space-y-1">
                        <p className="text-xs text-muted-foreground truncate">{device.name}</p>
                        <DeviceStream deviceId={device.id} width={720} height={1280} />
                    </div>
                ))}
            </div>
        </div>
    );
}
```

---

## Критерии готовности

- [ ] `frame.close()` вызывается после drawImage (утечки памяти нет)
- [ ] Annex B start code `0x00000001` добавляется перед каждым NAL unit
- [ ] `optimizeForLatency: true` в VideoDecoder.configure()
- [ ] Canvas click → координаты масштабируются с учётом CSS scale (getBoundingClientRect)
- [ ] WS binary type = `arraybuffer` (не Blob)
- [ ] Decoder.destroy() вызывается в useEffect cleanup
