/** Bounded aggregate only: never expose candidate addresses, SDP, IDs or credentials. */
export interface DirectProbeNetwork {
  localCandidates: number;
  remoteCandidates: number;
  pairs: number;
  checkingPairs: number;
  failedPairs: number;
  succeededPairs: number;
  requestsSent: number | null;
  responsesReceived: number | null;
  dtlsState: string | null;
}

export function probeNetwork(stats: RTCStatsReport): DirectProbeNetwork {
  const result: DirectProbeNetwork = {
    localCandidates: 0, remoteCandidates: 0, pairs: 0,
    checkingPairs: 0, failedPairs: 0, succeededPairs: 0,
    requestsSent: null, responsesReceived: null, dtlsState: null,
  };
  const requests: unknown[] = [], responses: unknown[] = [];
  stats.forEach(value => {
    if (value.type === 'local-candidate') result.localCandidates++;
    if (value.type === 'remote-candidate') result.remoteCandidates++;
    if (value.type === 'candidate-pair') {
      result.pairs++;
      if (value.state === 'in-progress') result.checkingPairs++;
      if (value.state === 'failed') result.failedPairs++;
      if (value.state === 'succeeded') result.succeededPairs++;
      requests.push(value.requestsSent); responses.push(value.responsesReceived);
    }
    if (value.type === 'transport' && ['new', 'connecting', 'connected', 'closed', 'failed'].includes(value.dtlsState)) {
      result.dtlsState = value.dtlsState;
    }
  });
  const sum = (values: unknown[]) => {
    if (!values.length || !values.every(v => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0)) return null;
    const total = (values as number[]).reduce((a, b) => a + b, 0);
    return Number.isSafeInteger(total) ? total : null;
  };
  result.requestsSent = sum(requests); result.responsesReceived = sum(responses);
  return result;
}
