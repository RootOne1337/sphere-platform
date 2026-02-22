'use client';
import { useState } from 'react';
import { useVpnPeers, useVpnQr, useRevokeVpn } from '@/lib/hooks/useVpn';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';

export function VpnAgentsTab() {
  const { data: peers } = useVpnPeers();
  const [qrDeviceId, setQrDeviceId] = useState<string | null>(null);
  const revoke = useRevokeVpn();

  const { data: qrData } = useVpnQr(qrDeviceId ?? '', !!qrDeviceId);

  return (
    <div className="mt-4 space-y-2">
      {peers?.map((peer) => (
        <div key={peer.id} className="flex items-center justify-between p-3 rounded border">
          <div>
            <p className="font-medium">{peer.device_name}</p>
            <p className="text-sm text-muted-foreground">{peer.assigned_ip}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={peer.status === 'active' ? 'default' : 'secondary'}>
              {peer.status}
            </Badge>
            <Button size="sm" variant="outline" onClick={() => setQrDeviceId(peer.device_id)}>
              QR
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={() => revoke.mutate(peer.device_id)}
            >
              Revoke
            </Button>
          </div>
        </div>
      ))}

      <Dialog open={!!qrDeviceId} onOpenChange={() => setQrDeviceId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>WireGuard QR Code</DialogTitle>
          </DialogHeader>
          {qrData?.qr_code && (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={`data:image/png;base64,${qrData.qr_code}`}
              alt="WireGuard QR"
              className="w-64 h-64 mx-auto"
            />
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
