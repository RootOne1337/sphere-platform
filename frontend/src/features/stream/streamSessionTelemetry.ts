import type { StreamDecoderStats } from '@/lib/h264-decoder';
import type { ContinuousPointerState } from './continuousPointer';
import type { DirectProbeResult } from './directProbe';
import type { DiagnosticProfile } from './DirectProbeDiagnostics';
import type { LiveVideoObservation } from './LiveDirectVideo';

type ControlObservation = { state: ContinuousPointerState | 'probing'; failure: string | null; rtt: number | null; attempts: number };
const counter = (value: number) => Number.isFinite(value) ? Math.min(Number.MAX_SAFE_INTEGER, Math.max(0, Math.floor(value))) : 0;
const milliseconds = (value: number | null) => value === null || !Number.isFinite(value) ? null : Math.min(86400000, Math.max(0, value));
const reasons = new Set(['probe_deadline', 'gathering_deadline', 'signaling_deadline', 'connection_deadline',
  'invalid_description', 'missing_binding', 'signaling_unavailable', 'invalid_ice_grant', 'invalid_answer',
  'invalid_signal', 'signaling_closed', 'webrtc_unavailable', 'invalid_video_track', 'video_track_ended',
  'video_renderer_failed', 'peer_disconnected', 'echo_timeout', 'channel_backpressure', 'echo_send_failed',
  'invalid_video_binding', 'invalid_echo', 'channel_failed', 'channel_closed', 'offer_failed',
  'video_access_rejected', 'video_first_frame_timeout', 'video_renderer_unavailable', 'capture_changed', 'session_lifetime']);
const directStates = new Set(['gathering', 'signaling', 'connecting', 'connected', 'finished', 'stopped', 'failed']);
export const directFailure = (reason: string | null | undefined) => reason ? reasons.has(reason) ? reason : 'other' : null;

/** Explicit scalar whitelist: decoder exception text and Android input never leave the viewer. */
export function browserStreamSample(stats: StreamDecoderStats, control: ControlObservation, now = Date.now(), direct?: LiveVideoObservation) {
  const age = (at: number | null) => at === null ? null : milliseconds(now - at);
  return { schema_version: 1, transport: direct?.active ? 'direct_webrtc' : 'server_websocket', visibility: document.hidden ? 'hidden' : 'visible',
    ...(direct ? { control_transport: 'server_websocket', direct_frames: counter(direct.frames),
      direct_frame_age_ms: age(direct.lastFrameAt), direct_path: direct.result?.path ?? 'unknown',
      direct_state: direct.result && directStates.has(direct.result.state) ? direct.result.state : null,
      direct_failure: directFailure(direct.result?.reason),
      direct_ice_state: direct.result?.iceState ?? null,
      direct_dtls_state: ['new', 'connecting', 'connected', 'closed', 'failed'].includes(direct.result?.network?.dtlsState ?? '')
        ? direct.result!.network!.dtlsState : null,
      direct_network_rtt_ms: milliseconds(direct.result?.videoStats?.networkRttMs ?? null),
      direct_jitter_buffer_ms: milliseconds(direct.result?.videoStats?.jitterBufferMs ?? null),
      direct_decode_ms: milliseconds(direct.result?.videoStats?.decodeMs ?? null),
      direct_fps: direct.result?.videoStats?.fps ?? null, direct_attempts: Math.min(1000000, counter(direct.attempts)) } : {}),
    received_packets: counter(stats.binaryMessagesReceived), received_bytes: counter(stats.binaryBytesReceived),
    rendered_frames: counter(stats.renderedFrames), decoded_frames: counter(stats.decodedOutputs),
    invalid_packets: counter(stats.invalidPackets), decode_errors: counter(stats.decodeErrors), render_errors: counter(stats.renderErrors),
    queue_recoveries: counter(stats.queueRecoveries), stale_output_drops: counter(stats.staleOutputDrops),
    decoder_queue: Math.min(1024, counter(stats.decoderQueueSize)), pending_outputs: Math.min(1024, counter(stats.pendingOutputCount)),
    incoming_fps: Math.min(1024, counter(stats.receivedPictureFps)), rendered_fps: Math.min(1024, counter(stats.renderedFps)),
    packet_age_ms: age(stats.lastBinaryAtMs), frame_age_ms: age(stats.lastRenderedAtMs), control_state: control.state,
    control_failure: !control.failure ? 'none' : control.failure.includes('timeout') ? 'timeout'
      : control.failure === 'server_rejected' ? 'server_rejected' : control.failure === 'server_admission_retry' ? 'admission_retry'
      : control.failure === 'server_runtime_retry' ? 'runtime_retry' : 'other',
    control_rtt_ms: milliseconds(control.rtt), recovery_attempts: Math.min(1000000, counter(control.attempts)) };
}

