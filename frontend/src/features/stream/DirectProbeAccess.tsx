'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { DirectProbeDiagnostics, type DiagnosticProfile } from './DirectProbeDiagnostics';

type Admission = { device: string; token: string; profiles: DiagnosticProfile[] };
const profileLabels: Record<DiagnosticProfile, string> = {
  host: 'Локальные адреса браузера', 'public-stun': 'STUN · поиск пути через NAT', turn: 'TURN · резервный маршрут',
};

export function parseProbeAdmission(value: unknown, device: string): DiagnosticProfile[] | null {
  if (!value || typeof value !== 'object') return null;
  const data = value as Record<string, unknown>;
  if (data.schema_version !== 1 || data.device_id !== device || typeof data.enabled !== 'boolean'
    || data.scope !== 'diagnostic_echo_only' || data.max_duration_ms !== 30000 || data.samples !== 20
    || !Array.isArray(data.profiles) || data.profiles.length > 3
    || data.profiles.some(profile => !['host', 'public-stun', 'turn'].includes(profile))
    || new Set(data.profiles).size !== data.profiles.length
    || data.enabled !== (data.profiles.length > 0)) return null;
  return data.profiles as DiagnosticProfile[];
}

/** The HTTP read never opens a peer. The authenticated WS rechecks every grant. */
export function DirectProbeAccess({ deviceId }: { deviceId: string }) {
  const token = useAuthStore(state => state.accessToken);
  const [admission, setAdmission] = useState<Admission | null>(null);
  const [failure, setFailure] = useState<{ device: string; token: string } | null>(null);
  const [selected, setSelected] = useState<DiagnosticProfile>('host');
  useEffect(() => {
    if (!token) return;
    const controller = new AbortController();
    let current = true;
    void api.get(`/devices/${encodeURIComponent(deviceId)}/direct-probe-capabilities`, { signal: controller.signal })
      .then(response => {
        if (!current) return;
        const profiles = parseProbeAdmission(response.data, deviceId);
        if (!profiles) throw Error('invalid_probe_admission');
        setAdmission({ device: deviceId, token, profiles });
        setFailure(null); setSelected(profiles.includes('turn') ? 'turn'
          : profiles.includes('public-stun') ? 'public-stun' : 'host');
      }).catch(() => { if (current) setFailure({ device: deviceId, token }); });
    return () => { current = false; controller.abort(); };
  }, [deviceId, token]);
  const active = admission?.device === deviceId && admission.token === token ? admission : null;
  const failed = failure?.device === deviceId && failure.token === token;
  if (!token) return null;
  if (failed) return <p className="mt-3 font-sans text-sm text-muted-foreground">Доступ к проверке прямого канала не получен. Текущий видеопоток продолжает использовать свой транспорт.</p>;
  if (!active) return <p className="mt-3 font-sans text-sm text-muted-foreground" role="status">Проверяем доступ к диагностике прямого канала…</p>;
  if (!active.profiles.length) return null;
  const profile = active.profiles.includes(selected) ? selected : active.profiles[0];
  return <div className="mt-3 min-w-0 font-sans">
    <label className="flex flex-wrap items-center gap-2 text-sm">Профиль проверки
      <select value={profile} onChange={event => setSelected(event.target.value as DiagnosticProfile)}
        className="min-w-0 max-w-full rounded-md border border-border bg-background px-2 py-1.5 focus-visible:ring-2 focus-visible:ring-ring">
        {active.profiles.map(value => <option key={value} value={value}>{profileLabels[value]}</option>)}
      </select>
    </label>
    <DirectProbeDiagnostics key={`${deviceId}:${profile}`} deviceId={deviceId} profile={profile} />
  </div>;
}
