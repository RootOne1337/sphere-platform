'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import type { CaptureFrameBinding } from '@/lib/h264-decoder';
import { parseProbeAdmission } from './DirectProbeAccess';
import { startDirectVideoSession, type DirectProbeResult } from './directProbe';
import type { DirectVideoBinding } from './directVideoProtocol';
import type { DirectControlEndpoint } from './directPointerTransport';

export interface LiveVideoObservation {
  admitted: boolean; admissionKnown: boolean; active: boolean; frames: number; lastFrameAt: number | null;
  attempts: number; result: DirectProbeResult | null;
}
const empty = (): LiveVideoObservation => ({ admitted: false, admissionKnown: false, active: false, frames: 0,
  lastFrameAt: null, attempts: 0, result: null });
const FRAME_PROGRESS_TIMEOUT_MS = 6000;
export function matchesDisplayedCapture(binding: DirectVideoBinding, expected: CaptureFrameBinding | null, width: number, height: number): boolean {
  return !!expected && binding.captureEpoch === expected.captureEpoch && binding.width === expected.frameWidth
    && binding.height === expected.frameHeight && width === binding.width && height === binding.height;
}

/** One current viewer owns the renderer. RTC readiness alone never changes the main surface. */
export function LiveDirectVideo({ deviceId, session, eligible, fit, expectedCapture, onFrame, onObservation, onControlChannel, onDeliveryChange }: {
  deviceId: string; session: string; eligible: boolean; fit?: 'contain' | 'cover' | 'fill';
  expectedCapture: () => CaptureFrameBinding | null;
  onFrame: (video: HTMLVideoElement, binding: DirectVideoBinding) => boolean;
  onObservation: (value: LiveVideoObservation) => void;
  onControlChannel?: (channel: DirectControlEndpoint | null) => void;
  onDeliveryChange?: (peerSession: string | null) => void;
}) {
  const token = useAuthStore(state => state.accessToken);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const [visible, setVisible] = useState(() => !document.hidden);
  const [active, setActive] = useState(false);
  const video = useRef<HTMLVideoElement>(null);
  const callbacks = useRef({ expectedCapture, onFrame, onObservation, onControlChannel, onDeliveryChange });
  callbacks.current = { expectedCapture, onFrame, onObservation, onControlChannel, onDeliveryChange };
  const controlEnabled = onControlChannel !== undefined;
  useEffect(() => {
    const changed = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  const admission = useQuery({
    queryKey: ['direct-probe-capabilities', deviceId, sessionVersion, 'live', session],
    enabled: !!token && eligible && visible,
    queryFn: async ({ signal }) => {
      const { data } = await api.get(`/devices/${encodeURIComponent(deviceId)}/direct-probe-capabilities`, { signal });
      const profiles = parseProbeAdmission(data, deviceId);
      if (!profiles || 'live_video_enabled' in data && typeof data.live_video_enabled !== 'boolean'
        || data.live_video_enabled === true && !data.enabled) throw Error('invalid_live_admission');
      if ('direct_input_enabled' in data && typeof data.direct_input_enabled !== 'boolean'
        || data.direct_input_enabled === true && data.live_video_enabled !== true) throw Error('invalid_input_admission');
      if ('legacy_video_handover_enabled' in data && typeof data.legacy_video_handover_enabled !== 'boolean'
        || data.legacy_video_handover_enabled === true && data.live_video_enabled !== true) throw Error('invalid_delivery_admission');
      return { admitted: data.live_video_enabled === true, profiles, input: data.direct_input_enabled === true,
        nativeHistory: data.native_history_enabled === true, handover: data.legacy_video_handover_enabled === true };
    },
    retry: (count, error) => count < 3 && isAxiosError(error) && (
      error.response ? [408, 429].includes(error.response.status) || error.response.status >= 500 && error.response.status <= 599
        : ['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'].includes(error.code ?? '')),
    retryDelay: count => Math.min(4000, 1000 * 2 ** count),
    refetchOnReconnect: true, staleTime: 30000, gcTime: 0,
  });
  useEffect(() => {
    const observation = empty();
    observation.admitted = admission.data?.admitted === true;
    observation.admissionKnown = !!admission.data || admission.isError;
    callbacks.current.onObservation(observation);
    if (!observation.admitted || !token || !eligible || !visible || !video.current) return;
    const element = video.current;
    // Permission is part of this peer's negotiated channels. Keep its release
    // callback even when the next render has already switched to read-only.
    const releaseControl = callbacks.current.onControlChannel;
    const releaseDelivery = callbacks.current.onDeliveryChange;
    let deliveryActive = false;
    const base = process.env.NEXT_PUBLIC_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
    // STUN supplies reflexive candidates alongside host candidates. ICE still
    // prefers a usable host pair; no separate 12-second host-only attempt.
    const stun = admission.data?.profiles.includes('public-stun') ? 'stun:stun.cloudflare.com:3478' : undefined;
    let disposed = false, generation = 0, attemptsInWindow = 0, cancel: (() => void) | null = null;
    let frameCallback: number | null = null, firstFrame: ReturnType<typeof setTimeout> | null = null;
    let frameWatchdog: ReturnType<typeof setInterval> | null = null;
    let deliveryRenewal: ReturnType<typeof setInterval> | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const publish = () => {
      if (disposed) return;
      setActive(observation.active);
      callbacks.current.onObservation({ ...observation });
    };
    const clearRenderer = () => {
      if (frameCallback !== null) element.cancelVideoFrameCallback?.(frameCallback);
      frameCallback = null;
      if (firstFrame !== null) clearTimeout(firstFrame);
      firstFrame = null;
      if (frameWatchdog !== null) clearInterval(frameWatchdog);
      frameWatchdog = null;
      if (deliveryRenewal !== null) clearInterval(deliveryRenewal);
      deliveryRenewal = null;
      if (deliveryActive) releaseDelivery?.(null);
      deliveryActive = false;
      element.pause(); element.srcObject = null;
    };
    const begin = () => {
      if (disposed || document.hidden || !callbacks.current.expectedCapture()) return;
      const current = ++generation;
      observation.attempts++; attemptsInWindow++;
      observation.active = false; observation.result = null; publish();
      let ended = false, seen = false, bindingDeadlineArmed = false, presentedSince: number | null = null;
      let lastPresentedAt: number | null = null;
      const finish = (result: DirectProbeResult) => {
        if (disposed || current !== generation || ended) return;
        ended = true;
        releaseControl?.(null);
        const stop = cancel; cancel = null; stop?.();
        clearRenderer(); observation.active = false; observation.result = result; publish();
        // A busy device or transient network loss must not produce a reconnect
        // storm. Four attempts per window, then one minute of server fallback.
        if (result.reason === 'video_access_rejected' || document.hidden) return;
        // A healthy displayed stream starts a new failure window. Old setup
        // failures must not impose a minute of fallback on a later isolated loss.
        if (presentedSince !== null && performance.now() - presentedSince >= 30000) attemptsInWindow = 1;
        const delay = attemptsInWindow >= 4 ? 60000 : Math.min(15000, 1000 * 2 ** (attemptsInWindow - 1));
        retry = setTimeout(() => { retry = null; if (attemptsInWindow >= 4) attemptsInWindow = 0; begin(); }, delay);
      };
      const fail = (reason: string) => finish({ ...(observation.result ?? { state: 'failed', samples: [], path: 'unknown', protocol: null }), state: 'failed', reason });
      const nextFrame = () => {
        if (disposed || ended || current !== generation) return;
        frameCallback = element.requestVideoFrameCallback((_at, metadata) => {
          frameCallback = null;
          if (disposed || ended || current !== generation) return;
          const binding = observation.result?.videoBinding;
          if (binding) {
            if (!matchesDisplayedCapture(binding, callbacks.current.expectedCapture(), metadata.width, metadata.height)) {
              fail('capture_changed'); return;
            }
            try {
              if (!callbacks.current.onFrame(element, binding)) { fail('video_renderer_failed'); return; }
            } catch { fail('video_renderer_failed'); return; }
            seen = true;
            presentedSince ??= performance.now();
            lastPresentedAt = performance.now();
            const peerSession = observation.result?.session;
            if (!deliveryActive && admission.data?.handover && releaseDelivery && peerSession && /^[0-9a-f]{32}$/.test(peerSession)) {
              // Promotion follows an actual canvas presentation. Periodic ICE
              // or telemetry updates cannot prolong suppression of the reserve.
              deliveryActive = true;
              callbacks.current.onDeliveryChange?.(peerSession);
              deliveryRenewal = setInterval(() => {
                if (!disposed && !ended && current === generation && !document.hidden && lastPresentedAt !== null
                  && performance.now() - lastPresentedAt < 3000) callbacks.current.onDeliveryChange?.(peerSession);
              }, 3000);
            }
            if (frameWatchdog === null) frameWatchdog = setInterval(() => {
              if (disposed || ended || current !== generation || document.hidden || lastPresentedAt === null) return;
              // ICE, echo and inbound RTP statistics cannot keep a frozen renderer
              // primary. Actual presentation is required, including idle refreshes.
              if (performance.now() - lastPresentedAt >= FRAME_PROGRESS_TIMEOUT_MS) fail('video_frame_timeout');
            }, 1000);
            if (firstFrame !== null) clearTimeout(firstFrame);
            firstFrame = null;
            const first = !observation.active;
            observation.frames++; observation.lastFrameAt = Date.now(); observation.active = true;
            // Frame delivery stays outside React; publish scalars at most once
            // per second, plus the first frame which activates this surface.
            if (first || observation.frames % 30 === 0) publish();
          }
          nextFrame();
        });
      };
      firstFrame = setTimeout(() => fail('video_first_frame_timeout'), 30000);
      try {
        const stop = startDirectVideoSession(`${base}/ws/direct-probe/${encodeURIComponent(deviceId)}`, token, result => {
          if (disposed || ended || current !== generation) return;
          observation.result = result;
          if (['failed', 'stopped', 'finished'].includes(result.state)) { finish(result); return; }
          if (result.videoBinding && !seen && !bindingDeadlineArmed && firstFrame !== null) {
            bindingDeadlineArmed = true;
            clearTimeout(firstFrame);
            firstFrame = setTimeout(() => fail('video_first_frame_timeout'), 8000);
          }
          publish();
        }, { controlledStunUrl: stun,
          hasRecentVideoFrame: () => !disposed && !ended && current === generation && !document.hidden
            && lastPresentedAt !== null && performance.now() - lastPresentedAt < FRAME_PROGRESS_TIMEOUT_MS,
          ...(admission.data?.nativeHistory || admission.data?.handover ? { historySession: session } : {}),
          ...(admission.data?.input && callbacks.current.onControlChannel ? {
            controlSession: session, onControlChannel: (channel: DirectControlEndpoint | null) => {
              if (!disposed && !ended && current === generation) callbacks.current.onControlChannel?.(channel);
            },
          } : {}), onTrack: track => {
          if (disposed || ended || current !== generation) { track.stop(); return; }
          element.srcObject = new MediaStream([track]);
          if (typeof element.requestVideoFrameCallback !== 'function') { fail('video_renderer_unavailable'); return; }
          nextFrame();
          void element.play().catch(() => {
            if (!disposed && !ended && current === generation) fail('video_renderer_failed');
          });
        } });
        if (disposed || ended || current !== generation) stop(); else cancel = stop;
      } catch { fail('webrtc_unavailable'); }
    };
    // A Wi-Fi/mobile transition can leave an otherwise connected peer bound to
    // obsolete candidates. Coalesce duplicate browser notifications and start a
    // new authenticated attempt, even during the normal failure cooldown. Old
    // callbacks are fenced before teardown; no input is queued or transferred.
    const networkChanged = () => {
      if (disposed || document.hidden) return;
      generation++;
      const old = cancel; cancel = null; old?.();
      clearRenderer(); releaseControl?.(null);
      observation.active = false;
      observation.result = { ...(observation.result ?? { samples: [], path: 'unknown', protocol: null }),
        state: 'failed', reason: 'network_changed' };
      publish();
      if (retry !== null) clearTimeout(retry);
      attemptsInWindow = 0;
      retry = setTimeout(() => { retry = null; begin(); }, 500);
    };
    const connection = (navigator as Navigator & { connection?: EventTarget & { type?: string } }).connection;
    let connectionType = connection?.type;
    const connectionChanged = () => {
      const nextType = connection?.type;
      const interfaceChanged = !!connectionType && !!nextType && connectionType !== nextType;
      connectionType = nextType;
      // This event also reports new bandwidth/RTT estimates. Do not tear down a
      // working stream or held input just because a congestion estimate changed.
      // Without a supported interface type, actual ICE loss still owns recovery.
      if (observation.active && observation.result?.state === 'connected' && !interfaceChanged) return;
      networkChanged();
    };
    window.addEventListener('online', networkChanged);
    connection?.addEventListener('change', connectionChanged);
    begin();
    return () => {
      disposed = true; generation++;
      window.removeEventListener('online', networkChanged);
      connection?.removeEventListener('change', connectionChanged);
      if (retry !== null) clearTimeout(retry);
      cancel?.(); clearRenderer();
      releaseControl?.(null);
      setActive(false);
      callbacks.current.onObservation({ ...empty(), admitted: observation.admitted, admissionKnown: observation.admissionKnown });
    };
  }, [deviceId, session, token, eligible, visible, admission.data, admission.isError, controlEnabled]);
  return <video ref={video} muted autoPlay playsInline aria-hidden="true" data-direct-video-active={active ? 'true' : 'false'}
    className="pointer-events-none absolute inset-0 h-full w-full rounded border border-gray-700 bg-black"
    style={{ objectFit: fit ?? 'contain', opacity: active ? 1 : 0 }} />;
}