export function directDiagnosticSample(result: DirectProbeResult, frames: number, profile: DiagnosticProfile, automatic: boolean) {
  const samples = result.samples.filter(value => Number.isFinite(value) && value >= 0).slice(0, 20).sort((a, b) => a - b);
  const ice = result.iceState;
  const dtls = result.network?.dtlsState;
  return { schema_version: 1, mode: 'readonly_video', trigger: automatic ? 'automatic' : 'manual', profile,
    state: ['finished', 'stopped', 'failed'].includes(result.state) ? result.state : 'failed', path: result.path,
    protocol: ['udp', 'tcp'].includes(result.protocol ?? '') ? result.protocol : null,
    reason: directFailure(result.reason),
    echoes: samples.length, echo_rtt_p95_ms: samples.length ? milliseconds(samples[Math.ceil(samples.length * .95) - 1]) : null,
    presented_frames: counter(frames), width: result.videoBinding?.width ?? null, height: result.videoBinding?.height ?? null,
    ice_state: ice && ['new', 'checking', 'connected', 'completed', 'disconnected', 'failed', 'closed'].includes(ice) ? ice : null,
    dtls_state: dtls && ['new', 'connecting', 'connected', 'closed', 'failed'].includes(dtls) ? dtls : null };
}

/** No timers, queues or retries. Reuses the existing viewer watchdog cadence. */
export class StreamSessionReporter {
  private session: string | null = null;
  private lastSent = -Infinity;
  constructor(private socket: WebSocket, private snapshot: () => ReturnType<typeof browserStreamSample> | null) {}
  get sessionId() { return this.session; }
  accept(value: unknown): boolean {
    if (!value || typeof value !== 'object') return false;
    const message = value as Record<string, unknown>;
    if (message.type !== 'stream_session' || message.schema_version !== 1 || message.history_enabled !== true
      || typeof message.session_id !== 'string' || !/^[a-f0-9]{16}$/.test(message.session_id)
      || message.report_interval_seconds !== 10 || this.session !== null) return false;
    this.session = message.session_id;
    this.report();
    return true;
  }
  private send(type: string, sample: unknown): boolean {
    if (!this.session || this.socket.readyState !== WebSocket.OPEN || this.socket.bufferedAmount > 64 * 1024) return false;
    try {
      const message = JSON.stringify({ type, sample });
      if (message.length > 4096) return false;
      this.socket.send(message); return true;
    } catch { return false; }
  }
  report(force = false): void {
    if (!this.session) return;
    const now = performance.now();
    if (now - this.lastSent < (force ? 1000 : 10000)) return;
    try {
      const sample = this.snapshot();
      if (sample && this.send('viewer_telemetry', sample)) this.lastSent = now;
    } catch { /* Optional telemetry cannot interrupt the video watchdog. */ }
  }
  direct(sample: ReturnType<typeof directDiagnosticSample>, session: string): boolean {
    return session === this.session && this.send('viewer_direct_result', sample);
  }
}
