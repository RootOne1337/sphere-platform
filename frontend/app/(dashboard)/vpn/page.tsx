'use client';

import { useState, useMemo } from 'react';
import { Network, ArrowUp, ArrowDown, Activity, Settings, Plus, Lock, Globe, Zap } from 'lucide-react';
import { Button } from '@/src/shared/ui/button';
import { Input } from '@/src/shared/ui/input';
import { Badge } from '@/src/shared/ui/badge';
import { VPNMap } from '@/src/features/vpn/VPNMap';
import { ThroughputChart } from '@/src/features/vpn/ThroughputChart';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';

interface Tunnel {
  id: string;
  name: string;
  endpoint: string;
  clients: number;
  rx: string;
  tx: string;
  status: string;
  uptime: string;
}

export default function VPNManagerPage() {
  const [search, setSearch] = useState('');

  // Fetch real VPN peers from backend
  const { data: tunnels = [], isLoading } = useQuery<Tunnel[]>({
    queryKey: ['vpn-peers'],
    queryFn: async () => {
      try {
        const { data } = await api.get('/vpn/peers');
        return data.map((d: any) => ({
          id: d.id,
          name: `Tunnel ${d.assigned_ip}`,
          endpoint: d.assigned_ip,
          clients: d.is_active ? 1 : 0,
          rx: '0 B',
          tx: '0 B',
          status: d.status.toUpperCase(),
          uptime: d.last_handshake_at ? 'Active' : 'N/A'
        }));
      } catch (e) {
        console.error('Failed to fetch VPN peers', e);
        return [];
      }
    }
  });

  // Демонстрационные данные для графиков скорости
  const aggregateChartData = useMemo(() => {
    return Array.from({ length: 24 }).map((_, i) => ({
      time: `${i}:00`,
      rx: Math.floor(Math.random() * 800) + 200,
      tx: Math.floor(Math.random() * 400) + 50,
    }));
  }, []);

  const generateNodeData = (id: string) => {
    return Array.from({ length: 15 }).map((_, i) => {
      const isDown = id === 'T-003';
      return {
        time: `${i}m`,
        rx: isDown ? 0 : Math.floor(Math.random() * 100) + 10,
        tx: isDown ? 0 : Math.floor(Math.random() * 50) + 5,
      };
    });
  };

  return (
    <div className="flex flex-col h-full bg-card">
      {/* Header Area */}
      <div className="px-6 py-5 border-b border-border bg-muted shrink-0">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <Network className="w-5 h-5 text-primary" />
              <h1 className="text-xl font-bold font-mono tracking-tight text-foreground uppercase pt-1">VPN Tunneling Manager</h1>
            </div>
            <p className="text-xs text-muted-foreground font-mono max-w-2xl">
              Secure reverse-tunnel infrastructure. Manage Android fleet connections, IPsec policies, and endpoint health routing.
            </p>
          </div>

          <div className="flex items-center gap-4 bg-black/40 p-3 rounded-sm border border-border">
            <div className="flex space-x-6">
              <div className="flex flex-col">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <ArrowDown className="w-3 h-3" /> Global RX
                </span>
                <span className="text-sm text-foreground font-mono font-bold">21.7 GB</span>
              </div>
              <div className="flex flex-col border-l border-border pl-6">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <ArrowUp className="w-3 h-3" /> Global TX
                </span>
                <span className="text-sm text-foreground font-mono font-bold">6.9 GB</span>
              </div>
              <div className="flex flex-col border-l border-border pl-6">
                <span className="text-[10px] text-muted-foreground uppercase tracking-widest font-bold flex items-center gap-1">
                  <Lock className="w-3 h-3" /> Encrypt
                </span>
                <span className="text-sm text-success font-mono font-bold">AES-256</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="p-6 flex-1 overflow-auto">
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-3">
            <Input
              placeholder="Search endpoints or IPs..."
              className="w-72 h-9 bg-black/50 border-border font-mono text-xs focus-visible:ring-primary/50"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <div className="flex gap-3">
            <Button variant="outline" size="sm" className="h-9 border-border hover:bg-border">
              <Settings className="w-4 h-4 mr-2" /> Global Policy
            </Button>
            <Button variant="default" size="sm" className="h-9">
              <Plus className="w-4 h-4 mr-2" /> Provision Node
            </Button>
          </div>
        </div>

        {/* Top Dashboards: Map & Flow */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
          <div className="col-span-2 flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Globe className="w-4 h-4" /> Global Tunnel Topology
            </h2>
            <VPNMap tunnels={tunnels} />
          </div>

          <div className="flex flex-col">
            <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase flex items-center gap-2">
              <Activity className="w-4 h-4" /> Aggregate Throughput
            </h2>
            <div className="bg-card border border-border rounded-sm p-4 flex-1 shadow-2xl relative overflow-hidden">
              <div className="absolute top-2 right-4 flex items-center gap-3 z-10">
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-success"></div><span className="text-[10px] text-muted-foreground font-mono">RX</span></div>
                <div className="flex items-center gap-1.5"><div className="w-2 h-2 rounded-full bg-blue-500"></div><span className="text-[10px] text-muted-foreground font-mono">TX</span></div>
              </div>
              <ThroughputChart data={aggregateChartData} />
            </div>
          </div>
        </div>

        {/* VPN Nodes Grid */}
        <h2 className="text-xs font-mono font-bold tracking-widest text-muted-foreground mb-3 uppercase mt-6 border-b border-border pb-2">Active Provider Nodes</h2>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
          {isLoading && <div className="col-span-1 xl:col-span-2 text-center text-muted-foreground p-10">Fetching secure tunnels from backend...</div>}
          {!isLoading && tunnels.filter(t => t.name.toLowerCase().includes(search.toLowerCase()) || t.endpoint.includes(search)).map(tunnel => (
            <div key={tunnel.id} className="bg-muted border border-border rounded-sm flex flex-col hover:border-[#444] transition-colors relative overflow-hidden group">
              {/* Background Graphic */}
              <Globe className="absolute -right-8 -bottom-8 w-48 h-48 text-[#ffffff03] pointer-events-none group-hover:scale-110 transition-transform duration-700" strokeWidth={1} />

              <div className="p-5 flex-1 relative z-10">
                <div className="flex justify-between items-start mb-6">
                  <div>
                    <div className="flex items-center gap-2 mb-1">
                      <h3 className="text-base font-bold font-mono text-foreground">{tunnel.name}</h3>
                      {tunnel.status === 'ACTIVE' && (
                        <Badge variant="outline" className="text-[9px] border-success text-success bg-success/5 animate-pulse">LIVE</Badge>
                      )}
                    </div>
                    <div className="text-xs text-muted-foreground font-mono flex items-center gap-2">
                      <span className="font-bold text-primary/80">{tunnel.id}</span>
                      <span>•</span>
                      <span>{tunnel.endpoint}</span>
                    </div>
                  </div>
                  <Badge variant="outline" className={`text-[10px] ${tunnel.status === 'ACTIVE' ? 'border-primary text-primary' :
                    tunnel.status === 'DEGRADED' ? 'border-warning text-warning' :
                      'border-destructive text-destructive'
                    }`}>
                    {tunnel.status}
                  </Badge>
                </div>

                <div className="grid grid-cols-4 gap-4 mb-2">
                  <div className="col-span-1 border-r border-border">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1">Active Fleet</div>
                    <div className="text-xl font-mono font-bold text-foreground flex items-center gap-2">
                      {tunnel.clients}
                      <Activity className={`w-3 h-3 ${tunnel.clients > 0 ? 'text-success' : 'text-destructive'}`} />
                    </div>
                  </div>
                  <div className="col-span-1">
                    <div className="text-[10px] uppercase font-bold tracking-widest text-muted-foreground mb-1 text-success">RX (MB/s)</div>
                    <div className="text-lg font-mono font-bold text-foreground">{tunnel.rx}</div>
                  </div>
                  <div className="col-span-2 h-[45px] opacity-80 pt-1">
                    {/* Mini individual chart per node */}
                    <ThroughputChart data={generateNodeData(tunnel.id)} />
                  </div>
                </div>
              </div>

              <div className="border-t border-border bg-[#151515] p-3 px-5 flex items-center justify-between relative z-10 mt-auto">
                <div className="text-[10px] uppercase tracking-widest font-bold text-muted-foreground flex items-center gap-2">
                  <Zap className="w-3.5 h-3.5 text-warning" /> Uptime: <span className="text-muted-foreground font-mono">{tunnel.uptime}</span>
                </div>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" className="h-8 text-[10px] uppercase font-bold tracking-widest text-muted-foreground hover:text-foreground">Reboot</Button>
                  <Button variant="ghost" size="sm" className="h-8 text-[10px] uppercase font-bold tracking-widest text-muted-foreground hover:text-foreground">Logs</Button>
                  <Button variant="ghost" size="sm" className="h-8 text-[10px] uppercase font-bold tracking-widest text-primary hover:text-primary hover:bg-primary/10">Configure</Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
