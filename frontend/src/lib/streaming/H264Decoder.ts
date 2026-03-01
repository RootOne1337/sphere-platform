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
  private needsKeyFrame = true;

  // FIX-AVCC: кешируем SPS и PPS — configure() вызывается ТОЛЬКО когда оба есть
  private _spsNal: Uint8Array | null = null;
  private _ppsNal: Uint8Array | null = null;
  // Буфер фреймов, пришедших до configure()
  private _pendingFrames: Uint8Array[] = [];

  // FIX-RECONNECT: автоматический reconnect при потере WS
  private _deviceId = "";
  private _authToken = "";
  private _destroyed = false;
  private _reconnecting = false;
  private _reconnectAttempts = 0;
  private _reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private static readonly MAX_RECONNECT_ATTEMPTS = 15;
  private static readonly MAX_BACKOFF_MS = 30_000;

  /** Вызывается когда WS закрылся и все попытки reconnect исчерпаны. */
  onDisconnect?: () => void;
  /** Вызывается при успешном reconnect. */
  onReconnect?: () => void;

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

    this._deviceId = deviceId;
    this._authToken = authToken;
    this._destroyed = false;
    this._reconnectAttempts = 0;

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
        // FIX-RECONNECT: автоматический reconnect при неожиданном закрытии
        // 1000 = нормальное закрытие (destroy() пользователем), 4001/4003/4004 = ошибка авторизации
        const isAuthError = [4001, 4003, 4004].includes(event.code);
        if (!this._destroyed && event.code !== 1000 && !isAuthError) {
          void this.scheduleReconnect();
        } else {
          this.onDisconnect?.();
        }
      };
    });
  }

  // ── Reconnect логика ─────────────────────────────────────────────────────────

  private async scheduleReconnect(): Promise<void> {
    if (this._destroyed || this._reconnecting) return;
    if (this._reconnectAttempts >= H264Decoder.MAX_RECONNECT_ATTEMPTS) {
      console.error(`[H264Decoder] Исчерпаны все ${H264Decoder.MAX_RECONNECT_ATTEMPTS} попыток reconnect`);
      this.onDisconnect?.();
      return;
    }

    this._reconnecting = true;
    const backoffMs = Math.min(
      1000 * Math.pow(2, this._reconnectAttempts),
      H264Decoder.MAX_BACKOFF_MS,
    );
    this._reconnectAttempts++;
    console.log(`[H264Decoder] Reconnect #${this._reconnectAttempts} через ${backoffMs}ms`);

    await new Promise<void>((resolve) => {
      this._reconnectTimer = setTimeout(resolve, backoffMs);
    });

    if (this._destroyed) {
      this._reconnecting = false;
      return;
    }

    // Сбросить декодер для получения свежего SPS/PPS
    this.configured = false;
    this.needsKeyFrame = true;
    this._spsNal = null;
    this._ppsNal = null;
    this._pendingFrames = [];
    try {
      this.decoder?.reset();
    } catch {
      // Игнорируем ошибки reset
    }

    try {
      await this.connectWebSocket(this._deviceId, this._authToken);
      this._reconnectAttempts = 0;
      this._reconnecting = false;
      console.log("[H264Decoder] Reconnect успешен");
      this.onReconnect?.();
    } catch (e) {
      console.warn("[H264Decoder] Reconnect неудачен:", e);
      this._reconnecting = false;
      void this.scheduleReconnect();
    }
  }

  // ── Frame handling ─────────────────────────────────────────────────────────

  /**
   * Strip Annex-B start codes (0x00000001 or 0x000001) from NAL data.
   * MediaCodec Surface encoder outputs Annex-B; WebCodecs AVCC needs raw NAL.
   */
  private static stripStartCode(nal: Uint8Array): Uint8Array {
    if (nal[0] === 0 && nal[1] === 0 && nal[2] === 0 && nal[3] === 1) {
      return nal.subarray(4);
    }
    if (nal[0] === 0 && nal[1] === 0 && nal[2] === 1) {
      return nal.subarray(3);
    }
    return nal;
  }

  /**
   * Build AVCDecoderConfigurationRecord from SPS + PPS (ISO/IEC 14496-15).
   * WebCodecs H.264 requires this format in `description`, not raw Annex-B.
   */
  private static buildAVCC(sps: Uint8Array, pps: Uint8Array): Uint8Array {
    const buf = new Uint8Array(11 + sps.length + pps.length);
    let off = 0;
    buf[off++] = 1;                              // configurationVersion
    buf[off++] = sps[1];                         // AVCProfileIndication
    buf[off++] = sps[2];                         // profile_compatibility
    buf[off++] = sps[3];                         // AVCLevelIndication
    buf[off++] = 0xff;                           // lengthSizeMinusOne = 3 (4-byte lengths)
    buf[off++] = 0xe1;                           // numSequenceParameterSets = 1
    buf[off++] = (sps.length >> 8) & 0xff;
    buf[off++] = sps.length & 0xff;
    buf.set(sps, off);
    off += sps.length;
    buf[off++] = 1;                              // numPictureParameterSets = 1
    buf[off++] = (pps.length >> 8) & 0xff;
    buf[off++] = pps.length & 0xff;
    buf.set(pps, off);
    return buf;
  }

  private handleVideoFrame(data: ArrayBuffer): void {
    const header = parseHeader(data);
    if (!header) return;

    if (header.frameSize !== data.byteLength - FRAME_HEADER_SIZE) return;

    // Strip Annex-B start code from NAL payload
    const rawNal = H264Decoder.stripStartCode(new Uint8Array(data, FRAME_HEADER_SIZE));
    const nalType = rawNal[0] & 0x1f;

    // SPS (7) / PPS (8) → cache and configure decoder when both collected
    if (nalType === 7 || nalType === 8) {
      if (nalType === 7) this._spsNal = rawNal;
      if (nalType === 8) this._ppsNal = rawNal;
      if (this._spsNal && this._ppsNal) {
        this.configureDecoder(this._spsNal, this._ppsNal);
      }
      return;
    }

    // Not configured yet — buffer frame for replay after configure
    if (!this.configured) {
      this._pendingFrames.push(rawNal);
      return;
    }

    this.decodeNal(rawNal, header.timestampMs);
  }

  private decodeNal(nal: Uint8Array, timestampMs: number): void {
    if (!this.decoder || !this.configured) return;

    const isKeyFrame = (nal[0] & 0x1f) === 5;

    // WebCodecs requires keyframe first after configure/flush — skip deltas until IDR
    if (this.needsKeyFrame && !isKeyFrame) return;
    this.needsKeyFrame = false;

    // AVCC format: 4-byte big-endian NAL unit length prefix (NOT Annex-B start code)
    const avcc = new Uint8Array(4 + nal.length);
    new DataView(avcc.buffer).setUint32(0, nal.length, false);
    avcc.set(nal, 4);

    try {
      this.decoder.decode(
        new EncodedVideoChunk({
          type: isKeyFrame ? "key" : "delta",
          timestamp: timestampMs * 1_000,
          data: avcc,
        }),
      );
      this.framesDecoded++;
    } catch {
      this.frameDrops++;
      if (this.frameDrops % 30 === 0) {
        console.warn(`[H264Decoder] Frame drops: ${this.frameDrops}`);
      }
    }
  }

  private configureDecoder(sps: Uint8Array, pps: Uint8Array): void {
    // Dynamic codec string from SPS profile/compat/level
    const profile = sps[1].toString(16).padStart(2, "0").toUpperCase();
    const compat = sps[2].toString(16).padStart(2, "0").toUpperCase();
    const level = sps[3].toString(16).padStart(2, "0").toUpperCase();

    this.decoder!.configure({
      codec: `avc1.${profile}${compat}${level}`,
      description: H264Decoder.buildAVCC(sps, pps),
      optimizeForLatency: true,
      hardwareAcceleration: "prefer-hardware",
    });
    this.configured = true;
    this.needsKeyFrame = true;

    // Replay buffered frames — find last IDR and decode from there
    let lastIdrIdx = -1;
    for (let i = this._pendingFrames.length - 1; i >= 0; i--) {
      if ((this._pendingFrames[i][0] & 0x1f) === 5) {
        lastIdrIdx = i;
        break;
      }
    }
    if (lastIdrIdx >= 0) {
      for (let i = lastIdrIdx; i < this._pendingFrames.length; i++) {
        this.decodeNal(this._pendingFrames[i], performance.now());
      }
    }
    this._pendingFrames = [];
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
    this.needsKeyFrame = true;
    this._spsNal = null;
    this._ppsNal = null;
    this._pendingFrames = [];
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
    this._destroyed = true;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
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
