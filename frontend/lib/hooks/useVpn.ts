import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';

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

export function useVpnPeers() {
  return useQuery<VpnPeer[]>({
    queryKey: ['vpn', 'peers'],
    queryFn: async () => {
      const { data } = await api.get('/vpn/peers');
      return data;
    },
    refetchInterval: 30_000,
  });
}

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

export function useAssignVpn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) => api.post(`/vpn/devices/${deviceId}/assign`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

export function useRevokeVpn() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) => api.delete(`/vpn/devices/${deviceId}/revoke`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

export function useBatchAssign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceIds: string[]) =>
      api.post('/vpn/batch/assign', { device_ids: deviceIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

export function useBatchRevoke() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deviceIds: string[]) =>
      api.post('/vpn/batch/revoke', { device_ids: deviceIds }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['vpn'] }),
  });
}

export function useVpnQr(deviceId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['vpn', 'qr', deviceId],
    queryFn: async () => {
      // FIX: правильный URL /vpn/devices/{id}/config/qr
      const { data } = await api.get(`/vpn/devices/${deviceId}/config/qr`);
      return data as { qr_code: string }; // base64 PNG
    },
    enabled,
    staleTime: Infinity, // QR не меняется без ротации
  });
}

export function useVpnHealth() {
  return useQuery({
    queryKey: ['vpn', 'health'],
    queryFn: async () => {
      const { data } = await api.get('/vpn/health');
      return data as {
        status: string;
        checks: Record<string, { status: string; detail?: string }>;
      };
    },
    refetchInterval: 30_000,
  });
}
