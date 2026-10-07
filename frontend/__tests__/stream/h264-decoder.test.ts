import { H264Decoder } from '@/lib/h264-decoder';

class Codec {
  static instances: Codec[] = [];
  state: CodecState = 'unconfigured';
  decodeQueueSize = 0;
  chunks: EncodedVideoChunkInit[] = [];
  configure = jest.fn(() => { this.state = 'configured'; });
  decode = jest.fn((chunk: EncodedVideoChunkInit) => {
    if (this.state !== 'configured') throw new Error('closed codec');
    this.decodeQueueSize++;
    this.chunks.push(chunk);
  });
  close = jest.fn(() => { this.state = 'closed'; this.decodeQueueSize = 0; });
  constructor(readonly callbacks: VideoDecoderInit) { Codec.instances.push(this); }
  output(timestamp: number, close = jest.fn()) {
    this.decodeQueueSize = Math.max(0, this.decodeQueueSize - 1);
    this.callbacks.output({ timestamp, close, displayWidth: 960, displayHeight: 540 } as unknown as VideoFrame);
    return close;
  }
}

const SPS = [0x67, 0x42, 0, 0x1f];
const PPS = [0x68, 0xce];
function packet(nal: number[] | Uint8Array, ms = 12345): ArrayBuffer {
  const bytes = new Uint8Array(18 + nal.length);
  bytes[0] = 1;
  const view = new DataView(bytes.buffer);
  view.setBigInt64(2, BigInt(ms)); view.setUint32(10, nal.length + 4);
  bytes.set([0, 0, 0, 1], 14); bytes.set(nal, 18);
  return bytes.buffer;
}
function configure(decoder: H264Decoder) {
  decoder.handleBinary(packet(SPS)); decoder.handleBinary(packet(PPS));
}
const CAPTURE_A = '00112233445566778899aabbccddeeff';
const CAPTURE_B = 'aabbccddeeff00112233445566778899';
function capturePacket(nal: number[], epoch = CAPTURE_A, ms = 12345): ArrayBuffer {
  const legacy = new Uint8Array(packet(nal, ms));
  const bytes = new Uint8Array(legacy.length + 16);
  bytes.set(legacy.subarray(0, 14)); bytes[0] = 2;
  bytes.set(Uint8Array.from(epoch.match(/../g)!, byte => parseInt(byte, 16)), 14);
  bytes.set(legacy.subarray(14), 30);
  return bytes.buffer;
}
function captureConfigure(epoch = CAPTURE_A) {
  decoder.handleBinary(capturePacket(SPS, epoch)); decoder.handleBinary(capturePacket(PPS, epoch));
}
function newest() { return Codec.instances[Codec.instances.length - 1]; }
let now: number;
let decoder: H264Decoder;
let rendered: jest.Mock;
beforeEach(() => {
  now = 0; Codec.instances = []; rendered = jest.fn();
  jest.spyOn(performance, 'now').mockImplementation(() => now);
  Object.defineProperty(global, 'VideoDecoder', { configurable: true, value: Codec });
  Object.defineProperty(global, 'EncodedVideoChunk', { configurable: true, value: class {
    constructor(value: EncodedVideoChunkInit) { Object.assign(this, value); }
  } });
  jest.spyOn(console, 'error').mockImplementation(() => {});
  decoder = new H264Decoder(rendered); decoder.init();
});
afterEach(() => { decoder.destroy(); jest.restoreAllMocks(); });

it('does not retain and replay frames received before SPS/PPS', () => {
  const idr = new Uint8Array(1024); idr[0] = 0x65;
  for (let i = 0; i < 2048; i++) decoder.handleBinary(packet(idr, i));
  configure(decoder);
  expect(Codec.instances.reduce((n, c) => n + c.chunks.length, 0)).toBe(0);
  decoder.handleBinary(packet([0x41, 1]));
  expect(newest().chunks).toHaveLength(0);
  decoder.handleBinary(packet([0x65, 2]));
  expect(newest().chunks).toHaveLength(1);
});

