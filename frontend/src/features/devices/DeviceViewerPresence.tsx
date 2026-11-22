'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { DeviceViewerBadge } from './DeviceViewerBadge';

export function DeviceViewerPresence({ deviceId }: { deviceId: string }) {
  const version = useAuthStore(state => state.sessionVersion);
  return <Presence key={`${deviceId}:${version}`} deviceId={deviceId} />;
}
function Presence({ deviceId }: { deviceId: string }) {
  const [counts, setCounts] = useState<{ card: number; stream: number } | null>(null);
  useEffect(() => {
    const bytes = new Uint8Array(16); crypto.getRandomValues(bytes);
    const session = [...bytes].map(n => n.toString(16).padStart(2, '0')).join('');
    let disposed = false, inFlight = false;
    const abort = new AbortController();
    const path = `/devices/${encodeURIComponent(deviceId)}/viewers`;
    const pulse = async () => {
      if (disposed || document.hidden || inFlight) return;
      inFlight = true;
      try {
        const { data } = await api.post(path, { session, active: true }, { signal: abort.signal, timeout: 4000 });
        if (!disposed) setCounts(data?.available === true && data.counts && ['card', 'stream'].every(key =>
          Number.isInteger(data.counts[key]) && data.counts[key] >= 0 && data.counts[key] <= 128) ? data.counts : null);
      } catch { if (!disposed) setCounts(null); }
      finally { inFlight = false; }
    };
    void pulse();
    const timer = setInterval(() => void pulse(), 15_000);
    const visibility = () => { if (!document.hidden) void pulse(); };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      disposed = true; abort.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visibility);
      void Promise.resolve().then(() => api.post(path, { session, active: false }, { timeout: 2000 })).catch(() => {});
    };
  }, [deviceId]);
  return <DeviceViewerBadge card={counts?.card} stream={counts?.stream} showEmpty />;
}
