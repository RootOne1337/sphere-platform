'use client';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { useVpnPeers } from '@/lib/hooks/useVpn';
import { ShieldAlert, ShieldOff } from 'lucide-react';

interface KillSwitchResponse {
  action: string;
  total: number;
  success: number;
  results: Record<string, boolean>;
}

export function VpnKillSwitchTab() {
  const { data: peers } = useVpnPeers();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<KillSwitchResponse | null>(null);

  const enableKs = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/vpn/killswitch', {
        action: 'enable',
        device_ids: Array.from(selectedIds),
        method: 'iptables',
      });
      return data as KillSwitchResponse;
    },
    onSuccess: setResult,
  });

  const disableKs = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/vpn/killswitch', {
        action: 'disable',
        device_ids: Array.from(selectedIds),
      });
      return data as KillSwitchResponse;
    },
    onSuccess: setResult,
  });

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const activePeers = peers?.filter((p) => p.device_id) ?? [];

  return (
    <div className="space-y-4 pt-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-sm text-muted-foreground">
            Kill Switch blocks all non-VPN traffic on the device using iptables rules.
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => enableKs.mutate()}
            disabled={enableKs.isPending || selectedIds.size === 0}
          >
            <ShieldAlert className="w-4 h-4 mr-2" />
            Enable ({selectedIds.size})
          </Button>
          <Button
            variant="destructive"
            onClick={() => disableKs.mutate()}
            disabled={disableKs.isPending || selectedIds.size === 0}
          >
            <ShieldOff className="w-4 h-4 mr-2" />
            Disable ({selectedIds.size})
          </Button>
        </div>
      </div>

      {activePeers.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">No VPN peers with devices</p>
      ) : (
        <div className="rounded border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="p-3 w-10">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === activePeers.length && activePeers.length > 0}
                    onChange={() => {
                      if (selectedIds.size === activePeers.length) setSelectedIds(new Set());
                      else setSelectedIds(new Set(activePeers.map((p) => p.device_id)));
                    }}
                  />
                </th>
                <th className="p-3">Device</th>
                <th className="p-3">IP</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {activePeers.map((peer) => (
                <tr key={peer.id} className="border-b hover:bg-accent/50">
                  <td className="p-3">
                    <input
                      type="checkbox"
                      checked={selectedIds.has(peer.device_id)}
                      onChange={() => toggleSelect(peer.device_id)}
                    />
                  </td>
                  <td className="p-3 font-mono text-xs">{peer.device_id.slice(0, 12)}…</td>
                  <td className="p-3 font-mono text-xs">{peer.assigned_ip}</td>
                  <td className="p-3">
                    <Badge variant="outline">{peer.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {result && (
        <div className="rounded border p-4">
          <p className="text-sm font-medium mb-2">
            {result.action === 'enable' ? 'Kill Switch enabled' : 'Kill Switch disabled'}:
            {' '}{result.success}/{result.total} devices
          </p>
          {Object.entries(result.results).map(([devId, ok]) => (
            <p key={devId} className={`text-xs ${ok ? 'text-green-400' : 'text-red-400'}`}>
              {devId.slice(0, 12)}… — {ok ? 'OK' : 'Failed'}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}
