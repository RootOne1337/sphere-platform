import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

// ── Типы ────────────────────────────────────────────────────────────────────

export interface VpnPeer {
  id: string;
  device_id: string;
  device_name: string;
  assigned_ip: string;
  status: 'active' | 'inactive' | 'error';
  last_handshake: string | null;
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
export function useVpnPeers(params?: { status?: string; device_id?: string }) {
  return useQuery<VpnPeer[]>({
    queryKey: ['vpn', 'peers', params],
    queryFn: async () => {
      const { data } = await api.get('/vpn/peers', { params });
      return data;
    },
    refetchInterval: 30_000,
  });
}

/** Статистика пула IP-адресов */
export function usePoolStats() {
  return useQuery<PoolStats>({
    queryKey: ['vpn', 'pool-stats'],
    queryFn: async () => {
      const { data } = await api.get('/vpn/pool/stats');
      return data;
    },
    refetchInterval: 60_000,
  });
}

/** Здоровье VPN-подсистемы */
export function useVpnHealth() {
  return useQuery<VpnHealthResponse>({
    queryKey: ['vpn', 'health'],
    queryFn: async () => {
      const { data } = await api.get('/vpn/health');
      return data;
    },
    refetchInterval: 30_000,
  });
}

// ── Мутации ─────────────────────────────────────────────────────────────────

/** Назначить VPN-пир устройству. Бекенд: POST /vpn/assign */
export function useAssignVpn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (params: { device_id: string; split_tunnel?: boolean }) =>
      api.post('/vpn/assign', params),
    onSuccess: () => {
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
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

/** Управление Kill Switch на устройствах. Бекенд: POST /vpn/killswitch */
export function useVpnKillSwitch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { device_ids: string[]; enabled: boolean }) =>
      api.post('/vpn/killswitch', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}
