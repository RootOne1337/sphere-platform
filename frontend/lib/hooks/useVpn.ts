import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useAuthStore } from '@/lib/store';
import { api } from '@/lib/api';
import { API_POLL_INTERVALS } from '@/lib/queryPollIntervals';

// ── Типы ────────────────────────────────────────────────────────────────────

export interface VpnPeer {
  id: string;
  device_id: string | null;
  assigned_ip: string | null;
  status: 'free' | 'assigned' | 'error' | 'provisioning' | 'revoking';
  is_active: boolean;
  last_handshake_at: string | null;
  public_key: string;
  created_at: string;
}

export interface PoolStats {
  total_ips: number;
  allocated: number;
  free: number;
  active_tunnels: number;
  stale_handshakes: number;
}

export interface VpnHealthResponse {
  status: string;
  checks: Record<string, { status: string; detail?: string }>;
}

export interface VPNBulkRevokeResponse {
  total: number;
  succeeded: number;
  failed: number;
  results: Array<{ device_id: string; success: boolean; error: string | null }>;
}

// ── Запросы (Query) ─────────────────────────────────────────────────────────

/** Список VPN-пиров с опциональной фильтрацией */
export function useVpnPeers(params?: { status?: VpnPeer['status']; device_id?: string }) {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  return useQuery<VpnPeer[]>({
    queryKey: ['vpn', 'peers', scope, params],
    queryFn: async () => {
      const { data } = await api.get('/vpn/peers', { params });
      if (!Array.isArray(data) || data.some(peer => !peer || typeof peer.id !== 'string' || !peer.id
        || (peer.device_id !== null && (typeof peer.device_id !== 'string' || !peer.device_id))
        || !['free', 'assigned', 'error', 'provisioning', 'revoking'].includes(peer.status)
        || typeof peer.is_active !== 'boolean' || (peer.assigned_ip !== null && typeof peer.assigned_ip !== 'string'))
        || new Set(data.map(peer => peer.id)).size !== data.length) throw new Error('Invalid VPN peer catalog');
      return data;
    },
    refetchInterval: API_POLL_INTERVALS.vpnPeersMs,
    retry: false,
  });
}

/** Статистика пула IP-адресов */
export function usePoolStats() {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  return useQuery<PoolStats>({
    queryKey: ['vpn', 'pool-stats', scope],
    queryFn: async () => {
      const { data } = await api.get('/vpn/pool/stats');
      return data;
    },
    refetchInterval: API_POLL_INTERVALS.vpnPoolStatsMs,
  });
}

/** Здоровье VPN-подсистемы */
export function useVpnHealth() {
  const actor = useAuthStore(s => s.user); const session = useAuthStore(s => s.sessionVersion);
  const scope = `${actor?.org_id}:${actor?.id}:${actor?.role}:${session}`;
  return useQuery<VpnHealthResponse>({
    queryKey: ['vpn', 'health', scope],
    queryFn: async () => {
      const { data } = await api.get('/vpn/health');
      return data;
    },
    refetchInterval: API_POLL_INTERVALS.vpnHealthMs,
  });
}

// ── Мутации ─────────────────────────────────────────────────────────────────

/** Назначить VPN-пир устройству. Бекенд: POST /vpn/assign */
export function useAssignVpn(options: { invalidateOnSuccess?: boolean } = {}) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { device_id: string; split_tunnel?: boolean }) =>
      api.post('/vpn/assign', params),
    onSuccess: () => {
      if (options.invalidateOnSuccess === false) return;
      qc.invalidateQueries({ queryKey: ['vpn'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}

/** Отозвать VPN-пир у устройства. Бекенд: DELETE /vpn/revoke/{device_id} */
export function useRevokeVpn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) => api.delete(`/vpn/revoke/${deviceId}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['vpn'] });
      qc.invalidateQueries({ queryKey: ['devices'] });
    },
  });
}

/** Отозвать VPN у выбранных устройств. Каждая операция фиксируется отдельно на backend. */
export function useBulkRevokeVpn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (device_ids: string[]) => {
      const { data } = await api.post('/vpn/revoke/bulk', { device_ids });
      return data as VPNBulkRevokeResponse;
    },
    onSuccess: async () => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: ['vpn'] }),
        qc.invalidateQueries({ queryKey: ['devices'] }),
      ]);
    },
  });
}

/** Массовая ротация VPN-адресов. Бекенд: POST /vpn/rotate */
export function useVpnRotate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { device_ids: string[] }) =>
      api.post('/vpn/rotate', body),
    retry: false,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

/** Управление Kill Switch на устройствах. Бекенд: POST /vpn/killswitch */
export function useVpnKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { device_ids: string[]; enabled: boolean }) =>
      api.post('/vpn/killswitch', { device_ids: body.device_ids, action: body.enabled ? 'enable' : 'disable' }),
    retry: false,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}
