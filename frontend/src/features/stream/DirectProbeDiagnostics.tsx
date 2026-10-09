'use client';
import { useEffect, useRef, useState } from 'react';
import { useAuthStore } from '@/lib/store';
import { startDirectProbe, type DirectProbeResult } from './directProbe';

export function DirectProbeDiagnostics({ deviceId }: { deviceId: string }) {
  const token = useAuthStore(state => state.accessToken);
  const [result, setResult] = useState<DirectProbeResult | null>(null);
  const stop = useRef<(() => void) | null>(null);
  const active = result && ['gathering', 'signaling', 'connected'].includes(result.state);
  useEffect(() => {
    const onHidden = () => { if (document.hidden) { stop.current?.(); stop.current = null; } };
    document.addEventListener('visibilitychange', onHidden);
    return () => { stop.current?.(); stop.current = null; document.removeEventListener('visibilitychange', onHidden); };
  }, [deviceId, token]);
  const begin = () => {
    if (!token) return;
    stop.current?.();
    try {
      const base = process.env.NEXT_PUBLIC_WS_URL ?? `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}`;
      stop.current = startDirectProbe(`${base}/ws/direct-probe/${encodeURIComponent(deviceId)}`, token, setResult);
    } catch { setResult({ state: 'failed', samples: [], path: 'unknown', protocol: null, reason: 'webrtc_unavailable' }); }
  };
  const sorted = result ? [...result.samples].sort((a, b) => a - b) : [];
  const p95 = sorted.length ? sorted[Math.ceil(sorted.length * .95) - 1].toFixed(1) : null;
  return <section className="mt-3 rounded-lg border border-border bg-background p-3 font-sans" aria-label="Проверка прямого канала WebRTC">
    <div className="font-medium">Прямой канал · экспериментальная проверка</div>
    <p className="mt-1 text-muted-foreground">До 20 замеров между браузером и APK. Видео и касания пока используют текущий транспорт. Здесь проверяется только host ICE; путь через NAT может быть недоступен.</p>
    <button type="button" disabled={!token || !!active} onClick={begin} className="mt-2 rounded-md border border-border px-3 py-1.5 disabled:opacity-50 focus-visible:ring-2 focus-visible:ring-ring">Проверить прямой канал</button>
    {active && <button type="button" onClick={() => { stop.current?.(); stop.current = null; }} className="ml-2 rounded-md border border-border px-3 py-1.5">Остановить</button>}
    {result && <div role="status" className="mt-2 break-words">{result.state} · {result.samples.length} замеров · путь: {result.path}{result.protocol && ` / ${result.protocol}`}{p95 && ` · RTT p95 ${p95} мс`}{result.reason && ` · ${result.reason}`}</div>}
  </section>;
}
