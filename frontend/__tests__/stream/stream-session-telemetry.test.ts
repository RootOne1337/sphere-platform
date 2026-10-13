import { browserStreamSample, directDiagnosticSample, StreamSessionReporter, directFailure } from '@/src/features/stream/streamSessionTelemetry';
import type { StreamDecoderStats } from '@/lib/h264-decoder';
import type { PointerFenceObservation } from '@/src/features/stream/continuousPointer';

const stats = { binaryMessagesReceived: 20, binaryBytesReceived: 300, renderedFrames: 10, decodedOutputs: 10,
  invalidPackets: 0, decodeErrors: 0, renderErrors: 0, queueRecoveries: 0, staleOutputDrops: 0,
  decoderQueueSize: 0, pendingOutputCount: 0, receivedPictureFps: 15, renderedFps: 15,
  lastBinaryAtMs: 900, lastRenderedAtMs: 800, lastDecodeError: 'private native exception' } as StreamDecoderStats;
const sample = () => browserStreamSample(stats, { state: 'ready', failure: null, rtt: 25, attempts: 1 }, 1000);
test('server echo and Android receipt retain separate scalar values and a missing echo stays unknown', () => {
  const result = browserStreamSample(stats, { state: 'ready', failure: null, rtt: 140, attempts: 0 }, 1000,
    undefined, { rttMs: 34, ageMs: 20 });
  expect(result).toMatchObject({ control_rtt_ms: 140, server_link_rtt_ms: 34, server_link_sample_age_ms: 20 });
  expect(sample().server_link_rtt_ms).toBeNull();
});
const session = { type: 'stream_session', schema_version: 1, session_id: 'abcdef0123456789', history_enabled: true, report_interval_seconds: 10 };
const socket = () => ({ readyState: WebSocket.OPEN, bufferedAmount: 0, send: jest.fn() } as unknown as WebSocket);
const fence: PointerFenceObservation = { reason: 'native_receipt_timeout', phase: 'ready', idleHeartbeatOnly: true,
  offeredSequence: 25, acknowledgedSequence: 20, pendingCount: 5, oldestSequence: 21, oldestAction: 4,
  oldestAgeMs: 1250, oldestDeadlineAgeMs: 1250, terminalSequence: null, terminalAgeMs: null, pointerHeld: false,
  tickGapMs: 16, lastSendAgeMs: 200, lastReceiptAgeMs: 1400, lastReceiptRoundTripMs: 250, socketState: 1, bufferedBytes: 0 };

test.each(['idle_receipt_timeout', 'pointer_receipt_timeout'])('preserves the specific timeout and one scalar fence snapshot: %s', failure => {
  const result = browserStreamSample(stats, {state: 'fenced', failure, rtt: 250, attempts: 1,
    fence: {...fence, owner: 'private owner', coordinates: [1,2], error: 'private exception'} as PointerFenceObservation, fenceAtMs: 900}, 1000);
  expect(result).toMatchObject({control_failure: 'timeout', control_failure_detail: failure,
    control_fence: {reason: 'native_receipt_timeout', phase: 'ready', age_ms: 100, pointer_held: false,
      idle_heartbeat_only: true, oldest_action: 4, oldest_deadline_age_ms: 1250,
      pending_count: 5, last_receipt_rtt_ms: 250, tick_gap_ms: 16, socket_state: 1, buffered_bytes: 0}});
  expect(JSON.stringify(result)).not.toMatch(/private|owner|coordinates|exception/);
});

test('a bad fence field remains unknown and a missing fence cannot inherit the previous viewer', () => {
  const result = browserStreamSample(stats, {state:'fenced', failure: 'scheduler_gap', rtt: null, attempts: 0,
    fence: {...fence, reason:'private exception', pendingCount: 33, lastReceiptRoundTripMs: NaN,
      offeredSequence: 2147483648, socketState: 99, bufferedBytes: -1}}, 1000);
  expect(result.control_fence).toMatchObject({reason:'other', pending_count: null, offered_sequence: null,
    last_receipt_rtt_ms: null, socket_state: null, buffered_bytes: null, age_ms: null});
  expect(sample().control_fence).toBeNull();
});

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

test.each(['control_channel_closed', 'control_channel_failed', 'invalid_control_message'])('direct input recovery keeps its bounded cause in history: %s', reason => {
  expect(directFailure(reason)).toBe(reason);
  const diagnostic = directDiagnosticSample({ state: 'failed', samples: [], path: 'host', protocol: 'udp', reason }, 1, 'host', true);
  expect(diagnostic.reason).toBe(reason);
  expect(JSON.stringify(diagnostic)).not.toMatch(/token|coordinate|SDP|credential/);
});

