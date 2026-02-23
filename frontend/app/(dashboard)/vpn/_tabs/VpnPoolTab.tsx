'use client';
import { usePoolStats } from '@/lib/hooks/useVpn';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Progress } from '@/components/ui/progress';

export function VpnPoolTab() {
  const { data: stats } = usePoolStats();
  const allocationPercent = stats
    ? Math.round((stats.allocated / stats.total_ips) * 100)
    : 0;

  return (
    <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mt-4">
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Total IPs</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-bold">{stats?.total_ips ?? '—'}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Allocated</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-bold text-orange-400">{stats?.allocated ?? '—'}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Available</CardTitle>
        </CardHeader>
        <CardContent>

          <p className="text-3xl font-bold text-green-400">{stats?.free ?? '—'}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Active Tunnels</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-bold text-blue-400">{stats?.active_tunnels ?? '—'}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Stale Tunnels</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-3xl font-bold text-yellow-400">{stats?.stale_handshakes ?? '—'}</p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm text-muted-foreground">Utilization</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xl font-bold mb-2">{allocationPercent.toFixed(1)}%</p>
          <Progress value={allocationPercent} className="h-2" />
        </CardContent>
      </Card>
    </div>
  );
}
