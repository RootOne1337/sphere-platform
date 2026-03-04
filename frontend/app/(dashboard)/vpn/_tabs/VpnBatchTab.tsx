'use client';
import { useState, useCallback } from 'react';
import { useAssignVpn, useRevokeVpn } from '@/lib/hooks/useVpn';
import { useDevices } from '@/lib/hooks/useDevices';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';

export function VpnBatchTab() {
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [processing, setProcessing] = useState(false);
  const { data } = useDevices({ page_size: 100 });
  const assignVpn = useAssignVpn();
  const revokeVpn = useRevokeVpn();

  const devices = data?.items ?? [];

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  // Бекенд не имеет batch VPN assign/revoke — выполняем последовательно
  const handleBatchAssign = useCallback(async () => {
    setProcessing(true);
    for (const deviceId of selected) {
      await assignVpn.mutateAsync({ device_id: deviceId });
    }
    setSelected(new Set());
    setProcessing(false);
  }, [selected, assignVpn]);

  const handleBatchRevoke = useCallback(async () => {
    setProcessing(true);
    for (const deviceId of selected) {
      await revokeVpn.mutateAsync(deviceId);
    }
    setSelected(new Set());
    setProcessing(false);
  }, [selected, revokeVpn]);

  return (
    <div className="mt-4 space-y-4">
      <div className="flex gap-2">
        <Button
          variant="outline"
          disabled={selected.size === 0 || processing}
          onClick={handleBatchAssign}
        >
          {processing ? 'Processing…' : `Assign VPN (${selected.size})`}
        </Button>
        <Button
          variant="destructive"
          disabled={selected.size === 0 || processing}
          onClick={handleBatchRevoke}
        >
          {processing ? 'Processing…' : `Revoke VPN (${selected.size})`}
        </Button>
      </div>

      <div className="space-y-1 max-h-96 overflow-auto">
        {devices.map((device) => (
          <label
            key={device.id}
            className="flex items-center gap-3 p-2 rounded hover:bg-accent cursor-pointer"
          >
            <Checkbox
              checked={selected.has(device.id)}
              onCheckedChange={() => toggle(device.id)}
            />
            <span className="text-sm">{device.name}</span>
            <span className="text-xs text-muted-foreground ml-auto">
              {device.vpn_assigned ? 'VPN assigned' : 'No VPN'}
            </span>
          </label>
        ))}
      </div>
    </div>
  );
}