it('separates binary receipt, decode submission, decoded output and rendered output', () => {
  configure(decoder);
  decoder.handleBinary(packet([0x65, 1]));

  const beforeOutput = decoder.stats;
  expect(beforeOutput.binaryMessagesReceived).toBe(3);
  expect(beforeOutput.idrUnits).toBe(1);
  expect(beforeOutput.decodeSubmitted).toBe(1);
  expect(beforeOutput.decodedOutputs).toBe(0);
  expect(beforeOutput.renderedFrames).toBe(0);

  newest().output(newest().chunks[0].timestamp);
  expect(decoder.stats.decodedOutputs).toBe(1);
  expect(decoder.stats.renderedFrames).toBe(1);
  expect(decoder.stats.pendingOutputCount).toBe(0);
});

it('renders the first picture when only the hardware AVC configuration is unavailable', () => {
  const codec = newest();
  codec.configure.mockImplementation(((config: VideoDecoderConfig) => {
    if (config.hardwareAcceleration === 'prefer-hardware') {
      throw new DOMException('Hardware AVC is unavailable', 'NotSupportedError');
    }
    codec.state = 'configured';
  }) as typeof codec.configure);
  configure(decoder);
  decoder.handleBinary(packet([0x65, 1]));
  expect(codec.chunks).toHaveLength(1);
  codec.output(codec.chunks[0].timestamp);
  expect(rendered).toHaveBeenCalledTimes(1);
  expect(decoder.stats).toMatchObject({ decodeErrors: 0, renderedFrames: 1, lastDecodeError: null });
});

it('reports one allowlisted decoder failure code without retaining its arbitrary message', () => {
  const error = new DOMException('Private driver diagnostic should not reach UI', 'OperationError');
  newest().callbacks.error(error);
  expect(decoder.stats.lastDecodeError).toBe('OperationError');
  expect(JSON.stringify(decoder.stats)).not.toContain('Private driver');
});

it('reduces unknown decoder errors to a bounded code and ignores retired callbacks', () => {
  const old = newest();
  old.callbacks.error(new DOMException('Unknown failure', 'UnboundedDriverSpecificName'));
  expect(decoder.stats.lastDecodeError).toBe('OtherError');
  const count = decoder.stats.decodeErrors;
  old.callbacks.error(new DOMException('Late failure', 'OperationError'));
  expect(decoder.stats.decodeErrors).toBe(count);
  expect(decoder.stats.lastDecodeError).toBe('OtherError');
});

it('counts malformed binary packets instead of silently losing evidence', () => {
  decoder.handleBinary(new Uint8Array([1, 2, 3]).buffer);
  expect(decoder.stats.binaryMessagesReceived).toBe(1);
  expect(decoder.stats.binaryBytesReceived).toBe(3);
  expect(decoder.stats.invalidPackets).toBe(1);
});

it('measures picture receipt and successful canvas output over the last second', () => {
  configure(decoder);
  for (let index = 0; index < 30; index++) {
    now = index * 1000 / 30;
    decoder.handleBinary(packet([index === 0 ? 0x65 : 0x41, index], index * 33));
    newest().output(newest().chunks[index].timestamp);
  }
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 30, renderedFps: 30, renderedFrames: 30 });
  now = 2_000;
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 0, renderedFps: 0, renderedFrames: 30 });
});

it('does not report codec config or malformed traffic as incoming video FPS', () => {
  configure(decoder);
  decoder.handleBinary(new Uint8Array([1, 2, 3]).buffer);
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 0, renderedFps: 0 });
});

it('reports incoming pictures independently when canvas drawing fails', () => {
  configure(decoder);
  rendered.mockImplementationOnce(() => { throw new Error('draw failed'); });
  decoder.handleBinary(packet([0x65, 1]));
  newest().output(newest().chunks[0].timestamp);
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 1, renderedFps: 0, renderErrors: 1 });
});

it('clears live FPS windows when the socket stream is reset', () => {
  configure(decoder);
  decoder.handleBinary(packet([0x65, 1]));
  newest().output(newest().chunks[0].timestamp);
  decoder.reset();
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 0, renderedFps: 0, renderedFrames: 1 });
});

