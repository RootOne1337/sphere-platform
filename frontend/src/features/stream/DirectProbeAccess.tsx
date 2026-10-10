'use client';
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { DirectProbeDiagnostics, type DiagnosticProfile } from './DirectProbeDiagnostics';
import { DirectVideoProbe } from './DirectVideoProbe';

type Admission = { device: string; profiles: DiagnosticProfile[]; video: boolean };
const profileLabels: Record<DiagnosticProfile, string> = {
  host: 'Локальные адреса браузера', 'public-stun': 'STUN · поиск пути через NAT', turn: 'TURN · резервный маршрут',
};

export function parseProbeAdmission(value: unknown, device: string): DiagnosticProfile[] | null {
  if (!value || typeof value !== 'object') return null;
  const data = value as Record<string, unknown>;
  if (data.schema_version !== 1 || data.device_id !== device || typeof data.enabled !== 'boolean'
    || data.scope !== 'diagnostic_echo_only' || data.max_duration_ms !== 30000 || data.samples !== 20
    || 'readonly_video_enabled' in data && typeof data.readonly_video_enabled !== 'boolean'
    || data.readonly_video_enabled === true && data.enabled !== true
    || !Array.isArray(data.profiles) || data.profiles.length > 3
    || data.profiles.some(profile => !['host', 'public-stun', 'turn'].includes(profile))
    || new Set(data.profiles).size !== data.profiles.length
    || data.enabled !== (data.profiles.length > 0)) return null;
  return data.profiles as DiagnosticProfile[];
}

/** The HTTP read never opens a peer. The authenticated WS rechecks every grant. */
export function DirectProbeAccess({ deviceId }: { deviceId: string }) {
  const token = useAuthStore(state => state.accessToken);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const [selected, setSelected] = useState<DiagnosticProfile | null>(null);
  const [mode, setMode] = useState<'echo' | 'video'>('echo');
  const [busy, setBusy] = useState(false);
  // Device online/offline events reconcile this read through the shared fleet
  // feed. No peer and no additional polling loop are created by this query.
  const admission = useQuery<Admission>({
    queryKey: ['direct-probe-capabilities', deviceId, sessionVersion],
    enabled: !!token && !busy,
    queryFn: async ({ signal }) => {
      const response = await api.get(`/devices/${encodeURIComponent(deviceId)}/direct-probe-capabilities`, { signal });
      const profiles = parseProbeAdmission(response.data, deviceId);
      if (!profiles) throw Error('invalid_probe_admission');
      return { device: deviceId, profiles, video: response.data.readonly_video_enabled === true };
    },
    retry: false, gcTime: 0, staleTime: 0,
    refetchOnWindowFocus: true, refetchOnReconnect: true,
  });
  useEffect(() => { setMode('echo'); setSelected(null); setBusy(false); }, [deviceId, token]);
  const active = admission.data?.device === deviceId ? admission.data : null;
  if (!token) return null;
  if (admission.isError) return <div className="mt-3 font-sans text-sm text-muted-foreground">
    <p>Доступ к проверке прямого канала не получен. Текущий видеопоток продолжает использовать свой транспорт.</p>
    <button type="button" disabled={admission.isFetching || busy} onClick={() => { void admission.refetch(); }}
      className="mt-2 rounded-md border border-border px-3 py-1.5 focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">Обновить доступ к проверке</button>
  </div>;
  if (!active) return <p className="mt-3 font-sans text-sm text-muted-foreground" role="status">Проверяем доступ к диагностике прямого канала…</p>;
  if (!active.profiles.length) return null;
  const profile = selected && active.profiles.includes(selected) ? selected
    : active.profiles.includes('turn') ? 'turn' : active.profiles.includes('public-stun') ? 'public-stun' : active.profiles[0];
  return <div className="mt-3 min-w-0 font-sans">
    {active.video && <label className="mb-2 flex flex-wrap items-center gap-2 text-sm">Что проверить
      <select value={mode} disabled={busy} onChange={event => setMode(event.target.value as 'echo' | 'video')}
        className="min-w-0 max-w-full rounded-md border border-border bg-background px-2 py-1.5 disabled:opacity-50">
        <option value="echo">Связь браузера с APK</option><option value="video">Видеокадры с APK по WebRTC</option>
      </select>
    </label>}
    <label className="flex flex-wrap items-center gap-2 text-sm">Профиль проверки
      <select value={profile} disabled={busy} onChange={event => setSelected(event.target.value as DiagnosticProfile)}
        className="min-w-0 max-w-full rounded-md border border-border bg-background px-2 py-1.5 focus-visible:ring-2 focus-visible:ring-ring">
        {active.profiles.map(value => <option key={value} value={value}>{profileLabels[value]}</option>)}
      </select>
    </label>
    {mode === 'video' && active.video
      ? <DirectVideoProbe key={`${deviceId}:${profile}`} deviceId={deviceId} profile={profile} onBusyChange={setBusy} />
      : <DirectProbeDiagnostics key={`${deviceId}:${profile}`} deviceId={deviceId} profile={profile} onBusyChange={setBusy} />}
  </div>;
}
