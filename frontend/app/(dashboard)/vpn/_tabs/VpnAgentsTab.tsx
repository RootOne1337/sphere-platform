'use client';
import { useVpnPeers, useRevokeVpn } from '@/lib/hooks/useVpn';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';

export function VpnAgentsTab() {
  const { data: peers } = useVpnPeers();
  const revoke = useRevokeVpn();

  return (
    <div className="mt-4 space-y-2">
      {peers?.map((peer) => (
        <div key={peer.id} className="flex items-center justify-between p-3 rounded border">
          <div>
            <p className="font-medium">{peer.device_id ? `Device ${peer.device_id.slice(0, 8)}` : 'Unassigned pool peer'}</p>
            <p className="text-sm text-muted-foreground">{peer.assigned_ip ?? 'No assigned address'}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={peer.is_active ? 'default' : peer.status === 'error' ? 'destructive' : 'secondary'}>
              {peer.status}{peer.is_active ? ' · recent handshake' : ''}
            </Badge>
            <Button
              size="sm"
              variant="destructive"
              disabled={!peer.device_id || revoke.isPending}
              onClick={() => { if (peer.device_id) revoke.mutate(peer.device_id); }}
            >
              Revoke
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
