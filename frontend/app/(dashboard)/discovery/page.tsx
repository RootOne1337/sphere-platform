'use client';
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Radar } from 'lucide-react';

interface DiscoveredDevice {
  ip: string;
  port: number;
  serial: string | null;
  model: string | null;
  registered: boolean;
}

interface DiscoverResponse {
  found: number;
  registered: number;
  devices: DiscoveredDevice[];
}

export default function DiscoveryPage() {
  const [subnet, setSubnet] = useState('192.168.1.0/24');
  const [ports, setPorts] = useState('5555,5037');
  const [autoRegister, setAutoRegister] = useState(true);

  const scan = useMutation({
    mutationFn: async () => {
      const { data } = await api.post('/discovery/scan', {
        subnet,
        ports: ports.split(',').map((p) => parseInt(p.trim(), 10)).filter(Boolean),
        auto_register: autoRegister,
      });
      return data as DiscoverResponse;
    },
  });

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Network Discovery</h1>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Radar className="w-5 h-5" />
            Subnet Scanner
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1">
              <Label>Subnet (CIDR)</Label>
              <Input value={subnet} onChange={(e) => setSubnet(e.target.value)} placeholder="192.168.1.0/24" />
            </div>
            <div className="space-y-1">
              <Label>ADB Ports</Label>
              <Input value={ports} onChange={(e) => setPorts(e.target.value)} placeholder="5555,5037" />
            </div>
            <div className="flex items-end gap-2">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="auto-register"
                  checked={autoRegister}
                  onChange={(e) => setAutoRegister(e.target.checked)}
                />
                <Label htmlFor="auto-register" className="text-sm">Auto-register</Label>
              </div>
            </div>
          </div>
          <Button onClick={() => scan.mutate()} disabled={scan.isPending}>
            {scan.isPending ? 'Scanning…' : 'Start Scan'}
          </Button>
        </CardContent>
      </Card>

      {scan.data && (
        <Card>
          <CardHeader>
            <CardTitle>
              Results: {scan.data.found} found, {scan.data.registered} registered
            </CardTitle>
          </CardHeader>
          <CardContent>
            {scan.data.devices.length === 0 ? (
              <p className="text-sm text-muted-foreground">No devices found in this subnet</p>
            ) : (
              <div className="rounded border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th className="p-3">IP</th>
                      <th className="p-3">Port</th>
                      <th className="p-3">Serial</th>
                      <th className="p-3">Model</th>
                      <th className="p-3">Registered</th>
                    </tr>
                  </thead>
                  <tbody>
                    {scan.data.devices.map((d, i) => (
                      <tr key={i} className="border-b hover:bg-accent/50">
                        <td className="p-3 font-mono">{d.ip}</td>
                        <td className="p-3">{d.port}</td>
                        <td className="p-3 font-mono text-xs">{d.serial ?? '—'}</td>
                        <td className="p-3">{d.model ?? '—'}</td>
                        <td className="p-3">
                          <Badge variant={d.registered ? 'default' : 'outline'}>
                            {d.registered ? 'Yes' : 'No'}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {scan.error && (
        <div className="rounded border border-red-800 bg-red-950 p-4 text-sm text-red-400">
          Scan failed: {(scan.error as Error).message}
        </div>
      )}
    </div>
  );
}
