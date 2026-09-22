'use client';
import { useEffect, useRef, useCallback, useState } from 'react';
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
  const [connection, setConnection] = useState<
    'connecting' | 'waiting' | 'live' | 'retrying' | 'unavailable'
  >('connecting');

  useEffect(() => {
    // Defer WS creation by one tick to avoid React StrictMode double-invoke.
    let ignore = false;
    let ws: WebSocket | null = null;
    let decoder: H264Decoder | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let keyFrameTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setInterval> | undefined;
    let scheduleKeyFrameRecovery: ((delayMs?: number) => void) | undefined;
    let attempt = 0;
    setConnection('connecting');

    const timer = setTimeout(() => {
      if (ignore) return;

      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d')!;

      decoder = new H264Decoder((frame) => {
        if (ignore || wsRef.current?.readyState !== WebSocket.OPEN) return;
        setConnection('live');
        clearTimeout(keyFrameTimer);
        // Mutate canvas directly for performance, avoid React state re-renders
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
      }, () => {
        if (ignore) return;
        setConnection('waiting');
        // Кодек может быть исправен, но первый серверный запрос IDR мог
        // прийти до готовности захвата. Повторяем запрос до первого output.
        scheduleKeyFrameRecovery?.();
      });
      decoder.init();
      decoderRef.current = decoder;

      const wsBase = process.env.NEXT_PUBLIC_WS_URL ??
        (typeof window !== 'undefined'
          ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
          : 'ws://localhost');
      const wsUrl = `${wsBase}/ws/stream/${deviceId}`;

      // One connection generation owns its callbacks and timers. A TCP open is
      // not proof of a usable stream: reset backoff only after server traffic.
      const createWs = () => {
        if (ignore) return;
        const newWs = new WebSocket(wsUrl);
        newWs.binaryType = 'arraybuffer';
        ws = newWs;
        wsRef.current = newWs;
        let ended = false;
        let lastReceived = Date.now();
        let opened = false;
        let keyFrameAttempts = 0;
        const requestKeyFrame = () => {
          if (
            ignore || ended || newWs !== wsRef.current || newWs.readyState !== WebSocket.OPEN
          ) return;
          newWs.send(JSON.stringify({ type: 'request_keyframe' }));
          keyFrameAttempts += 1;
          const nextDelay = keyFrameAttempts === 1
            ? 2000
            : Math.min(5000 * 2 ** Math.min(keyFrameAttempts - 2, 2), 20_000);
          keyFrameTimer = setTimeout(requestKeyFrame, nextDelay);
        };
        const scheduleKeyFrameRequests = (delayMs = 1100) => {
          clearTimeout(keyFrameTimer);
          keyFrameAttempts = 0;
          keyFrameTimer = setTimeout(requestKeyFrame, delayMs);
        };
        scheduleKeyFrameRecovery = scheduleKeyFrameRequests;
        const finish = (retry: boolean) => {
          if (ended) return;
          ended = true;
          clearInterval(watchdog);
          clearTimeout(keyFrameTimer);
          if (scheduleKeyFrameRecovery === scheduleKeyFrameRequests) scheduleKeyFrameRecovery = undefined;
          newWs.onopen = newWs.onmessage = newWs.onclose = newWs.onerror = null;
          if (wsRef.current === newWs) wsRef.current = null;
          decoder?.reset();
          if (newWs.readyState === WebSocket.OPEN || newWs.readyState === WebSocket.CONNECTING) {
            newWs.close();
          }
          if (ignore) return;
          setConnection(retry ? 'retrying' : 'unavailable');
          if (retry) {
            const delay = Math.min(500 * 2 ** Math.min(attempt++, 6), 15_000);
            retryTimer = setTimeout(createWs, delay * (0.8 + Math.random() * 0.4));
          }
        };
        watchdog = setInterval(() => {
          if (Date.now() - lastReceived >= (opened ? 30_000 : 15_000)) finish(true);
        }, 5_000);
        newWs.onopen = () => {
          if (ignore || ended) return;
          opened = true;
          lastReceived = Date.now();
          newWs.send(JSON.stringify({ token: accessToken }));
          setConnection('waiting');
          scheduleKeyFrameRequests();
        };
        newWs.onmessage = (evt) => {
          if (ignore || ended) return;
          lastReceived = Date.now();
          attempt = 0;
          if (evt.data instanceof ArrayBuffer) decoder?.handleBinary(evt.data);
          if (typeof evt.data === 'string') {
            try {
              const msg = JSON.parse(evt.data);
              if (msg.type === 'ping' && newWs.readyState === WebSocket.OPEN) {
                newWs.send(JSON.stringify({ type: 'pong' }));
              }
            } catch { /* Ignore malformed control messages. */ }
          }
        };
        // A remote normal close can be a server restart. Only effect cleanup
        // means the user stopped viewing; access/device rejections remain terminal.
        newWs.onclose = event => finish(![4001, 4003, 4004].includes(event.code));
        newWs.onerror = () => finish(true);
      };

      createWs();
    }, 0);

    return () => {
      ignore = true;
      clearTimeout(timer);
      clearTimeout(retryTimer);
      clearTimeout(keyFrameTimer);
      clearInterval(watchdog);
      wsRef.current = null;
      ws?.close();
      decoder?.destroy();
      decoderRef.current = null;
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
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'click', x: start.x, y: start.y }));
        }
      } else {
        // Swipe — duration proportional to distance, min 150ms max 600ms
        const duration_ms = Math.min(600, Math.max(150, Math.round(dist * 0.8)));
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms }));
        }
      }
    },
    [toCanvasCoords, onTap],
  );

  return (
    <div className="relative">
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      className="cursor-pointer rounded border border-gray-700 bg-black touch-none"
      style={{ width: '100%', height: 'auto' }}
    />
    {connection !== 'live' && (
      <div role="status" className="absolute inset-0 flex items-center justify-center bg-black/85 text-sm text-white">
        {connection === 'connecting' && 'Подключение…'}
        {connection === 'waiting' && 'Ожидание видеокадра…'}
        {connection === 'retrying' && 'Переподключение…'}
        {connection === 'unavailable' && 'Стрим недоступен'}
      </div>
    )}
    </div>
  );
}
