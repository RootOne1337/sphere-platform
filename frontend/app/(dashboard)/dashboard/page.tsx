'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import { usePoolStats, useVpnHealth } from '@/lib/hooks/useVpn';
import { Card, CardContent, CardHeader, CardTitle } from '@/src/shared/ui/card';
import { Badge } from '@/src/shared/ui/badge';
import { Progress } from '@/src/shared/ui/progress';
import {
  Smartphone,
  Wifi,
  WifiOff,
  Activity,
  ShieldCheck,
  ShieldAlert,
  Server,
  Cpu,
  HardDrive,
  Zap,
} from 'lucide-react';

/* ── Device fleet summary ── */
interface FleetStats {
  total: number;
  online: number;
  offline: number;
  busy: number;
  vpn_active: number;
}

function useFleetStats() {
  return useQuery<FleetStats>({
    queryKey: ['dashboard', 'fleet'],
    queryFn: async () => {
      // Fetch all devices (lightweight)
      const { data } = await api.get('/devices', {
        params: { per_page: 1 },
      });
      const total = data.total ?? 0;

      // Fetch per-status counts in parallel
      const [onlineRes, offlineRes] = await Promise.all([
        api.get('/devices', { params: { status: 'online', per_page: 1 } }),
        api.get('/devices', { params: { status: 'offline', per_page: 1 } }),
      ]);
      const online = onlineRes.data.total ?? 0;
      const offline = offlineRes.data.total ?? 0;

      return {
        total,
        online,
        offline,
        busy: Math.max(0, total - online - offline),
        vpn_active: 0,
      };
    },
    refetchInterval: 30_000,
    staleTime: 10_000,
  });
}

/* ── Stat card (High-Density) ── */
function StatCard({
  title,
  value,
  subtitle,
  icon: Icon,
  color = 'text-primary',
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  color?: string;
}) {
  return (
    <Card className="bg-card border-border rounded-sm overflow-hidden group">
      <CardContent className="p-4 flex items-center justify-between relative">
        <div className="z-10">
          <p className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold mb-1">{title}</p>
          <p className="text-3xl font-mono font-bold tracking-tight text-foreground">{value}</p>
          {subtitle && (
            <p className="text-[10px] text-muted-foreground mt-1 tracking-wide">{subtitle}</p>
          )}
        </div>
        <Icon className={`w-10 h-10 ${color} opacity-20 absolute -right-2 -bottom-2 group-hover:opacity-40 transition-opacity z-0`} />
      </CardContent>
    </Card>
  );
}

