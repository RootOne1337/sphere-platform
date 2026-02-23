"use client";

import { useEffect, useRef, useState } from "react";
import { H264Decoder } from "@/src/lib/streaming/H264Decoder";

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

  const handleCanvasClick = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect) return;
    decoderRef.current?.sendTap(e.clientX - rect.left, e.clientY - rect.top);
  };

  return (
    <div className={`relative bg-black ${className}`}>
      <canvas
        ref={canvasRef}
        onClick={handleCanvasClick}
        className="w-full h-full cursor-pointer"
        style={{ touchAction: "none" }}
      />
      {status !== "streaming" && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 text-white text-sm select-none">
          {status === "connecting" ? "Подключение..." : "Нет сигнала"}
        </div>
      )}
    </div>
  );
}
