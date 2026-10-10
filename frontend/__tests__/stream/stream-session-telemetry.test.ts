import { browserStreamSample, directDiagnosticSample, StreamSessionReporter } from '@/src/features/stream/streamSessionTelemetry';
import type { StreamDecoderStats } from '@/lib/h264-decoder';

const stats = { binaryMessagesReceived: 20, binaryBytesReceived: 300, renderedFrames: 10, decodedOutputs: 10,
  invalidPackets: 0, decodeErrors: 0, renderErrors: 0, queueRecoveries: 0, staleOutputDrops: 0,
  decoderQueueSize: 0, pendingOutputCount: 0, receivedPictureFps: 15, renderedFps: 15,
  lastBinaryAtMs: 900, lastRenderedAtMs: 800, lastDecodeError: 'private native exception' } as StreamDecoderStats;
const sample = () => browserStreamSample(stats, { state: 'ready', failure: null, rtt: 25, attempts: 1 }, 1000);
const session = { type: 'stream_session', schema_version: 1, session_id: 'abcdef0123456789', history_enabled: true, report_interval_seconds: 10 };
const socket = () => ({ readyState: WebSocket.OPEN, bufferedAmount: 0, send: jest.fn() } as unknown as WebSocket);

beforeEach(() => jest.useFakeTimers());
afterEach(() => jest.useRealTimers());

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
