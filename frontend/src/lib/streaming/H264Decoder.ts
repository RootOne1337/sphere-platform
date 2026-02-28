/**
 * H.264 browser decoder using the WebCodecs API.
 *
 * Connects to /ws/stream/{deviceId}, decodes binary frames and renders
 * each decoded VideoFrame to a Canvas element.
 *
 * Wire format (Sphere Binary Frame, Big Endian):
 *   [0]     version   1 byte  = 0x01
 *   [1]     flags     1 byte  bit0 = keyframe
 *   [2:10]  timestamp 8 bytes = ms since stream start (Int64, FIX-5.1)
 *   [10:14] frameSize 4 bytes
 *   [14:]   NAL data
 */

const FRAME_HEADER_SIZE = 14;
const FRAME_VERSION = 0x01;
const FLAG_KEYFRAME = 0x01;

interface FrameHeader {
  version: number;
  isKeyFrame: boolean;
  /** Milliseconds since stream start (agent clock). */
  timestampMs: number;
  frameSize: number;
}

/**
 * Parse the 14-byte Sphere frame header.
 * Returns null if the data is too short or the version is unknown.
 */
function parseHeader(data: ArrayBuffer): FrameHeader | null {
  if (data.byteLength < FRAME_HEADER_SIZE) return null;
  const view = new DataView(data);

  const version = view.getUint8(0);
  if (version !== FRAME_VERSION) return null;

  const flags = view.getUint8(1);
  // FIX-5.1: timestamp is 8 bytes (Int64). getBigInt64 returns BigInt — convert
  // to Number. Safe for up to ~292 million year streams on 24/7 farms.
  const timestampMs = Number(view.getBigInt64(2, false /* big-endian */));
  const frameSize = view.getUint32(10, false);

  return {
    version,
    isKeyFrame: (flags & FLAG_KEYFRAME) !== 0,
    timestampMs,
    frameSize,
  };
}

function isSpsOrPps(data: ArrayBuffer): boolean {
  const bytes = new Uint8Array(data);
  if (bytes.length < 5) return false;
  // Look for Annex-B start code 0x00 0x00 0x00 0x01
  if (bytes[0] !== 0 || bytes[1] !== 0 || bytes[2] !== 0 || bytes[3] !== 1) {
    return false;
  }
  const nalType = bytes[4] & 0x1f;
  return nalType === 7 /* SPS */ || nalType === 8 /* PPS */;
}

export interface StreamStats {
  framesDecoded: number;
  frameDrops: number;
  dropRatio: number;
}

export class H264Decoder {
  private decoder: VideoDecoder | null = null;
  private ws: WebSocket | null = null;

  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;

  private configured = false;
  private framesDecoded = 0;
  private frameDrops = 0;

  /** Called when the WebSocket connection closes unexpectedly. */
  onDisconnect?: () => void;

  constructor(canvas: HTMLCanvasElement) {
    this.canvas = canvas;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Could not get 2D context from canvas");
    this.ctx = ctx;
  }

  async init(deviceId: string, authToken: string): Promise<void> {
    if (!("VideoDecoder" in window)) {
      throw new Error(
        "WebCodecs API not supported. Use Chrome 94+, Edge 94+ or Safari 15.4+",
      );
    }

    this.decoder = new VideoDecoder({
      output: (frame: VideoFrame) => this.renderFrame(frame),
      error: (error: Error) => {
        console.error("[H264Decoder] VideoDecoder error:", error);
        void this.reconfigure();
      },
    });

    await this.connectWebSocket(deviceId, authToken);
  }

  // ── WebSocket ──────────────────────────────────────────────────────────────

