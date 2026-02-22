// lib/h264-decoder.ts
// MED-8: ТЕМПОРАЛЬНАЯ ВЕРСИЯ — при merge заменить на канонический import:
// import { H264Decoder } from "@/lib/streaming/H264Decoder";  // из TZ-05 SPLIT-5
export type FrameCallback = (frame: VideoFrame) => void;

const FRAME_HEADER_SIZE = 10; // version(1) + flags(1) + ts(4) + size(4)

export class H264Decoder {
  private decoder: VideoDecoder | null = null;
  private configured = false;
  private pendingFrames: Uint8Array[] = [];
  private onFrame: FrameCallback;
  private spsNal: Uint8Array | null = null;
  private ppsNal: Uint8Array | null = null;

  constructor(onFrame: FrameCallback) {
    this.onFrame = onFrame;
  }

  init() {
    this.decoder = new VideoDecoder({
      output: (frame) => {
        this.onFrame(frame);
        frame.close(); // Обязательно освобождаем память
      },
      error: (e) => console.error('VideoDecoder error:', e),
    });
  }

  private configure(spsNal: Uint8Array, ppsNal: Uint8Array) {
    if (!this.decoder) return;

    // AVC Decoder Configuration Record
    const extradata = buildAVCCExtradata(spsNal, ppsNal);

    this.decoder.configure({
      codec: 'avc1.42E01F', // Level 3.1 — соответствует encoder TZ-05 SPLIT-2
      hardwareAcceleration: 'prefer-hardware',
      optimizeForLatency: true,
      description: extradata,
    });
    this.configured = true;

    // Процессировать накопившиеся кадры
    this.pendingFrames.forEach((f) => this.decodeFrame(f));
    this.pendingFrames = [];
  }

  handleBinary(data: ArrayBuffer) {
    const view = new DataView(data);
    if (view.byteLength < FRAME_HEADER_SIZE) return;

    const version = view.getUint8(0);
    if (version !== 1) return;

    const nalData = new Uint8Array(data, FRAME_HEADER_SIZE);
    const nalType = nalData[0] & 0x1f;

    if (nalType === 7 || nalType === 8) {
      this.handleSPSPPS(nalType, nalData);
      return;
    }

    if (!this.configured) {
      this.pendingFrames.push(nalData);
      return;
    }

    this.decodeFrame(nalData);
  }

  private handleSPSPPS(nalType: number, nal: Uint8Array) {
    if (nalType === 7) this.spsNal = nal;
    if (nalType === 8) this.ppsNal = nal;
    if (this.spsNal && this.ppsNal) {
      this.configure(this.spsNal, this.ppsNal);
    }
  }

  private decodeFrame(nal: Uint8Array) {
    if (!this.decoder || !this.configured) return;

    // Обернуть в Annex B (добавить start code 0x00000001)
    const annexB = new Uint8Array(4 + nal.length);
    annexB[3] = 1;
    annexB.set(nal, 4);

    const isKeyFrame = (nal[0] & 0x1f) === 5;

    this.decoder.decode(
      new EncodedVideoChunk({
        type: isKeyFrame ? 'key' : 'delta',
        timestamp: performance.now() * 1000,
        data: annexB,
      }),
    );
  }

  destroy() {
    this.decoder?.close();
    this.decoder = null;
  }
}

function buildAVCCExtradata(sps: Uint8Array, pps: Uint8Array): Uint8Array {
  const buf = new Uint8Array(11 + sps.length + pps.length);
  let off = 0;
  buf[off++] = 1;                       // configurationVersion
  buf[off++] = sps[1];                  // AVCProfileIndication
  buf[off++] = sps[2];                  // profile_compatibility
  buf[off++] = sps[3];                  // AVCLevelIndication
  buf[off++] = 0xff;                    // lengthSizeMinusOne = 3
  buf[off++] = 0xe1;                    // numSequenceParameterSets = 1
  buf[off++] = (sps.length >> 8) & 0xff;
  buf[off++] = sps.length & 0xff;
  buf.set(sps, off);
  off += sps.length;
  buf[off++] = 1;                       // numPictureParameterSets
  buf[off++] = (pps.length >> 8) & 0xff;
  buf[off++] = pps.length & 0xff;
  buf.set(pps, off);
  return buf;
}
