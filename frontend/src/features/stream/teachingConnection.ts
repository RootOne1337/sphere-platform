import { api } from '@/lib/api';
import { parseProbeAdmission } from './DirectProbeAccess';
import { startDirectVideoSession, type DirectProbeResult } from './directProbe';
import type { DirectControlEndpoint } from './directPointerTransport';
import type { DirectVideoBinding } from './directVideoProtocol';

export type TeachingConnection = { close(): void; fresh(): boolean; binding(): DirectVideoBinding | null;
  endpoint(): DirectControlEndpoint | null; worker: Worker };

/** One explicit capture-only presence and one direct peer. No media relay or automatic retry. */
export async function connectTeaching(deviceId: string, token: string, video: HTMLVideoElement,
  signal: AbortSignal, report: (value: DirectProbeResult) => void, failed: (reason: string) => void,
  workerMessage: (message: Record<string, unknown>) => void): Promise<TeachingConnection> {
  if (!window.isSecureContext || !('RTCRtpScriptTransform' in window) || !navigator.storage?.getDirectory
    || typeof video.requestVideoFrameCallback !== 'function') throw Error('browser_recording_unavailable');
  const { data } = await api.get(`/devices/${encodeURIComponent(deviceId)}/direct-probe-capabilities`, { signal });
  const profiles = parseProbeAdmission(data, deviceId);
  if (!profiles || data.live_video_enabled !== true || data.direct_input_enabled !== true || data.shared_input_enabled !== true)
    throw Error('shared_direct_video_not_admitted');
  if (signal.aborted) throw Error('connection_cancelled');
  const base = process.env.NEXT_PUBLIC_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
  const socket = new WebSocket(`${base}/ws/stream/${encodeURIComponent(deviceId)}`);
  const worker = new Worker('/teaching-recorder.worker.js');
  let session: string | null = null, dimensions: { width: number; height: number } | null = null;
  let binding: DirectVideoBinding | null = null, endpoint: DirectControlEndpoint | null = null;
  let cancel: (() => void) | null = null, disposed = false, attached = false;
  let lastFrame = 0, frameId: number | null = null;
  const close = () => {
    if (disposed) return;
    disposed = true; clearTimeout(deadline); clearInterval(watchdog); signal.removeEventListener('abort', close);
    socket.onopen = socket.onmessage = socket.onerror = socket.onclose = null;
    socket.close(); cancel?.(); endpoint = null;
    if (frameId !== null) video.cancelVideoFrameCallback(frameId);
    video.pause(); video.srcObject = null;
    // Caller finalizes files before terminating the separate recorder worker.
  };
  const fault = (reason: string) => { if (!disposed) failed(reason); };
  const fresh = () => !disposed && !!binding && !!lastFrame && performance.now() - lastFrame < 250 && !document.hidden;
  const present = () => { frameId = video.requestVideoFrameCallback((_at, frame) => {
    if (disposed) return;
    if (!binding) { present(); return; }
    if (frame.width !== binding.width || frame.height !== binding.height) { fault('display_capture_changed'); return; }
    lastFrame = performance.now(); clearTimeout(deadline); present();
  }); };
  const deadline = setTimeout(() => fault('teaching_connection_timeout'), 30000);
  const watchdog = setInterval(() => {
    if (disposed) return;
    if (lastFrame && performance.now() - lastFrame > 1000) fault('video_stalled');
    if (document.hidden) fault('page_hidden');
  }, 100);
  signal.addEventListener('abort', close, { once: true });
  worker.onmessage = event => {
    if (event.data?.type === 'attached') attached = true;
    workerMessage(event.data);
  };
  worker.onerror = () => fault('recorder_worker_failed');
  socket.onopen = () => socket.send(JSON.stringify({ token, delivery: 'capture_only' }));
  socket.onerror = () => fault('capture_socket_failed'); socket.onclose = () => fault('capture_socket_closed');
  socket.onmessage = event => {
    if (disposed) return;
    if (typeof event.data !== 'string' || event.data.length > 4096) { fault('unexpected_server_media'); return; }
    try {
      const value = JSON.parse(event.data);
      if (value.type === 'stream_session') {
        if (session || value.schema_version !== 1 || value.delivery !== 'capture_only'
          || typeof value.session_id !== 'string' || !/^[0-9a-f]{16}$/.test(value.session_id)) throw Error();
        session = value.session_id;
      } else if (value.type === 'capture_ready') {
        if (dimensions || !session || value.session_id !== session || value.schema_version !== 1
          || !Number.isInteger(value.width) || !Number.isInteger(value.height)
          || value.width < 1 || value.height < 1 || value.width > 8192 || value.height > 8192) throw Error();
        dimensions = { width: value.width, height: value.height };
        cancel = startDirectVideoSession(`${base}/ws/direct-probe/${encodeURIComponent(deviceId)}`, token, result => {
          if (disposed) return;
          if (result.videoBinding) {
            const next = result.videoBinding;
            if (next.width !== dimensions!.width || next.height !== dimensions!.height
              || binding && binding.captureEpoch !== next.captureEpoch) { fault('direct_capture_changed'); return; }
            binding = next;
          }
          report(result);
          if (['failed','stopped','finished'].includes(result.state)) fault(result.reason ?? 'direct_video_closed');
        }, { historySession: session, controlSession: session, sharedInput: true, receiverSize: dimensions,
          trickleIce: data.trickle_ice_enabled === true,
          controlledStunUrl: profiles.includes('public-stun') ? 'stun:stun.cloudflare.com:3478' : undefined,
          hasRecentVideoFrame: fresh,
          onReceiver: receiver => {
            if (attached) throw Error('second_receiver');
            receiver.transform = new RTCRtpScriptTransform(worker);
          },
          onControlChannel: channel => { endpoint = channel; if (!channel && !disposed) fault('control_channel_closed'); },
          onTrack: track => {
            video.srcObject = new MediaStream([track]); present();
            void video.play().catch(() => fault('video_play_failed'));
          },
        });
      // This is a server liveness notice, not an application request. The
      // capture-only socket rejects client pong messages; WebSocket ping/pong
      // control frames are handled by the browser/network stack separately.
      } else if (value.type === 'ping') { /* no application reply */ }
      else if (!['stream_link_ready','video_delivery_ack'].includes(value.type)) throw Error();
    } catch { fault('invalid_capture_message'); }
  };
  return { close, fresh, binding: () => binding, endpoint: () => endpoint, worker };
}