  private async connectWebSocket(
    deviceId: string,
    token: string,
  ): Promise<void> {
    const base =
      process.env.NEXT_PUBLIC_WS_URL ??
      (typeof window !== "undefined"
        ? `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.host}`
        : "");
    const url = `${base}/ws/stream/${deviceId}`;

    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(url);
      this.ws.binaryType = "arraybuffer";

      this.ws.onopen = () => {
        // First-message auth — JWT in payload (not URL)
        this.ws!.send(JSON.stringify({ token, device_id: deviceId }));
        resolve();
      };

      this.ws.onerror = (ev) => reject(new Error("WebSocket error"));

      this.ws.onmessage = (event: MessageEvent) => {
        if (event.data instanceof ArrayBuffer) {
          this.handleVideoFrame(event.data);
        } else {
          try {
            this.handleControlMessage(JSON.parse(event.data as string));
          } catch {
            // ignore malformed control messages
          }
        }
      };

      this.ws.onclose = (event: CloseEvent) => {
        console.log(`[H264Decoder] Stream closed: ${event.code} ${event.reason}`);
        this.onDisconnect?.();
      };
    });
  }

  // ── Frame handling ─────────────────────────────────────────────────────────

  private handleVideoFrame(data: ArrayBuffer): void {
    const header = parseHeader(data);
    if (!header) return;

    if (header.frameSize !== data.byteLength - FRAME_HEADER_SIZE) return;

    const nalData = data.slice(FRAME_HEADER_SIZE);

    // SPS/PPS arrives before the first frame — configure decoder from it
    if (!this.configured && isSpsOrPps(nalData)) {
      this.configureDecoder(nalData);
      return;
    }

    if (!this.configured) return;

    const chunk = new EncodedVideoChunk({
      type: header.isKeyFrame ? "key" : "delta",
      // EncodedVideoChunk.timestamp is in microseconds
      timestamp: header.timestampMs * 1_000,
      data: nalData,
    });

    try {
      this.decoder!.decode(chunk);
      this.framesDecoded++;
    } catch {
      this.frameDrops++;
      if (this.frameDrops % 30 === 0) {
        console.warn(`[H264Decoder] Frame drops: ${this.frameDrops}`);
      }
    }
  }

  private configureDecoder(spsData: ArrayBuffer): void {
    this.decoder!.configure({
      // H.264 Baseline Profile Level 3.1 — matches encoder config in H264Encoder.kt
      codec: "avc1.42E01F",
      description: new Uint8Array(spsData),
      optimizeForLatency: true,
      hardwareAcceleration: "prefer-hardware",
    });
    this.configured = true;
  }

  private renderFrame(frame: VideoFrame): void {
    this.canvas.width = frame.displayWidth;
    this.canvas.height = frame.displayHeight;
    this.ctx.drawImage(frame, 0, 0);
    // CRITICAL: must release every frame to avoid GPU memory leak
    frame.close();
  }

  private async reconfigure(): Promise<void> {
    this.configured = false;
    try {
      this.decoder?.reset();
    } catch {
      // ignore reset errors
    }
    // Request fresh SPS/PPS + I-frame from the agent
    this.ws?.send(JSON.stringify({ type: "request_keyframe" }));
  }

  private handleControlMessage(msg: Record<string, unknown>): void {
    // Control messages from backend (e.g. stream status updates) — extend as needed
    console.debug("[H264Decoder] control:", msg);
  }

  // ── Input mapping ─────────────────────────────────────────────────────────

  /**
   * Send a tap/click at the given canvas-relative coordinates.
   * Coordinates are scaled from CSS pixels to device pixels before sending.
   */
  sendTap(canvasX: number, canvasY: number): void {
    const deviceX = Math.round(
      (canvasX / this.canvas.clientWidth) * this.canvas.width,
    );
    const deviceY = Math.round(
      (canvasY / this.canvas.clientHeight) * this.canvas.height,
    );
    this.ws?.send(JSON.stringify({ type: "click", x: deviceX, y: deviceY }));
  }

  /**
   * Send a swipe gesture from (x1,y1) to (x2,y2) over a duration (ms).
   */
  sendSwipe(canvasX1: number, canvasY1: number, canvasX2: number, canvasY2: number, durationMs: number = 300): void {
    const deviceX1 = Math.round((canvasX1 / this.canvas.clientWidth) * this.canvas.width);
    const deviceY1 = Math.round((canvasY1 / this.canvas.clientHeight) * this.canvas.height);
    const deviceX2 = Math.round((canvasX2 / this.canvas.clientWidth) * this.canvas.width);
    const deviceY2 = Math.round((canvasY2 / this.canvas.clientHeight) * this.canvas.height);

    this.ws?.send(JSON.stringify({
      type: "swipe",
      x1: deviceX1, y1: deviceY1,
      x2: deviceX2, y2: deviceY2,
      duration: durationMs
    }));
  }

  /**
   * Send a hardware key event (e.g. KEYCODE_HOME = 3, KEYCODE_BACK = 4, KEYCODE_POWER = 26)
   */
  sendKeyEvent(keyCode: number): void {
    this.ws?.send(JSON.stringify({ type: "keyevent", code: keyCode }));
  }

  /**
   * Send a string of text to the device
   */
  sendText(text: string): void {
    this.ws?.send(JSON.stringify({ type: "text", text }));
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────

  destroy(): void {
    try {
      this.decoder?.close();
    } catch {
      // ignore
    }
    this.ws?.close();
    this.decoder = null;
    this.ws = null;
  }

  get stats(): StreamStats {
    return {
      framesDecoded: this.framesDecoded,
      frameDrops: this.frameDrops,
      dropRatio: this.frameDrops / Math.max(1, this.framesDecoded + this.frameDrops),
    };
  }
}