it('bounds live FPS accounting and explicitly marks a saturated count', () => {
  for (let index = 0; index < 4000; index++) decoder.handleBinary(packet([0x65, 1], index));
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 1024, receivedPictureFpsCapped: true, renderedFps: 0 });
  now = 1000;
  expect(decoder.stats).toMatchObject({ receivedPictureFps: 0, receivedPictureFpsCapped: false });
});

it('bounds submissions when a codec stops consuming input', () => {
  configure(decoder);
  for (let i = 0; i < 1000; i++) decoder.handleBinary(packet([0x65, 1], i));
  expect(Math.max(...Codec.instances.map(c => c.chunks.length))).toBeLessThanOrEqual(8);
  expect(Codec.instances.length).toBeLessThanOrEqual(2);
});

it('also bounds internal pending output when decodeQueueSize reports zero', () => {
  configure(decoder);
  for (let i = 0; i < 1000; i++) {
    decoder.handleBinary(packet([i === 0 ? 0x65 : 0x41, 1], i));
    newest().decodeQueueSize = 0;
  }
  expect(Codec.instances.reduce((n, c) => n + c.chunks.length, 0)).toBeLessThanOrEqual(8);
});

it('discards an expired reference chain and resumes only from a new IDR', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  const old = newest(); now = 501;
  decoder.handleBinary(packet([0x41, 2]));
  expect(old.close).toHaveBeenCalledTimes(1);
  now = 2000; decoder.handleBinary(packet([0x41, 3]));
  expect(Codec.instances.reduce((n, c) => n + c.chunks.length, 0)).toBe(1);
  decoder.handleBinary(packet([0x65, 4]));
  expect(newest().chunks.at(-1)?.type).toBe('key');
});

it('bounds retained encoded bytes even when every frame is an IDR', () => {
  configure(decoder);
  const nal = new Uint8Array(700_000); nal[0] = 0x65;
  for (let i = 0; i < 6; i++) decoder.handleBinary(packet(nal, i));
  expect(Math.max(...Codec.instances.map(c => c.chunks.length))).toBeLessThanOrEqual(2);
});

it('recovers from an async closed-codec error without throwing on new packets', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  const old = newest(); old.state = 'closed';
  old.callbacks.error(new DOMException('codec failure'));
  expect(() => decoder.handleBinary(packet([0x41, 2]))).not.toThrow();
  now = 2000; decoder.handleBinary(packet([0x65, 3]));
  expect(newest()).not.toBe(old);
  expect(newest().chunks).toHaveLength(1);
});

it('closes frames even when rendering throws', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  rendered.mockImplementation(() => { throw new Error('canvas unavailable'); });
  const close = jest.fn();
  try { newest().output(newest().chunks[0].timestamp, close); } catch { /* caller exception is allowed */ }
  expect(close).toHaveBeenCalledTimes(1);
});

it('ignores delayed output after destroy and closes every frame exactly once', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  const old = newest(); decoder.destroy();
  expect(old.output(old.chunks[0].timestamp)).toHaveBeenCalledTimes(1);
  expect(rendered).not.toHaveBeenCalled();
  expect(() => decoder.destroy()).not.toThrow();
  expect(old.close).toHaveBeenCalledTimes(1);
});

it('ignores output from a replaced codec generation', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  const old = newest(); old.state = 'closed'; old.callbacks.error(new DOMException('gone'));
  now = 2000; decoder.handleBinary(packet([0x65, 2]));
  expect(old.output(old.chunks[0].timestamp)).toHaveBeenCalledTimes(1);
  expect(rendered).not.toHaveBeenCalled();
  const current = newest(); current.output(current.chunks[0].timestamp);
  expect(rendered).toHaveBeenCalledTimes(1);
});

it('preserves the source timestamp as microseconds without claiming wall-clock latency', () => {
  now = 999999; configure(decoder); decoder.handleBinary(packet([0x65, 1], 12345));
  expect(newest().chunks[0].timestamp).toBe(12_345_000);
});

