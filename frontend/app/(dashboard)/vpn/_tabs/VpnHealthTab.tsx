'use client';
import { useVpnHealth } from '@/lib/hooks/useVpn';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

export function VpnHealthTab() {
  const { data: health, isLoading } = useVpnHealth();

  if (isLoading) {
    return <p className="mt-4 text-sm text-muted-foreground">Loading health data…</p>;
  }

  return (
    <div className="mt-4 space-y-4">
      <div className="flex items-center gap-2">
        <span className="font-medium">Overall Status:</span>
        <Badge variant={health?.status === 'healthy' ? 'default' : 'destructive'}>
          {health?.status ?? 'unknown'}
        </Badge>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {health?.checks &&
          Object.entries(health.checks).map(([name, check]) => (
            <Card key={name}>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm capitalize">{name.replace(/_/g, ' ')}</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-2">
                  <Badge variant={check.status === 'ok' ? 'default' : 'destructive'}>
                    {check.status}
                  </Badge>
                  {check.detail && (
                    <span className="text-xs text-muted-foreground">{check.detail}</span>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
      </div>
    </div>
  );
}
