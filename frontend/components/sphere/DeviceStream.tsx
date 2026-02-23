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

export function DeviceStream({
  deviceId,
  width = 360,
  height = 640,
  onTap,
}: DeviceStreamProps) {
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
    const wsUrl = apiBase.replace(/^http/, 'ws') + `/ws/stream/${deviceId}`;
    const ws = new WebSocket(wsUrl);
    ws.binaryType = 'arraybuffer';
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

    return () => {
      ws.close();
      decoder.destroy();
    };
  }, [deviceId, accessToken]);

  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;

      const rect = canvas.getBoundingClientRect();
      const scaleX = canvas.width / rect.width;
      const scaleY = canvas.height / rect.height;

      const x = Math.round((e.clientX - rect.left) * scaleX);
      const y = Math.round((e.clientY - rect.top) * scaleY);

      onTap?.(x, y);
      wsRef.current?.send(JSON.stringify({ type: 'click', x, y }));
    },
    [onTap],
  );

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
