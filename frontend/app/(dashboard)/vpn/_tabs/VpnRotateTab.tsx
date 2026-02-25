'use client';
import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { useVpnPeers } from '@/lib/hooks/useVpn';
import { RotateCcw } from 'lucide-react';

interface RotateDetail {
  device_id: string;
  old_ip: string | null;
  new_ip: string | null;
  error: string | null;
}

interface RotateResponse {
  total: number;
  success: number;
  failed: number;
  details: RotateDetail[];
}

export function VpnRotateTab() {
  const { data: peers } = useVpnPeers();
  const qc = useQueryClient();
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<RotateResponse | null>(null);

  const rotate = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/vpn/rotate', {
        device_ids: Array.from(selectedIds),
      });
      return data as RotateResponse;
    },
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ['vpn'] });
    },
  });

  const rotateAll = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/vpn/rotate', { device_ids: [] });
      return data as RotateResponse;
    },
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ['vpn'] });
    },
  });

  const toggleSelect = (id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const assignedPeers = peers?.filter((p) => p.status === 'active' || p.status === 'inactive') ?? [];

  return (
    <div className="space-y-4 pt-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">
          Select devices to rotate their VPN IPs (revoke + reassign).
        </p>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => rotate.mutate()}
            disabled={rotate.isPending || selectedIds.size === 0}
          >
            <RotateCcw className="w-4 h-4 mr-2" />
            Rotate Selected ({selectedIds.size})
          </Button>
          <Button
            variant="destructive"
            onClick={() => rotateAll.mutate()}
            disabled={rotateAll.isPending}
          >
            Rotate All
          </Button>
        </div>
      </div>

      {assignedPeers.length === 0 ? (
        <p className="text-sm text-muted-foreground text-center py-6">No assigned VPN peers</p>
      ) : (
        <div className="rounded border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="p-3 w-10">
                  <input
                    type="checkbox"
                    checked={selectedIds.size === assignedPeers.length && assignedPeers.length > 0}
                    onChange={() => {
                      if (selectedIds.size === assignedPeers.length) setSelectedIds(new Set());
                      else setSelectedIds(new Set(assignedPeers.map((p) => p.device_id)));
                    }}
                  />
                </th>
                <th className="p-3">Device</th>
                <th className="p-3">IP</th>
                <th className="p-3">Status</th>
              </tr>
            </thead>
            <tbody>
              {assignedPeers.map((peer) => (
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
        <div className="rounded border p-4 space-y-2">
          <p className="text-sm font-medium">
            Rotation complete: {result.success} success, {result.failed} failed ({result.total} total)
          </p>
          {result.details
            .filter((d) => d.error)
            .map((d, i) => (
              <p key={i} className="text-xs text-red-400">
                {d.device_id.slice(0, 8)}…: {d.error}
              </p>
            ))}
          {result.details
            .filter((d) => !d.error)
            .map((d, i) => (
              <p key={i} className="text-xs text-green-400">
                {d.device_id.slice(0, 8)}… {d.old_ip} → {d.new_ip}
              </p>
            ))}
        </div>
      )}
    </div>
  );
}
