'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { isAxiosError } from 'axios';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { parseProbeAdmission } from './DirectProbeAccess';
import { DirectVideoProbe } from './DirectVideoProbe';
import type { DirectProbeResult } from './directProbe';
import type { DiagnosticProfile } from './DirectProbeDiagnostics';
import { directDiagnosticSample } from './streamSessionTelemetry';

/** One finite host attempt, then at most one admitted NAT attempt per viewer. */
export function AutomaticStreamDiagnostic({ deviceId, session, eligible, onDiagnostic, onBusyChange }: {
  deviceId: string; session: string | null; eligible: boolean;
  onDiagnostic: (sample: ReturnType<typeof directDiagnosticSample>, session: string) => void;
  onBusyChange: (busy: boolean) => void;
}) {
  const token = useAuthStore(state => state.accessToken);
  const sessionVersion = useAuthStore(state => state.sessionVersion);
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const changed = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', changed);
    return () => document.removeEventListener('visibilitychange', changed);
  }, []);
  const admission = useQuery({
    // Admission belongs to this viewer generation. A cached read from the
    // manual panel or a previous server connection must not suppress its test.
    queryKey: ['direct-probe-capabilities', deviceId, sessionVersion, 'automatic', session],
    enabled: !!token && !!session && eligible && visible,
    queryFn: async ({ signal }) => {
      const response = await api.get(`/devices/${encodeURIComponent(deviceId)}/direct-probe-capabilities`, { signal });
      const profiles = parseProbeAdmission(response.data, deviceId);
      if (!profiles) throw Error('invalid_probe_admission');
      return { profiles, video: response.data.readonly_video_enabled === true };
    },
    retry: (failures, error) => failures < 1 && isAxiosError(error)
      && (error.response === undefined || error.response.status >= 500),
    retryDelay: 1000, staleTime: 60000, gcTime: 0, refetchOnWindowFocus: false,
  });
  const consumed = useRef<string | null>(null);
  const latestSession = useRef(session); latestSession.current = session;
  const latestEligible = useRef(eligible); latestEligible.current = eligible;
  const fallback = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [attempt, setAttempt] = useState<{ session: string; profile: DiagnosticProfile } | null>(null);
  const [busy, setBusy] = useState(false);
  const [last, setLast] = useState<{ session: string; frames: number; result: DirectProbeResult } | null>(null);
  useEffect(() => { onBusyChange(busy); return () => onBusyChange(false); }, [busy, onBusyChange]);
  useEffect(() => () => { if (fallback.current) clearTimeout(fallback.current); }, [session, token, deviceId]);
  useEffect(() => {
    if (!session || !eligible || !visible || !admission.data?.video || consumed.current === session) return;
    const profiles = admission.data.profiles;
    const profile = profiles.includes('host') ? 'host' : profiles.includes('public-stun') ? 'public-stun' : null;
    if (!profile) return; // Automatic tests never consume an unrequested TURN relay grant.
    consumed.current = session;
    setLast(null); setAttempt({ session, profile });
  }, [session, eligible, visible, admission.data]);
  const current = attempt?.session === session ? attempt : null;
  const completed = last?.session === session ? last : null;
  if (!session || !admission.data?.video || !current) return null;
  return <details open={busy} className="mt-2 min-w-0 rounded-lg border border-border bg-muted/20 p-2 text-left font-sans text-xs">
    <summary className="cursor-pointer select-none font-medium">Автодиагностика прямого видео · {busy ? 'выполняется'
      : completed ? completed.frames > 0 ? `${completed.frames} кадров подтверждено` : 'кадры не подтверждены' : 'подготовка'}</summary>
    <p className="mt-2 text-muted-foreground">Проверка выполняется в этой вкладке. Основное видео и управление пока используют сервер; результат доступен в последних 10 сеансах.</p>
    <DirectVideoProbe key={`${current.session}:${current.profile}`} deviceId={deviceId} profile={current.profile}
      automaticKey={`${current.session}:${current.profile}`} enabled={eligible && visible} compact onBusyChange={setBusy}
      onOutcome={(result, frames) => {
        if (latestSession.current !== current.session) return;
        onDiagnostic(directDiagnosticSample(result, frames, current.profile, true), current.session);
        setLast({ session: current.session, frames, result });
        if (current.profile === 'host' && result.state === 'failed' && frames === 0
          && admission.data?.profiles.includes('public-stun') && latestEligible.current && !document.hidden) {
          fallback.current = setTimeout(() => {
            fallback.current = null;
            if (latestSession.current === current.session && latestEligible.current && !document.hidden)
              setAttempt({ session: current.session, profile: 'public-stun' });
          }, 1000);
        }
      }} />
  </details>;
}