test('reports only after server admission, once per cadence, with no raw decoder text or credentials', () => {
  const ws = socket(), snapshot = jest.fn(sample), reporter = new StreamSessionReporter(ws, snapshot);
  reporter.report(); expect(snapshot).not.toHaveBeenCalled();
  expect(reporter.accept(session)).toBe(true);
  expect(reporter.accept(session)).toBe(false);
  reporter.report(); expect(ws.send).toHaveBeenCalledTimes(1);
  jest.advanceTimersByTime(10000); reporter.report(); expect(ws.send).toHaveBeenCalledTimes(2);
  const message = JSON.parse((ws.send as jest.Mock).mock.calls[0][0]);
  expect(message.sample.packet_age_ms).toBe(100);
  expect(message.sample.frame_age_ms).toBe(200);
  expect(JSON.stringify(message)).not.toMatch(/private|token|session_id|lastDecodeError|captureEpoch/);
});

test('backpressure, invalid admission and a closed socket never queue or resend diagnostics', () => {
  const ws = socket(), reporter = new StreamSessionReporter(ws, sample);
  expect(reporter.accept({ ...session, session_id: 'foreign/id' })).toBe(false);
  expect(reporter.accept({ ...session, report_interval_seconds: 0 })).toBe(false);
  (ws as unknown as { bufferedAmount: number }).bufferedAmount = 100000;
  reporter.accept(session); expect(ws.send).not.toHaveBeenCalled();
  (ws as unknown as { readyState: number }).readyState = WebSocket.CLOSED;
  reporter.report(true); expect(ws.send).not.toHaveBeenCalled();
});

test('a telemetry getter failure cannot prevent the next watchdog tick or throw into stream handling', () => {
  const ws = socket(), snapshot = jest.fn().mockImplementationOnce(() => { throw Error('optional'); }).mockImplementation(sample);
  const reporter = new StreamSessionReporter(ws, snapshot);
  expect(() => reporter.accept(session)).not.toThrow();
  reporter.report(); expect(ws.send).toHaveBeenCalledTimes(1);
});

const failureSample = (attempt = 1) => browserStreamSample(stats,
  { state: 'ready', failure: null, rtt: 25, attempts: 1 }, 1000,
  { admitted: true, admissionKnown: true, active: false, frames: 0, lastFrameAt: null, attempts: attempt,
    result: { state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'connection_deadline',
      iceState: 'checking', network: { localCandidates: 5, remoteCandidates: 2, pairs: 2, checkingPairs: 2,
        failedPairs: 0, succeededPairs: 0, requestsSent: 143, responsesReceived: 0, dtlsState: 'new' } } });

test('a failure between periodic reports is sent before a retry erases its ICE observation', () => {
  const ws = socket();
  let current = sample();
  const reporter = new StreamSessionReporter(ws, () => current);
  reporter.accept(session);
  jest.advanceTimersByTime(50);
  current = failureSample();
  reporter.reportFailure();
  const messages = (ws.send as jest.Mock).mock.calls.map(([text]) => JSON.parse(text));
  expect(messages).toHaveLength(2);
  expect(messages[1]).toMatchObject({ type: 'viewer_telemetry', sample: {
    direct_state: 'failed', direct_failure: 'connection_deadline', direct_attempts: 1,
    direct_network: { requests_sent: 143, responses_received: 0 }, direct_dtls_state: 'new',
  } });
  // A subsequent setup state cannot mutate the already sent failure.
  current = sample();
  jest.advanceTimersByTime(5000); reporter.report();
  expect(ws.send).toHaveBeenCalledTimes(2);
  expect(JSON.stringify(messages[1])).not.toMatch(/private|token|session_id|credential|candidateId|coordinate/);
});

test('failure callbacks are deduplicated and rate capped separately from the periodic report', () => {
  const ws = socket();
  let current = failureSample();
  const reporter = new StreamSessionReporter(ws, () => current);
  reporter.accept(session);
  reporter.reportFailure(); reporter.reportFailure();
  expect(ws.send).toHaveBeenCalledTimes(2);
  jest.advanceTimersByTime(1000); reporter.reportFailure();
  expect(ws.send).toHaveBeenCalledTimes(2);
  // A new peer/effect can restart its attempt counter within the same viewer.
  reporter.reportFailure(false); reporter.reportFailure();
  expect(ws.send).toHaveBeenCalledTimes(3);
  current = failureSample(2); reporter.reportFailure();
  expect(ws.send).toHaveBeenCalledTimes(3);
  jest.advanceTimersByTime(1000); reporter.reportFailure();
  expect(ws.send).toHaveBeenCalledTimes(4);
});

test('terminal diagnostics never gain admission, retain a payload for replay, or affect a replacement viewer', () => {
  const ws = socket(), snapshot = jest.fn(failureSample);
  const reporter = new StreamSessionReporter(ws, snapshot);
  reporter.reportFailure(); expect(snapshot).not.toHaveBeenCalled();
  (ws as unknown as { bufferedAmount: number }).bufferedAmount = 100000;
  reporter.accept(session); reporter.reportFailure();
  expect(ws.send).not.toHaveBeenCalled();
  (ws as unknown as { bufferedAmount: number }).bufferedAmount = 0;
  jest.advanceTimersByTime(1000);
  expect(ws.send).not.toHaveBeenCalled();
  (ws as unknown as { readyState: number }).readyState = WebSocket.CLOSED;
  reporter.reportFailure(); expect(ws.send).not.toHaveBeenCalled();
  const replacement = socket(), next = new StreamSessionReporter(replacement, sample);
  next.accept({ ...session, session_id: '1'.repeat(16) });
  next.reportFailure();
  expect(replacement.send).toHaveBeenCalledTimes(1);
  expect(JSON.parse((replacement.send as jest.Mock).mock.calls[0][0]).sample.direct_failure).toBeUndefined();
});