it('ignores repeated identical parameter sets instead of losing reference state', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1]));
  const codec = newest(); codec.output(codec.chunks[0].timestamp);
  configure(decoder); decoder.handleBinary(packet([0x41, 2]));
  expect(codec.configure).toHaveBeenCalledTimes(1);
  expect(codec.chunks.at(-1)?.type).toBe('delta');
});

it.each(['size', 'version', 'empty', 'timestamp', 'oversize'])('rejects invalid %s packets before configuring or decoding', kind => {
  configure(decoder);
  let bytes = packet([0x65, 1]); const view = new DataView(bytes);
  if (kind === 'size') view.setUint32(10, 900);
  if (kind === 'version') view.setUint8(0, 2);
  if (kind === 'empty') bytes = packet([]);
  if (kind === 'timestamp') view.setBigInt64(2, -1n);
  if (kind === 'oversize') { const nal = new Uint8Array(1_048_577); nal[0] = 0x65; bytes = packet(nal); }
  expect(() => decoder.handleBinary(bytes)).not.toThrow();
  expect(Codec.instances.reduce((n, c) => n + c.chunks.length, 0)).toBe(0);
});

it('converts all NALs in an access unit into one AVCC picture', () => {
  configure(decoder);
  decoder.handleBinary(packet([6, 9, 0, 0, 1, 0x65, 1, 0, 0, 0, 1, 0x65, 2]));
  expect(newest().chunks).toHaveLength(1);
  expect(newest().chunks[0].type).toBe('key');
  expect(Array.from(newest().chunks[0].data as Uint8Array)).toEqual([
    0, 0, 0, 2, 6, 9, 0, 0, 0, 2, 0x65, 1, 0, 0, 0, 2, 0x65, 2,
  ]);
});

it('waits for fresh PPS and IDR after changed SPS, and fences old output', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1])); const old = newest();
  decoder.handleBinary(packet([0x67, 0x42, 0, 0x20]));
  decoder.handleBinary(packet([0x65, 2]));
  expect(old.close).toHaveBeenCalledTimes(1);
  expect(old.output(old.chunks[0].timestamp)).toHaveBeenCalledTimes(1);
  expect(rendered).not.toHaveBeenCalled();
  decoder.handleBinary(packet(PPS)); decoder.handleBinary(packet([0x41, 3]));
  decoder.handleBinary(packet([0x65, 4]));
  expect(newest()).not.toBe(old); expect(newest().chunks).toHaveLength(1);
});

it('clears configuration and pending frames for a different socket generation', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1])); const old = newest();
  decoder.reset(); decoder.handleBinary(packet([0x65, 2]));
  expect(old.close).toHaveBeenCalledTimes(1);
  configure(decoder); decoder.handleBinary(packet([0x41, 3])); decoder.handleBinary(packet([0x65, 4]));
  expect(newest()).not.toBe(old); expect(newest().chunks).toHaveLength(1);
});

it.each(['configure', 'decode'] as const)('contains a synchronous %s failure and recovers on a new keyframe', method => {
  configure(decoder); const old = newest();
  old[method].mockImplementationOnce(() => { throw new Error('codec unavailable'); });
  expect(() => decoder.handleBinary(packet([0x65, 1]))).not.toThrow();
  now = 2000; decoder.handleBinary(packet([0x65, 2]));
  expect(newest()).not.toBe(old); expect(newest().chunks).toHaveLength(1);
});

it('renders sustained output without growing submissions in flight', () => {
  configure(decoder);
  for (let i = 0; i < 1000; i++) {
    decoder.handleBinary(packet([i === 0 ? 0x65 : 0x41, 1], i));
    newest().output(i * 1000); now += 33;
  }
  expect(Codec.instances).toHaveLength(1);
  expect(rendered).toHaveBeenCalledTimes(1000);
});

