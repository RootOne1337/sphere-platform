'use client';
import { useEffect, useRef, useCallback, useState } from 'react';
import { H264Decoder } from '@/lib/h264-decoder';
import type { StreamDecoderStats } from '@/lib/h264-decoder';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';

interface DeviceStreamProps {
  deviceId: string;
  onTap?: (x: number, y: number) => void;
  enableDiagnostics?: boolean;
  fit?: 'contain' | 'cover' | 'fill';
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
  enableDiagnostics = false,
  fit,
}: DeviceStreamProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const decoderRef = useRef<H264Decoder | null>(null);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const { accessToken } = useAuthStore();
  const [connection, setConnection] = useState<
    'connecting' | 'waiting' | 'live' | 'stale' | 'retrying' | 'unavailable'
  >('connecting');
  const [streamError, setStreamError] = useState<string | null>(null);
  const [diagnosticsOpen, setDiagnosticsOpen] = useState(false);
  const [agentDiagnostics, setAgentDiagnostics] = useState<StreamDiagnosticResponse | null>(null);
  const [diagnosticsError, setDiagnosticsError] = useState<string | null>(null);
  const [browserStats, setBrowserStats] = useState<StreamDecoderStats | null>(null);

  useEffect(() => {
    // Defer WS creation by one tick to avoid React StrictMode double-invoke.
    let ignore = false;
    let ws: WebSocket | null = null;
    let decoder: H264Decoder | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let keyFrameTimer: ReturnType<typeof setTimeout> | undefined;
    let frameStaleTimer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setInterval> | undefined;
    let scheduleKeyFrameRecovery: ((delayMs?: number) => void) | undefined;
    let attempt = 0;
    setConnection('connecting');
    setStreamError(null);

    const timer = setTimeout(() => {
      if (ignore) return;

      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d')!;

      decoder = new H264Decoder((frame) => {
        if (ignore || wsRef.current?.readyState !== WebSocket.OPEN) return;
        setConnection('live');
        setStreamError(null);
        clearTimeout(keyFrameTimer);
        clearTimeout(frameStaleTimer);
        frameStaleTimer = setTimeout(() => {
          if (ignore || wsRef.current?.readyState !== WebSocket.OPEN) return;
          setConnection('stale');
          scheduleKeyFrameRecovery?.();
        }, FRAME_STALE_TIMEOUT_MS);
        // Mutate canvas directly for performance, avoid React state re-renders
        if (canvas.width !== frame.displayWidth || canvas.height !== frame.displayHeight) {
          canvas.width = frame.displayWidth;
          canvas.height = frame.displayHeight;
        }
        ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);
      }, () => {
        if (ignore) return;
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
        setStreamError(null);
        const newWs = new WebSocket(wsUrl);
        newWs.binaryType = 'arraybuffer';
        ws = newWs;
        wsRef.current = newWs;
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
          clearInterval(watchdog);
          clearTimeout(keyFrameTimer);
          clearTimeout(frameStaleTimer);
          if (scheduleKeyFrameRecovery === scheduleKeyFrameRequests) scheduleKeyFrameRecovery = undefined;
          newWs.onopen = newWs.onmessage = newWs.onclose = newWs.onerror = null;
          if (wsRef.current === newWs) wsRef.current = null;
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
              if (msg.type === 'ping' && newWs.readyState === WebSocket.OPEN) {
                newWs.send(JSON.stringify({ type: 'pong' }));
              } else if (msg.type === 'error') {
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
      };

      createWs();
    }, 0);

    return () => {
      ignore = true;
      clearTimeout(timer);
      clearTimeout(retryTimer);
      clearTimeout(keyFrameTimer);
      clearTimeout(frameStaleTimer);
      clearInterval(watchdog);
      wsRef.current = null;
      ws?.close();
      decoder?.destroy();
      decoderRef.current = null;
    };
  }, [deviceId, accessToken]);

  useEffect(() => {
    if (!enableDiagnostics || !diagnosticsOpen) return;
    let active = true;
    const refreshAgent = async () => {
      try {
        const { data } = await api.get<StreamDiagnosticResponse>(
          `/devices/${deviceId}/stream-diagnostics`,
        );
        if (active) {
          setAgentDiagnostics(data);
          setDiagnosticsError(null);
        }
      } catch {
        if (active) setDiagnosticsError('Не удалось получить телеметрию устройства');
      }
    };
    void refreshAgent();
    const agentTimer = window.setInterval(() => void refreshAgent(), 15_000);
    const browserTimer = window.setInterval(() => {
      if (active) setBrowserStats(decoderRef.current?.stats ?? null);
    }, 1000);
    setBrowserStats(decoderRef.current?.stats ?? null);
    return () => {
      active = false;
      window.clearInterval(agentTimer);
      window.clearInterval(browserTimer);
    };
  }, [deviceId, diagnosticsOpen, enableDiagnostics]);

  // ── coordinate helpers ───────────────────────────────────────────────────
  const toCanvasCoords = useCallback(
    (clientX: number, clientY: number) => {
      const canvas = canvasRef.current;
      if (!canvas) return null;
      const rect = canvas.getBoundingClientRect();
      return {
        x: Math.round((clientX - rect.left) * (canvas.width / rect.width)),
        y: Math.round((clientY - rect.top) * (canvas.height / rect.height)),
      };
    },
    [],
  );

  // ── pointer down — begin drag / tap ─────────────────────────────────────
  const handlePointerDown = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const pt = toCanvasCoords(e.clientX, e.clientY);
      if (!pt) return;
      dragRef.current = pt;
      (e.target as HTMLCanvasElement).setPointerCapture(e.pointerId);
    },
    [toCanvasCoords],
  );

  // ── pointer up — tap or swipe ────────────────────────────────────────────
  const handlePointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const start = dragRef.current;
      dragRef.current = null;
      if (!start) return;

      const pt = toCanvasCoords(e.clientX, e.clientY);
      if (!pt) return;

      const dist = Math.hypot(pt.x - start.x, pt.y - start.y);

      if (dist < 12) {
        // Tap
        onTap?.(start.x, start.y);
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'click', x: start.x, y: start.y }));
        }
      } else {
        // Swipe — duration proportional to distance, min 150ms max 600ms
        const duration_ms = Math.min(600, Math.max(150, Math.round(dist * 0.8)));
        if (wsRef.current?.readyState === WebSocket.OPEN) {
          wsRef.current.send(JSON.stringify({ type: 'swipe', x1: start.x, y1: start.y, x2: pt.x, y2: pt.y, duration_ms }));
        }
      }
    },
    [toCanvasCoords, onTap],
  );

  return (
    <div className={fit ? 'relative h-full w-full min-h-0 min-w-0' : 'relative'}>
    <canvas
      ref={canvasRef}
      onPointerDown={handlePointerDown}
      onPointerUp={handlePointerUp}
      className="cursor-pointer rounded border border-gray-700 bg-black touch-none"
      style={{
        display: 'block',
        width: '100%',
        height: fit ? '100%' : 'auto',
        objectFit: fit ?? 'contain',
      }}
    />
    {(connection !== 'live' || streamError) && (
      <div role="status" className="absolute inset-0 flex items-center justify-center bg-black/85 text-sm text-white">
        {streamError ?? (
          connection === 'connecting' ? 'Подключение…' :
          connection === 'waiting' ? 'Ожидание видеокадра…' :
          connection === 'stale' ? 'Нет новых видеокадров более 10 секунд' :
          connection === 'retrying' ? 'Переподключение…' : 'Стрим недоступен'
        )}
      </div>
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
            {diagnosticsError ? <div className="text-red-300">{diagnosticsError}</div> : (
              <>
                <div>Отчёт APK: {agentDiagnostics?.state === 'active_report' ? 'захват активен' : agentDiagnostics?.state ?? 'загрузка…'}
                  {agentDiagnostics?.age_seconds != null && ` · snapshot ${Math.floor(agentDiagnostics.age_seconds)} сек назад`}
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
                      <span>FPS-throttle drops: {t.frame_throttle_drops_total ?? '—'}</span>
                    </div>
                  );
                })() : <div>Нет свежего отчёта активного захвата от APK.</div>}
                <div className="mt-2 border-t border-white/15 pt-2">
                  <div>Браузерный viewer: {browserStats ? `${browserStats.binaryMessagesReceived} пакетов · ${browserStats.binaryBytesReceived} байт` : 'нет данных'}</div>
                  {browserStats && (
                    <div className="grid grid-cols-2 gap-x-3">
                      <span>Последний пакет: {formatTimestampAgo(browserStats.lastBinaryAtMs)}</span>
                      <span>Последний canvas frame: {formatTimestampAgo(browserStats.lastRenderedAtMs)}</span>
                      <span>NAL SPS/PPS: {browserStats.spsUnits}/{browserStats.ppsUnits}</span>
                      <span>IDR/delta: {browserStats.idrUnits}/{browserStats.deltaUnits}</span>
                      <span>Decode submitted: {browserStats.decodeSubmitted}</span>
                      <span>Decoded output: {browserStats.decodedOutputs}</span>
                      <span>Drawn to canvas: {browserStats.renderedFrames}</span>
                      <span>Invalid packets: {browserStats.invalidPackets}</span>
                      <span>Decode/render errors: {browserStats.decodeErrors}/{browserStats.renderErrors}</span>
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
  );
}
