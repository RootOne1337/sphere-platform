'use client';

import { useEffect, useRef, useCallback, useState } from 'react';
import { H264Decoder } from '@/lib/h264-decoder';
import { useAuthStore } from '@/lib/store';
import { Button } from '@/src/shared/ui/button';
import { ZoomIn, ZoomOut, Maximize, MousePointer2, Move, Activity } from 'lucide-react';

interface DeviceStreamProps {
  deviceId: string;
  onTap?: (x: number, y: number) => void;
}

export function DeviceStream({ deviceId, onTap }: DeviceStreamProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const decoderRef = useRef<H264Decoder | null>(null);

  // Stored Android native resolution
  const nativeRes = useRef({ w: 1080, h: 1920 });

  // Stream telemetry state
  const [fps, setFps] = useState(0);
  const framesRendered = useRef(0);
  const [bitrate, setBitrate] = useState(0);

  // Interaction Mode
  const [mode, setMode] = useState<'pointer' | 'pan'>('pointer');

  // Transformation state
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const isDragging = useRef(false);
  const startPanPt = useRef({ x: 0, y: 0 });
  const startDragPt = useRef({ x: 0, y: 0 }); // for click/swipe calc

  const { accessToken } = useAuthStore();

  useEffect(() => {
    let ignore = false;
    let ws: WebSocket | null = null;
    let decoder: H264Decoder | null = null;
    let lastTime = performance.now();

    const frameCounterInterval = setInterval(() => {
      setFps(framesRendered.current);
      framesRendered.current = 0;
    }, 1000);

    const timer = setTimeout(() => {
      if (ignore) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const ctx = canvas.getContext('2d')!;

      decoder = new H264Decoder((frame) => {
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
          nativeRes.current = { w: frame.displayWidth, h: frame.displayHeight };
        }
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        framesRendered.current++;
      });
      decoder.init();
      decoderRef.current = decoder;

      const wsBase = process.env.NEXT_PUBLIC_WS_URL ??
        (typeof window !== 'undefined'
          ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
          : 'ws://localhost');
      ws = new WebSocket(`${wsBase}/ws/stream/${deviceId}`);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => { ws!.send(JSON.stringify({ token: accessToken })); };
      ws.onmessage = (evt) => {
        if (evt.data instanceof ArrayBuffer) {
          decoder!.handleBinary(evt.data);
          setBitrate(prev => (prev * 0.9) + ((evt.data.byteLength * 8) * 0.1)); // Smooth bitrate
        }
      };
    }, 0);

    // Key handlers for Pan Mode (Spacebar)
    const handleKeyDown = (e: KeyboardEvent) => { if (e.code === 'Space' && document.activeElement?.tagName !== 'INPUT') setMode('pan'); };
    const handleKeyUp = (e: KeyboardEvent) => { if (e.code === 'Space') setMode('pointer'); };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('keyup', handleKeyUp);

    return () => {
      ignore = true;
      clearTimeout(timer);
      clearInterval(frameCounterInterval);
      ws?.close();
      decoder?.destroy();
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('keyup', handleKeyUp);
    };
  }, [deviceId, accessToken]);

  // ── HUD Math ─────────────────────────────────────────────────────────────
  const mbps = (bitrate / 1000000).toFixed(2);

  // ── Coordinates Math (Accounting for Zoom & Pan) ─────────────────────────
  const toNativeCoords = useCallback((clientX: number, clientY: number) => {
    const container = containerRef.current;
    if (!container) return null;
    const rect = container.getBoundingClientRect();

    // Relative position inside container container (0 to 1)
    const relX = (clientX - rect.left - rect.width / 2 - pan.x) / (rect.width * zoom) + 0.5;
    const relY = (clientY - rect.top - rect.height / 2 - pan.y) / (rect.height * zoom) + 0.5;

    // Reject out of bounds
    if (relX < 0 || relX > 1 || relY < 0 || relY > 1) return null;

    // Convert to native android pixels
    return {
      x: Math.round(relX * nativeRes.current.w),
      y: Math.round(relY * nativeRes.current.h),
    };
  }, [zoom, pan]);

  // ── Interaction Handlers ─────────────────────────────────────────────────
  const handleWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    e.preventDefault();
    const zoomDelta = e.deltaY > 0 ? -0.1 : 0.1;
    setZoom((prev) => Math.min(Math.max(0.5, prev + prev * zoomDelta), 5));
  };

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    if (e.button !== 0 && e.button !== 1) return; // Only Left or Middle click

    // Middle click triggers Pan mode temporarily
    const isPanAction = mode === 'pan' || e.button === 1;

    if (isPanAction) {
      isDragging.current = true;
      startPanPt.current = { x: e.clientX - pan.x, y: e.clientY - pan.y };
    } else {
      const pt = toNativeCoords(e.clientX, e.clientY);
      if (pt) startDragPt.current = pt;
    }
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDragging.current) {
      setPan({ x: e.clientX - startPanPt.current.x, y: e.clientY - startPanPt.current.y });
    }
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (isDragging.current) {
      isDragging.current = false;
      return;
    }

    // Android Interaction (Tap / Swipe)
    const start = startDragPt.current;
    if (!start) return;

    const pt = toNativeCoords(e.clientX, e.clientY);
    if (!pt) return;

    const dist = Math.hypot(pt.x - start.x, pt.y - start.y);

    if (dist < 15) {
      // Tap (Tolerate slight movements as tap)
      onTap?.(start.x, start.y);
      wsRef.current?.send(JSON.stringify({ type: 'click', x: start.x, y: start.y }));
    } else {
      // Swipe
      const duration_ms = Math.min(800, Math.max(200, Math.round(dist * 1.2)));
      wsRef.current?.send(
        JSON.stringify({ type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms })
      );
    }

    startDragPt.current = { x: 0, y: 0 };
  };

  return (
    <div className="relative w-full h-full bg-[#050505] overflow-hidden group select-none flex items-center justify-center">

      {/* Interactive Transformable Container */}
      <div
        ref={containerRef}
        onWheel={handleWheel}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={handlePointerUp}
        className={`absolute transition-transform duration-75 ease-out ${mode === 'pan' ? 'cursor-grab active:cursor-grabbing' : 'cursor-crosshair'}`}
        style={{
          transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center'
        }}
      >
        <canvas ref={canvasRef} className="shadow-2xl border border-white/5 bg-black" style={{ maxHeight: '100%', maxWidth: '100%', objectFit: 'contain' }} />
      </div>

      {/* Telemetry Overlay */}
      <div className="absolute top-2 left-2 flex gap-2 pointer-events-none opacity-50 group-hover:opacity-100 transition-opacity">
        <div className="bg-black/60 backdrop-blur border border-white/10 text-[10px] font-mono px-2 py-1 flex items-center gap-2 rounded-sm text-muted-foreground">
          <Activity className="w-3 h-3 text-primary" />
          <span>{fps} FPS</span>
          <span className="text-white/20">|</span>
          <span>{mbps} Mbps</span>
          <span className="text-white/20">|</span>
          <span className="text-white/50">{nativeRes.current.w}x{nativeRes.current.h}</span>
        </div>
      </div>

      {/* Floating Toolbar */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1 p-1 rounded-sm bg-black/60 backdrop-blur border border-white/10 shadow-2xl opacity-0 group-hover:opacity-100 transition-opacity translate-y-2 group-hover:translate-y-0 duration-300">
        <Button variant="ghost" size="icon" className={`h-8 w-8 rounded-sm ${mode === 'pointer' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-white'}`} onClick={() => setMode('pointer')} title="Interaction Mode (Android)">
          <MousePointer2 className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="icon" className={`h-8 w-8 rounded-sm ${mode === 'pan' ? 'bg-primary/20 text-primary' : 'text-muted-foreground hover:text-white'}`} onClick={() => setMode('pan')} title="Pan Mode (Hold Space)">
          <Move className="w-4 h-4" />
        </Button>
        <div className="w-[1px] h-4 bg-white/20 mx-1" />
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-sm text-muted-foreground hover:text-white" onClick={() => setZoom(z => Math.max(0.5, z - 0.2))}>
          <ZoomOut className="w-4 h-4" />
        </Button>
        <div className="text-[10px] font-mono w-10 text-center text-muted-foreground select-none">
          {Math.round(zoom * 100)}%
        </div>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-sm text-muted-foreground hover:text-white" onClick={() => setZoom(z => Math.min(5, z + 0.2))}>
          <ZoomIn className="w-4 h-4" />
        </Button>
        <Button variant="ghost" size="icon" className="h-8 w-8 rounded-sm text-muted-foreground hover:text-white" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} title="Reset View">
          <Maximize className="w-4 h-4" />
        </Button>
      </div>
    </div>
  );
}