test('direct results are bound to their viewer and distinguish echo RTT from presented frames', () => {
  const ws = socket(), reporter = new StreamSessionReporter(ws, sample);
  reporter.accept(session);
  const result = directDiagnosticSample({ state: 'finished', samples: Array(20).fill(25), path: 'nat', protocol: 'udp', reason: null }, 0, 'host', true);
  expect(result).toMatchObject({ presented_frames: 0, echo_rtt_p95_ms: 25, trigger: 'automatic' });
  expect(reporter.direct(result, 'another-viewer')).toBe(false);
  expect(reporter.direct(result, session.session_id)).toBe(true);
  expect(directDiagnosticSample({ state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'private exception' }, 0, 'host', true).reason).toBe('other');
});

test('the main video records bounded failure and ICE phases even when no direct picture arrived', () => {
  const direct = { admitted: true, admissionKnown: true, active: false, frames: 0, lastFrameAt: null, attempts: 2,
    result: { state: 'failed' as const, reason: 'connection_deadline', samples: [], path: 'unknown' as const, protocol: null,
      iceState: 'checking' as const, network: { dtlsState: 'new' } as never } };
  const result = browserStreamSample(stats, { state: 'ready', failure: null, rtt: 200, attempts: 0 }, 1000, direct);
  expect(result).toMatchObject({ transport: 'server_websocket', direct_state: 'failed',
    direct_failure: 'connection_deadline', direct_ice_state: 'checking', direct_dtls_state: 'new', direct_frames: 0 });
  direct.result.reason = 'private SDP or credential';
  expect(browserStreamSample(stats, { state: 'ready', failure: null, rtt: null, attempts: 0 }, 1000, direct).direct_failure).toBe('other');
});

test('retains only whitelisted control causes and the selected primary transport protocol', () => {
  const direct = { admitted: true, admissionKnown: true, active: true, frames: 12, lastFrameAt: 900, attempts: 1,
    result: { state: 'connected' as const, reason: null, samples: [], path: 'nat' as const, protocol: 'udp' } };
  expect(browserStreamSample(stats, { state: 'fenced', failure: 'native_input_rejected_or_unknown', rtt: null, attempts: 1 }, 1000, direct))
    .toMatchObject({ control_failure: 'other', control_failure_detail: 'native_input_rejected_or_unknown', direct_protocol: 'udp' });
  direct.result.protocol = 'private address or credential';
  const privateResult = browserStreamSample(stats, { state: 'fenced', failure: 'private native exception', rtt: null, attempts: 1 }, 1000, direct);
  expect(privateResult.control_failure_detail).toBeNull();
  expect(privateResult.direct_protocol).toBeNull();
  expect(JSON.stringify(privateResult)).not.toContain('private');
});

test('automatic primary history projects only bounded ICE counts, preserving unknown packet measurements', () => {
  const network = { localCandidates: 5, remoteCandidates: 1, pairs: 1, checkingPairs: 1, failedPairs: 0,
    succeededPairs: 0, requestsSent: 237, responsesReceived: null, dtlsState: 'new',
    address: 'private endpoint', candidateId: 'private id', credential: 'private key' };
  const direct = { admitted: true, admissionKnown: true, active: false, frames: 0, lastFrameAt: null, attempts: 1,
    result: { state: 'failed' as const, reason: 'connection_deadline', samples: [], path: 'unknown' as const,
      protocol: null, network, networkSampleAtMs: 12000, networkAgeAtStopMs: 400 } };
  const value = browserStreamSample(stats, { state: 'ready', failure: null, rtt: 200, attempts: 0 }, 1000, direct);
  expect(value.direct_network).toEqual({ local_candidates: 5, remote_candidates: 1, pairs: 1, checking_pairs: 1,
    failed_pairs: 0, succeeded_pairs: 0, requests_sent: 237, responses_received: null });
  expect(value).toMatchObject({ direct_network_sample_elapsed_ms: 12000, direct_network_age_at_stop_ms: 400,
    transport: 'server_websocket', control_transport: 'server_websocket', direct_frames: 0 });
  expect(JSON.stringify(value)).not.toMatch(/private|address|candidateId|credential/);
  network.requestsSent = Number.MAX_SAFE_INTEGER + 1;
  expect(browserStreamSample(stats, { state: 'ready', failure: null, rtt: null, attempts: 0 }, 1000, direct)
    .direct_network?.requests_sent).toBeNull();
  network.localCandidates = 257;
  expect(browserStreamSample(stats, { state: 'ready', failure: null, rtt: null, attempts: 0 }, 1000, direct)
    .direct_network).toBeNull();
});
