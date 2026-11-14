"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { H264Decoder } from "@/src/lib/streaming/H264Decoder";
import { RemoteControlWidget } from "./RemoteControlWidget";

interface DeviceStreamProps {
  deviceId: string;
  authToken: string;
  className?: string;
}

type StreamStatus = "connecting" | "waiting" | "streaming" | "stale" | "reconnecting" | "offline";

const FRAME_STALE_TIMEOUT_MS = 10_000;

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
  const frameReceivedRef = useRef(false);
  const frameStaleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const statusRef = useRef<StreamStatus>("connecting");
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const transitionStatus = useCallback((next: StreamStatus) => {
    if (statusRef.current === next) return;
    statusRef.current = next;
    setStatus(next);
  }, []);

  useEffect(() => {
    if (!canvasRef.current) return;
    if (!authToken) {
      transitionStatus("offline");
      return;
    }

    let disposed = false;
    const decoder = new H264Decoder(canvasRef.current);
    decoderRef.current = decoder;
    frameReceivedRef.current = false;
    transitionStatus("connecting");
    if (frameStaleTimerRef.current) clearTimeout(frameStaleTimerRef.current);
    frameStaleTimerRef.current = null;

    decoder.onDisconnect = () => {
      if (disposed) return;
      if (frameStaleTimerRef.current) clearTimeout(frameStaleTimerRef.current);
      frameStaleTimerRef.current = null;
      transitionStatus("offline");
    };
    decoder.onReconnectStart = () => {
      if (disposed) return;
      frameReceivedRef.current = false;
      if (frameStaleTimerRef.current) clearTimeout(frameStaleTimerRef.current);
      frameStaleTimerRef.current = null;
      transitionStatus("reconnecting");
    };
    // Opening a WebSocket proves transport only; wait for decoded canvas output.
    decoder.onReconnect = () => {
      if (!disposed) transitionStatus("waiting");
    };
    decoder.onFrame = () => {
      if (disposed) return;
      frameReceivedRef.current = true;
      if (frameStaleTimerRef.current) clearTimeout(frameStaleTimerRef.current);
      frameStaleTimerRef.current = setTimeout(
        () => {
          if (!disposed && statusRef.current === "streaming") transitionStatus("stale");
        },
        FRAME_STALE_TIMEOUT_MS,
      );
      transitionStatus("streaming");
    };

    decoder
      .init(deviceId, authToken)
      .then(() => {
        if (!disposed && !frameReceivedRef.current) transitionStatus("waiting");
      })
      .catch((err: unknown) => {
        if (disposed) return;
        console.error("[DeviceStream] init failed:", err);
        transitionStatus("offline");
      });

    return () => {
      disposed = true;
      if (frameStaleTimerRef.current) clearTimeout(frameStaleTimerRef.current);
      frameStaleTimerRef.current = null;
      decoder.destroy();
      decoderRef.current = null;
    };
  }, [deviceId, authToken, transitionStatus]);

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
          {status === "connecting"
            ? "Подключение..."
            : status === "waiting"
              ? "Ожидание видеокадра..."
              : status === "stale"
                ? "Нет новых видеокадров более 10 секунд"
              : status === "reconnecting"
                ? "Переподключение..."
                : "Нет сигнала"}
        </div>
      )}
    </div>
  );
}
