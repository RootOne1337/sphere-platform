'use client';
import { useEffect, useRef, useCallback, useState } from 'react';
import { H264Decoder } from '@/lib/h264-decoder';
import type { StreamDecoderStats } from '@/lib/h264-decoder';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';
import type { StreamFrameDimensions } from '@/src/features/stream/streamAspectRatio';
import { AndroidNavigationBar } from '@/src/features/stream/AndroidNavigationBar';
import type { UiBounds } from '@/src/features/stream/uiHierarchy';
import type { AcknowledgedControl, StreamInput } from '@/src/features/stream/controlObservation';
import { ContinuousPointer, attachContinuousPointer } from '@/src/features/stream/continuousPointer';
import type { ContinuousPointerState } from '@/src/features/stream/continuousPointer';

interface DeviceStreamProps {
  deviceId: string;
  onTap?: (x: number, y: number) => void;
  /** A successful WebSocket send is not an Android execution acknowledgement. */
  onControlSent?: (input: StreamInput) => void;
  /** HTTP key/text submissions and the separate installed-APK result. */
  onControlCommand?: (event: AcknowledgedControl) => void;
  /** Explicit discrete recorder intent; observing command results never changes input mode. */
  recordingMode?: boolean;
  /** True only after this viewer has released native ownership and discrete recording can accept input. */
  onRecordingControlReady?: (ready: boolean) => void;
  enableDiagnostics?: boolean;
  /** Diagnostic export of a decoded, potentially lossy H.264 frame, never an Android screenshot. */
  enableScreenshot?: boolean;
  enableNavigation?: boolean;
  /** Single-device control only; frame age alone does not invalidate geometry. */
  enableStaticInput?: boolean;
  /** Viewing a stream never implies authority to inject Android input. */
  readOnly?: boolean;
  /** Explain temporary execution locks separately from role restrictions. */
  readOnlyReason?: string;
  fit?: 'contain' | 'cover' | 'fill';
  onFrameDimensions?: (dimensions: StreamFrameDimensions) => void;
  inspection?: { onPick: (x: number, y: number, dimensions: StreamFrameDimensions) => void; bounds: UiBounds | null };
  onInspectionInvalidated?: () => void;
  /** Root inspection must wait for this viewer's acknowledged native release. */
  onInspectionControlReady?: (ready: boolean) => void;
}

interface StreamDiagnosticResponse {
  state: 'active_report' | 'not_streaming' | 'stale' | 'unavailable';
  agent_status: string | null;
  last_heartbeat: string | null;
  age_seconds: number | null;
  diagnostics: {
    observed_at: string;
    telemetry: {
      schema_version: number;
      capture_fps?: number | null;
      render_fps?: number | null;
      capture_frames_total?: number | null;
      rendered_frames_total?: number | null;
      capture_read_failures_total?: number | null;
      render_failures_total?: number | null;
      encoder_errors_total?: number | null;
      frame_throttle_drops_total?: number | null;
      capture_throttle_drops_total?: number | null;
      encoder_input_drops_total?: number | null;
      encoder_fps: number;
      encoded_frames_total: number;
      encoded_bytes_total: number;
      ws_queue_attempts_total: number;
      ws_queue_accepted_total: number;
      ws_queue_rejected_total: number;
      ws_queue_accepted_bytes_total: number;
    };
  } | null;
}

const FRAME_STALE_TIMEOUT_MS = 10_000;

function formatTimestampAgo(timestamp: number | null): string {
  if (timestamp == null) return 'никогда';
  const ageSeconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  if (ageSeconds < 60) return `${ageSeconds} сек назад`;
  return `${Math.floor(ageSeconds / 60)} мин назад`;
}

function formatIsoTimestampAgo(timestamp: string | null | undefined): string {
  if (!timestamp) return 'нет данных';
  const parsed = Date.parse(timestamp);
  if (!Number.isFinite(parsed)) return 'время неизвестно';
  return formatTimestampAgo(parsed);
}

