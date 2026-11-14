import { probeNetwork } from '@/src/features/stream/directProbeNetwork';

const report = (entries: any[]) => new Map(entries.map((v, i) => [String(i), v])) as unknown as RTCStatsReport;

test('aggregate ICE checks expose no candidate addresses, credentials, IDs or certificates', () => {
  const value = probeNetwork(report([
    { type: 'local-candidate', address: '10.0.0.2', port: 4000, usernameFragment: 'secret' },
    { type: 'remote-candidate', address: 'example.local', foundation: 'private' },
    { type: 'candidate-pair', state: 'in-progress', requestsSent: 3, responsesReceived: 0, localCandidateId: 'sensitive' },
    { type: 'candidate-pair', state: 'failed', requestsSent: 2, responsesReceived: 1 },
    { type: 'candidate-pair', state: 'succeeded', requestsSent: 4, responsesReceived: 3 },
    { type: 'transport', dtlsState: 'connecting', tlsVersion: 'raw', selectedCandidatePairId: 'not exported' },
    { type: 'certificate', fingerprint: 'secret-certificate' },
  ]));
  expect(value).toEqual({ localCandidates: 1, remoteCandidates: 1, pairs: 3, checkingPairs: 1,
    failedPairs: 1, succeededPairs: 1, requestsSent: 9, responsesReceived: 4, dtlsState: 'connecting' });
  expect(JSON.stringify(value)).not.toMatch(/secret|address|port|example|10\.0|fingerprint|CandidateId/);
});

test('absent or partial measurements remain unknown instead of a fabricated zero', () => {
  expect(probeNetwork(report([]))).toMatchObject({ pairs: 0, requestsSent: null, responsesReceived: null, dtlsState: null });
  expect(probeNetwork(report([
    { type: 'candidate-pair', state: 'waiting', requestsSent: 0, responsesReceived: 0 },
    { type: 'candidate-pair', state: 'waiting', requestsSent: 0 },
  ]))).toMatchObject({ requestsSent: 0, responsesReceived: null });
  for (const value of [-1, .5, NaN, Infinity, '3', Number.MAX_SAFE_INTEGER + 1]) {
    expect(probeNetwork(report([{ type: 'candidate-pair', requestsSent: value }])).requestsSent).toBeNull();
  }
  expect(probeNetwork(report([
    { type: 'candidate-pair', requestsSent: Number.MAX_SAFE_INTEGER }, { type: 'candidate-pair', requestsSent: 1 },
  ])).requestsSent).toBeNull();
});
