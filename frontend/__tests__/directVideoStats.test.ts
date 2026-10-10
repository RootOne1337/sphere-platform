import { DirectVideoStatsSampler, preferLowVideoDelay } from '@/src/features/stream/directVideoStats';
const report = (row: Record<string, unknown>) => new Map([['inbound', { id: 'inbound', type: 'inbound-rtp', kind: 'video', ...row }]]) as unknown as RTCStatsReport;

test('reports interval buffer and decode time separately from network RTT', () => {
  const sample = new DirectVideoStatsSampler();
  const first = sample.sample(report({ timestamp: 1000, framesDecoded: 100, jitterBufferDelay: 10, jitterBufferEmittedCount: 100, totalDecodeTime: .2 }));
  expect(first.jitterBufferMs).toBeNull(); expect(first.decodeMs).toBeNull();
  const result = sample.sample(report({ timestamp: 2000, framesDecoded: 120, jitterBufferDelay: 11, jitterBufferEmittedCount: 120, totalDecodeTime: .24 }));
  expect(result.jitterBufferMs).toBeCloseTo(50); expect(result.decodeMs).toBeCloseTo(2); expect(result.fps).toBe(20);
  expect(result.networkRttMs).toBeNull(); expect(result).not.toHaveProperty('videoLatencyMs');
});
test('missing counters, resets and track changes never become fabricated zero delay', () => {
  const sample = new DirectVideoStatsSampler();
  sample.sample(report({ timestamp: 1000, framesDecoded: 20, jitterBufferDelay: 1, jitterBufferEmittedCount: 20, totalDecodeTime: .1 }));
  for (const row of [ { timestamp: 2000 }, { timestamp: 3000, framesDecoded: 10, jitterBufferDelay: .1 },
    { id: 'new', timestamp: 4000, framesDecoded: 20, jitterBufferDelay: 1, jitterBufferEmittedCount: 20, totalDecodeTime: .1 }]) {
    const result = sample.sample(report(row)); expect(result.jitterBufferMs).toBeNull(); expect(result.decodeMs).toBeNull();
  }
});
test('uses only the selected ICE pair and exposes no candidate addresses or IDs', () => {
  const stats = new Map<string, Record<string, unknown>>([ ['transport', { type: 'transport', selectedCandidatePairId: 'selected' }],
    ['selected', { type: 'candidate-pair', currentRoundTripTime: .002, localCandidateId: 'private' }],
    ['other', { type: 'candidate-pair', currentRoundTripTime: .250 }],
    ['private', { type: 'local-candidate', address: '192.168.0.9' }] ]) as unknown as RTCStatsReport;
  const value = new DirectVideoStatsSampler().sample(stats);
  expect(value.networkRttMs).toBe(2); expect(JSON.stringify(value)).not.toContain('192.168.0.9');
});
test('optional low-delay target is feature-detected and rejecting browsers keep their defaults', () => {
  const receiver = { jitterBufferTarget: 100 }; preferLowVideoDelay(receiver as unknown as RTCRtpReceiver);
  expect(receiver.jitterBufferTarget).toBe(0);
  expect(() => preferLowVideoDelay({} as RTCRtpReceiver)).not.toThrow();
  const rejecting = Object.defineProperty({}, 'jitterBufferTarget', { set() { throw Error(); } });
  expect(() => preferLowVideoDelay(rejecting as RTCRtpReceiver)).not.toThrow();
});