/* ── Device status distribution (High-Density) ── */
function DeviceDistribution({ stats }: { stats: FleetStats }) {
  const pctOnline = stats.total > 0 ? (stats.online / stats.total) * 100 : 0;
  return (
    <Card className="bg-card border-border rounded-sm">
      <CardHeader className="p-4 pb-2 border-b border-border">
        <CardTitle className="text-xs uppercase tracking-widest font-bold font-mono">Fleet Matrix</CardTitle>
      </CardHeader>
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 w-24">
            <span className="w-2 h-2 rounded-full bg-success"></span>
            <span className="font-medium text-muted-foreground uppercase tracking-wider text-[10px]">Online</span>
          </div>
          <Progress value={pctOnline} className="flex-1 mx-4 h-1 bg-border [&>div]:bg-success" />
          <span className="font-mono font-bold w-12 text-right">{stats.online}</span>
        </div>

        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 w-24">
            <span className="w-2 h-2 rounded-full bg-destructive"></span>
            <span className="font-medium text-muted-foreground uppercase tracking-wider text-[10px]">Offline</span>
          </div>
          <Progress
            value={stats.total > 0 ? (stats.offline / stats.total) * 100 : 0}
            className="flex-1 mx-4 h-1 bg-border [&>div]:bg-destructive"
          />
          <span className="font-mono font-bold w-12 text-right">{stats.offline}</span>
        </div>

        <div className="flex items-center justify-between text-xs">
          <div className="flex items-center gap-2 w-24">
            <span className="w-2 h-2 rounded-full bg-warning"></span>
            <span className="font-medium text-muted-foreground uppercase tracking-wider text-[10px]">Busy</span>
          </div>
          <Progress
            value={stats.total > 0 ? (stats.busy / stats.total) * 100 : 0}
            className="flex-1 mx-4 h-1 bg-border [&>div]:bg-warning"
          />
          <span className="font-mono font-bold w-12 text-right">{stats.busy}</span>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── VPN stats card (High-Density) ── */
function VpnOverview() {
  const { data: pool } = usePoolStats();
  const { data: health } = useVpnHealth();
  const utilization =
    pool && pool.total_ips > 0
      ? Math.round(((pool.allocated ?? 0) / pool.total_ips) * 100)
      : 0;

  return (
    <Card className="bg-card border-border rounded-sm">
      <CardHeader className="p-4 pb-2 border-b border-border flex flex-row items-center space-y-0">
        <CardTitle className="text-xs flex-1 uppercase tracking-widest font-bold font-mono">VPN Tunneling</CardTitle>
        {health?.status === 'ok' ? (
          <Badge variant="outline" className="border-success text-success bg-success/10 text-[10px] tracking-wide rounded-sm py-0 h-5">
            <ShieldCheck className="w-3 h-3 mr-1" />
            OK
          </Badge>
        ) : (
          <Badge variant="outline" className="border-destructive text-destructive bg-destructive/10 text-[10px] tracking-wide rounded-sm py-0 h-5">
            <ShieldAlert className="w-3 h-3 mr-1" />
            {health?.status ?? 'ERR'}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="p-4 space-y-4">
        <div className="grid grid-cols-2 gap-y-4 gap-x-2">
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Active Tunnels</p>
            <p className="text-lg font-mono font-bold">{pool?.active_tunnels ?? 0}</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Stale Tunnels</p>
            <p className="text-lg font-mono font-bold text-warning">
              {pool?.stale_handshakes ?? 0}
            </p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Pool Usage</p>
            <p className="text-lg font-mono font-bold text-success">{utilization}%</p>
          </div>
          <div>
            <p className="text-[10px] uppercase tracking-widest text-muted-foreground">Free IPs</p>
            <p className="text-lg font-mono font-bold">{pool?.free ?? 0}</p>
          </div>
        </div>
        <Progress value={utilization} className="h-1 bg-border [&>div]:bg-success" />
      </CardContent>
    </Card>
  );
}

/* ── System health card (High-Density) ── */
function SystemHealth() {
  const { data } = useQuery({
    queryKey: ['dashboard', 'health'],
    queryFn: async () => {
      const { data } = await api.get('/health');
      return data as { status: string; version: string };
    },
    refetchInterval: 60_000,
  });

  return (
    <Card className="bg-card border-border rounded-sm">
      <CardHeader className="p-4 pb-2 border-b border-border">
        <CardTitle className="text-xs uppercase tracking-widest font-bold font-mono">Core Health</CardTitle>
      </CardHeader>
      <CardContent className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-muted-foreground" />
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">Backend API</span>
          </div>
          <Badge
            variant="outline"
            className={
              data?.status === 'ok'
                ? 'border-success text-success bg-success/10 text-[10px] rounded-sm py-0 h-5'
                : 'border-destructive text-destructive bg-destructive/10 text-[10px] rounded-sm py-0 h-5'
            }
          >
            {data?.status ?? 'CHK'}
          </Badge>
        </div>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-muted-foreground" />
            <span className="text-[11px] uppercase tracking-wider text-muted-foreground">Version</span>
          </div>
          <span className="text-[11px] font-mono font-bold text-foreground">
            {data?.version ?? '—'}
          </span>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Dashboard page ── */
export default function DashboardPage() {
  const { data: fleet, isLoading } = useFleetStats();

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-lg font-mono font-bold tracking-widest text-primary flex items-center gap-2">
          <Activity className="w-5 h-5 text-primary" />
          NOC_OVERVIEW
        </h1>
        <p className="text-[11px] text-muted-foreground mt-1 tracking-wider uppercase font-mono">
          Global infrastructure analytics
        </p>
      </div>

      {/* Top stat cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Devices"
          value={fleet?.total ?? '—'}
          icon={Smartphone}
          color="text-blue-500"
        />
        <StatCard
          title="Online"
          value={fleet?.online ?? '—'}
          subtitle={
            fleet && fleet.total > 0
              ? `${Math.round((fleet.online / fleet.total) * 100)}% of fleet`
              : undefined
          }
          icon={Wifi}
          color="text-green-500"
        />
        <StatCard
          title="Offline"
          value={fleet?.offline ?? '—'}
          icon={WifiOff}
          color="text-red-400"
        />
        <StatCard
          title="Active Tasks"
          value={fleet?.busy ?? '—'}
          icon={Activity}
          color="text-amber-500"
        />
      </div>

      {/* Detail sections */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <DeviceDistribution stats={fleet ?? { total: 0, online: 0, offline: 0, busy: 0, vpn_active: 0 }} />
        <VpnOverview />
        <SystemHealth />
      </div>
    </div>
  );
}
