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
            <p className="font-medium">{peer.device_name}</p>
            <p className="text-sm text-muted-foreground">{peer.assigned_ip}</p>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant={peer.status === 'active' ? 'default' : 'secondary'}>
              {peer.status}
            </Badge>
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
    </div>
  );
}