export function DeviceStream({
  deviceId,
  onTap,
  onControlSent,
  onControlCommand,
  recordingMode = false,
  onRecordingControlReady,
  enableDiagnostics = false,
  enableScreenshot = false,
  enableNavigation = false,
  enableStaticInput = false,
  readOnly = false,
  readOnlyReason,
  fit,
  onFrameDimensions,
  inspection,
  onInspectionInvalidated,
  onInspectionControlReady,
}: DeviceStreamProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const renderedSocketRef = useRef<WebSocket | null>(null);
  const lastWheelAt = useRef(-Infinity);
  const decoderRef = useRef<H264Decoder | null>(null);
  const continuousRef = useRef<ContinuousPointer | null>(null);
  const continuousDisposeRef = useRef<(() => void) | null>(null);
  const continuousRequestedRef = useRef(false);
  const continuousProbeArmRef = useRef<(() => void) | null>(null);
  const lastContinuousReceiptAt = useRef(-Infinity);
  const continuousAllowedRef = useRef(false);
  const continuousPointRef = useRef<(x: number, y: number, clamp: boolean) => { x: number; y: number } | null>(() => null);
  const automaticProbeRef = useRef<WebSocket | null>(null);
  const discreteBusyRef = useRef(false);
  const releaseWaiterRef = useRef<{ controller: ContinuousPointer; finish: (known: boolean) => void } | null>(null);
  const wheelUpTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [discreteBusy, setDiscreteBusy] = useState(false);
  const [controlSession, setControlSession] = useState(0);
  const continuousSupportedRef = useRef(false);
  const continuousFaultRef = useRef(false);
  const idleRecoveryCountRef = useRef(0);
  const [idleRecoveryCount, setIdleRecoveryCount] = useState(0);
  const [continuousFault, setContinuousFault] = useState(false);
  const [surfaceActive, setSurfaceActive] = useState(() => typeof document !== 'undefined' && !document.hidden);
  const [continuousState, setContinuousState] = useState<ContinuousPointerState | 'probing'>('idle');
  const [continuousReason, setContinuousReason] = useState<string | null>(null);
  const [continuousFailureCode, setContinuousFailureCode] = useState<string | null>(null);
  const [continuousReceipt, setContinuousReceipt] = useState<{ action: number; sequence: number; ms: number } | null>(null);
  const dragRef = useRef<{
    x: number; y: number; pointerId: number; frameWidth: number; frameHeight: number; inspection: boolean;
  } | null>(null);
  const { accessToken } = useAuthStore();
  const [connection, setConnection] = useState<
    'connecting' | 'waiting' | 'live' | 'stale' | 'retrying' | 'unavailable'
  >('connecting');
  const [hasRenderedFrame, setHasRenderedFrame] = useState(false);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [inputError, setInputError] = useState<string | null>(null);
  const [screenshotError, setScreenshotError] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [agentReport, setAgentReport] = useState<{
    deviceId: string; accessToken: string | null; data: StreamDiagnosticResponse; receivedAtMs: number;
  } | null>(null);
  const [diagnosticNowMs, setDiagnosticNowMs] = useState(0);
  // A prior device/auth response must never be rendered under the new selection.
  const agentDiagnostics = agentReport?.deviceId === deviceId && agentReport.accessToken === accessToken
    ? agentReport.data : null;
  const diagnosticAgeSeconds = agentDiagnostics?.age_seconds != null && agentReport
    ? agentDiagnostics.age_seconds + Math.max(0, diagnosticNowMs - agentReport.receivedAtMs) / 1000 : null;
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [browserStats, setBrowserStats] = useState<StreamDecoderStats | null>(null);
  const currentFrameOwned = hasRenderedFrame && !streamError
    && wsRef.current?.readyState === WebSocket.OPEN
    && renderedSocketRef.current === wsRef.current;
  const canInteract = surfaceActive && !continuousFault && !discreteBusy && !inspection && !readOnly && currentFrameOwned && (connection === 'live'
    || (enableStaticInput && connection === 'stale'));
  const canSelectElement = !!inspection && currentFrameOwned && (connection === 'live'
    || (enableStaticInput && connection === 'stale'));
  const canSaveFrame = currentFrameOwned && connection === 'live';
  const continuousBusy = !['idle', 'probing', 'closed', 'destroyed'].includes(continuousState);
  const continuousRecording = recordingMode;
  const inspectionActive = !!inspection;
  continuousAllowedRef.current = canInteract && !continuousRecording && continuousRequestedRef.current;
  // Age is not a disconnect: an idle ImageReader can retain its last picture.
  // A new socket/decoder still needs its own first frame before accepting input.
  const canNavigate = surfaceActive && !continuousFault && !inspection && !readOnly && hasRenderedFrame && !streamError
    && (connection === 'live' || connection === 'stale')
    && renderedSocketRef.current === wsRef.current;
  const onFrameDimensionsRef = useRef(onFrameDimensions);
  const lastFrameDimensionsRef = useRef<StreamFrameDimensions | null>(null);
  onFrameDimensionsRef.current = onFrameDimensions;
  const invalidateInspectionRef = useRef(onInspectionInvalidated);
  invalidateInspectionRef.current = onInspectionInvalidated;

  useEffect(() => {
    lastFrameDimensionsRef.current = null;
    dragRef.current = null;
  }, [deviceId]);
  useEffect(() => {
    const focus = () => setSurfaceActive(!document.hidden);
    const blur = () => setSurfaceActive(false);
    window.addEventListener('focus', focus);
    window.addEventListener('blur', blur);
    document.addEventListener('visibilitychange', focus);
    return () => {
      window.removeEventListener('focus', focus);
      window.removeEventListener('blur', blur);
      document.removeEventListener('visibilitychange', focus);
    };
  }, []);

  useEffect(() => {
    // Defer WS creation by one tick to avoid React StrictMode double-invoke.
    let ignore = false;
    let ws: WebSocket | null = null;
    let decoder: H264Decoder | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let keyFrameTimer: ReturnType<typeof setTimeout> | undefined;
    let frameStaleTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setInterval> | undefined;
    let probeTimer: ReturnType<typeof setTimeout> | undefined;
    let scheduleKeyFrameRecovery: ((delayMs?: number) => void) | undefined;
    let attempt = 0;
    setConnection('connecting');
    setHasRenderedFrame(false);
    setStreamError(null);
    setInputError(null);
    continuousDisposeRef.current?.();
    continuousDisposeRef.current = null;
    continuousRef.current = null;
    continuousRequestedRef.current = false;
    automaticProbeRef.current = null;
    continuousSupportedRef.current = false;
    continuousFaultRef.current = false;
    idleRecoveryCountRef.current = 0;
    setIdleRecoveryCount(0);
    setContinuousFault(false);
    discreteBusyRef.current = false;
    setDiscreteBusy(false);
    releaseWaiterRef.current?.finish(false);
    releaseWaiterRef.current = null;
    if (wheelUpTimerRef.current) clearTimeout(wheelUpTimerRef.current);
    wheelUpTimerRef.current = null;
    setContinuousState('idle');
    setContinuousReason(null);
    setContinuousFailureCode(null);
    setContinuousReceipt(null);

    const timer = setTimeout(() => {
      if (ignore) return;

      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d')!;

      decoder = new H264Decoder((frame) => {
        if (ignore || wsRef.current?.readyState !== WebSocket.OPEN) return;
        if (!ctx || frame.displayWidth < 1 || frame.displayHeight < 1) throw new Error('Invalid canvas frame.');
        // Mutate canvas directly for performance, avoid React state re-renders
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          // Coordinates captured before rotation/resizing belong to the old
          // frame. Never combine them with a release mapped to the new frame.
          dragRef.current = null;
          invalidateInspectionRef.current?.();
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        // Only a successful canvas render proves a picture. A decoder output
        // that throws during drawImage must not unlock clicks or PNG export.
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
        renderedSocketRef.current = wsRef.current;
        setConnection('live');
        setHasRenderedFrame(true);
        setStreamError(null);
        clearTimeout(keyFrameTimer);
        clearTimeout(frameStaleTimer);
        frameStaleTimer = setTimeout(() => {
          if (ignore || wsRef.current?.readyState !== WebSocket.OPEN) return;
          dragRef.current = null;
          setConnection('stale');
          scheduleKeyFrameRecovery?.();
        }, FRAME_STALE_TIMEOUT_MS);
        if (frame.displayWidth > 0 && frame.displayHeight > 0) {
          const previousDimensions = lastFrameDimensionsRef.current;
          if (
            previousDimensions?.width !== frame.displayWidth
            || previousDimensions?.height !== frame.displayHeight
          ) {
            const dimensions = { width: frame.displayWidth, height: frame.displayHeight };
            lastFrameDimensionsRef.current = dimensions;
            onFrameDimensionsRef.current?.(dimensions);
          }
        }
      }, () => {
        if (ignore) return;
        dragRef.current = null;
        setConnection('waiting');
        // Кодек может быть исправен, но первый серверный запрос IDR мог
        // прийти до готовности захвата. Повторяем запрос до первого output.
        scheduleKeyFrameRecovery?.();
      });
      decoder.init();
      decoderRef.current = decoder;

      const wsBase = process.env.NEXT_PUBLIC_WS_URL ??
        (typeof window !== 'undefined'
          ? `${window.location.protocol === 'https:' ? 'wss' : 'ws'}://${window.location.host}`
          : 'ws://localhost');
      const wsUrl = `${wsBase}/ws/stream/${deviceId}`;

      // One connection generation owns its callbacks and timers. A TCP open is
      // not proof of a usable stream: reset backoff only after server traffic.
      const createWs = () => {
        if (ignore) return;
        dragRef.current = null;
        invalidateInspectionRef.current?.();
        lastFrameDimensionsRef.current = null;
        setStreamError(null);
        setInputError(null);
        const newWs = new WebSocket(wsUrl);
        newWs.binaryType = 'arraybuffer';
        ws = newWs;
        wsRef.current = newWs;
        automaticProbeRef.current = null;
        continuousSupportedRef.current = false;
        continuousFaultRef.current = false;
        setContinuousFault(false);
        setContinuousReason(null);
        setContinuousFailureCode(null);
        let ended = false;
        let lastReceived = Date.now();
        let opened = false;
        let keyFrameAttempts = 0;
        const requestKeyFrame = () => {
          if (
            ignore || ended || newWs !== wsRef.current || newWs.readyState !== WebSocket.OPEN
          ) return;
          newWs.send(JSON.stringify({ type: 'request_keyframe' }));
          keyFrameAttempts += 1;
          const nextDelay = keyFrameAttempts === 1
            ? 2000
            : Math.min(5000 * 2 ** Math.min(keyFrameAttempts - 2, 2), 20_000);
          keyFrameTimer = setTimeout(requestKeyFrame, nextDelay);
        };
        const scheduleKeyFrameRequests = (delayMs = 1100) => {
          clearTimeout(keyFrameTimer);
          keyFrameAttempts = 0;
          keyFrameTimer = setTimeout(requestKeyFrame, delayMs);
        };
        scheduleKeyFrameRecovery = scheduleKeyFrameRequests;
        const finish = (retry: boolean, terminalMessage?: string) => {
          if (ended) return;
          ended = true;
          releaseWaiterRef.current?.finish(false);
          releaseWaiterRef.current = null;
          discreteBusyRef.current = false;
          setDiscreteBusy(false);
          if (wheelUpTimerRef.current) clearTimeout(wheelUpTimerRef.current);
          wheelUpTimerRef.current = null;
          continuousDisposeRef.current?.();
          continuousDisposeRef.current = null;
          continuousRef.current = null;
          continuousRequestedRef.current = false;
          setContinuousState('idle');
          clearTimeout(probeTimer);
          dragRef.current = null;
          clearInterval(watchdog);
          clearTimeout(keyFrameTimer);
          clearTimeout(frameStaleTimer);
          if (scheduleKeyFrameRecovery === scheduleKeyFrameRequests) scheduleKeyFrameRecovery = undefined;
          newWs.onopen = newWs.onmessage = newWs.onclose = newWs.onerror = null;
          if (wsRef.current === newWs) wsRef.current = null;
          if (renderedSocketRef.current === newWs) renderedSocketRef.current = null;
          decoder?.reset();
          if (newWs.readyState === WebSocket.OPEN || newWs.readyState === WebSocket.CONNECTING) {
            newWs.close();
          }
          if (ignore) return;
          setConnection(retry ? 'retrying' : 'unavailable');
          if (retry) {
            const delay = Math.min(500 * 2 ** Math.min(attempt++, 6), 15_000);
            retryTimer = setTimeout(createWs, delay * (0.8 + Math.random() * 0.4));
          } else {
            setStreamError(terminalMessage ?? null);
          }
        };
        watchdog = setInterval(() => {
          if (Date.now() - lastReceived >= (opened ? 30_000 : 15_000)) finish(true);
        }, 5_000);
        newWs.onopen = () => {
          if (ignore || ended) return;
          opened = true;
          lastReceived = Date.now();
          newWs.send(JSON.stringify({ token: accessToken }));
          setConnection('waiting');
          clearTimeout(frameStaleTimer);
          frameStaleTimer = setTimeout(() => {
            if (ignore || ended || newWs !== wsRef.current || newWs.readyState !== WebSocket.OPEN) return;
            dragRef.current = null;
            setConnection('stale');
          }, FRAME_STALE_TIMEOUT_MS);
          scheduleKeyFrameRequests();
        };
        newWs.onmessage = (evt) => {
          if (ignore || ended) return;
          lastReceived = Date.now();
          attempt = 0;
          if (evt.data instanceof ArrayBuffer) decoder?.handleBinary(evt.data);
          if (typeof evt.data === 'string') {
            try {
              const msg = JSON.parse(evt.data);
              if (msg.type === 'touch_capability' && continuousRequestedRef.current && !continuousRef.current) {
                if (!continuousAllowedRef.current || discreteBusyRef.current || dragRef.current) {
                  // A capability probe has no owner. Never change input paths midway through a legacy drag.
                  continuousRequestedRef.current = false;
                  setContinuousState('idle');
                  setContinuousReason('Дискретное управление · текущий жест завершается без смены режима.');
                  return;
                }
                const capture = decoder?.lastRenderedCapture;
                if (!capture || msg.capture_epoch !== capture.captureEpoch || msg.frame_width !== capture.frameWidth
                  || msg.frame_height !== capture.frameHeight) {
                  setContinuousState('idle');
                  continuousRequestedRef.current = false;
                  setContinuousReason('Кадр и захват Android изменились. Подключите жесты ещё раз.');
                  return;
                }
                const controller = new ContinuousPointer({ socket: newWs,
                  renderedCapture: () => decoder?.lastRenderedCapture ?? null,
                  onState: (state, reason) => {
                    if (ignore || ended || newWs !== wsRef.current) return;
                    setContinuousState(state);
                    const idleRecovery = reason === 'native_receipt_timeout' && controller.recoverableIdleReceiptLoss
                      && idleRecoveryCountRef.current === 0;
                    if (idleRecovery) {
                      idleRecoveryCountRef.current++;
                      setIdleRecoveryCount(idleRecoveryCountRef.current);
                      setContinuousFailureCode('idle_receipt_timeout');
                      setContinuousReason('Задержка подтверждения связи без касания · ожидаем освобождение Android перед повторным согласованием.');
                    } else if (reason && !['viewer_closed', 'surface_blur', 'surface_hidden', 'surface_control_lost', 'control_mode_changed', 'capture_or_socket_lost'].includes(reason)) {
                      continuousFaultRef.current = true;
                      setContinuousFault(true);
                      setContinuousFailureCode(reason);
                      setContinuousReason('Управление приостановлено: Android не подтвердил команду. Повтора нет. Проверьте экран перед восстановлением.');
                    }
                    if (state === 'closed') {
                      continuousRequestedRef.current = false;
                      if (!continuousFaultRef.current) {
                        setContinuousReason(null);
                        automaticProbeRef.current = null;
                      }
                      const waiting = releaseWaiterRef.current;
                      if (waiting?.controller === controller) waiting.finish(true);
                    }
                  },
                  onReceipt: receipt => {
                    if (ignore || ended || newWs !== wsRef.current) return;
                    const now = performance.now();
                    if (now - lastContinuousReceiptAt.current < 250 && receipt.action !== 1 && receipt.action !== 3) return;
                    lastContinuousReceiptAt.current = now;
                    setContinuousReceipt({ action: receipt.action, sequence: receipt.sequence,
                      ms: Math.round(receipt.receiptRoundTripMs) });
                  },
                });
                continuousSupportedRef.current = true;
                continuousRef.current = controller;
                continuousDisposeRef.current = attachContinuousPointer({ canvas, controller,
                  allowed: () => continuousAllowedRef.current,
                  point: (event, clamp) => continuousPointRef.current(event.clientX, event.clientY, clamp) });
                clearTimeout(probeTimer);
                controller.open(capture);
                return;
              }
              if (msg.type === 'touch_session' || msg.type === 'continuous_input_status') {
                continuousRef.current?.receive(msg);
                return;
              }
              if (msg.type === 'touch_error') {
                clearTimeout(probeTimer);
                continuousRef.current?.retire('server_rejected');
                if (!continuousRef.current) {
                  continuousRequestedRef.current = false;
                  setContinuousState('idle');
                }
                if (continuousRef.current) {
                  continuousFaultRef.current = true;
                  setContinuousFault(true);
                  setContinuousFailureCode('server_rejected');
                }
                setContinuousReason(continuousRef.current
                  ? 'Управление приостановлено сервером. Видеопоток продолжается; команды не повторяются.'
                  : 'Дискретное управление · сервер не подтвердил непрерывные жесты.');
                return;
              }
              if (msg.type === 'ping' && newWs.readyState === WebSocket.OPEN) {
                newWs.send(JSON.stringify({ type: 'pong' }));
              } else if (msg.type === 'error') {
                dragRef.current = null;
                if (msg.error === 'stream_input_invalid') {
                  // Rejection before dispatch is separate from a broken stream
                  // or an unknown applied action. Never replay the rejected input.
                  setInputError(msg.reason === 'unsupported_message'
                    ? 'Этот тип управления не поддерживается сервером. Видеопоток продолжается.'
                    : 'Сервер отклонил некорректную команду до отправки на Android. Видеопоток продолжается.');
                  return;
                }
                const messages: Record<string, string> = {
                  stream_control_unavailable: 'Сервер не смог передать запрос видеопотока Android-агенту.',
                  stream_control_denied: 'У этой учётной записи нет права управлять видеопотоком.',
                };
                const code = typeof msg.error === 'string' ? msg.error.slice(0, 80) : '';
                setStreamError(messages[code] ?? 'Сервер сообщил об ошибке видеосессии.');
              }
            } catch { /* Ignore malformed control messages. */ }
          }
        };
        // A remote normal close can be a server restart. Only effect cleanup
        // means the user stopped viewing; access/device rejections remain terminal.
        newWs.onclose = event => {
          const closeMessages: Record<number, string> = {
            4001: 'Сессия просмотра не авторизована. Обновите вход и откройте устройство снова.',
            4003: 'У этой учётной записи нет доступа к просмотру устройства.',
            4004: 'Устройство не найдено или недоступно в этой организации.',
          };
          finish(![4001, 4003, 4004].includes(event.code), closeMessages[event.code]);
        };
        newWs.onerror = () => finish(true);
        continuousProbeArmRef.current = () => {
          clearTimeout(probeTimer);
          probeTimer = setTimeout(() => {
            if (continuousRequestedRef.current && !continuousRef.current) {
              continuousRequestedRef.current = false;
              setContinuousState('idle');
              setContinuousReason('Дискретное управление · APK не подтвердил непрерывные жесты.');
            }
          }, 6000);
        };
      };

      createWs();
    }, 0);

    return () => {
      ignore = true;
      continuousDisposeRef.current?.();
      continuousDisposeRef.current = null;
      continuousRef.current = null;
      continuousRequestedRef.current = false;
      continuousProbeArmRef.current = null;
      releaseWaiterRef.current?.finish(false);
      releaseWaiterRef.current = null;
      if (wheelUpTimerRef.current) clearTimeout(wheelUpTimerRef.current);
      wheelUpTimerRef.current = null;
      clearTimeout(probeTimer);
      dragRef.current = null;
      clearTimeout(timer);
      clearTimeout(retryTimer);
      clearTimeout(keyFrameTimer);
      clearTimeout(frameStaleTimer);
      clearInterval(watchdog);
      wsRef.current = null;
      renderedSocketRef.current = null;
      ws?.close();
      decoder?.destroy();
      decoderRef.current = null;
    };
  }, [deviceId, accessToken, controlSession]);

  useEffect(() => {
    if (!enableDiagnostics || !diagnosticsOpen) return;
    let active = true;
    let inFlight = false;
    const controller = new AbortController();
    setAgentReport(null);
    setDiagnosticsError(null);
    const refreshAgent = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const { data } = await api.get<StreamDiagnosticResponse>(
          `/devices/${deviceId}/stream-diagnostics`,
          { signal: controller.signal },
        );
        if (active) {
          const receivedAtMs = performance.now();
          setAgentReport({ deviceId, accessToken, data, receivedAtMs });
          setDiagnosticNowMs(receivedAtMs);
          setDiagnosticsError(null);
        }
      } catch {
        if (active) setDiagnosticsError('Не удалось получить телеметрию устройства');
      } finally {
        inFlight = false;
      }
    };
    void refreshAgent();
    const agentTimer = window.setInterval(() => void refreshAgent(), 15_000);
    const browserTimer = window.setInterval(() => {
      if (active) {
        setBrowserStats(decoderRef.current?.stats ?? null);
        setDiagnosticNowMs(performance.now());
      }
    }, 1000);
    setBrowserStats(decoderRef.current?.stats ?? null);
    return () => {
      active = false;
      controller.abort();
      window.clearInterval(agentTimer);
      window.clearInterval(browserTimer);
    };
  }, [deviceId, accessToken, diagnosticsOpen, enableDiagnostics]);

  // ── coordinate helpers ───────────────────────────────────────────────────
  const toCanvasCoords = useCallback(
    (clientX: number, clientY: number, clampToFrame = false) => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0 || canvas.width <= 0 || canvas.height <= 0) return null;
      const localX = clientX - rect.left;
      const localY = clientY - rect.top;
      let x: number;
      let y: number;

      if (fit === 'contain' || fit === 'cover') {
        const scale = fit === 'contain'
          ? Math.min(rect.width / canvas.width, rect.height / canvas.height)
          : Math.max(rect.width / canvas.width, rect.height / canvas.height);
        const renderedWidth = canvas.width * scale;
        const renderedHeight = canvas.height * scale;
        const offsetX = (rect.width - renderedWidth) / 2;
        const offsetY = (rect.height - renderedHeight) / 2;
        if (!clampToFrame && (
          localX < offsetX || localX > offsetX + renderedWidth ||
          localY < offsetY || localY > offsetY + renderedHeight
        )) return null;
        x = (localX - offsetX) / scale;
        y = (localY - offsetY) / scale;
      } else {
        x = localX * (canvas.width / rect.width);
        y = localY * (canvas.height / rect.height);
      }

      return {
        x: Math.max(0, Math.min(canvas.width - 1, Math.round(x))),
        y: Math.max(0, Math.min(canvas.height - 1, Math.round(y))),
      };
    },
    [fit],
  );

  // ── pointer down — begin drag / tap ─────────────────────────────────────
  continuousPointRef.current = toCanvasCoords;
  const beginContinuous = () => {
    const controller = continuousRef.current;
    if (controller && !['closed', 'destroyed'].includes(controller.state)) {
      return;
    }
    if (!canInteract || continuousRecording || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) return;
    continuousDisposeRef.current?.();
    continuousDisposeRef.current = null;
    continuousRef.current = null;
    continuousRequestedRef.current = true;
    continuousAllowedRef.current = true;
    dragRef.current = null;
    setContinuousState('probing');
    setContinuousReason(null);
    setContinuousFailureCode(null);
    setContinuousReceipt(null);
    wsRef.current.send(JSON.stringify({ type: 'touch_probe' }));
    continuousProbeArmRef.current?.();
  };
  useEffect(() => {
    if (inspection || readOnly || continuousRecording) {
      automaticProbeRef.current = null;
      if (!continuousRef.current) {
        continuousRequestedRef.current = false;
        if (continuousState === 'probing') setContinuousState('idle');
      }
      return;
    }
    const socket = wsRef.current;
    if (!enableNavigation || !canInteract || continuousFaultRef.current || discreteBusyRef.current || !socket
      || automaticProbeRef.current === socket || !decoderRef.current?.lastRenderedCapture
      || continuousRef.current && !['closed', 'destroyed'].includes(continuousRef.current.state)) return;
    automaticProbeRef.current = socket;
    beginContinuous();
    // A single capability attempt per owned video/mode; never replay a failed gesture.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canInteract, enableNavigation, inspection, readOnly, continuousRecording, discreteBusy, continuousState]);

  const prepareDiscreteInput = (): ((confirmed: boolean) => void) | Promise<((confirmed: boolean) => void) | null> | null => {
    const socket = wsRef.current;
    const controller = continuousRef.current;
    if (!canNavigate || discreteBusyRef.current || !socket || socket.readyState !== WebSocket.OPEN
      || controller && !['ready', 'closed', 'destroyed'].includes(controller.state)) return null;
    discreteBusyRef.current = true;
    setDiscreteBusy(true);
    continuousRequestedRef.current = false;
    const finish = (confirmed: boolean) => {
      if (wsRef.current !== socket) return;
      discreteBusyRef.current = false;
      setDiscreteBusy(false);
      if (confirmed && controller) automaticProbeRef.current = null;
      if (!confirmed) {
        continuousFaultRef.current = true;
        setContinuousFault(true);
        setContinuousFailureCode('discrete_result_unknown');
        setContinuousReason('Результат команды не подтверждён. Проверьте экран перед продолжением управления.');
      }
    };
    if (!controller || ['closed', 'destroyed'].includes(controller.state)) {
      if (continuousState === 'probing') setContinuousState('idle');
      return finish;
    }
    return new Promise(resolve => {
      let settled = false;
      const timeout = setTimeout(() => waiting.finish(false), 3000);
      const waiting = { controller, finish: (known: boolean) => {
        if (settled) return;
        settled = true;
        clearTimeout(timeout);
        if (releaseWaiterRef.current === waiting) releaseWaiterRef.current = null;
        if (known && wsRef.current === socket) resolve(finish);
        else { setContinuousState('fenced'); finish(false); resolve(null); }
      } };
      releaseWaiterRef.current = waiting;
      controller.close(); // The HTTP command waits for native RELEASE3, never a timeout or Redis acceptance.
    });
  };
  useEffect(() => {
    // A partially recorded discrete drag belongs to the old mode. Never replay
    // its UP after Stop, inspection, a lock or permission change.
    dragRef.current = null;
    if (inspection || readOnly || continuousRecording) continuousRef.current?.retire('control_mode_changed');
  }, [inspection, readOnly, continuousRecording]);
  useEffect(() => {
    const controller = continuousRef.current;
    onInspectionControlReady?.(!!inspection && currentFrameOwned && !discreteBusy
      && (!controller || controller.state === 'closed'));
  }, [inspection, currentFrameOwned, discreteBusy, continuousState, onInspectionControlReady]);
  useEffect(() => {
    const controller = continuousRef.current;
    onRecordingControlReady?.(continuousRecording && canInteract
      && (!controller || controller.state === 'closed'));
  }, [continuousRecording, canInteract, continuousState, onRecordingControlReady]);
  useEffect(() => {
    const controller = continuousRef.current;
    if (!(inspectionActive || continuousRecording) || !controller || controller.state === 'closed' || !currentFrameOwned) return;
    const timeout = setTimeout(() => {
      if (continuousRef.current !== controller || controller.state === 'closed') return;
      continuousFaultRef.current = true;
      setContinuousFault(true);
      setContinuousFailureCode(inspectionActive ? 'inspection_release_unknown' : 'recording_release_unknown');
      setContinuousReason(inspectionActive ? 'Освобождение управления Android не подтверждено. Чтение дерева не отправлено; восстановите подключение.' : 'Освобождение управления Android не подтверждено. Запись действий заблокирована; восстановите подключение.');
    }, 3000);
    return () => clearTimeout(timeout);
  }, [inspectionActive, continuousRecording, currentFrameOwned, continuousState]);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      // Inspection only selects a frame; it never injects Android input. Recording
      // may use discrete input again after this controller's known native release.
      if (!inspection && (discreteBusyRef.current || continuousFaultRef.current
        || continuousSupportedRef.current && !continuousRecording
        || continuousRef.current && !['closed', 'destroyed'].includes(continuousRef.current.state))) return;
      if (!(canInteract || canSelectElement) || wsRef.current?.readyState !== WebSocket.OPEN
        || renderedSocketRef.current !== wsRef.current) {
        dragRef.current = null;
        return;
      }
      if (e.button !== 0 || dragRef.current) return;
      const pt = toCanvasCoords(e.clientX, e.clientY);
      if (!pt) return;
      dragRef.current = {
        ...pt, pointerId: e.pointerId,
        frameWidth: e.currentTarget.width, frameHeight: e.currentTarget.height,
        inspection: !!inspection,
      };
      e.currentTarget.setPointerCapture(e.pointerId);
    },
    [canInteract, canSelectElement, inspection, continuousRecording, toCanvasCoords],
  );

  // ── pointer up — tap or swipe ────────────────────────────────────────────
  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const start = dragRef.current;
      if (!start || e.pointerId !== start.pointerId) return;
      dragRef.current = null;
      if (!(canInteract || canSelectElement) || start.inspection !== !!inspection || wsRef.current?.readyState !== WebSocket.OPEN
        || renderedSocketRef.current !== wsRef.current || e.button !== 0
        || e.currentTarget.width !== start.frameWidth
        || e.currentTarget.height !== start.frameHeight) return;

      const pt = toCanvasCoords(e.clientX, e.clientY, true);
      if (!pt) return;

      const dist = Math.hypot(pt.x - start.x, pt.y - start.y);

      if (inspection) {
        if (dist < 12) inspection.onPick(start.x, start.y, { width: start.frameWidth, height: start.frameHeight });
        return;
      }

      if (dist < 12) {
        // Tap
        onTap?.(start.x, start.y);
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'click', x: start.x, y: start.y }));
          onControlSent?.({ deviceId, at: performance.now(), dimensions: { width: start.frameWidth, height: start.frameHeight }, command: { type: 'click', x: start.x, y: start.y } });
        }
      } else {
        // Swipe — duration proportional to distance, min 150ms max 600ms
        const duration_ms = Math.min(600, Math.max(150, Math.round(dist * 0.8)));
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms }));
          onControlSent?.({ deviceId, at: performance.now(), dimensions: { width: start.frameWidth, height: start.frameHeight }, command: { type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms } });
        }
      }
    },
    [canInteract, canSelectElement, inspection, toCanvasCoords, onTap, onControlSent, deviceId],
  );

  const handlePointerCancel = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    if (e.pointerId === dragRef.current?.pointerId) dragRef.current = null;
  }, []);

  const handleWheel = useCallback((e: WheelEvent) => {
    const continuous = continuousRef.current;
    if (discreteBusyRef.current || continuousFaultRef.current || continuousSupportedRef.current && !continuousRecording && continuous?.state !== 'ready'
      || continuous && !['ready', 'closed', 'destroyed'].includes(continuous.state)) return;
    // Wheel control belongs to the selected-device view. Never intercept
    // browser zoom, inspection, a retained old socket frame or a held drag.
    const socket = wsRef.current;
    const canvas = canvasRef.current;
    if (!enableNavigation || !canInteract || !canvas || !socket || socket.readyState !== WebSocket.OPEN
      || renderedSocketRef.current !== socket || socket.bufferedAmount > 64 * 1024 || dragRef.current || e.ctrlKey || e.metaKey) return;
    const point = toCanvasCoords(e.clientX, e.clientY);
    if (!point || !Number.isFinite(e.deltaX) || !Number.isFinite(e.deltaY)) return;
    const horizontal = Math.abs(e.deltaX) > Math.abs(e.deltaY);
    const delta = horizontal ? e.deltaX : e.deltaY;
    if (!delta) return;
    e.preventDefault();
    if (continuous?.pointerHeld || wheelUpTimerRef.current) return;
    const at = performance.now();
    if (at - lastWheelAt.current < 250) return;
    lastWheelAt.current = at;
    const size = horizontal ? canvas.width : canvas.height;
    const normalized = Math.abs(delta) * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? size : 1);
    const distance = Math.min(size * 0.25, 240, Math.max(40, normalized * 2));
    const direction = Math.sign(delta);
    const clamp = (value: number) => Math.round(Math.max(0, Math.min(size - 1, value)));
    const position = horizontal ? point.x : point.y;
    const from = clamp(position + direction * distance / 2);
    const to = clamp(position - direction * distance / 2);
    if (from === to) return;
    if (continuous?.state === 'ready') {
      const start = { x: horizontal ? from : point.x, y: horizontal ? point.y : from };
      const end = { x: horizontal ? to : point.x, y: horizontal ? point.y : to };
      if (!continuous.down(0, start)) return;
      continuous.moveTo(0, end);
      wheelUpTimerRef.current = setTimeout(() => {
        wheelUpTimerRef.current = null;
        if (continuousRef.current === continuous && continuousAllowedRef.current) continuous.up(0, end);
        else continuous.retire('wheel_control_lost');
      }, 180);
      return;
    }
    socket.send(JSON.stringify({ type: 'swipe', x1: horizontal ? from : point.x, y1: horizontal ? point.y : from,
      x2: horizontal ? to : point.x, y2: horizontal ? point.y : to, duration_ms: 180 }));
    onControlSent?.({ deviceId, at, dimensions: { width: canvas.width, height: canvas.height }, command: { type: 'swipe', x1: horizontal ? from : point.x, y1: horizontal ? point.y : from,
      x2: horizontal ? to : point.x, y2: horizontal ? point.y : to, duration_ms: 180 } });
  }, [canInteract, enableNavigation, continuousRecording, toCanvasCoords, onControlSent, deviceId]);
  useEffect(() => {
    const canvas = canvasRef.current;
    // React delegates wheel events passively in modern browsers. A native
    // non-passive listener is required to prevent scrolling the surrounding page.
    canvas?.addEventListener('wheel', handleWheel, { passive: false });
    return () => canvas?.removeEventListener('wheel', handleWheel);
  }, [handleWheel]);

  const saveFrame = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canSaveFrame || !canvas || canvas.width < 1 || canvas.height < 1) return;
    setScreenshotError(null);
    try {
      canvas.toBlob((blob) => {
        if (!blob) { setScreenshotError('Не удалось сохранить декодированный кадр.'); return; }
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = `Sphere-frame-${deviceId.replace(/[^a-zA-Z0-9_-]/g, '_')}-${Date.now()}.png`;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
      }, 'image/png');
    } catch {
      setScreenshotError('Не удалось сохранить декодированный кадр.');
    }
  }, [canSaveFrame, deviceId]);

  return (
    <div className={fit ? 'flex h-full w-full min-h-0 min-w-0 flex-col' : 'min-w-0'}>
    {readOnly && enableNavigation && <p role="status" className="border-b border-border bg-muted px-3 py-2 text-xs text-muted-foreground">Только просмотр · {readOnlyReason ?? 'роль не разрешает клики, жесты и навигацию Android.'}</p>}
    {enableNavigation && ((!inspection && !readOnly) || (inspection && continuousFault)) && <div data-control-state={continuousState} data-control-failure={continuousFailureCode ?? undefined} className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border bg-muted/30 px-3 py-2">
      <span className={`h-2 w-2 shrink-0 rounded-full ${continuousState === 'ready' ? 'bg-emerald-500' : 'bg-muted-foreground'}`} aria-hidden />
      <span role="status" className="text-xs text-muted-foreground">{continuousReason ?? (discreteBusy ? 'Клавиатура и навигация · ожидаем подтверждение Android' : continuousRecording ? 'Запись использует отдельные завершённые действия' : continuousState === 'ready'
        ? 'Непрерывное управление · зажмите и ведите мышь' : continuousState === 'opening' ? 'Подключаем управление Android…' : continuousState === 'probing' ? 'Определяем возможности APK · обычные нажатия доступны' : continuousState === 'closed' ? 'Касание Android освобождено' : 'Управление Android')}
      {continuousReceipt && continuousState === 'ready' && ` · ACK №${continuousReceipt.sequence}: ${continuousReceipt.ms} мс`}</span>
      {['fenced', 'closed'].includes(continuousState) && continuousReason && <button type="button" onClick={() => setControlSession(value => value + 1)} className="ml-auto rounded-lg border border-border px-3 py-2 text-xs hover:bg-muted">Восстановить управление</button>}
    </div>}
    {inputError && <div role="status" className="flex shrink-0 items-start justify-between gap-3 border-b border-amber-500/25 bg-amber-500/10 px-3 py-2 text-xs text-foreground">
      <p>{inputError}</p><button type="button" onClick={() => setInputError(null)} aria-label="Скрыть сообщение об отклонённой команде" className="shrink-0 rounded px-2 py-1 text-muted-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">Скрыть</button>
    </div>}
    <div className={fit ? `relative w-full min-h-0 min-w-0 flex-1${enableNavigation ? '' : ' h-full'}` : 'relative'}>
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerCancel}
      onLostPointerCapture={handlePointerCancel}
      aria-label={inspection ? 'Экран устройства: выбор элемента без нажатия Android' : readOnly ? readOnlyReason ? `Экран устройства: только просмотр. ${readOnlyReason}` : 'Экран устройства: только просмотр, управление запрещено для вашей роли' : canInteract
        ? connection === 'stale' ? 'Экран устройства: управление по последнему кадру' : 'Экран устройства: свежий видеопоток'
        : 'Экран устройства: управление доступно после получения свежего видеокадра'}
      aria-disabled={!(canInteract || canSelectElement)}
      className={`${canInteract || canSelectElement ? 'cursor-crosshair' : 'pointer-events-none cursor-not-allowed'} rounded border border-gray-700 bg-black touch-none`}
      style={{
        display: 'block',
        width: '100%',
        height: fit ? '100%' : 'auto',
        objectFit: fit ?? 'contain',
      }}
    />
    {inspection?.bounds && lastFrameDimensionsRef.current && <svg aria-label="Границы выбранного элемента" className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${lastFrameDimensionsRef.current.width} ${lastFrameDimensionsRef.current.height}`} preserveAspectRatio={fit === 'fill' ? 'none' : fit === 'cover' ? 'xMidYMid slice' : 'xMidYMid meet'}>
      <rect x={inspection.bounds.left} y={inspection.bounds.top} width={inspection.bounds.right - inspection.bounds.left} height={inspection.bounds.bottom - inspection.bounds.top} fill="rgba(20,184,166,0.15)" stroke="#14b8a6" strokeWidth="2" vectorEffect="non-scaling-stroke" />
    </svg>}
    {enableScreenshot && <div className="absolute bottom-2 left-2 z-20 max-w-[calc(100%-1rem)]">
      <button type="button" disabled={!canSaveFrame} onClick={saveFrame} title="Декодированный кадр H.264: PNG не восстанавливает потерянные при кодировании пиксели. Для эталонов используйте исходный PNG с Android." className="rounded-lg border border-white/20 bg-black/80 px-3 py-2 text-xs text-white disabled:cursor-not-allowed disabled:opacity-50">Кадр видео (PNG) · не оригинал</button>
      {screenshotError && <p role="alert" className="mt-1 rounded bg-black/90 p-2 text-xs text-red-200">{screenshotError}</p>}
    </div>}
    {(connection !== 'live' || streamError) && (
      hasRenderedFrame ? (
        <div
          role="status"
          aria-live="polite"
          className={`pointer-events-none absolute left-3 top-3 z-10 flex max-w-[calc(100%-1.5rem)] items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium shadow-lg backdrop-blur ${
            streamError || connection === 'unavailable'
              ? 'border-red-300/25 bg-red-950/85 text-red-100'
              : 'border-amber-300/25 bg-black/80 text-amber-100'
          }`}
        >
          <span
            aria-hidden="true"
            className={`h-2 w-2 shrink-0 rounded-full ${
              streamError || connection === 'unavailable' ? 'bg-red-400' : 'bg-amber-400'
            }`}
          />
          <span className="truncate">
            {streamError ?? (
              connection === 'stale' ? canInteract
                ? 'Экран не обновлялся более 10 секунд · управление по последнему кадру'
                : 'Нет новых видеокадров более 10 секунд · показан последний кадр' :
              connection === 'retrying' ? 'Переподключение · показан последний кадр' :
              connection === 'unavailable' ? 'Стрим недоступен · показан последний кадр' :
              'Ожидание нового кадра · показан последний кадр'
            )}
          </span>
        </div>
      ) : (
        <div role="status" aria-live="polite" className="absolute inset-0 flex items-center justify-center bg-black/85 text-sm text-white">
          {streamError ?? (
            connection === 'connecting' ? 'Подключение…' :
            connection === 'waiting' ? 'Ожидание видеокадра…' :
            connection === 'stale' ? 'Первый видеокадр не получен за 10 секунд' :
            connection === 'retrying' ? 'Переподключение…' : 'Стрим недоступен'
          )}
        </div>
      )
    )}
    {enableDiagnostics && (
      <div className="absolute right-2 top-2 z-20">
        <button
          type="button"
          aria-expanded={diagnosticsOpen}
          aria-controls={`stream-diagnostics-${deviceId}`}
          onClick={() => setDiagnosticsOpen(value => !value)}
          className="rounded border border-white/20 bg-black/80 px-2 py-1 text-xs text-white"
        >
          {diagnosticsOpen ? 'Скрыть диагностику' : 'Диагностика'}
        </button>
        {diagnosticsOpen && (
          <div
            id={`stream-diagnostics-${deviceId}`}
            role="status"
            aria-live="polite"
            className="mt-2 max-h-[70vh] w-[min(92vw,34rem)] overflow-auto rounded border border-white/20 bg-black/95 p-3 text-left font-mono text-[11px] leading-5 text-white shadow-xl"
          >
            <div className="mb-2 font-semibold">Сквозная диагностика кадра</div>
            <div>Управление Android: {continuousState}{continuousFailureCode ? ` · причина: ${continuousFailureCode}` : ''}</div>
            <div>Повторное согласование после задержки idle ACK: {idleRecoveryCount}/1 в этой видеосессии. Касания и команды не повторяются.</div>
            {diagnosticsError ? <div className="text-red-300">{diagnosticsError}</div> : (
              <>
                <div>Отчёт APK: {agentDiagnostics?.state === 'active_report' ? 'захват активен' : agentDiagnostics?.state ?? 'загрузка…'}
                  {diagnosticAgeSeconds != null && ` · snapshot ${Math.floor(diagnosticAgeSeconds)} сек назад`}
                </div>
                <div>Последний Android heartbeat: {formatIsoTimestampAgo(agentDiagnostics?.last_heartbeat)}</div>
                {agentDiagnostics?.diagnostics ? (() => {
                  const t = agentDiagnostics.diagnostics.telemetry;
  return (
                    <div className="mt-1 grid grid-cols-2 gap-x-3">
                      <span>Capture FPS: {t.capture_fps ?? '—'}</span>
                      <span>Surface FPS: {t.render_fps ?? '—'}</span>
                      <span>Encoder FPS: {t.encoder_fps}</span>
                      <span>Encoded: {t.encoded_frames_total}</span>
                      <span>Captured: {t.capture_frames_total ?? '—'}</span>
                      <span>Rendered: {t.rendered_frames_total ?? '—'}</span>
                      <span>Local WS accepted: {t.ws_queue_accepted_total}/{t.ws_queue_attempts_total}</span>
                      <span>Local WS rejected: {t.ws_queue_rejected_total}</span>
                      <span>Capture errors: {t.capture_read_failures_total ?? '—'}</span>
                      <span>Surface errors: {t.render_failures_total ?? '—'}</span>
                      <span>Encoder errors: {t.encoder_errors_total ?? '—'}</span>
                      <span>Raw capture FPS skips: {t.capture_throttle_drops_total ?? '—'}</span>
                      <span>Raw codec input skips: {t.encoder_input_drops_total ?? '—'}</span>
                      <span>Encoded FPS drops: {t.frame_throttle_drops_total ?? '—'}</span>
                    </div>
                  );
                })() : <div>Нет свежего отчёта активного захвата от APK.</div>}
                <div className="mt-2 border-t border-white/15 pt-2">
                  <div>Браузерный viewer: {browserStats ? `${browserStats.binaryMessagesReceived} пакетов · ${browserStats.binaryBytesReceived} байт` : 'нет данных'}</div>
                  {browserStats && (
                    <div className="grid grid-cols-2 gap-x-3">
                      <span>Входной видео FPS (1 с): {browserStats.receivedPictureFpsCapped ? '≥' : ''}{browserStats.receivedPictureFps}</span>
                      <span>Отрисовка FPS (1 с): {browserStats.renderedFpsCapped ? '≥' : ''}{browserStats.renderedFps}</span>
                      <span>Последний пакет: {formatTimestampAgo(browserStats.lastBinaryAtMs)}</span>
                      <span>Последний canvas frame: {formatTimestampAgo(browserStats.lastRenderedAtMs)}</span>
                      <span>NAL SPS/PPS: {browserStats.spsUnits}/{browserStats.ppsUnits}</span>
                      <span>IDR/delta: {browserStats.idrUnits}/{browserStats.deltaUnits}</span>
                      <span>Decode submitted: {browserStats.decodeSubmitted}</span>
                      <span>Decoded output: {browserStats.decodedOutputs}</span>
                      <span>Drawn to canvas: {browserStats.renderedFrames}</span>
                      <span>Invalid packets: {browserStats.invalidPackets}</span>
                      <span>Decode/render errors: {browserStats.decodeErrors}/{browserStats.renderErrors}</span>
                      {browserStats.lastDecodeError && <span>Последняя ошибка декодера: {browserStats.lastDecodeError}</span>}
                      <span>WebCodecs queue: {browserStats.decoderQueueSize}</span>
                      <span>Pending outputs: {browserStats.pendingOutputCount}</span>
                      <span>Queue recoveries: {browserStats.queueRecoveries}</span>
                      <span>Stale output drops: {browserStats.staleOutputDrops}</span>
                      <span>Dropped before SPS/PPS: {browserStats.framesDroppedBeforeConfiguration}</span>
                    </div>
                  )}
                </div>
                <p className="mt-2 border-t border-white/15 pt-2 text-white/70">
                  Принятие кадра локальной очередью APK не подтверждает получение сервером. Сейчас серверный receipt каждого кадра и браузерный декодер не связаны общим frame ID; сравнивайте Android counters с viewer counters.
                </p>
              </>
            )}
          </div>
        )}
      </div>
    )}
    </div>
    {enableNavigation && <AndroidNavigationBar key={deviceId} deviceId={deviceId} extended
      available={canNavigate && (!continuousBusy || continuousState === 'ready') && wsRef.current?.readyState === WebSocket.OPEN}
      prepareCommand={prepareDiscreteInput}
      isAvailable={() => canNavigate && !continuousFaultRef.current && (!continuousRef.current || ['ready', 'closed', 'destroyed'].includes(continuousRef.current.state)) && wsRef.current?.readyState === WebSocket.OPEN}
      onControlCommand={onControlCommand}
      getFrameDimensions={() => {
        const canvas = canvasRef.current;
        return canvas && canNavigate && renderedSocketRef.current === wsRef.current
          ? { width: canvas.width, height: canvas.height } : null;
      }} />}
    </div>
  );
}
