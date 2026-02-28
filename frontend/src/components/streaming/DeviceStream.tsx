"use client";

import { useEffect, useRef, useState } from "react";
import { H264Decoder } from "@/src/lib/streaming/H264Decoder";
import { RemoteControlWidget } from "./RemoteControlWidget";

interface DeviceStreamProps {
  deviceId: string;
  authToken: string;
  className?: string;
}

type StreamStatus = "connecting" | "streaming" | "offline";

/**
 * Renders a live H.264 stream from an Android device onto a canvas element.
 *
 * - Connects to /ws/stream/{deviceId} via WebSocket
 * - Decodes NAL units using the WebCodecs VideoDecoder API
 * - Forwards click/tap events to the agent (coordinate-mapped)
 *
 * MERGE-5 note: when merging with TZ-10, remove any duplicate h264-decoder.ts
 * from frontend/src/lib/ and update imports to point here.
 */
export function DeviceStream({
  deviceId,
  authToken,
  className = "",
}: DeviceStreamProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const decoderRef = useRef<H264Decoder | null>(null);
  const [status, setStatus] = useState<StreamStatus>("connecting");

  useEffect(() => {
    if (!canvasRef.current || !authToken) return;

    const decoder = new H264Decoder(canvasRef.current);
    decoderRef.current = decoder;

    decoder.onDisconnect = () => setStatus("offline");

    decoder
      .init(deviceId, authToken)
      .then(() => setStatus("streaming"))
      .catch((err: unknown) => {
        console.error("[DeviceStream] init failed:", err);
        setStatus("offline");
      });

    return () => {
      decoder.destroy();
      decoderRef.current = null;
    };
  }, [deviceId, authToken]);

  const pointerState = useRef<{ x: number; y: number; time: number } | null>(null);

  const handlePointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    pointerState.current = {
      x: e.clientX,
      y: e.clientY,
      time: Date.now(),
    };
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.releasePointerCapture(e.pointerId);
    if (!pointerState.current || !canvasRef.current || !decoderRef.current) return;

    const rect = canvasRef.current.getBoundingClientRect();
    const endX = e.clientX;
    const endY = e.clientY;

    // Вычисляем дельты
    const dx = endX - pointerState.current.x;
    const dy = endY - pointerState.current.y;
    const distance = Math.sqrt(dx * dx + dy * dy);
    const duration = Date.now() - pointerState.current.time;

    // Конвертируем координаты в относительные для канваса
    const startCanvasX = pointerState.current.x - rect.left;
    const startCanvasY = pointerState.current.y - rect.top;
    const endCanvasX = endX - rect.left;
    const endCanvasY = endY - rect.top;

    if (distance > 10) {
      // Это свайп
      decoderRef.current.sendSwipe(startCanvasX, startCanvasY, endCanvasX, endCanvasY, duration);
    } else {
      // Это тап
      decoderRef.current.sendTap(endCanvasX, endCanvasY);
    }

    pointerState.current = null;
  };

  const handleSendKey = (keyCode: number) => {
    decoderRef.current?.sendKeyEvent(keyCode);
  };

  const handleSendText = (text: string) => {
    decoderRef.current?.sendText(text);
  };

  return (
    <div className={`relative bg-black ${className}`}>
      <canvas
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerUp={handlePointerUp}
        onContextMenu={(e) => e.preventDefault()}
        className="w-full h-full cursor-crosshair touch-none"
        style={{ touchAction: "none" }}
      />

      {status === "streaming" && (
        <RemoteControlWidget onSendKey={handleSendKey} onSendText={handleSendText} />
      )}

      {status !== "streaming" && (
        <div className="absolute inset-0 flex items-center justify-center bg-background/80 text-foreground text-sm select-none">
          {status === "connecting" ? "Подключение..." : "Нет сигнала"}
        </div>
      )}
    </div>
  );
}
