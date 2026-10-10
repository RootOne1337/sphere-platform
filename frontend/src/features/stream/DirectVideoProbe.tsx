'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { startDirectVideoProbe, type DirectProbeResult } from './directProbe';
import type { DiagnosticProfile } from './DirectProbeDiagnostics';

const running = (result: DirectProbeResult | null) => !!result && ['gathering', 'signaling', 'connecting', 'connected'].includes(result.state);

/** Isolated read-only renderer: it cannot unlock input on the ordinary canvas. */
export function DirectVideoProbe({ deviceId, profile, onBusyChange, automaticKey, enabled = true, compact = false, onOutcome }: {
  deviceId: string; profile: DiagnosticProfile; onBusyChange?: (busy: boolean) => void;
  automaticKey?: string | null; enabled?: boolean; compact?: boolean;
  onOutcome?: (result: DirectProbeResult, presentedFrames: number) => void;
}) {
  const token = useAuthStore(state => state.accessToken);
  const video = useRef<HTMLVideoElement>(null);
  const stop = useRef<(() => void) | null>(null);
  const generation = useRef(0);
  const frameCallback = useRef<number | null>(null);
  const frameCount = useRef(0);
  const firstFrameDeadline = useRef<ReturnType<typeof setTimeout> | null>(null);
  const latestResult = useRef<DirectProbeResult | null>(null);
  const outcome = useRef(onOutcome); outcome.current = onOutcome;
  const automaticStarted = useRef<string | null>(null);
  const beginRef = useRef<() => void>(() => {});
  const [result, setResult] = useState<DirectProbeResult | null>(null);
  const [presented, setPresented] = useState(0);
  const [renderError, setRenderError] = useState<string | null>(null);
  const active = running(result);
  const retire = useCallback(() => { ++generation.current; stop.current?.(); stop.current = null; }, []);
  useEffect(() => { onBusyChange?.(active); }, [active, onBusyChange]);
  const clearVideo = useCallback((element: HTMLVideoElement | null = video.current) => {
    if (firstFrameDeadline.current !== null) clearTimeout(firstFrameDeadline.current);
    firstFrameDeadline.current = null;
    if (!element) return;
    if (frameCallback.current !== null) element.cancelVideoFrameCallback?.(frameCallback.current);
    frameCallback.current = null;
    element.pause(); element.srcObject = null;
  }, []);
  useEffect(() => {
    setResult(null); setPresented(0); setRenderError(null);
    const element = video.current;
    const hidden = () => { if (document.hidden) stop.current?.(); };
    document.addEventListener('visibilitychange', hidden);
    return () => {
      retire(); clearVideo(element);
      document.removeEventListener('visibilitychange', hidden);
    };
  }, [deviceId, token, profile, clearVideo, retire]);

  const begin = () => {
    if (!token || active) return;
    stop.current?.(); clearVideo();
    const current = ++generation.current;
    let rendererFailed = false;
    let outcomeSent = false;
    const publishOutcome = (value: DirectProbeResult) => {
      if (!outcomeSent) { outcomeSent = true; outcome.current?.(value, frameCount.current); }
    };
    let unboundFrame: { width: number; height: number } | null = null;
    frameCount.current = 0; latestResult.current = null;
    setPresented(0); setRenderError(null);
    const failRenderer = (message: string) => {
      if (generation.current !== current) return;
      rendererFailed = true;
      setRenderError(message); stop.current?.(); clearVideo();
      const failed: DirectProbeResult = { ...(latestResult.current ?? {
        samples: [], path: 'unknown', protocol: null,
      }), state: 'failed', reason: 'video_renderer_failed' };
      latestResult.current = failed; setResult(failed);
      publishOutcome(failed);
    };
    const verifyFrame = (dimensions: { width: number; height: number }) => {
      const binding = latestResult.current?.videoBinding;
      if (!binding) { unboundFrame = dimensions; return; }
      if (dimensions.width !== binding.width || dimensions.height !== binding.height) {
        failRenderer('Размер полученного кадра не совпал с захватом APK. Проверка остановлена.'); return;
      }
      frameCount.current++;
      if (frameCount.current === 1) {
        if (firstFrameDeadline.current !== null) clearTimeout(firstFrameDeadline.current);
        firstFrameDeadline.current = null;
        setPresented(1);
      }
    };
    const base = process.env.NEXT_PUBLIC_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
    try {
      const cancel = startDirectVideoProbe(`${base}/ws/direct-probe/${encodeURIComponent(deviceId)}`, token, value => {
        if (generation.current !== current || rendererFailed) return;
        latestResult.current = value;
        if (running(value) && value.videoBinding && unboundFrame) {
          const pending = unboundFrame; unboundFrame = null; verifyFrame(pending);
          if (rendererFailed) return;
        }
        setResult(value); setPresented(frameCount.current);
        if (!running(value)) { clearVideo(); publishOutcome(value); }
        else if (value.videoBinding && frameCount.current === 0 && firstFrameDeadline.current === null) {
          firstFrameDeadline.current = setTimeout(() => failRenderer(
            'APK согласовал видеоканал, но первый видеокадр не отображён за 8 секунд. Проверка остановлена.'), 8_000);
        }
      }, {
        controlledStunUrl: profile === 'public-stun' ? 'stun:stun.cloudflare.com:3478' : undefined,
        relayGrant: profile === 'turn',
        onTrack: track => {
          if (generation.current !== current || rendererFailed || !video.current) { track.stop(); return; }
          const element = video.current;
          element.srcObject = new MediaStream([track]);
          const rendered = (_now: number, metadata: VideoFrameCallbackMetadata) => {
            if (generation.current !== current || rendererFailed || !running(latestResult.current)) return;
            verifyFrame(metadata);
            if (!rendererFailed) frameCallback.current = element.requestVideoFrameCallback(rendered);
          };
          if (element.requestVideoFrameCallback) frameCallback.current = element.requestVideoFrameCallback(rendered);
          else failRenderer('Браузер не поддерживает проверку отображённых видеокадров.');
          void element.play().catch(() => failRenderer('Браузер не смог воспроизвести видеодорожку.'));
        },
      });
      stop.current = cancel;
      if (rendererFailed) cancel();
    } catch {
      const failed: DirectProbeResult = { state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'webrtc_unavailable' };
      setResult(failed); publishOutcome(failed);
      clearVideo();
    }
  };
  beginRef.current = begin;
  useEffect(() => {
    if (!enabled) { stop.current?.(); return; }
    if (!automaticKey || !token || document.hidden || automaticStarted.current === automaticKey) return;
    automaticStarted.current = automaticKey;
    beginRef.current();
  }, [automaticKey, enabled, token]);
  const sorted = result ? [...result.samples].sort((a, b) => a - b) : [];
  const p95 = sorted.length ? sorted[Math.ceil(sorted.length * .95) - 1].toFixed(1) : null;
  return <section className={`min-w-0 rounded-lg border border-border bg-background p-3 font-sans ${compact ? 'text-xs' : 'mt-3'}`} aria-label="Проверка видео WebRTC">
    <div className="font-medium">Видео с APK · проверка WebRTC</div>
    <p className="mt-1 text-sm text-muted-foreground">{automaticKey ? 'Автоматическая проверка до 30 секунд. Результат сохраняется в истории сеанса.' : 'Отдельный просмотр до 30 секунд. Видео передаётся по выбранному ICE-пути; касания и клавиатура остаются в основном видеопотоке. Звук не включается.'}</p>
    {!automaticKey && <div className="mt-3 flex flex-wrap gap-2">
      <button type="button" disabled={!token || active} onClick={begin} className="rounded-md border border-border px-3 py-1.5 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring">Проверить видео с APK</button>
      {active && <button type="button" onClick={() => stop.current?.()} className="rounded-md border border-border px-3 py-1.5">Остановить проверку</button>}
    </div>}
    <div className={`relative mt-3 aspect-video overflow-hidden rounded-md border border-border bg-black ${compact ? 'max-w-48' : ''}`}>
      <video ref={video} muted autoPlay playsInline className="h-full w-full object-contain" aria-label="Видео Android по WebRTC" />
      {(!active || !presented) && <div className="absolute inset-0 grid place-items-center p-3 text-center text-xs text-white/70">{active ? 'Ожидаем видеокадр с APK…' : 'Проверка просмотра по WebRTC'}</div>}
    </div>
    {result && <>
      <p className="mt-3 font-medium" role="status">{active ? presented ? 'Кадры отображаются по WebRTC' : 'Соединяем видеоканал…' : presented ? 'Проверка завершена · видеокадры получены' : 'Видеокадры не подтверждены'}</p>
      <dl className="mt-2 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
        <div><dt className="text-muted-foreground">Отображено кадров</dt><dd>{presented}</dd></div>
        <div><dt className="text-muted-foreground">Размер захвата</dt><dd>{result.videoBinding ? `${result.videoBinding.width} × ${result.videoBinding.height}` : 'Не подтверждён'}</dd></div>
        <div><dt className="text-muted-foreground">Выбранный путь</dt><dd>{({ host: 'Host-кандидаты', nat: 'Через NAT', relay: 'TURN-ретранслятор', unknown: 'Не подтверждён' })[result.path]}{result.protocol && ` · ${result.protocol.toUpperCase()}`}</dd></div>
        <div><dt className="text-muted-foreground">RTT контрольных пакетов p95</dt><dd>{p95 ? `${p95} мс · ${sorted.length}/20` : 'Не измерен'}</dd></div>
      </dl>
      <p className="mt-2 text-xs text-muted-foreground">RTT контрольных пакетов не измеряет задержку видео или выполнение касания. Получение SDP и открытый канал сами по себе не подтверждают изображение.</p>
      {result.reason && <p className="mt-2 text-sm text-muted-foreground">Проверка остановлена: <code className="break-all">{result.reason}</code>. Основной видеопоток использует свой транспорт.</p>}
    </>}
    {renderError && <p role="alert" className="mt-2 text-sm text-destructive">{renderError}</p>}
  </section>;
}
