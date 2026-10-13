import { h264ReceiverOffer } from '@/src/features/stream/h264ReceiverOffer';

const offer: RTCSessionDescriptionInit = { type: 'offer', sdp: 'v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96 97\r\na=rtpmap:96 H264/90000\r\na=fmtp:96 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\na=rtpmap:97 VP9/90000\r\na=fmtp:97 profile-id=0\r\na=fingerprint:sha-256 unchanged\r\na=candidate:unchanged\r\n' };
const size = { width: 960, height: 540 };
let decode: jest.Mock;
beforeEach(() => { decode = jest.fn().mockResolvedValue({ supported: true }); Object.defineProperty(navigator, 'mediaCapabilities', { configurable: true, value: { decodingInfo: decode } }); });
test('only a confirmed receiver capability raises constrained baseline fmtp', async () => {
  const actual = await h264ReceiverOffer(offer, size);
  expect(actual.sdp).toBe(offer.sdp!.replace('42e01f', '42e029'));
  expect(decode).toHaveBeenCalledWith(expect.objectContaining({ type: 'webrtc', video: expect.objectContaining({ width: 960, height: 540, framerate: 60 }) }));
});
test('1080p60 uses level42 while a missing capability retains the ordinary offer', async () => {
  expect((await h264ReceiverOffer(offer, { width: 1920, height: 1080 })).sdp).toContain('42e02a');
  decode.mockResolvedValue({ supported: false }); expect(await h264ReceiverOffer(offer, size)).toBe(offer);
  decode.mockRejectedValue(new Error()); expect(await h264ReceiverOffer(offer, size)).toBe(offer);
});
test('malformed dimensions never create a decoder probe or raise any capability', async () => {
  for (const dimensions of [undefined, { width: 0, height: 540 }, { width: 960.5, height: 540 }, { width: 8193, height: 540 }])
    expect(await h264ReceiverOffer(offer, dimensions)).toBe(offer);
  expect(decode).not.toHaveBeenCalled();
});
test('an indefinitely pending browser probe cannot block direct setup beyond its bounded deadline', async () => {
  jest.useFakeTimers();
  try {
    decode.mockReturnValue(new Promise(() => {}));
    const result = h264ReceiverOffer(offer, size);
    jest.advanceTimersByTime(500);
    expect(await result).toBe(offer);
  } finally { jest.useRealTimers(); }
});
test('another H264 profile or packetization mode is never rewritten', async () => {
  for (const sdp of [offer.sdp!.replace('42e01f', '64001f'), offer.sdp!.replace('packetization-mode=1', 'packetization-mode=0')])
    expect((await h264ReceiverOffer({ type: 'offer', sdp }, size)).sdp).toBe(sdp);
});
