'use client';
import { useEffect, useRef, useCallback } from 'react';
import { H264Decoder } from '@/lib/h264-decoder';
import { useAuthStore } from '@/lib/store';

interface DeviceStreamProps {
  deviceId: string;
  onTap?: (x: number, y: number) => void;
}

export function DeviceStream({
  deviceId,
  onTap,
}: DeviceStreamProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const decoderRef = useRef<H264Decoder | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const { accessToken } = useAuthStore();

  useEffect(() => {
    // Defer WS creation by one tick to avoid React StrictMode double-invoke.
    let ignore = false;
    let ws: WebSocket | null = null;
    let decoder: H264Decoder | null = null;

    const timer = setTimeout(() => {
      if (ignore) return;

      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d')!;

      decoder = new H264Decoder((frame) => {
        // Mutate canvas directly for performance, avoid React state re-renders
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
      });
      decoder.init();
      decoderRef.current = decoder;

      const wsBase = process.env.NEXT_PUBLIC_WS_URL ??
        (typeof window !== 'undefined'
          ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
          : 'ws://localhost');
      const wsUrl = `${wsBase}/ws/stream/${deviceId}`;
      ws = new WebSocket(wsUrl);
      ws.binaryType = 'arraybuffer';
      wsRef.current = ws;

      ws.onopen = () => {
        ws!.send(JSON.stringify({ token: accessToken }));
      };
      ws.onmessage = (evt) => {
        if (evt.data instanceof ArrayBuffer) {
          decoder!.handleBinary(evt.data);
        }
      };
    }, 0);

    return () => {
      ignore = true;
      clearTimeout(timer);
      ws?.close();
      decoder?.destroy();
    };
  }, [deviceId, accessToken]);

  // ── coordinate helpers ───────────────────────────────────────────────────
  const toCanvasCoords = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      return {
        x: Math.round((clientX - rect.left) * (canvas.width / rect.width)),
        y: Math.round((clientY - rect.top) * (canvas.height / rect.height)),
      };
    },
    [],
  );

  // ── pointer down — begin drag / tap ─────────────────────────────────────
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const pt = toCanvasCoords(e.clientX, e.clientY);
      if (!pt) return;
      dragRef.current = pt;
      (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    },
    [toCanvasCoords],
  );

  // ── pointer up — tap or swipe ────────────────────────────────────────────
  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const start = dragRef.current;
      dragRef.current = null;
      if (!start) return;

      const pt = toCanvasCoords(e.clientX, e.clientY);
      if (!pt) return;

      const dist = Math.hypot(pt.x - start.x, pt.y - start.y);

      if (dist < 12) {
        // Tap
        onTap?.(start.x, start.y);
        wsRef.current?.send(JSON.stringify({ type: 'click', x: start.x, y: start.y }));
      } else {
        // Swipe — duration proportional to distance, min 150ms max 600ms
        const duration_ms = Math.min(600, Math.max(150, Math.round(dist * 0.8)));
        wsRef.current?.send(
          JSON.stringify({ type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms }),
        );
      }
    },
    [toCanvasCoords, onTap],
  );

  return (
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      className="cursor-pointer rounded border border-gray-700 bg-black touch-none"
      style={{ width: '100%', height: 'auto' }}
    />
  );
}