it('drops stale decoded output instead of rendering an old image', () => {
  configure(decoder); decoder.handleBinary(packet([0x65, 1])); const old = newest();
  now = 501;
  expect(old.output(old.chunks[0].timestamp)).toHaveBeenCalledTimes(1);
  expect(rendered).not.toHaveBeenCalled(); expect(old.close).toHaveBeenCalledTimes(1);
});

it('binds capture identity only after its current-generation picture is drawn', () => {
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1]));
  expect(decoder.lastRenderedCapture).toBeNull();
  const codec = newest(); codec.output(codec.chunks[0].timestamp);
  expect(decoder.lastRenderedCapture).toEqual({ captureEpoch: '00112233-4455-6677-8899-aabbccddeeff', frameWidth: 960, frameHeight: 540 });
  expect(rendered.mock.calls[0][1]).toEqual(decoder.lastRenderedCapture);
});

it('does not promote a received or decoded picture when canvas drawing fails', () => {
  captureConfigure(); rendered.mockImplementationOnce(() => { throw new Error('draw failed'); });
  decoder.handleBinary(capturePacket([0x65, 1])); newest().output(newest().chunks[0].timestamp);
  expect(decoder.lastRenderedCapture).toBeNull();
});

it('retires the previous capture before a same-size replacement is decoded', () => {
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1]));
  const old = newest(); old.output(old.chunks[0].timestamp);
  decoder.handleBinary(capturePacket(SPS, CAPTURE_B));
  expect(decoder.lastRenderedCapture).toBeNull();
  expect(old.close).toHaveBeenCalledTimes(1);
  decoder.handleBinary(capturePacket([0x65, 2], CAPTURE_B));
  expect(newest().chunks).toHaveLength(1); // The closed old codec; no new submission yet.
  decoder.handleBinary(capturePacket(PPS, CAPTURE_B));
  decoder.handleBinary(capturePacket([0x41, 3], CAPTURE_B));
  decoder.handleBinary(capturePacket([0x65, 4], CAPTURE_B));
  const current = newest(); expect(current).not.toBe(old); expect(current.chunks).toHaveLength(1);
  current.output(current.chunks[0].timestamp);
  expect(decoder.lastRenderedCapture?.captureEpoch).toBe('aabbccdd-eeff-0011-2233-445566778899');
});

it('cannot rebind late old output with the replacement capture identity', () => {
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1])); const old = newest();
  captureConfigure(CAPTURE_B); decoder.handleBinary(capturePacket([0x65, 2], CAPTURE_B));
  const current = newest();
  expect(old.output(old.chunks[0].timestamp)).toHaveBeenCalledTimes(1);
  expect(rendered).not.toHaveBeenCalled(); expect(decoder.lastRenderedCapture).toBeNull();
  current.output(current.chunks[0].timestamp);
  expect(decoder.lastRenderedCapture?.captureEpoch).toBe('aabbccdd-eeff-0011-2233-445566778899');
});

it.each(['reset', 'error', 'legacy'] as const)('invalidates capture binding on %s without promoting a header', reason => {
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1])); const codec = newest(); codec.output(codec.chunks[0].timestamp);
  if (reason === 'reset') decoder.reset();
  if (reason === 'error') codec.callbacks.error(new DOMException('closed'));
  if (reason === 'legacy') decoder.handleBinary(packet(SPS));
  expect(decoder.lastRenderedCapture).toBeNull();
});

it('protects the decoder binding from callback and getter mutation', () => {
  rendered.mockImplementation((_frame, binding) => { binding.captureEpoch = 'changed'; });
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1])); newest().output(newest().chunks[0].timestamp);
  const copy = decoder.lastRenderedCapture!; copy.captureEpoch = 'changed-again';
  expect(decoder.lastRenderedCapture?.captureEpoch).toBe('00112233-4455-6677-8899-aabbccddeeff');
});

it('does not publish capture readiness when rendering itself resets the decoder', () => {
  rendered.mockImplementationOnce(() => decoder.reset());
  captureConfigure(); decoder.handleBinary(capturePacket([0x65, 1])); newest().output(newest().chunks[0].timestamp);
  expect(decoder.lastRenderedCapture).toBeNull();
});
