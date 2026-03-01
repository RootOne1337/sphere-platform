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

      // FIX-CLOUDFLARE: Общая функция создания WS (для initial и reconnect).
      // Decoder НЕ пересоздаётся при reconnect — сохраняет SPS/PPS конфигурацию.
      // Бэкенд шлёт кэшированные SPS→PPS→IDR при register_viewer, что позволяет
      // декодеру показать картинку без ожидания нового IDR от агента.
      const createWs = () => {
        if (ignore) return;
        const newWs = new WebSocket(wsUrl);
        newWs.binaryType = 'arraybuffer';
        ws = newWs;
        wsRef.current = newWs;

        newWs.onopen = () => {
          newWs.send(JSON.stringify({ token: accessToken }));
        };
        newWs.onmessage = (evt) => {
          if (evt.data instanceof ArrayBuffer) {
            decoder?.handleBinary(evt.data);
          }
          // Сервер шлёт JSON ping — отвечаем pong для keepalive через Cloudflare
          if (typeof evt.data === 'string') {
            try {
              const msg = JSON.parse(evt.data);
              if (msg.type === 'ping') {
                newWs.send(JSON.stringify({ type: 'pong' }));
              }
            } catch { /* не JSON binary — игнорируем */ }
          }
        };
        newWs.onclose = (event) => {
          const isAuthError = [4001, 4003, 4004].includes(event.code);
          if (!ignore && event.code !== 1000 && !isAuthError) {
            // FIX-CLOUDFLARE: Aggressive reconnect — Cloudflare Quick Tunnel дропает
            // WS через 5-50 секунд. Быстрый backoff: 500ms → 1s → 2s → ... → max 5s.
            let attempt = 0;
            const maxAttempts = 100; // Бесконечный reconnect пока компонент жив
            const tryReconnect = () => {
              if (ignore || attempt >= maxAttempts) return;
              const backoff = Math.min(500 * Math.pow(1.5, attempt), 5000);
              attempt++;
              setTimeout(() => {
                if (ignore) return;
                createWs();
              }, backoff);
            };
            tryReconnect();
          }
        };
        newWs.onerror = () => {};
      };

      createWs();
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
