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
    this.callbacks.output({ timestamp, close } as unknown as VideoFrame);
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
