'use client';

import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { useAuthStore } from '@/lib/store';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';
import { parseFleetCoverage } from './fleetCoverageTypes';

export function useFleetCoverage() {
    const user = useAuthStore(state => state.user);
    const sessionVersion = useAuthStore(state => state.sessionVersion);
    const orgId = user?.org_id;
    const [now, setNow] = useState(Date.now);
    const query = useQuery({
        queryKey: ['fleet-coverage', orgId, user?.id, user?.role, sessionVersion],
        queryFn: async ({ signal }) => parseFleetCoverage((await api.get('/monitoring/fleet-coverage', { signal, timeout: 10000 })).data, orgId!),
        enabled: !!orgId, retry: false,
        refetchInterval: API_POLL_INTERVALS.fleetCoverageMs, refetchIntervalInBackground: false, refetchOnWindowFocus: 'always',
    });
    useEffect(() => {
        const tick = () => setNow(Date.now());
        const timer = setInterval(tick, 5000);
        document.addEventListener('visibilitychange', tick);
        return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
    }, []);
    const at = Date.parse(query.data?.generated_at ?? '');
    const stale = !!query.data && (!Number.isFinite(at) || now - at > 45000 || at > now + 5000);
    return { query, orgId, stale, snapshot: query.isError || stale ? undefined : query.data };
}
